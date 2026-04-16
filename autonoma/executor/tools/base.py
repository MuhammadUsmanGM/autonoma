"""Base tool interface for all Autonoma tools."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal


PermissionLevel = Literal["safe", "cautious", "dangerous"]


@dataclass
class ToolPermission:
    """Declares what a tool is allowed to do."""
    level: PermissionLevel = "safe"
    network: bool = False       # Can make outbound network requests
    filesystem: bool = False    # Can read/write files
    shell: bool = False         # Can execute shell commands
    secrets: bool = False       # Accesses API keys or credentials
    description: str = ""       # Human-readable explanation


class BaseTool(ABC):
    """Abstract base for all tools the agent can invoke."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def description(self) -> str: ...

    @property
    @abstractmethod
    def input_schema(self) -> dict[str, Any]:
        """JSON Schema for the tool's input parameters."""
        ...

    @property
    def permissions(self) -> ToolPermission:
        """Declare what this tool needs. Override in subclasses."""
        return ToolPermission()

    @abstractmethod
    async def execute(self, params: dict[str, Any]) -> str:
        """Execute the tool and return a text result."""
        ...

    def to_definition(self) -> dict[str, Any]:
        """Convert to Anthropic tool definition format for LLM."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }

    def to_manifest(self) -> dict[str, Any]:
        """Export permission manifest for auditing."""
        p = self.permissions
        return {
            "name": self.name,
            "description": self.description,
            "permissions": {
                "level": p.level,
                "network": p.network,
                "filesystem": p.filesystem,
                "shell": p.shell,
                "secrets": p.secrets,
                "description": p.description,
            },
        }
