"""OpenRouter LLM provider — access Claude, GPT-4o, Gemini, Llama, etc. via one API."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx

from autonoma.models.provider import LLMProvider
from autonoma.schema import ContentBlock, LLMMessage, LLMResponse, ToolCall

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
        tools: list[dict] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        api_messages = self._build_messages(messages, system_prompt)

        payload = {
            "model": self._model,
            "messages": api_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            # Convert Anthropic tool format to OpenAI format
            payload["tools"] = self._convert_tools(tools)

        response = await self._client.post("/chat/completions", json=payload)
        response.raise_for_status()
        data = response.json()
        return self._parse_response(data)

    async def stream(
        self,
        messages: list[LLMMessage],
        *,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> AsyncIterator[str]:
        api_messages = self._build_messages(messages, system_prompt)

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

    def _build_messages(
        self, messages: list[LLMMessage], system_prompt: str | None = None
    ) -> list[dict]:
        """Convert LLMMessage list to OpenAI API format.

        Handles Anthropic-format structured content blocks (tool_use in
        assistant messages, tool_result in user messages) and converts
        them to the OpenAI function-calling format.
        """
        api_messages = []
        if system_prompt:
            api_messages.append({"role": "system", "content": system_prompt})

        for m in messages:
            if m.role == "system":
                continue
            if m.role == "tool":
                # Already in OpenAI tool format
                api_messages.append({
                    "role": "tool",
                    "tool_call_id": m.tool_call_id or "",
                    "content": m.content if isinstance(m.content, str) else json.dumps(m.content),
                })
            elif isinstance(m.content, list):
                if m.role == "assistant":
                    # Anthropic-format assistant message with tool_use blocks
                    # → convert to OpenAI assistant message with tool_calls array
                    self._convert_assistant_blocks(api_messages, m.content)
                elif m.role == "user":
                    # Anthropic-format user message with tool_result blocks
                    # → convert to separate role="tool" messages (OpenAI format)
                    self._convert_tool_result_blocks(api_messages, m.content)
                else:
                    # Fallback: extract text
                    text_parts = [
                        b.get("text", "") for b in m.content if b.get("type") == "text"
                    ]
                    api_messages.append({"role": m.role, "content": "\n".join(text_parts)})
            else:
                api_messages.append({"role": m.role, "content": m.content})

        return api_messages

    def _convert_assistant_blocks(
        self, api_messages: list[dict], blocks: list[dict]
    ) -> None:
        """Convert Anthropic assistant content blocks to OpenAI format.

        Anthropic: [{"type":"text","text":"..."}, {"type":"tool_use","id":"...","name":"...","input":{}}]
        OpenAI:    {"role":"assistant","content":"...","tool_calls":[{"id":"...","type":"function","function":{"name":"...","arguments":"..."}}]}
        """
        text_parts = []
        tool_calls = []

        for block in blocks:
            if block.get("type") == "text" and block.get("text"):
                text_parts.append(block["text"])
            elif block.get("type") == "tool_use":
                tool_calls.append({
                    "id": block["id"],
                    "type": "function",
                    "function": {
                        "name": block["name"],
                        "arguments": json.dumps(block.get("input", {})),
                    },
                })

        msg: dict = {"role": "assistant"}
        msg["content"] = "\n".join(text_parts) if text_parts else None
        if tool_calls:
            msg["tool_calls"] = tool_calls
        api_messages.append(msg)

    def _convert_tool_result_blocks(
        self, api_messages: list[dict], blocks: list[dict]
    ) -> None:
        """Convert Anthropic tool_result content blocks to OpenAI format.

        Anthropic: [{"type":"tool_result","tool_use_id":"...","content":"..."}]  (single user message)
        OpenAI:    [{"role":"tool","tool_call_id":"...","content":"..."}]  (one message per result)
        """
        for block in blocks:
            if block.get("type") == "tool_result":
                api_messages.append({
                    "role": "tool",
                    "tool_call_id": block["tool_use_id"],
                    "content": block.get("content", ""),
                })

    def _convert_tools(self, anthropic_tools: list[dict]) -> list[dict]:
        """Convert Anthropic tool format to OpenAI function-calling format."""
        openai_tools = []
        for tool in anthropic_tools:
            openai_tools.append({
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": tool.get("input_schema", {}),
                },
            })
        return openai_tools

    def _parse_response(self, data: dict) -> LLMResponse:
        """Parse OpenAI-format response into LLMResponse."""
        choice = data["choices"][0]
        message = choice["message"]
        finish_reason = choice.get("finish_reason", "stop")

        blocks: list[ContentBlock] = []

        # Text content
        if text := message.get("content"):
            blocks.append(ContentBlock(type="text", text=text))

        # Tool calls
        if tool_calls := message.get("tool_calls"):
            for tc in tool_calls:
                func = tc["function"]
                args = func.get("arguments", "{}")
                if isinstance(args, str):
                    args = json.loads(args)
                tool_call = ToolCall(
                    id=tc["id"],
                    name=func["name"],
                    input=args,
                )
                blocks.append(ContentBlock(type="tool_use", tool_call=tool_call))

        # Map OpenAI finish reasons to our format
        stop_reason = "end_turn"
        if finish_reason == "tool_calls":
            stop_reason = "tool_use"
        elif finish_reason == "length":
            stop_reason = "max_tokens"
        elif tool_calls:
            stop_reason = "tool_use"

        return LLMResponse(content=blocks, stop_reason=stop_reason)
