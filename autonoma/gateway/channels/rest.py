"""REST API channel — POST /api/chat for programmatic access."""

from __future__ import annotations

import asyncio
import json
import logging

from autonoma.config import RESTConfig
from autonoma.gateway.channels._http_server import HTTPServer
from autonoma.gateway.channels.base import ChannelAdapter, MessageHandler
from autonoma.schema import Message

logger = logging.getLogger(__name__)


class RESTChannel(ChannelAdapter):
    """HTTP JSON endpoint for agent interaction."""

    def __init__(self, config: RESTConfig, http_server: HTTPServer):
        self._config = config
        self._http = http_server
        self._handler: MessageHandler | None = None
        self._stop_event = asyncio.Event()

    @property
    def name(self) -> str:
        return "rest"

    async def start(self, message_handler: MessageHandler) -> None:
        self._handler = message_handler
        self._http.add_route("POST", "/api/chat", self._handle_request)
        logger.info("REST API channel ready at POST /api/chat")
        await self._stop_event.wait()

    async def stop(self) -> None:
        self._stop_event.set()

    async def send(self, content: str) -> None:
        pass  # REST is request/response only

    async def _handle_request(self, request: dict) -> tuple[int, dict[str, str], str]:
        headers = {"Content-Type": "application/json"}

        # Auth check
        if self._config.api_token:
            auth_header = request["headers"].get("authorization", "")
            if auth_header != f"Bearer {self._config.api_token}":
                return 401, headers, json.dumps({"error": "Unauthorized"})

        # Parse body
        data = request.get("json", {})
        content = data.get("message", "").strip()
        if not content:
            return 400, headers, json.dumps({"error": "Missing 'message' field"})

        user_id = data.get("user_id", "api_user")
        channel_id = data.get("channel_id", f"rest_{user_id}")

        message = Message(
            channel="rest",
            channel_id=channel_id,
            user_id=user_id,
            user_name=data.get("user_name"),
            content=content,
        )

        response = await self._handler(message)

        return 200, headers, json.dumps({
            "response": response.content,
            "metadata": response.metadata,
        })
