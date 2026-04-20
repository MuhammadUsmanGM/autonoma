"""Trace storage — collects and queries agent loop traces."""

from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
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
    # Token/cost accounting — summed across every LLM call in the loop (incl.
    # all ReAct iterations). ``model`` is the last model the provider answered
    # with; if the user swaps providers mid-trace, later calls will overwrite.
    # Kept as 0 defaults so older JSONL entries stay compatible.
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    model: str = ""

    def add_span(self, stage: str, data: dict[str, Any]) -> None:
        self.spans.append(TraceSpan(stage=stage, data=data))

    def add_usage(self, tokens_in: int, tokens_out: int, cost: float, model: str = "") -> None:
        """Accumulate one LLM call's usage into the trace totals."""
        self.tokens_in += int(tokens_in or 0)
        self.tokens_out += int(tokens_out or 0)
        self.cost_usd += float(cost or 0.0)
        if model:
            self.model = model

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

    def get_usage_stats(self) -> dict:
        """Aggregate token + cost spend over today / this week / this month.

        Reads the in-memory ring (fast path) plus any persisted JSONL files
        from disk covering the last ~31 days. Persisted files are the source
        of truth for history beyond the 500-trace ring.

        Returns::

            {
              "today":  {"tokens_in": int, "tokens_out": int, "cost_usd": float, "calls": int},
              "week":   {...},
              "month":  {...},
              "by_model": {"claude-sonnet-4-6": {...}, ...},   # month scope
              "total":  {...},
            }
        """
        now = datetime.utcnow()
        today = now.date()
        week_start = today - timedelta(days=today.weekday())   # Mon of this week
        month_start = today.replace(day=1)

        buckets = {
            "today": {"tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0, "calls": 0},
            "week": {"tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0, "calls": 0},
            "month": {"tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0, "calls": 0},
            "total": {"tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0, "calls": 0},
        }
        by_model: dict[str, dict[str, Any]] = {}

        seen_ids: set[str] = set()

        def _ingest(rec: dict) -> None:
            rid = rec.get("id") or ""
            if rid in seen_ids:
                return
            seen_ids.add(rid)

            tin = int(rec.get("tokens_in", 0) or 0)
            tout = int(rec.get("tokens_out", 0) or 0)
            cost = float(rec.get("cost_usd", 0.0) or 0.0)
            model = rec.get("model") or "unknown"
            if tin == 0 and tout == 0 and cost == 0.0:
                return  # nothing to bill

            started = rec.get("started_at") or ""
            try:
                ts = datetime.fromisoformat(started).date() if started else today
            except ValueError:
                ts = today

            def _add(b: dict) -> None:
                b["tokens_in"] += tin
                b["tokens_out"] += tout
                b["cost_usd"] += cost
                b["calls"] += 1

            _add(buckets["total"])
            if ts >= month_start:
                _add(buckets["month"])
                m = by_model.setdefault(
                    model,
                    {"tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0, "calls": 0},
                )
                _add(m)
            if ts >= week_start:
                _add(buckets["week"])
            if ts == today:
                _add(buckets["today"])

        # In-memory ring first (covers the most recent ~500 traces).
        for t in self._traces:
            _ingest(t.to_dict())

        # Then any persisted JSONL files within the last 31 days.
        if self._persist_dir:
            try:
                dir_path = Path(self._persist_dir)
                if dir_path.exists():
                    cutoff = today - timedelta(days=31)
                    for p in sorted(dir_path.glob("*_traces.jsonl")):
                        try:
                            file_date = datetime.strptime(p.stem.split("_")[0], "%Y-%m-%d").date()
                        except ValueError:
                            continue
                        if file_date < cutoff:
                            continue
                        try:
                            with open(p, encoding="utf-8") as f:
                                for line in f:
                                    line = line.strip()
                                    if not line:
                                        continue
                                    try:
                                        _ingest(json.loads(line))
                                    except json.JSONDecodeError:
                                        continue
                        except OSError:
                            continue
            except Exception as e:  # pragma: no cover — advisory
                logger.warning("Usage stats: persisted read failed: %s", e)

        # Round costs for display (keep 6 decimals — a cent is 0.01).
        for b in buckets.values():
            b["cost_usd"] = round(b["cost_usd"], 6)
        for m in by_model.values():
            m["cost_usd"] = round(m["cost_usd"], 6)

        return {**buckets, "by_model": by_model}

    @staticmethod
    def _append_file(path, content: str) -> None:
        with open(path, "a", encoding="utf-8") as f:
            f.write(content)
