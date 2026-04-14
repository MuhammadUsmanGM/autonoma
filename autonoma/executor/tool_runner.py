"""Tool runner — dispatches tool calls and collects results."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from autonoma.executor.sandbox import Sandbox
from autonoma.executor.tools.base import BaseTool
from autonoma.schema import ToolCall, ToolResult

logger = logging.getLogger(__name__)


class ToolRunner:
    """Dispatches tool calls to registered tools, enforces sandbox."""

    def __init__(self, sandbox: Sandbox):
        self._sandbox = sandbox
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool
        logger.info("Registered tool: %s", tool.name)

    def get_tool(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def list_tools(self) -> list[str]:
        return list(self._tools.keys())

    async def execute(self, tool_call: ToolCall) -> ToolResult:
        """Execute a tool call and return the result."""
        tool = self._tools.get(tool_call.name)
        if not tool:
            logger.warning("Unknown tool requested: %s", tool_call.name)
            return ToolResult(
                tool_use_id=tool_call.id,
                content=f"Error: Unknown tool '{tool_call.name}'. Available tools: {', '.join(self._tools.keys())}",
                is_error=True,
            )

        logger.info("Executing tool: %s (id=%s)", tool_call.name, tool_call.id)
        logger.debug("Tool input: %s", tool_call.input)

        try:
            result = await asyncio.wait_for(
                tool.execute(tool_call.input),
                timeout=self._sandbox.timeout,
            )
            logger.info("Tool %s completed successfully", tool_call.name)
            return ToolResult(
                tool_use_id=tool_call.id,
                content=result,
                is_error=False,
            )
        except asyncio.TimeoutError:
            msg = f"Tool '{tool_call.name}' timed out after {self._sandbox.timeout}s"
            logger.error(msg)
            return ToolResult(
                tool_use_id=tool_call.id,
                content=msg,
                is_error=True,
            )
        except Exception as e:
            msg = f"Tool '{tool_call.name}' failed: {e}"
            logger.error(msg, exc_info=True)
            return ToolResult(
                tool_use_id=tool_call.id,
                content=msg,
                is_error=True,
            )
