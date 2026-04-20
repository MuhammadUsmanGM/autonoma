"""Core data models for the Autonoma agent platform."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Literal
from uuid import uuid4


@dataclass
class Message:
    """Unified message format across all channels."""

    channel: str  # "cli", "telegram", "api", etc.
    channel_id: str
    user_id: str
    content: str
    id: str = field(default_factory=lambda: uuid4().hex[:16])
    user_name: str | None = None
    timestamp: datetime = field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentResponse:
    """Response from the agent back to a channel."""

    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMMessage:
    """A single message in the LLM conversation format."""

    role: str  # "system", "user", "assistant", "tool"
    content: str | list[dict[str, Any]] = ""  # str for text, list for tool_result blocks
    tool_call_id: str | None = None  # For role="tool" messages (OpenAI format)


@dataclass
class ToolCall:
    """A tool invocation requested by the LLM."""

    id: str
    name: str
    input: dict[str, Any]


@dataclass
class ToolResult:
    """Result from executing a tool."""

    tool_use_id: str  # Matches ToolCall.id
    content: str
    is_error: bool = False


@dataclass
class ContentBlock:
    """A single content block from an LLM response."""

    type: str  # "text" or "tool_use"
    text: str | None = None
    tool_call: ToolCall | None = None


@dataclass
class LLMResponse:
    """Full response from LLM — text + tool calls + metadata."""

    content: list[ContentBlock]
    stop_reason: str  # "end_turn", "tool_use", "max_tokens", "stop"
    usage: dict[str, int] | None = None  # {"input_tokens": N, "output_tokens": N}
    model: str = ""  # model slug the provider actually answered with

    @property
    def text(self) -> str:
        """Combined text from all text blocks."""
        parts = [b.text for b in self.content if b.type == "text" and b.text]
        return "\n".join(parts)

    @property
    def tool_calls(self) -> list[ToolCall]:
        """All tool_use blocks from the response."""
        return [b.tool_call for b in self.content if b.type == "tool_use" and b.tool_call]

    @property
    def has_tool_calls(self) -> bool:
        return self.stop_reason == "tool_use" and len(self.tool_calls) > 0


@dataclass
class LLMOptions:
    """Options for LLM inference calls."""

    model: str | None = None
    temperature: float = 0.7
    max_tokens: int = 4096
    system_prompt: str | None = None


@dataclass
class MemoryEntry:
    """A single memory record from the database."""

    id: int
    content: str
    type: str  # "fact", "preference", "remember", "conversation_summary"
    source: str
    importance: float
    created_at: str
    accessed_at: str
    access_count: int
    active: bool = True
    relevance_score: float = 0.0  # BM25 score, set during retrieval


@dataclass
class SessionEntry:
    """One line in a JSONL session file."""

    role: str  # "user", "assistant"
    content: str
    channel: str
    user_id: str
    id: str = field(default_factory=lambda: uuid4().hex[:12])
    timestamp: datetime = field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        """Serialize to JSON string for JSONL storage."""
        d = asdict(self)
        d["timestamp"] = self.timestamp.isoformat()
        return json.dumps(d)

    @classmethod
    def from_json(cls, raw: str) -> SessionEntry:
        """Deserialize from JSON string."""
        d = json.loads(raw)
        d["timestamp"] = datetime.fromisoformat(d["timestamp"])
        return cls(**d)
