"""Abstract LLM provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from autonoma.schema import LLMMessage


class LLMProvider(ABC):
    """Base class for all LLM providers."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    async def chat(
        self,
        messages: list[LLMMessage],
        *,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> str:
        """Send messages and get a text completion."""
        ...

    async def stream(
        self,
        messages: list[LLMMessage],
        *,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> AsyncIterator[str]:
        """Stream tokens. Default implementation yields the full response."""
        result = await self.chat(
            messages,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        yield result
