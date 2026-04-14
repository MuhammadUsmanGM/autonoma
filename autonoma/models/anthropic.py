"""Anthropic (Claude) LLM provider."""

from __future__ import annotations

from collections.abc import AsyncIterator

import anthropic

from autonoma.models.provider import LLMProvider
from autonoma.schema import LLMMessage


class AnthropicProvider(LLMProvider):
    """Claude adapter using the official Anthropic SDK."""

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-6"):
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model

    @property
    def name(self) -> str:
        return "anthropic"

    async def chat(
        self,
        messages: list[LLMMessage],
        *,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> str:
        api_messages = [
            {"role": m.role, "content": m.content}
            for m in messages
            if m.role != "system"
        ]

        response = await self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_prompt or "",
            messages=api_messages,
        )
        return response.content[0].text

    async def stream(
        self,
        messages: list[LLMMessage],
        *,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> AsyncIterator[str]:
        api_messages = [
            {"role": m.role, "content": m.content}
            for m in messages
            if m.role != "system"
        ]

        async with self._client.messages.stream(
            model=self._model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_prompt or "",
            messages=api_messages,
        ) as stream:
            async for text in stream.text_stream:
                yield text
