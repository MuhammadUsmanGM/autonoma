"""Anthropic (Claude) LLM provider."""

from __future__ import annotations

from collections.abc import AsyncIterator

import anthropic

from autonoma.models.provider import LLMProvider
from autonoma.schema import ContentBlock, LLMMessage, LLMResponse, ToolCall


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
        tools: list[dict] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        api_messages = self._build_messages(messages)

        kwargs = {
            "model": self._model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system_prompt or "",
            "messages": api_messages,
        }
        if tools:
            kwargs["tools"] = tools

        response = await self._client.messages.create(**kwargs)
        return self._parse_response(response)

    async def stream(
        self,
        messages: list[LLMMessage],
        *,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> AsyncIterator[str]:
        api_messages = self._build_messages(messages)

        async with self._client.messages.stream(
            model=self._model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_prompt or "",
            messages=api_messages,
        ) as stream:
            async for text in stream.text_stream:
                yield text

    def _build_messages(self, messages: list[LLMMessage]) -> list[dict]:
        """Convert LLMMessage list to Anthropic API format."""
        api_messages = []
        for m in messages:
            if m.role == "system":
                continue
            if isinstance(m.content, list):
                # Tool result blocks — pass as structured content
                api_messages.append({"role": m.role, "content": m.content})
            else:
                api_messages.append({"role": m.role, "content": m.content})
        return api_messages

    def _parse_response(self, response) -> LLMResponse:
        """Parse Anthropic response into LLMResponse."""
        blocks = []
        for block in response.content:
            if block.type == "text":
                blocks.append(ContentBlock(type="text", text=block.text))
            elif block.type == "tool_use":
                tc = ToolCall(id=block.id, name=block.name, input=block.input)
                blocks.append(ContentBlock(type="tool_use", tool_call=tc))

        # Usage comes back as a typed Usage object on the SDK response; we
        # defensively getattr so older SDKs (or mocks in tests) without the
        # attribute still work.
        usage: dict[str, int] | None = None
        raw_usage = getattr(response, "usage", None)
        if raw_usage is not None:
            usage = {
                "input_tokens": int(getattr(raw_usage, "input_tokens", 0) or 0),
                "output_tokens": int(getattr(raw_usage, "output_tokens", 0) or 0),
            }

        return LLMResponse(
            content=blocks,
            stop_reason=response.stop_reason,
            usage=usage,
            model=getattr(response, "model", "") or self._model,
        )
