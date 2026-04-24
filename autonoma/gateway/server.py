"""Gateway server — WebSocket listener and channel coordinator."""

from __future__ import annotations

import asyncio
import json
import logging

import websockets

from autonoma.gateway.auth import AuthMiddleware
from autonoma.gateway.channels.base import ChannelAdapter
from autonoma.gateway.router import GatewayRouter
from autonoma.config import GatewayConfig
from autonoma.observability.metrics import set_channel_status

logger = logging.getLogger(__name__)


class GatewayServer:
    """Manages the WebSocket server, HTTP server, and all registered channel adapters."""

    def __init__(
        self,
        config: GatewayConfig,
        router: GatewayRouter,
        auth: AuthMiddleware,
        http_server=None,
    ):
        self._config = config
        self._router = router
        self._auth = auth
        self._http_server = http_server
        self._channels: dict[str, ChannelAdapter] = {}
        self._ws_server = None
        self._channel_tasks: list[asyncio.Task] = []

        # Track status per channel for the dashboard
        # shape: { "channel_name": {"status": "running" | "stopped" | "error", "last_error": str | None} }
        self._channel_status: dict[str, dict] = {}

        # Per-channel locks guard rebuild() against concurrent clicks. Without
        # this, a fast double-click on "Reconnect" (or a rebuild triggered by
        # a credentials save landing at the same time as a manual reconnect)
        # could interleave stop/start and leak a zombie task.
        self._rebuild_locks: dict[str, asyncio.Lock] = {}

    def register_channel(self, channel: ChannelAdapter) -> None:
        self._channels[channel.name] = channel
        self._channel_status[channel.name] = {"status": "stopped", "last_error": None}
        set_channel_status(channel.name, "stopped")
        logger.info("Registered channel: %s", channel.name)

    async def start(self) -> None:
        """Start the WebSocket server and all channel adapters."""
        # Start WebSocket server
        self._ws_server = await websockets.serve(
            self._handle_ws_connection,
            self._config.host,
            self._config.port,
        )
        logger.info(
            "Gateway WebSocket server listening on ws://%s:%d",
            self._config.host,
            self._config.port,
        )

        # Start HTTP server if configured
        if self._http_server:
            await self._http_server.start()

        # Start all channel adapters
        for channel in self._channels.values():
            self._start_channel_task(channel)
            
    def _start_channel_task(self, channel: ChannelAdapter) -> None:
        self._channel_status[channel.name]["status"] = "starting"
        self._channel_status[channel.name]["last_error"] = None
        set_channel_status(channel.name, "starting")
        task = asyncio.create_task(
            self._run_channel(channel),
            name=f"channel-{channel.name}",
        )
        self._channel_tasks.append(task)

    async def stop(self) -> None:
        """Shut down all channels and the WebSocket server."""
        logger.info("Shutting down gateway...")

        # Stop channels
        for channel in self._channels.values():
            await channel.stop()

        # Cancel channel tasks, then await them so that Discord gateway sockets,
        # Telegram polling loops, Gmail IMAP connections, etc. all get a chance
        # to run their CancelledError handlers and release resources before we
        # tear down the transports underneath them.
        for task in self._channel_tasks:
            task.cancel()
        if self._channel_tasks:
            await asyncio.gather(*self._channel_tasks, return_exceptions=True)
        self._channel_tasks.clear()

        # Close HTTP server
        if self._http_server:
            await self._http_server.stop()

        # Close WebSocket server
        if self._ws_server:
            self._ws_server.close()
            await self._ws_server.wait_closed()

        logger.info("Gateway shutdown complete.")

    async def _run_channel(self, channel: ChannelAdapter) -> None:
        """Run a channel adapter with error logging so crashes aren't silent."""
        try:
            self._channel_status[channel.name]["status"] = "running"
            set_channel_status(channel.name, "running")
            await channel.start(self._router.handle_message)
            self._channel_status[channel.name]["status"] = "stopped"
            set_channel_status(channel.name, "stopped")
        except asyncio.CancelledError:
            self._channel_status[channel.name]["status"] = "stopped"
            set_channel_status(channel.name, "stopped")
            raise
        except Exception as e:
            self._channel_status[channel.name]["status"] = "error"
            self._channel_status[channel.name]["last_error"] = str(e)
            set_channel_status(channel.name, "error")
            from autonoma.alerts import alert_manager
            alert_manager.add_alert(
                level="error",
                title=f"Channel {channel.name.capitalize()} Crashed",
                message=str(e),
                channel=channel.name
            )
            logger.exception("Channel '%s' crashed", channel.name)

    def _build_channel(self, name: str) -> ChannelAdapter | None:
        """Construct a fresh ChannelAdapter from the current on-disk config.

        Re-reads `.env` + `autonoma.yaml` so that rebuilds pick up credential
        changes written by the dashboard / TUI without requiring a full
        process restart. Returns None if the channel is disabled in config
        (caller treats that as "stop and forget").

        Imports are deferred (matching main.py) so disabled channels don't
        pull in their optional deps (e.g. python-telegram-bot).
        """
        from autonoma.config import load_config

        cfg = load_config()
        ch = cfg.channels

        if name == "rest":
            if not ch.rest.enabled:
                return None
            from autonoma.gateway.channels.rest import RESTChannel
            return RESTChannel(ch.rest, self._http_server)

        if name == "telegram":
            if not ch.telegram.enabled:
                return None
            from autonoma.gateway.channels.telegram import TelegramChannel
            return TelegramChannel(ch.telegram)

        if name == "discord":
            if not ch.discord.enabled:
                return None
            from autonoma.gateway.channels.discord_channel import DiscordChannel
            return DiscordChannel(ch.discord)

        if name == "whatsapp":
            if not ch.whatsapp.enabled:
                return None
            from autonoma.gateway.channels.whatsapp import WhatsAppChannel
            return WhatsAppChannel(ch.whatsapp, self._http_server)

        if name == "gmail":
            if not ch.gmail.enabled:
                return None
            from autonoma.gateway.channels.gmail import GmailChannel
            return GmailChannel(ch.gmail)

        # CLI channel is owned by main.py (and only registered in headless
        # mode). We don't rebuild it — there's no credential flow for stdin.
        return None

    async def rebuild_channel(self, name: str) -> None:
        """Tear down an existing channel and rebuild it from fresh config.

        This is the primary path for applying credential changes live. The
        old adapter is stopped and its task awaited (so sockets/IMAP/etc.
        actually release) before a new adapter is constructed from the
        current `.env` and registered in place.

        A per-channel lock serializes rebuilds so concurrent requests
        (dashboard double-click, credentials save racing reconnect) resolve
        to a single clean swap instead of interleaving.
        """
        lock = self._rebuild_locks.setdefault(name, asyncio.Lock())
        async with lock:
            old = self._channels.get(name)

            # Stop the old adapter first (best-effort — we want to proceed
            # even if its stop() raises, so a wedged channel can be recovered).
            if old is not None:
                try:
                    await old.stop()
                except Exception as e:
                    logger.warning(
                        "Error stopping channel %s during rebuild: %s", name, e
                    )

            # Cancel and await the old task so its CancelledError handler
            # runs before we replace the adapter. Without the await we can
            # race the new task against a still-closing socket.
            stale_tasks = [
                t for t in self._channel_tasks
                if t.get_name() == f"channel-{name}"
            ]
            for t in stale_tasks:
                if not t.done():
                    t.cancel()
            if stale_tasks:
                await asyncio.gather(*stale_tasks, return_exceptions=True)
            self._channel_tasks = [
                t for t in self._channel_tasks if not t.done()
            ]

            # Build the replacement from fresh config. If the channel is now
            # disabled (e.g. user toggled it off), drop it entirely — leaving
            # the stale object around would make /api/channels lie about state.
            new_channel = self._build_channel(name)
            if new_channel is None:
                self._channels.pop(name, None)
                self._channel_status.pop(name, None)
                logger.info("Channel %s disabled — removed after rebuild", name)
                return

            self._channels[name] = new_channel
            self._channel_status[name] = {"status": "stopped", "last_error": None}
            self._start_channel_task(new_channel)
            logger.info("Channel %s rebuilt with fresh config", name)

    async def reconnect_channel(self, name: str) -> None:
        """Backwards-compatible alias — delegates to rebuild so reconnect
        picks up credential changes that may have been saved since the
        channel was first registered."""
        if name not in self._channels:
            raise ValueError(f"Channel {name} not found")
        await self.rebuild_channel(name)

    async def _handle_ws_connection(self, websocket, path=None) -> None:
        """Handle incoming WebSocket connections from clients (like the Dashboard)."""
        # Check auth
        headers = dict(websocket.request_headers) if hasattr(websocket, 'request_headers') else {}
        if not await self._auth.authenticate(headers):
            await websocket.close(1008, "Unauthorized")
            return

        logger.info("WebSocket client connected")
        from autonoma.logs import log_buffer
        from autonoma.alerts import alert_manager
        
        # Async queue for pushes
        q = asyncio.Queue()
        
        def _on_event(entry):
            # Check if alert vs log
            if "title" in entry:
                q.put_nowait({"type": "alert", "data": entry})
            else:
                q.put_nowait({"type": "log", "data": entry})
            
        async def _pusher():
            while True:
                payload = await q.get()
                try:
                    await websocket.send(json.dumps(payload))
                except Exception:
                    break
                    
        pusher_task = None

        try:
            async for raw in websocket:
                try:
                    data = json.loads(raw)
                    action = data.get("type")
                    if action == "subscribe_logs":
                        if pusher_task is None:
                            pusher_task = asyncio.create_task(_pusher())
                        if _on_event not in log_buffer.subscribers:
                            log_buffer.subscribers.append(_on_event)
                        await websocket.send(json.dumps({"status": "ok", "message": "Subscribed to logs"}))
                    elif action == "subscribe_alerts":
                        if pusher_task is None:
                            pusher_task = asyncio.create_task(_pusher())
                        alert_manager.subscribe(_on_event)
                        await websocket.send(json.dumps({"status": "ok", "message": "Subscribed to alerts"}))
                    else:
                        await websocket.send(
                            json.dumps({"status": "ok", "message": "Unknown command"})
                        )
                except json.JSONDecodeError:
                    await websocket.send(
                        json.dumps({"error": "Invalid JSON"})
                    )
        except Exception as e:
            logger.info("WebSocket client disconnected: %s", e)
        finally:
            if _on_event in log_buffer.subscribers:
                log_buffer.subscribers.remove(_on_event)
            alert_manager.unsubscribe(_on_event)
            if pusher_task:
                pusher_task.cancel()

    async def wait_for_channels(self) -> None:
        """Wait for all channel tasks to complete (blocks until shutdown)."""
        if self._channel_tasks:
            await asyncio.gather(*self._channel_tasks, return_exceptions=True)
