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

    role: str  # "system", "user", "assistant"
    content: str


@dataclass
class LLMOptions:
    """Options for LLM inference calls."""

    model: str | None = None
    temperature: float = 0.7
    max_tokens: int = 4096
    system_prompt: str | None = None


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
