"""WhatsApp channel — Twilio API via httpx, webhook on shared HTTP server."""

from __future__ import annotations

import asyncio
import logging

import httpx

from autonoma.config import WhatsAppConfig
from autonoma.gateway.channels._http_server import HTTPServer
from autonoma.gateway.channels._util import split_message
from autonoma.gateway.channels.base import ChannelAdapter, MessageHandler
from autonoma.schema import Message

logger = logging.getLogger(__name__)

TWILIO_API = "https://api.twilio.com/2010-04-01"


class WhatsAppChannel(ChannelAdapter):
    """WhatsApp bot using Twilio REST API + inbound webhook."""

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
        pass

    async def _handle_webhook(self, request: dict) -> tuple[int, dict[str, str], str]:
        """Handle inbound Twilio webhook (form-encoded POST)."""
        form = request.get("form_data", {})
        sender = form.get("From", "")
        body = form.get("Body", "").strip()

        if not body:
            return 200, {"Content-Type": "text/xml"}, "<Response></Response>"

        message = Message(
            channel="whatsapp",
            channel_id=sender,
            user_id=sender,
            user_name=form.get("ProfileName"),
            content=body,
        )

        response = await self._handler(message)

        # Send reply via Twilio REST API
        await self._send_twilio_message(sender, response.content)

        # Return empty TwiML so Twilio doesn't send a duplicate
        return 200, {"Content-Type": "text/xml"}, "<Response></Response>"

    async def _send_twilio_message(self, to: str, body: str) -> None:
        """Send a WhatsApp message via Twilio REST API."""
        url = f"{TWILIO_API}/Accounts/{self._config.twilio_account_sid}/Messages.json"
        auth = (self._config.twilio_account_sid, self._config.twilio_auth_token)

        for chunk in split_message(body, max_len=1600):
            resp = await self._client.post(
                url,
                auth=auth,
                data={
                    "From": self._config.twilio_phone_number,
                    "To": to,
                    "Body": chunk,
                },
            )
            if resp.status_code >= 400:
                logger.error("Twilio send error %d: %s", resp.status_code, resp.text)
