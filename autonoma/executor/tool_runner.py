"""Tool runner — dispatches tool calls and collects results."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Literal

from autonoma.executor.sandbox import Sandbox
from autonoma.executor.tools.base import BaseTool, PermissionLevel
from autonoma.observability.metrics import tool_calls_total, tool_duration_seconds
from autonoma.schema import ToolCall, ToolResult

logger = logging.getLogger(__name__)


def _record_tool_metric(tool_name: str, status: str, started_at: float) -> None:
    """Best-effort metric emission — never raise into the caller."""
    try:
        tool_calls_total.inc(labels={"tool": tool_name, "status": status})
        tool_duration_seconds.observe(
            time.perf_counter() - started_at,
            labels={"tool": tool_name},
        )
    except Exception:  # pragma: no cover — defensive
        pass


class ToolRunner:
    """Dispatches tool calls to registered tools, enforces sandbox and permissions."""

    def __init__(
        self,
        sandbox: Sandbox,
        max_permission_level: PermissionLevel = "dangerous",
        blocked_permissions: set[str] | None = None,
    ):
        self._sandbox = sandbox
        self._tools: dict[str, BaseTool] = {}
        self._max_level = max_permission_level
        self._blocked: set[str] = blocked_permissions or set()

    # Permission level ordering for comparison
    _LEVEL_ORDER: dict[str, int] = {"safe": 0, "cautious": 1, "dangerous": 2}

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool
        perm = tool.permissions
        logger.info(
            "Registered tool: %s (level=%s, net=%s, fs=%s, shell=%s)",
            tool.name, perm.level, perm.network, perm.filesystem, perm.shell,
        )

    def get_tool(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def list_tools(self) -> list[str]:
        return list(self._tools.keys())

    def get_manifest(self) -> list[dict]:
        """Export full permission manifest for all registered tools."""
        return [tool.to_manifest() for tool in self._tools.values()]

    def _check_permissions(self, tool: BaseTool) -> str | None:
        """Validate tool permissions. Returns error message if blocked, None if allowed."""
        perm = tool.permissions

        # Check permission level ceiling
        if self._LEVEL_ORDER.get(perm.level, 0) > self._LEVEL_ORDER.get(self._max_level, 2):
            return (
                f"Tool '{tool.name}' requires permission level '{perm.level}' "
                f"but max allowed is '{self._max_level}'."
            )

        # Check specific blocked capabilities
        for cap in ("network", "filesystem", "shell", "secrets"):
            if getattr(perm, cap) and cap in self._blocked:
                return (
                    f"Tool '{tool.name}' requires '{cap}' permission "
                    f"which is blocked by policy."
                )

        return None

    async def execute(self, tool_call: ToolCall) -> ToolResult:
        """Execute a tool call and return the result."""
        started_at = time.perf_counter()
        tool = self._tools.get(tool_call.name)
        if not tool:
            logger.warning("Unknown tool requested: %s", tool_call.name)
            _record_tool_metric(tool_call.name, "unknown", started_at)
            return ToolResult(
                tool_use_id=tool_call.id,
                content=f"Error: Unknown tool '{tool_call.name}'. Available tools: {', '.join(self._tools.keys())}",
                is_error=True,
            )

        # Permission check
        perm_error = self._check_permissions(tool)
        if perm_error:
            logger.warning("Permission denied for tool %s: %s", tool_call.name, perm_error)
            _record_tool_metric(tool_call.name, "denied", started_at)
            return ToolResult(
                tool_use_id=tool_call.id,
                content=f"Error: {perm_error}",
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
            _record_tool_metric(tool_call.name, "ok", started_at)
            return ToolResult(
                tool_use_id=tool_call.id,
                content=result,
                is_error=False,
            )
        except asyncio.TimeoutError:
            msg = f"Tool '{tool_call.name}' timed out after {self._sandbox.timeout}s"
            logger.error(msg)
            _record_tool_metric(tool_call.name, "timeout", started_at)
            return ToolResult(
                tool_use_id=tool_call.id,
                content=msg,
                is_error=True,
            )
        except Exception as e:
            msg = f"Tool '{tool_call.name}' failed: {e}"
            logger.error(msg, exc_info=True)
            _record_tool_metric(tool_call.name, "error", started_at)
            return ToolResult(
                tool_use_id=tool_call.id,
                content=msg,
                is_error=True,
            )
