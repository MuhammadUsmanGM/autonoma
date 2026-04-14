"""Skill registry — collects tools and generates LLM tool definitions."""

from __future__ import annotations

import logging
from typing import Any

from autonoma.executor.tools.base import BaseTool

logger = logging.getLogger(__name__)


class SkillRegistry:
    """Central registry for all available tools/skills."""

    def __init__(self):
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool
        logger.info("Registered skill: %s", tool.name)

    def get_tool(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        """Generate tool definitions in Anthropic format for the LLM."""
        return [tool.to_definition() for tool in self._tools.values()]

    def get_tool_names(self) -> list[str]:
        return list(self._tools.keys())

    def get_tool_descriptions(self) -> str:
        """Human-readable tool listing for system prompt injection."""
        if not self._tools:
            return "(No tools available.)"
        lines = []
        for tool in self._tools.values():
            lines.append(f"- **{tool.name}**: {tool.description}")
        return "\n".join(lines)
