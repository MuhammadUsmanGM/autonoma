"""Tool runner — dispatches tool calls and collects results.

The runner is the single choke point between the LLM's requested tool calls
and the sandbox. On top of permission checks and timeouts it enforces two
extra controls that matter for production deployments:

* **Per-session sliding-window rate limit.** A runaway ReAct loop that calls
  ``shell`` 1000 times in 30 seconds is capped by policy, not by whatever the
  upstream provider happens to return. Window + cap are drawn from
  ``SandboxConfig.rate_limit_calls`` / ``rate_limit_window``.
* **JSONL audit log.** Every tool invocation — success, denial, timeout,
  error — is appended as a single JSON line to ``<session_dir>/audit.log``.
  Inputs are hashed (sha256-16) rather than stored verbatim so the log
  stays cheap to ship off-host while still letting an operator correlate
  replays across sessions.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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


def _hash_input(data: Any) -> str:
    """Deterministic short hash of a tool input — stable across runs."""
    try:
        canon = json.dumps(data, sort_keys=True, default=str)
    except Exception:
        canon = repr(data)
    return hashlib.sha256(canon.encode("utf-8", errors="replace")).hexdigest()[:16]


class _SlidingWindowLimiter:
    """Simple sliding-window counter keyed by session id.

    Kept in-memory — the audit log is the durable record. On restart the
    window resets, which is the right behavior: a fresh process is a fresh
    budget. For multi-instance deployments, put the limit in front (API
    gateway, ingress) instead of relying on this.
    """

    __slots__ = ("_max_calls", "_window", "_hits")

    def __init__(self, max_calls: int, window_seconds: float):
        self._max_calls = max_calls
        self._window = window_seconds
        self._hits: dict[str, deque[float]] = {}

    def check(self, key: str, now: float | None = None) -> bool:
        """Return True if the call is allowed, False if it should be throttled.

        On True the call is recorded; on False nothing is recorded (so a
        throttled caller that retries later won't be double-counted).
        """
        if self._max_calls <= 0 or self._window <= 0:
            return True
        now = now if now is not None else time.monotonic()
        q = self._hits.get(key)
        if q is None:
            q = deque()
            self._hits[key] = q
        cutoff = now - self._window
        while q and q[0] < cutoff:
            q.popleft()
        if len(q) >= self._max_calls:
            return False
        q.append(now)
        return True


class _AuditLog:
    """Append-only JSONL audit trail for tool invocations.

    We don't want a tool call to fail just because the audit disk is full or
    the directory is read-only — audit failure degrades, never propagates.
    """

    def __init__(self, path: str | Path | None):
        self._path: Path | None = Path(path) if path else None
        self._disabled = False
        self._warned = False
        if self._path is not None:
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                logger.warning("Audit log disabled — cannot create %s: %s", self._path, e)
                self._disabled = True

    def write(self, record: dict[str, Any]) -> None:
        if self._disabled or self._path is None:
            return
        try:
            line = json.dumps(record, default=str) + "\n"
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(line)
        except OSError as e:  # pragma: no cover — best-effort
            if not self._warned:
                self._warned = True
                logger.warning("Audit log write failed (further errors suppressed): %s", e)


class ToolRunner:
    """Dispatches tool calls to registered tools, enforces sandbox and permissions."""

    # Permission level ordering for comparison
    _LEVEL_ORDER: dict[str, int] = {"safe": 0, "cautious": 1, "dangerous": 2}

    def __init__(
        self,
        sandbox: Sandbox,
        max_permission_level: PermissionLevel = "dangerous",
        blocked_permissions: set[str] | None = None,
        audit_log_path: str | Path | None = None,
    ):
        self._sandbox = sandbox
        self._tools: dict[str, BaseTool] = {}
        self._max_level = max_permission_level
        self._blocked: set[str] = blocked_permissions or set()

        cfg = sandbox.config
        self._limiter = _SlidingWindowLimiter(
            max_calls=cfg.rate_limit_calls,
            window_seconds=cfg.rate_limit_window,
        )
        self._audit = _AuditLog(audit_log_path)

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

        if self._LEVEL_ORDER.get(perm.level, 0) > self._LEVEL_ORDER.get(self._max_level, 2):
            return (
                f"Tool '{tool.name}' requires permission level '{perm.level}' "
                f"but max allowed is '{self._max_level}'."
            )

        for cap in ("network", "filesystem", "shell", "secrets"):
            if getattr(perm, cap) and cap in self._blocked:
                return (
                    f"Tool '{tool.name}' requires '{cap}' permission "
                    f"which is blocked by policy."
                )

        return None

    def _audit_record(
        self,
        *,
        tool_call: ToolCall,
        session_id: str | None,
        status: str,
        elapsed_ms: int,
        truncated_input_hash: str,
        error: str | None = None,
    ) -> None:
        self._audit.write({
            "ts": datetime.now(timezone.utc).isoformat(),
            "session_id": session_id,
            "tool": tool_call.name,
            "tool_use_id": tool_call.id,
            "input_hash": truncated_input_hash,
            "status": status,
            "elapsed_ms": elapsed_ms,
            "error": error,
        })

    async def execute(
        self,
        tool_call: ToolCall,
        *,
        session_id: str | None = None,
    ) -> ToolResult:
        """Execute a tool call and return the result.

        ``session_id`` is optional so legacy callers still work; when present
        it gates the per-session rate limiter and lands in the audit log.
        """
        started_at = time.perf_counter()
        input_hash = _hash_input(tool_call.input)
        limiter_key = session_id or "__anonymous__"

        def _elapsed_ms() -> int:
            return int((time.perf_counter() - started_at) * 1000)

        tool = self._tools.get(tool_call.name)
        if not tool:
            logger.warning("Unknown tool requested: %s", tool_call.name)
            _record_tool_metric(tool_call.name, "unknown", started_at)
            msg = (
                f"Error: Unknown tool '{tool_call.name}'. "
                f"Available tools: {', '.join(self._tools.keys())}"
            )
            self._audit_record(
                tool_call=tool_call, session_id=session_id,
                status="unknown", elapsed_ms=_elapsed_ms(),
                truncated_input_hash=input_hash, error=msg,
            )
            return ToolResult(tool_use_id=tool_call.id, content=msg, is_error=True)

        # Permission check
        perm_error = self._check_permissions(tool)
        if perm_error:
            logger.warning("Permission denied for tool %s: %s", tool_call.name, perm_error)
            _record_tool_metric(tool_call.name, "denied", started_at)
            self._audit_record(
                tool_call=tool_call, session_id=session_id,
                status="denied", elapsed_ms=_elapsed_ms(),
                truncated_input_hash=input_hash, error=perm_error,
            )
            return ToolResult(
                tool_use_id=tool_call.id,
                content=f"Error: {perm_error}",
                is_error=True,
            )

        # Rate-limit check. Runs after permissions so a blocked tool
        # doesn't burn the caller's budget.
        if not self._limiter.check(limiter_key):
            cfg = self._sandbox.config
            msg = (
                f"Tool rate limit exceeded: {cfg.rate_limit_calls} calls / "
                f"{cfg.rate_limit_window:g}s per session. Slow down and retry."
            )
            logger.warning(
                "Rate-limited session=%s tool=%s", limiter_key, tool_call.name
            )
            _record_tool_metric(tool_call.name, "rate_limited", started_at)
            self._audit_record(
                tool_call=tool_call, session_id=session_id,
                status="rate_limited", elapsed_ms=_elapsed_ms(),
                truncated_input_hash=input_hash, error=msg,
            )
            return ToolResult(
                tool_use_id=tool_call.id,
                content=f"Error: {msg}",
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
            self._audit_record(
                tool_call=tool_call, session_id=session_id,
                status="ok", elapsed_ms=_elapsed_ms(),
                truncated_input_hash=input_hash,
            )
            return ToolResult(
                tool_use_id=tool_call.id,
                content=result,
                is_error=False,
            )
        except asyncio.TimeoutError:
            msg = f"Tool '{tool_call.name}' timed out after {self._sandbox.timeout}s"
            logger.error(msg)
            _record_tool_metric(tool_call.name, "timeout", started_at)
            self._audit_record(
                tool_call=tool_call, session_id=session_id,
                status="timeout", elapsed_ms=_elapsed_ms(),
                truncated_input_hash=input_hash, error=msg,
            )
            return ToolResult(
                tool_use_id=tool_call.id,
                content=msg,
                is_error=True,
            )
        except Exception as e:
            msg = f"Tool '{tool_call.name}' failed: {e}"
            logger.error(msg, exc_info=True)
            _record_tool_metric(tool_call.name, "error", started_at)
            self._audit_record(
                tool_call=tool_call, session_id=session_id,
                status="error", elapsed_ms=_elapsed_ms(),
                truncated_input_hash=input_hash, error=str(e),
            )
            return ToolResult(
                tool_use_id=tool_call.id,
                content=msg,
                is_error=True,
            )
