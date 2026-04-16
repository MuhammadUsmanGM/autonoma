"""Trace storage — collects and queries agent loop traces."""

from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)

MAX_TRACES = 500  # Keep last N traces in memory


@dataclass
class TraceSpan:
    """A single stage within a trace."""
    stage: str
    data: dict[str, Any]
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class Trace:
    """Complete trace of one agent loop execution."""
    id: str = field(default_factory=lambda: uuid4().hex[:12])
    session_id: str = ""
    channel: str = ""
    user_id: str = ""
    started_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    completed_at: str | None = None
    elapsed_seconds: float = 0.0
    status: str = "running"  # "running", "completed", "error"
    spans: list[TraceSpan] = field(default_factory=list)
    tool_calls: list[dict] = field(default_factory=list)
    error: str | None = None

    def add_span(self, stage: str, data: dict[str, Any]) -> None:
        self.spans.append(TraceSpan(stage=stage, data=data))

    def complete(self, elapsed: float) -> None:
        self.status = "completed"
        self.elapsed_seconds = elapsed
        self.completed_at = datetime.utcnow().isoformat()

    def fail(self, error: str, elapsed: float) -> None:
        self.status = "error"
        self.error = error
        self.elapsed_seconds = elapsed
        self.completed_at = datetime.utcnow().isoformat()

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


class TraceStore:
    """In-memory trace store with optional JSONL persistence."""

    def __init__(self, persist_dir: str | None = None):
        self._traces: deque[Trace] = deque(maxlen=MAX_TRACES)
        self._lock = asyncio.Lock()
        self._persist_dir = persist_dir

    def create_trace(
        self, session_id: str = "", channel: str = "", user_id: str = ""
    ) -> Trace:
        """Create and register a new trace. Returns the trace object for the loop to populate."""
        trace = Trace(session_id=session_id, channel=channel, user_id=user_id)
        self._traces.append(trace)
        return trace

    async def persist_trace(self, trace: Trace) -> None:
        """Append completed trace to JSONL file."""
        if not self._persist_dir:
            return
        try:
            from pathlib import Path
            dir_path = Path(self._persist_dir)
            dir_path.mkdir(parents=True, exist_ok=True)
            path = dir_path / f"{datetime.utcnow().strftime('%Y-%m-%d')}_traces.jsonl"
            line = json.dumps(trace.to_dict()) + "\n"
            async with self._lock:
                await asyncio.to_thread(self._append_file, path, line)
        except Exception as e:
            logger.warning("Failed to persist trace: %s", e)

    def list_traces(
        self,
        limit: int = 50,
        status: str | None = None,
        session_id: str | None = None,
    ) -> list[dict]:
        """List recent traces (newest first)."""
        traces = list(reversed(self._traces))
        if status:
            traces = [t for t in traces if t.status == status]
        if session_id:
            traces = [t for t in traces if t.session_id == session_id]
        return [t.to_dict() for t in traces[:limit]]

    def get_trace(self, trace_id: str) -> dict | None:
        """Get a single trace by ID."""
        for t in self._traces:
            if t.id == trace_id:
                return t.to_dict()
        return None

    def get_stats(self) -> dict:
        """Trace statistics."""
        total = len(self._traces)
        completed = sum(1 for t in self._traces if t.status == "completed")
        errors = sum(1 for t in self._traces if t.status == "error")
        avg_elapsed = 0.0
        completed_traces = [t for t in self._traces if t.status == "completed"]
        if completed_traces:
            avg_elapsed = sum(t.elapsed_seconds for t in completed_traces) / len(completed_traces)
        return {
            "total": total,
            "completed": completed,
            "errors": errors,
            "running": total - completed - errors,
            "avg_elapsed_seconds": round(avg_elapsed, 3),
        }

    @staticmethod
    def _append_file(path, content: str) -> None:
        with open(path, "a", encoding="utf-8") as f:
            f.write(content)
