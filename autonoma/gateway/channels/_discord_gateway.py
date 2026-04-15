"""Minimal Discord Gateway v10 client using websockets + httpx."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable, Awaitable

import httpx
import websockets

logger = logging.getLogger(__name__)

DISCORD_API = "https://discord.com/api/v10"
GATEWAY_VERSION = "10"
GATEWAY_ENCODING = "json"

# Intents: GUILD_MESSAGES (1<<9) | DIRECT_MESSAGES (1<<12) | MESSAGE_CONTENT (1<<15)
DEFAULT_INTENTS = (1 << 9) | (1 << 12) | (1 << 15)  # 33280

# Gateway opcodes
OP_DISPATCH = 0
OP_HEARTBEAT = 1
OP_IDENTIFY = 2
OP_RESUME = 6
OP_RECONNECT = 7
OP_INVALID_SESSION = 9
OP_HELLO = 10
OP_HEARTBEAT_ACK = 11


class DiscordGateway:
    """Connects to Discord Gateway, maintains heartbeat, dispatches events."""

    def __init__(
        self,
        token: str,
        on_event: Callable[[str, dict[str, Any]], Awaitable[None]],
        intents: int = DEFAULT_INTENTS,
    ):
        self._token = token
        self._on_event = on_event
        self._intents = intents
        self._ws: Any = None
        self._heartbeat_interval: float = 41.25
        self._sequence: int | None = None
        self._session_id: str | None = None
        self._running = False
        self._heartbeat_task: asyncio.Task | None = None

    async def connect(self) -> None:
        """Connect to the Discord Gateway and start listening."""
        self._running = True

        # Get gateway URL
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{DISCORD_API}/gateway/bot",
                headers={"Authorization": f"Bot {self._token}"},
            )
            resp.raise_for_status()
            gateway_url = resp.json()["url"]

        url = f"{gateway_url}?v={GATEWAY_VERSION}&encoding={GATEWAY_ENCODING}"

        while self._running:
            try:
                await self._run_connection(url)
            except (websockets.exceptions.ConnectionClosed, OSError) as e:
                if not self._running:
                    break
                logger.warning("Discord Gateway disconnected: %s. Reconnecting in 5s...", e)
                await asyncio.sleep(5)

    async def _run_connection(self, url: str) -> None:
        """Run a single Gateway connection lifecycle."""
        async with websockets.connect(url) as ws:
            self._ws = ws

            # Wait for Hello
            hello = json.loads(await ws.recv())
            if hello.get("op") != OP_HELLO:
                logger.error("Expected Hello, got op=%s", hello.get("op"))
                return

            self._heartbeat_interval = hello["d"]["heartbeat_interval"] / 1000.0
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

            # Identify
            await self._send(OP_IDENTIFY, {
                "token": self._token,
                "intents": self._intents,
                "properties": {
                    "os": "linux",
                    "browser": "autonoma",
                    "device": "autonoma",
                },
            })

            # Listen for events
            async for raw in ws:
                payload = json.loads(raw)
                op = payload.get("op")
                data = payload.get("d")
                event = payload.get("t")

                if payload.get("s") is not None:
                    self._sequence = payload["s"]

                if op == OP_DISPATCH and event:
                    if event == "READY":
                        self._session_id = data.get("session_id")
                        logger.info("Discord Gateway READY (session=%s)", self._session_id)
                    await self._on_event(event, data or {})

                elif op == OP_HEARTBEAT:
                    await self._send(OP_HEARTBEAT, self._sequence)

                elif op == OP_RECONNECT:
                    logger.info("Discord requested reconnect")
                    break

                elif op == OP_INVALID_SESSION:
                    logger.warning("Invalid session, re-identifying in 3s")
                    await asyncio.sleep(3)
                    self._sequence = None
                    self._session_id = None
                    break

        # Clean up heartbeat
        if self._heartbeat_task:
            self._heartbeat_task.cancel()

    async def _heartbeat_loop(self) -> None:
        """Send periodic heartbeats to keep the connection alive."""
        try:
            while self._running:
                await asyncio.sleep(self._heartbeat_interval)
                if self._ws:
                    await self._send(OP_HEARTBEAT, self._sequence)
        except asyncio.CancelledError:
            pass

    async def _send(self, op: int, d: Any) -> None:
        if self._ws:
            await self._ws.send(json.dumps({"op": op, "d": d}))

    async def disconnect(self) -> None:
        self._running = False
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
        if self._ws:
            await self._ws.close()
