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
    """Manages the WebSocket server and all registered channel adapters."""

    def __init__(
        self,
        config: GatewayConfig,
        router: GatewayRouter,
        auth: AuthMiddleware,
    ):
        self._config = config
        self._router = router
        self._auth = auth
        self._channels: dict[str, ChannelAdapter] = {}
        self._ws_server = None
        self._channel_tasks: list[asyncio.Task] = []

    def register_channel(self, channel: ChannelAdapter) -> None:
        self._channels[channel.name] = channel
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

        # Start all channel adapters
        for channel in self._channels.values():
            task = asyncio.create_task(
                channel.start(self._router.handle_message),
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

        # Close WebSocket server
        if self._ws_server:
            self._ws_server.close()
            await self._ws_server.wait_closed()

        logger.info("Gateway shutdown complete.")

    async def _handle_ws_connection(self, websocket, path=None) -> None:
        """Handle incoming WebSocket connections (minimal in Phase 1)."""
        # Check auth
        headers = dict(websocket.request_headers) if hasattr(websocket, 'request_headers') else {}
        if not await self._auth.authenticate(headers):
            await websocket.close(1008, "Unauthorized")
            return

        logger.info("WebSocket client connected")
        try:
            async for raw in websocket:
                try:
                    data = json.loads(raw)
                    await websocket.send(
                        json.dumps({"status": "ok", "message": "WebSocket channel not fully implemented in Phase 1"})
                    )
                except json.JSONDecodeError:
                    await websocket.send(
                        json.dumps({"error": "Invalid JSON"})
                    )
        except websockets.exceptions.ConnectionClosed:
            logger.info("WebSocket client disconnected")

    async def wait_for_channels(self) -> None:
        """Wait for all channel tasks to complete (blocks until shutdown)."""
        if self._channel_tasks:
            await asyncio.gather(*self._channel_tasks, return_exceptions=True)
