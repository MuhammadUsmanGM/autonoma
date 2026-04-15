"""WhatsApp channel — talks to local whatsapp-web.js sidecar."""

from __future__ import annotations

import asyncio
import json
import logging

import httpx

from autonoma.config import WhatsAppConfig
from autonoma.gateway.channels._http_server import HTTPServer
from autonoma.gateway.channels._util import split_message
from autonoma.gateway.channels.base import ChannelAdapter, MessageHandler
from autonoma.schema import Message

logger = logging.getLogger(__name__)


class WhatsAppChannel(ChannelAdapter):
    """WhatsApp channel via local whatsapp-web.js bridge sidecar."""

    def __init__(self, config: WhatsAppConfig, http_server: HTTPServer):
        self._config = config
        self._http_server = http_server
        self._handler: MessageHandler | None = None
        self._client = httpx.AsyncClient(timeout=30.0)
        self._stop_event = asyncio.Event()

    @property
    def name(self) -> str:
        return "whatsapp"

    async def start(self, message_handler: MessageHandler) -> None:
        self._handler = message_handler
        self._http_server.add_route(
            "POST", self._config.webhook_path, self._handle_webhook
        )
        logger.info("WhatsApp webhook registered at %s", self._config.webhook_path)
        await self._stop_event.wait()

    async def stop(self) -> None:
        self._stop_event.set()
        await self._client.aclose()

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
