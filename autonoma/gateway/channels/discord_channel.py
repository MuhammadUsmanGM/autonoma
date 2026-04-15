"""Discord bot channel — raw Gateway + REST API, zero external deps."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from autonoma.config import DiscordConfig
from autonoma.gateway.channels._discord_gateway import DiscordGateway
from autonoma.gateway.channels._util import split_message
from autonoma.gateway.channels.base import ChannelAdapter, MessageHandler
from autonoma.schema import Message

logger = logging.getLogger(__name__)

DISCORD_API = "https://discord.com/api/v10"


class DiscordChannel(ChannelAdapter):
    """Discord bot using raw Gateway WebSocket + REST API."""

    def __init__(self, config: DiscordConfig):
        self._config = config
        self._handler: MessageHandler | None = None
        self._gateway: DiscordGateway | None = None
        self._http = httpx.AsyncClient(
            base_url=DISCORD_API,
            headers={"Authorization": f"Bot {config.bot_token}"},
            timeout=30.0,
        )
        self._bot_user_id: str | None = None

    @property
    def name(self) -> str:
        return "discord"

    async def start(self, message_handler: MessageHandler) -> None:
        self._handler = message_handler
        self._gateway = DiscordGateway(self._config.bot_token, self._on_event)
        await self._gateway.connect()

    async def stop(self) -> None:
        if self._gateway:
            await self._gateway.disconnect()
        await self._http.aclose()

    async def send(self, content: str) -> None:
        pass

    async def _on_event(self, event: str, data: dict[str, Any]) -> None:
        if event == "READY":
            self._bot_user_id = data.get("user", {}).get("id")
            logger.info("Discord bot user ID: %s", self._bot_user_id)
            return

        if event != "MESSAGE_CREATE":
            return

        # Skip bot's own messages
        author = data.get("author", {})
        if author.get("bot") or author.get("id") == self._bot_user_id:
            return

        content = data.get("content", "").strip()
        if not content:
            return

        message = Message(
            channel="discord",
            channel_id=str(data["channel_id"]),
            user_id=str(author["id"]),
            user_name=author.get("username"),
            content=content,
        )

        response = await self._handler(message)

        # Send reply, splitting at Discord's 2000-char limit
        channel_id = data["channel_id"]
        for chunk in split_message(response.content, max_len=2000):
            await self._http.post(
                f"/channels/{channel_id}/messages",
                json={"content": chunk},
            )
