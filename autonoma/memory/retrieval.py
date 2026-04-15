"""Ranked memory retrieval — BM25 + importance + recency scoring."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from autonoma.memory.database import MemoryDatabase
from autonoma.schema import MemoryEntry

logger = logging.getLogger(__name__)


class MemoryRetriever:
    """Ranked memory retrieval for context assembly."""

    def __init__(self, db: MemoryDatabase, max_results: int = 15):
        self._db = db
        self._max_results = max_results

    def retrieve(self, query: str) -> list[MemoryEntry]:
        """Main retrieval pipeline: FTS5 search + recent + merge + rank + cap."""
        seen_ids: set[int] = set()
        scored: list[tuple[float, MemoryEntry]] = []

        # 1. FTS5 search for query-relevant memories
        if query.strip():
            candidates = self._db.search(query, limit=self._max_results * 2)
            for row in candidates:
                entry = _row_to_entry(row)
                entry.relevance_score = row.get("bm25_score", 0.0)
                score = self._combined_score(
                    entry.relevance_score, entry.importance, entry.accessed_at
                )
                scored.append((score, entry))
                seen_ids.add(entry.id)
                # Bump access stats
                self._db.update_access(entry.id)

        # 2. Get recent memories (always include regardless of relevance)
        recent = self._db.get_recent(limit=5, active_only=True)
        for row in recent:
            if row["id"] in seen_ids:
                continue
            entry = _row_to_entry(row)
            score = self._combined_score(0.0, entry.importance, entry.accessed_at)
            scored.append((score, entry))
            seen_ids.add(entry.id)

        # 3. Sort by combined score DESC, cap at max_results
        scored.sort(key=lambda x: x[0], reverse=True)
        return [entry for _, entry in scored[: self._max_results]]

    def retrieve_for_context(self, query: str) -> str:
        """Retrieve memories and format as grouped markdown for prompt injection."""
        entries = self.retrieve(query)
        if not entries:
            return "(No stored memories yet.)"

        # Group by type
        groups: dict[str, list[MemoryEntry]] = {}
        for e in entries:
            groups.setdefault(e.type, []).append(e)

        parts: list[str] = []

        # Render in priority order
        for type_name, label in [
            ("preference", "Preferences"),
            ("fact", "Facts"),
            ("remember", "Memories"),
            ("conversation_summary", "Past Conversations"),
        ]:
            items = groups.get(type_name, [])
            if not items:
                continue
            parts.append(f"**{label}:**")
            for e in items:
                parts.append(f"- {e.content}")

        return "\n".join(parts) if parts else "(No stored memories yet.)"

    def _combined_score(
        self, bm25_score: float, importance: float, accessed_at: str
    ) -> float:
        """Weighted combination of BM25, importance, and recency."""
        # BM25 is negative in SQLite (more negative = more relevant), negate it
        relevance = -bm25_score if bm25_score else 0.0
        recency = _recency_boost(accessed_at)
        return (relevance * 0.5) + (importance * 0.3) + (recency * 0.2)


def _recency_boost(accessed_at: str) -> float:
    """Score multiplier based on how recently a memory was accessed."""
    try:
        accessed = datetime.fromisoformat(accessed_at)
    except (ValueError, TypeError):
        return 0.5

    age = datetime.utcnow() - accessed
    if age < timedelta(hours=1):
        return 1.5
    if age < timedelta(days=1):
        return 1.2
    if age < timedelta(weeks=1):
        return 1.0
    return 0.8


def _row_to_entry(row: dict) -> MemoryEntry:
    """Convert a database row dict to a MemoryEntry."""
    return MemoryEntry(
        id=row["id"],
        content=row["content"],
        type=row["type"],
        source=row.get("source", ""),
        importance=row["importance"],
        created_at=row["created_at"],
        accessed_at=row["accessed_at"],
        access_count=row.get("access_count", 0),
        active=bool(row.get("active", 1)),
    )
