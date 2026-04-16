"""Ranked memory retrieval — hybrid BM25 + vector + importance + recency scoring."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from autonoma.memory.database import MemoryDatabase
from autonoma.memory.embeddings import EmbeddingProvider
from autonoma.schema import MemoryEntry

logger = logging.getLogger(__name__)


class MemoryRetriever:
    """Hybrid retrieval: combines FTS5/BM25 with vector similarity."""

    def __init__(
        self,
        db: MemoryDatabase,
        max_results: int = 15,
        embedding_provider: EmbeddingProvider | None = None,
    ):
        self._db = db
        self._max_results = max_results
        self._embedder = embedding_provider

    def retrieve(self, query: str) -> list[MemoryEntry]:
        """Main retrieval pipeline: BM25 + vector + recent + merge + rank + cap."""
        seen_ids: set[int] = set()
        scored: list[tuple[float, MemoryEntry]] = []

        # 1. FTS5/BM25 search for query-relevant memories
        if query.strip():
            candidates = self._db.search(query, limit=self._max_results * 2)
            for row in candidates:
                entry = _row_to_entry(row)
                entry.relevance_score = row.get("bm25_score", 0.0)
                score = self._combined_score(
                    bm25_score=entry.relevance_score,
                    cosine_score=0.0,
                    importance=entry.importance,
                    accessed_at=entry.accessed_at,
                )
                scored.append((score, entry))
                seen_ids.add(entry.id)
                self._db.update_access(entry.id)

        # 2. Get recent memories (always include regardless of relevance)
        recent = self._db.get_recent(limit=5, active_only=True)
        for row in recent:
            if row["id"] in seen_ids:
                continue
            entry = _row_to_entry(row)
            score = self._combined_score(
                bm25_score=0.0,
                cosine_score=0.0,
                importance=entry.importance,
                accessed_at=entry.accessed_at,
            )
            scored.append((score, entry))
            seen_ids.add(entry.id)

        # 3. Sort by combined score DESC, cap at max_results
        scored.sort(key=lambda x: x[0], reverse=True)
        return [entry for _, entry in scored[: self._max_results]]

    async def retrieve_hybrid(self, query: str) -> list[MemoryEntry]:
        """Async hybrid retrieval: BM25 + vector search combined."""
        seen_ids: set[int] = set()
        scored: list[tuple[float, MemoryEntry]] = []

        if not query.strip():
            entries = await asyncio.to_thread(self._db.get_recent, 10, True)
            return [_row_to_entry(r) for r in entries]

        # 1. BM25 search
        bm25_results = await asyncio.to_thread(
            self._db.search, query, limit=self._max_results * 2
        )
        bm25_map: dict[int, float] = {}
        for row in bm25_results:
            bm25_map[row["id"]] = row.get("bm25_score", 0.0)
            entry = _row_to_entry(row)
            seen_ids.add(entry.id)

        # 2. Vector search (if embedder available)
        vector_map: dict[int, float] = {}
        if self._embedder:
            query_embedding = await self._embedder.embed_one(query)
            vector_results = await asyncio.to_thread(
                self._db.vector_search, query_embedding, self._max_results * 2
            )
            for row in vector_results:
                vector_map[row["id"]] = row.get("cosine_score", 0.0)
                seen_ids.add(row["id"])

        # 3. Merge: get full data for all candidate IDs
        all_ids = seen_ids.copy()
        # Also include recent memories
        recent = await asyncio.to_thread(self._db.get_recent, 5, True)
        for row in recent:
            all_ids.add(row["id"])

        # Build scored list from all candidates
        all_active = await asyncio.to_thread(self._db.get_all_active, limit=500)
        id_to_row = {r["id"]: r for r in all_active}

        for mid in all_ids:
            row = id_to_row.get(mid)
            if not row:
                continue
            entry = _row_to_entry(row)
            score = self._combined_score(
                bm25_score=bm25_map.get(mid, 0.0),
                cosine_score=vector_map.get(mid, 0.0),
                importance=entry.importance,
                accessed_at=entry.accessed_at,
            )
            scored.append((score, entry))
            # Bump access for relevant results
            if mid in bm25_map or mid in vector_map:
                await asyncio.to_thread(self._db.update_access, mid)

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

    async def retrieve_for_context_hybrid(self, query: str) -> str:
        """Async hybrid version of retrieve_for_context."""
        entries = await self.retrieve_hybrid(query)
        if not entries:
            return "(No stored memories yet.)"

        groups: dict[str, list[MemoryEntry]] = {}
        for e in entries:
            groups.setdefault(e.type, []).append(e)

        parts: list[str] = []
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
        self,
        bm25_score: float,
        cosine_score: float,
        importance: float,
        accessed_at: str,
    ) -> float:
        """Weighted combination of BM25, vector similarity, importance, and recency."""
        # BM25 is negative in SQLite (more negative = more relevant), negate it
        relevance = -bm25_score if bm25_score else 0.0
        recency = _recency_boost(accessed_at)

        if cosine_score > 0:
            # Hybrid mode: weight both search signals
            return (
                (relevance * 0.3)
                + (cosine_score * 0.3)
                + (importance * 0.2)
                + (recency * 0.2)
            )
        else:
            # BM25-only mode
            return (relevance * 0.5) + (importance * 0.3) + (recency * 0.2)

    async def index_memory(self, memory_id: int, content: str) -> None:
        """Generate and store embedding for a memory entry."""
        if not self._embedder:
            return
        try:
            embedding = await self._embedder.embed_one(content)
            await asyncio.to_thread(
                self._db.store_embedding, memory_id, embedding, self._embedder.name
            )
        except Exception as e:
            logger.warning("Failed to index memory %d: %s", memory_id, e)

    async def backfill_embeddings(self) -> int:
        """Generate embeddings for memories that don't have them yet."""
        if not self._embedder:
            return 0
        missing = await asyncio.to_thread(
            self._db.get_memories_without_embeddings, 100
        )
        if not missing:
            return 0

        texts = [m["content"] for m in missing]
        try:
            embeddings = await self._embedder.embed(texts)
            for mem, emb in zip(missing, embeddings):
                await asyncio.to_thread(
                    self._db.store_embedding, mem["id"], emb, self._embedder.name
                )
            logger.info("Backfilled embeddings for %d memories", len(missing))
            return len(missing)
        except Exception as e:
            logger.warning("Embedding backfill failed: %s", e)
            return 0


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
