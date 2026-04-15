"""Telegram bot channel — long-polling via python-telegram-bot."""

from __future__ import annotations

import asyncio
import logging

from autonoma.config import TelegramConfig
from autonoma.gateway.channels._util import split_message
from autonoma.gateway.channels.base import ChannelAdapter, MessageHandler
from autonoma.schema import Message

logger = logging.getLogger(__name__)


class TelegramChannel(ChannelAdapter):
    """Telegram bot using python-telegram-bot v22+ (async, httpx-based)."""

    def __init__(self, config: TelegramConfig):
        self._config = config
        self._handler: MessageHandler | None = None
        self._app = None
        self._stop_event = asyncio.Event()

    @property
    def name(self) -> str:
        return "telegram"

    async def start(self, message_handler: MessageHandler) -> None:
        self._handler = message_handler

        try:
            from telegram import Update
            from telegram.ext import (
                ApplicationBuilder,
                ContextTypes,
                MessageHandler as TGHandler,
                filters,
            )
        except ImportError:
            logger.error(
                "python-telegram-bot not installed. "
                "Install it with: pip install python-telegram-bot"
            )
            return

        async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
            if not update.message or not update.message.text:
                return

            logger.info(
                "Telegram message from %s: %s",
                update.effective_user.first_name,
                update.message.text[:80],
            )

            message = Message(
                channel="telegram",
                channel_id=str(update.effective_chat.id),
                user_id=str(update.effective_user.id),
                user_name=update.effective_user.first_name,
                content=update.message.text,
            )

            try:
                response = await self._handler(message)
                for chunk in split_message(response.content, max_len=4096):
                    await update.message.reply_text(chunk)
            except Exception:
                logger.exception("Error handling Telegram message")
                await update.message.reply_text(
                    "Sorry, something went wrong processing your message."
                )

        async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
            logger.error("Telegram error: %s", context.error, exc_info=context.error)

        self._app = ApplicationBuilder().token(self._config.bot_token).build()
        self._app.add_handler(TGHandler(filters.TEXT & ~filters.COMMAND, on_message))
        self._app.add_error_handler(on_error)

        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling(drop_pending_updates=True)

        logger.info("Telegram bot started (long-polling)")
        await self._stop_event.wait()

    async def stop(self) -> None:
        self._stop_event.set()
        if self._app:
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()

    async def send(self, content: str) -> None:
        pass  # Proactive send needs a chat_id; not used in request/response flow
