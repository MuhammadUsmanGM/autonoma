"""Google Gemini provider using the native Generative Language API."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx

from autonoma.models.provider import LLMProvider
from autonoma.schema import ContentBlock, LLMMessage, LLMResponse, ToolCall


class GoogleProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "gemini-2.5-flash"):
        self._api_key = api_key
        self._model = model
        self._client = httpx.AsyncClient(
            base_url="https://generativelanguage.googleapis.com/v1beta",
            timeout=120.0,
        )

    @property
    def name(self) -> str:
        return "google"

    async def chat(
        self, messages: list[LLMMessage], *, system_prompt: str | None = None,
        tools: list[dict] | None = None, temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        contents = self._build_contents(messages)
        payload: dict = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }
        if system_prompt:
            payload["systemInstruction"] = {"parts": [{"text": system_prompt}]}
        if tools:
            payload["tools"] = [{"functionDeclarations": [self._tool_schema(t) for t in tools]}]

        response = await self._client.post(
            f"/models/{self._model}:generateContent",
            params={"key": self._api_key}, json=payload,
        )
        response.raise_for_status()
        return self._parse_response(response.json())

    async def stream(
        self, messages: list[LLMMessage], *, system_prompt: str | None = None,
        temperature: float = 0.7, max_tokens: int = 4096,
    ) -> AsyncIterator[str]:
        result = await self.chat(
            messages, system_prompt=system_prompt, temperature=temperature,
            max_tokens=max_tokens,
        )
        yield result.text

    @staticmethod
    def _tool_schema(tool: dict) -> dict:
        schema = tool.get("input_schema", {})
        return {
            "name": tool["name"],
            "description": tool.get("description", ""),
            "parameters": schema,
        }

    def _build_contents(self, messages: list[LLMMessage]) -> list[dict]:
        contents: list[dict] = []
        for message in messages:
            if message.role == "system":
                continue
            role = "model" if message.role == "assistant" else "user"
            parts: list[dict] = []
            if isinstance(message.content, str):
                parts.append({"text": message.content})
            else:
                for block in message.content:
                    if block.get("type") == "text":
                        parts.append({"text": block.get("text", "")})
                    elif block.get("type") == "tool_use":
                        parts.append({"functionCall": {
                            "name": block["name"], "args": block.get("input", {}),
                        }})
                    elif block.get("type") == "tool_result":
                        tool_id = block.get("tool_use_id", "tool")
                        function_name = tool_id.removeprefix("google:")
                        parts.append({"functionResponse": {
                            "name": function_name,
                            "response": {"content": block.get("content", "")},
                        }})
            if parts:
                contents.append({"role": role, "parts": parts})
        return contents

    def _parse_response(self, data: dict) -> LLMResponse:
        parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
        blocks: list[ContentBlock] = []
        for part in parts:
            if part.get("text"):
                blocks.append(ContentBlock(type="text", text=part["text"]))
            if call := part.get("functionCall"):
                blocks.append(ContentBlock(
                    type="tool_use",
                    tool_call=ToolCall(
                        id=f"google:{call['name']}", name=call["name"],
                        input=call.get("args", {}),
                    ),
                ))
        usage = data.get("usageMetadata") or {}
        return LLMResponse(
            content=blocks,
            stop_reason="tool_use" if any(b.type == "tool_use" for b in blocks) else "end_turn",
            usage={
                "input_tokens": int(usage.get("promptTokenCount", 0) or 0),
                "output_tokens": int(usage.get("candidatesTokenCount", 0) or 0),
            },
            model=self._model,
        )