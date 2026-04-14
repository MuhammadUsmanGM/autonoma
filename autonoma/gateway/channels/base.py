"""Abstract channel adapter interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable

from autonoma.schema import AgentResponse, Message


# Type for the message handler callback
MessageHandler = Callable[[Message], Awaitable[AgentResponse]]


class ChannelAdapter(ABC):
    """Base class for all channel adapters (CLI, Telegram, API, etc.)."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Channel identifier, e.g., 'cli', 'telegram'."""
        ...

    @abstractmethod
    async def start(self, message_handler: MessageHandler) -> None:
        """Start the channel. Call message_handler for each incoming message."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Gracefully shut down the channel."""
        ...

    @abstractmethod
    async def send(self, content: str) -> None:
        """Send a message to the user through this channel."""
        ...
