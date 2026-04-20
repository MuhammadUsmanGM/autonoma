"""WhatsApp channel — talks to local whatsapp-web.js sidecar."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

import httpx

from autonoma.config import WhatsAppConfig
from autonoma.gateway.channels._http_server import HTTPServer
from autonoma.gateway.channels._util import split_message
from autonoma.gateway.channels.base import ChannelAdapter, MessageHandler
from autonoma.schema import Message

logger = logging.getLogger(__name__)


def _default_bridge_dir() -> Path:
    """Where the whatsapp-bridge sidecar lives by default.

    Tries two places, in order:
      1. $AUTONOMA_HOME/whatsapp-bridge (user's workspace, e.g. an
         npm-installed Autonoma that vendored the bridge next to the CLI)
      2. <repo-root>/whatsapp-bridge (dev layout: sibling of the autonoma
         Python package)
    The first one that contains a package.json wins.
    """
    candidates: list[Path] = []
    home = os.environ.get("AUTONOMA_HOME")
    if home:
        candidates.append(Path(home) / "whatsapp-bridge")
    # autonoma/gateway/channels/whatsapp.py → go up 3 dirs to repo root.
    candidates.append(Path(__file__).resolve().parents[3] / "whatsapp-bridge")
    candidates.append(Path.cwd() / "whatsapp-bridge")

    for c in candidates:
        if (c / "package.json").exists():
            return c
    # Fall back to the dev-layout path so the error message from
    # _spawn_bridge is actionable.
    return Path(__file__).resolve().parents[3] / "whatsapp-bridge"


class WhatsAppChannel(ChannelAdapter):
    """WhatsApp channel via local whatsapp-web.js bridge sidecar."""

    def __init__(self, config: WhatsAppConfig, http_server: HTTPServer):
        self._config = config
        self._http_server = http_server
        self._handler: MessageHandler | None = None
        self._client = httpx.AsyncClient(timeout=30.0)
        self._stop_event = asyncio.Event()
        # Populated by _spawn_bridge when auto_spawn_bridge is on. Kept so
        # stop() can terminate the child cleanly; otherwise every Autonoma
        # restart would leak a puppeteer process.
        self._bridge_proc: subprocess.Popen | None = None
        self._bridge_log_handle = None
        # Watchdog task — polls the sidecar and respawns it if the Node
        # process dies (chromium OOM, puppeteer crash, etc). Populated by
        # start(), cancelled by stop().
        self._watchdog_task: asyncio.Task | None = None
        # Exponential backoff state so a wedged sidecar doesn't chew CPU
        # in a spawn loop. Reset on every successful up-check.
        self._restart_attempts = 0

    @property
    def name(self) -> str:
        return "whatsapp"

    async def start(self, message_handler: MessageHandler) -> None:
        self._handler = message_handler
        self._http_server.add_route(
            "POST", self._config.webhook_path, self._handle_webhook
        )
        logger.info("WhatsApp webhook registered at %s", self._config.webhook_path)

        # Spin up the Node sidecar automatically unless the user has
        # explicitly opted out (e.g. they're running the bridge under PM2
        # or on a separate host). If the port is already in use we assume
        # that's the user's own bridge and leave it alone.
        if self._config.auto_spawn_bridge:
            await self._ensure_bridge_running()
            # Watchdog only makes sense for bridges we own. If the user is
            # running their own (port was already bound), _bridge_proc is
            # None and the watchdog idles harmlessly — but we still start
            # it so the port-probe path covers "user's bridge crashed,
            # we'll take over" scenarios cleanly.
            self._watchdog_task = asyncio.create_task(
                self._run_watchdog(), name="whatsapp-bridge-watchdog"
            )

        await self._stop_event.wait()

    async def stop(self) -> None:
        self._stop_event.set()
        # Cancel the watchdog BEFORE we terminate the child, so it doesn't
        # see the child die and immediately respawn it in the middle of
        # our shutdown sequence. Awaiting the cancellation is essential —
        # asyncio doesn't guarantee the task has released the Popen handle
        # until the CancelledError has propagated.
        if self._watchdog_task is not None and not self._watchdog_task.done():
            self._watchdog_task.cancel()
            try:
                await self._watchdog_task
            except (asyncio.CancelledError, Exception):
                pass
            self._watchdog_task = None
        await self._client.aclose()
        # Tear down the spawned bridge (if we own it). Graceful terminate
        # first, kill after 5s if it refuses — puppeteer occasionally
        # wedges on chromium shutdown and we'd rather leave a zombie
        # chromium than block Autonoma's own shutdown forever.
        if self._bridge_proc is not None and self._bridge_proc.poll() is None:
            logger.info("Stopping whatsapp-bridge sidecar (pid=%s)", self._bridge_proc.pid)
            try:
                self._bridge_proc.terminate()
                try:
                    await asyncio.to_thread(self._bridge_proc.wait, 5.0)
                except subprocess.TimeoutExpired:
                    logger.warning("whatsapp-bridge did not exit; killing")
                    self._bridge_proc.kill()
            except OSError as e:
                logger.warning("Error stopping whatsapp-bridge: %s", e)
        if self._bridge_log_handle is not None:
            try:
                self._bridge_log_handle.close()
            except OSError:
                pass
            self._bridge_log_handle = None

    async def _ensure_bridge_running(self) -> None:
        """Start the Node sidecar if nothing's listening on its port.

        If the port is already bound we assume an existing bridge (maybe
        the user's own, maybe a leftover from a crashed run) and defer to
        it. Otherwise we spawn `npm start` from the bridge dir.
        """
        parsed = urlparse(self._config.bridge_url or "http://localhost:3001")
        host = parsed.hostname or "localhost"
        port = parsed.port or 3001

        # Probe first so we don't double-spawn. 0.5s is plenty on loopback.
        try:
            with socket.create_connection((host, port), timeout=0.5):
                logger.info(
                    "whatsapp-bridge already listening on %s:%d — not spawning",
                    host, port,
                )
                return
        except OSError:
            pass

        await asyncio.to_thread(self._spawn_bridge)

    async def _run_watchdog(self) -> None:
        """Keep the bridge alive.

        Every 5 s:
          - If we own a child Popen: check whether it's still running.
            If not, log the exit code and respawn (with backoff).
          - If we don't own a child (user's own bridge, port already
            bound at start): TCP-probe the port. If it's suddenly
            unreachable, we take over — the user's bridge crashed and
            we'd rather have a working WhatsApp than spare their config.

        Backoff: 2s, 4s, 8s, capped at 60s. Resets to 0 every time the
        bridge is confirmed up. Without the cap a wedged chromium binary
        (e.g. corrupt LocalAuth dir) would push spawn attempts to hours
        between retries — that's worse than a steady 1/min ping.
        """
        max_backoff = 60.0
        while not self._stop_event.is_set():
            try:
                await asyncio.sleep(5.0)
            except asyncio.CancelledError:
                raise

            # Don't run health checks after stop() was called — race
            # between sleep completing and stop() setting the event.
            if self._stop_event.is_set():
                return

            if self._bridge_proc is not None:
                # We own the child — check its exit status.
                exit_code = self._bridge_proc.poll()
                if exit_code is None:
                    # Still running. Reset backoff so the next crash
                    # (whenever it comes) starts fresh.
                    self._restart_attempts = 0
                    continue

                # Process died. Log what we have (exit code is the most
                # actionable signal for users — puppeteer exits 1 on
                # session lock, 143 on SIGTERM we didn't send, etc.).
                logger.warning(
                    "whatsapp-bridge exited unexpectedly (code=%s, attempt=%d). "
                    "Respawning. Check bridge.log for details.",
                    exit_code, self._restart_attempts + 1,
                )
                # Alert the dashboard so users notice even if they're
                # not watching logs. Keep the message short — the full
                # context is in the Node log.
                try:
                    from autonoma.alerts import alert_manager
                    alert_manager.add_alert(
                        level="warning",
                        title="WhatsApp bridge crashed",
                        message=f"Exit code {exit_code}. Auto-respawning (attempt #{self._restart_attempts + 1}).",
                        channel="whatsapp",
                    )
                except Exception:
                    # Alerts are best-effort — never let a broken
                    # subscriber take down the watchdog itself.
                    pass

                # Clear the dead handle so _spawn_bridge can overwrite it.
                self._bridge_proc = None
                if self._bridge_log_handle is not None:
                    try:
                        self._bridge_log_handle.close()
                    except OSError:
                        pass
                    self._bridge_log_handle = None

                # Backoff before the respawn so a hard-crashing bridge
                # doesn't spin. 2^n seconds capped at max_backoff.
                self._restart_attempts += 1
                backoff = min(2.0 * (2 ** (self._restart_attempts - 1)), max_backoff)
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=backoff)
                    return  # stop() fired during backoff
                except asyncio.TimeoutError:
                    pass

                await asyncio.to_thread(self._spawn_bridge)
                continue

            # We don't own a child (port was bound at start by someone
            # else's bridge). Probe to see if that bridge is still up.
            parsed = urlparse(self._config.bridge_url or "http://localhost:3001")
            host = parsed.hostname or "localhost"
            port = parsed.port or 3001
            try:
                with socket.create_connection((host, port), timeout=1.0):
                    self._restart_attempts = 0
                    continue
            except OSError:
                # Foreign bridge died. Adopt the port — it's ours now.
                logger.warning(
                    "External whatsapp-bridge at %s:%d is down; taking over.",
                    host, port,
                )
                self._restart_attempts += 1
                backoff = min(2.0 * (2 ** (self._restart_attempts - 1)), max_backoff)
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=backoff)
                    return
                except asyncio.TimeoutError:
                    pass
                await asyncio.to_thread(self._spawn_bridge)

    def _spawn_bridge(self) -> None:
        """Synchronous spawn — called via asyncio.to_thread from start().

        Picks the configured bridge_dir if set, otherwise tries the usual
        candidates. Logs go to <bridge_dir>/bridge.log so users can tail
        them without needing a second terminal.
        """
        bridge_dir = (
            Path(self._config.bridge_dir).expanduser().resolve()
            if self._config.bridge_dir
            else _default_bridge_dir()
        )

        if not (bridge_dir / "package.json").exists():
            logger.error(
                "Cannot auto-spawn whatsapp-bridge: %s has no package.json. "
                "Install the sidecar there or set channels.whatsapp.bridge_dir.",
                bridge_dir,
            )
            return

        if not (bridge_dir / "node_modules").exists():
            logger.error(
                "whatsapp-bridge at %s has no node_modules — run `npm install` "
                "in that directory first.",
                bridge_dir,
            )
            return

        # npm.cmd on Windows, npm on POSIX. If node is installed via nvm
        # on Windows the .cmd shim is what lives on PATH.
        npm = shutil.which("npm") or shutil.which("npm.cmd")
        if not npm:
            logger.error(
                "Cannot auto-spawn whatsapp-bridge: `npm` not on PATH. "
                "Install Node.js or disable channels.whatsapp.auto_spawn_bridge."
            )
            return

        log_path = bridge_dir / "bridge.log"
        try:
            self._bridge_log_handle = open(log_path, "a", buffering=1, encoding="utf-8")
            self._bridge_log_handle.write(
                f"\n\n=== Bridge spawned by Autonoma (pid={os.getpid()}) ===\n"
            )
            self._bridge_log_handle.flush()
        except OSError as e:
            logger.warning("Could not open %s for bridge logs: %s", log_path, e)
            self._bridge_log_handle = None

        kwargs: dict = {
            "cwd": str(bridge_dir),
            "stdout": self._bridge_log_handle or subprocess.DEVNULL,
            "stderr": subprocess.STDOUT,
            "stdin": subprocess.DEVNULL,
        }
        # Put the child in its own process group so Ctrl+C in the TUI
        # terminal doesn't propagate to it (we manage its lifecycle via
        # terminate() in stop()). On POSIX that's start_new_session;
        # on Windows it's CREATE_NEW_PROCESS_GROUP.
        if sys.platform == "win32":
            kwargs["creationflags"] = 0x00000200  # CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True

        try:
            self._bridge_proc = subprocess.Popen([npm, "start"], **kwargs)  # noqa: S603
            logger.info(
                "Spawned whatsapp-bridge: pid=%d, cwd=%s, log=%s",
                self._bridge_proc.pid, bridge_dir, log_path,
            )
        except OSError as e:
            logger.error("Failed to spawn whatsapp-bridge: %s", e)
            self._bridge_proc = None
            if self._bridge_log_handle is not None:
                self._bridge_log_handle.close()
                self._bridge_log_handle = None

    async def send(self, content: str) -> None:
        pass  # Proactive send needs a chat_id; not used in request/response flow

    async def _handle_webhook(self, request: dict) -> tuple[int, dict[str, str], str]:
        """Handle inbound message from whatsapp-web.js sidecar (JSON POST)."""
        headers = {"Content-Type": "application/json"}
        data = request.get("json", {})

        sender = data.get("from", "")
        body = data.get("body", "").strip()
        push_name = data.get("pushName", "")

        if not body:
            return 200, headers, json.dumps({"status": "ignored"})

        message = Message(
            channel="whatsapp",
            channel_id=sender,
            user_id=sender,
            user_name=push_name or None,
            content=body,
        )

        logger.info("WhatsApp message from %s: %s", push_name or sender, body[:80])

        try:
            response = await self._handler(message)
            await self._send_bridge_message(sender, response.content)
        except Exception:
            logger.exception("Error handling WhatsApp message")
            await self._send_bridge_message(
                sender, "Sorry, something went wrong processing your message."
            )

        return 200, headers, json.dumps({"status": "ok"})

    async def _send_bridge_message(self, chat_id: str, text: str) -> None:
        """Send a message via the whatsapp-web.js bridge sidecar."""
        url = f"{self._config.bridge_url}/send"

        for chunk in split_message(text, max_len=4096):
            try:
                resp = await self._client.post(
                    url, json={"chatId": chat_id, "text": chunk}
                )
                if resp.status_code >= 400:
                    logger.error(
                        "Bridge send error %d: %s", resp.status_code, resp.text
                    )
            except httpx.HTTPError as exc:
                logger.error("Bridge send failed: %s", exc)
