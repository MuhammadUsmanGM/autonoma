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

    def register_channel(self, channel: ChannelAdapter) -> None:
        self._channels[channel.name] = channel
        self._channel_status[channel.name] = {"status": "stopped", "last_error": None}
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

        # Cancel channel tasks
        for task in self._channel_tasks:
            task.cancel()

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
            await channel.start(self._router.handle_message)
            self._channel_status[channel.name]["status"] = "stopped"
        except asyncio.CancelledError:
            self._channel_status[channel.name]["status"] = "stopped"
            raise
        except Exception as e:
            self._channel_status[channel.name]["status"] = "error"
            self._channel_status[channel.name]["last_error"] = str(e)
            from autonoma.alerts import alert_manager
            alert_manager.add_alert(
                level="error",
                title=f"Channel {channel.name.capitalize()} Crashed",
                message=str(e),
                channel=channel.name
            )
            logger.exception("Channel '%s' crashed", channel.name)

    async def reconnect_channel(self, name: str) -> None:
        """Force restart a channel (stop and re-start)."""
        channel = self._channels.get(name)
        if not channel:
            raise ValueError(f"Channel {name} not found")
        
        # Stop existing
        try:
            await channel.stop()
        except Exception as e:
            logger.warning(f"Error stopping channel {name} during reconnect: {e}")
            
        # Cancel task if running
        for t in self._channel_tasks:
            if t.get_name() == f"channel-{name}" and not t.done():
                t.cancel()
                
        # Remove dead tasks from list
        self._channel_tasks = [t for t in self._channel_tasks if not t.done()]
        
        # Start new
        self._start_channel_task(channel)

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
                pusher_task.cancel()

    async def wait_for_channels(self) -> None:
        """Wait for all channel tasks to complete (blocks until shutdown)."""
        if self._channel_tasks:
            await asyncio.gather(*self._channel_tasks, return_exceptions=True)
