"""Memory store — SQLite + FTS5 backend with ranked retrieval."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import date, datetime
from pathlib import Path

from autonoma.memory.database import MemoryDatabase
from autonoma.memory.embeddings import EmbeddingProvider, create_embedding_provider
from autonoma.memory.retrieval import MemoryRetriever
from autonoma.schema import MemoryEntry, Message

logger = logging.getLogger(__name__)

# Regex patterns for memory commands in LLM responses
REMEMBER_RE = re.compile(r"\[REMEMBER:\s*(.+?)\]", re.IGNORECASE)
FACT_RE = re.compile(r"\[FACT:\s*(.+?)\]", re.IGNORECASE)
PREFERENCE_RE = re.compile(r"\[PREFERENCE:\s*(.+?)\]", re.IGNORECASE)
FORGET_RE = re.compile(r"\[FORGET:\s*(.+?)\]", re.IGNORECASE)
ALL_TAGS_RE = re.compile(
    r"\[(?:REMEMBER|FACT|PREFERENCE|FORGET):\s*.+?\]", re.IGNORECASE
)


class MemoryStore:
    """Read/write interface for agent memory with SQLite + FTS5 backend."""

    def __init__(
        self,
        workspace_dir: str,
        db_path: str | None = None,
        embedding_provider: EmbeddingProvider | None = None,
    ):
        self._workspace = Path(workspace_dir)
        self._memory_file = self._workspace / "MEMORY.md"
        self._daily_dir = self._workspace / "memory"
        self._write_lock = asyncio.Lock()

        # SQLite backend
        resolved = db_path or str(Path(".memory") / "autonoma.db")
        Path(resolved).parent.mkdir(parents=True, exist_ok=True)
        self._db = MemoryDatabase(resolved)

        # Embedding provider (defaults to local hash-based if no API key)
        self._embedder = embedding_provider or create_embedding_provider()
        self._retriever = MemoryRetriever(
            self._db, embedding_provider=self._embedder
        )

    async def initialize(self) -> None:
        """Run once at startup: migrate MEMORY.md into SQLite if needed, backfill embeddings."""
        await asyncio.to_thread(self._migrate_if_needed)
        # Backfill embeddings for any memories missing them
        backfilled = await self._retriever.backfill_embeddings()
        if backfilled:
            logger.info("Backfilled %d memory embeddings on startup", backfilled)

    # --- Long-term memory (SQLite) ---

    async def read_long_term(self) -> str:
        """Read all active memories as formatted text."""
        entries = await asyncio.to_thread(self._db.get_all_active, limit=200)
        if not entries:
            return ""
        lines = [f"- [{e['created_at'][:10]}] {e['content']}" for e in entries]
        return "\n".join(lines)

    async def append_long_term(self, fact: str) -> None:
        """Insert a fact into SQLite with dedup check."""
        type_, content = self._parse_fact_prefix(fact)
        await self._store_if_new(content, type_)
        logger.info("Stored memory (%s): %s", type_, content[:80])

    # --- Daily logs (still file-based) ---

    async def read_daily_log(self, target_date: date | None = None) -> str:
        """Read a daily log file. Defaults to today."""
        d = target_date or date.today()
        path = self._daily_dir / f"{d.isoformat()}.md"
        if not path.exists():
            return ""
        return await asyncio.to_thread(path.read_text, "utf-8")

    async def append_daily_log(self, entry: str) -> None:
        """Append an entry to today's daily log."""
        async with self._write_lock:
            self._daily_dir.mkdir(parents=True, exist_ok=True)
            path = self._daily_dir / f"{date.today().isoformat()}.md"

            if not path.exists():
                header = f"# Daily Log — {date.today().isoformat()}\n\n"
                await asyncio.to_thread(self._write_file, path, header)

            timestamp = datetime.utcnow().strftime("%H:%M")
            line = f"- [{timestamp}] {entry}\n"
            await asyncio.to_thread(self._append_file, path, line)

    # --- Memory command extraction ---

    async def process_memory_commands(
        self, response: str, message: Message
    ) -> str:
        """Extract memory tags from LLM response, store them, return cleaned response."""
        # Handle FORGET tags
        for match in FORGET_RE.finditer(response):
            query = match.group(1).strip()
            count = await asyncio.to_thread(self._db.soft_delete_matching, query)
            if count:
                logger.info("Forgot %d memories matching: %s", count, query[:80])
                await self.append_daily_log(f"Forgot ({count}): {query}")

        # Handle REMEMBER tags
        for match in REMEMBER_RE.finditer(response):
            fact = match.group(1).strip()
            await self._store_if_new(fact, "remember")
            await self.append_daily_log(f"Remembered: {fact}")

        # Handle FACT tags
        for match in FACT_RE.finditer(response):
            fact = match.group(1).strip()
            await self._store_if_new(fact, "fact", importance=0.8)
            await self.append_daily_log(f"Learned fact: {fact}")

        # Handle PREFERENCE tags
        for match in PREFERENCE_RE.finditer(response):
            pref = match.group(1).strip()
            await self._store_if_new(pref, "preference")
            await self.append_daily_log(f"Preference noted: {pref}")

        # Strip all memory tags from visible response
        cleaned = ALL_TAGS_RE.sub("", response).strip()
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned

    # --- Context assembly ---

    async def get_memory_context(self, query: str = "") -> str:
        """Build the memory context string for prompt assembly.

        When query is provided, uses hybrid BM25 + vector retrieval.
        Otherwise returns top memories by importance.
        """
        if query:
            return await self._retriever.retrieve_for_context_hybrid(query)
        # Fallback: top memories by importance
        entries = await asyncio.to_thread(self._db.export_top_memories, limit=15)
        if not entries:
            return "(No stored memories yet.)"
        lines = [f"- {e['content']}" for e in entries]
        return "\n".join(lines)

    async def get_daily_context(self) -> str:
        """Get today's daily log for context injection."""
        log = await self.read_daily_log()
        if not log.strip():
            return "(No activity logged today.)"
        return log

    # --- Public helpers ---

    async def search(self, query: str, limit: int = 10) -> list[MemoryEntry]:
        """Public search interface."""
        results = await asyncio.to_thread(self._db.search, query, limit=limit)
        return [_row_to_entry(r) for r in results]

    async def get_stats(self) -> dict:
        """Return memory database statistics."""
        total = await asyncio.to_thread(self._db.count, False)
        active = await asyncio.to_thread(self._db.count, True)
        expiry_stats = await asyncio.to_thread(self._db.get_expiry_stats)
        return {
            "total_active": active,
            "total_archived": total - active,
            **expiry_stats,
        }

    async def get_stale_memories(self, limit: int = 50) -> list[dict]:
        """Return memories flagged as stale for review."""
        return await asyncio.to_thread(self._db.get_stale_memories, limit)

    async def mark_reviewed(self, memory_id: int) -> None:
        """Mark a stale memory as reviewed (confirmed valid)."""
        await asyncio.to_thread(self._db.mark_reviewed, memory_id)

    async def set_expiry(self, memory_id: int, expires_at: str | None = None) -> None:
        """Set expiry date for a memory."""
        await asyncio.to_thread(self._db.set_expiry, memory_id, expires_at)

    # --- Private helpers ---

    async def _store_if_new(
        self, content: str, type: str, importance: float = 1.0
    ) -> None:
        """Insert only if no near-duplicate exists. Boosts existing if duplicate."""
        async with self._write_lock:
            dupes = await asyncio.to_thread(self._db.find_duplicates, content)
            if dupes:
                best = max(dupes, key=lambda d: d["importance"])
                new_imp = min(best["importance"] + 0.1, 2.0)
                await asyncio.to_thread(
                    self._db.update_importance, best["id"], new_imp
                )
                logger.debug(
                    "Boosted existing memory %d instead of duplicate", best["id"]
                )
            else:
                mem_id = await asyncio.to_thread(
                    self._db.insert, content, type,
                    source="tag_extraction", importance=importance,
                )
                # Index embedding for the new memory
                await self._retriever.index_memory(mem_id, content)

    def _migrate_if_needed(self) -> None:
        """Import MEMORY.md entries into SQLite on first run."""
        if self._db.count() > 0:
            return  # Already has data
        if not self._memory_file.exists():
            return

        text = self._memory_file.read_text("utf-8")
        imported = 0
        for line in text.strip().split("\n"):
            if not line.startswith("- "):
                continue
            content = line[2:].strip()

            # Extract date if present: [2025-04-16] rest
            date_match = re.match(r"\[(\d{4}-\d{2}-\d{2})\]\s*(.*)", content)
            if date_match:
                created = date_match.group(1) + "T00:00:00"
                content = date_match.group(2)
            else:
                created = None  # Let database use current time

            type_, content = self._parse_fact_prefix(content)
            if content.strip():
                self._db.insert(
                    content, type_, source="migration",
                    importance=0.8, created_at=created,
                )
                imported += 1

        if imported:
            logger.info("Migrated %d entries from MEMORY.md to SQLite", imported)

    @staticmethod
    def _parse_fact_prefix(text: str) -> tuple[str, str]:
        """Parse '[Fact] ...' or '[Preference] ...' prefix. Return (type, content)."""
        if text.startswith("[Fact] "):
            return "fact", text[7:]
        if text.startswith("[Preference] "):
            return "preference", text[13:]
        return "remember", text

    @staticmethod
    def _append_file(path: Path, content: str) -> None:
        with open(path, "a", encoding="utf-8") as f:
            f.write(content)

    @staticmethod
    def _write_file(path: Path, content: str) -> None:
        path.write_text(content, encoding="utf-8")


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
