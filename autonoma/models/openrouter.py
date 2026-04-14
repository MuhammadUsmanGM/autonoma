"""OpenRouter LLM provider — access Claude, GPT-4o, Gemini, Llama, etc. via one API."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx

from autonoma.models.provider import LLMProvider
from autonoma.schema import LLMMessage

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


class OpenRouterProvider(LLMProvider):
    """OpenRouter adapter using the OpenAI-compatible API format."""

    def __init__(
        self,
        api_key: str,
        model: str = "anthropic/claude-sonnet-4-6",
        app_name: str = "Autonoma",
    ):
        self._api_key = api_key
        self._model = model
        self._app_name = app_name
        self._client = httpx.AsyncClient(
            base_url=OPENROUTER_BASE_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "X-Title": app_name,
                "Content-Type": "application/json",
            },
            timeout=120.0,
        )

    @property
    def name(self) -> str:
        return "openrouter"

    async def chat(
        self,
        messages: list[LLMMessage],
        *,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> str:
        api_messages = []
        if system_prompt:
            api_messages.append({"role": "system", "content": system_prompt})
        for m in messages:
            if m.role != "system":
                api_messages.append({"role": m.role, "content": m.content})

        payload = {
            "model": self._model,
            "messages": api_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        response = await self._client.post("/chat/completions", json=payload)
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]

    async def stream(
        self,
        messages: list[LLMMessage],
        *,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> AsyncIterator[str]:
        api_messages = []
        if system_prompt:
            api_messages.append({"role": "system", "content": system_prompt})
        for m in messages:
            if m.role != "system":
                api_messages.append({"role": m.role, "content": m.content})

        payload = {
            "model": self._model,
            "messages": api_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }

        async with self._client.stream(
            "POST", "/chat/completions", json=payload
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                chunk = line[6:]
                if chunk.strip() == "[DONE]":
                    break
                try:
                    data = json.loads(chunk)
                    delta = data["choices"][0].get("delta", {})
                    if content := delta.get("content"):
                        yield content
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue
