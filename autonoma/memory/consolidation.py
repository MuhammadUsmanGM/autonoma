"""Memory consolidation — decay, dedup, archive, MEMORY.md sync."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from autonoma.memory.database import MemoryDatabase, _token_overlap

logger = logging.getLogger(__name__)


class MemoryConsolidator:
    """Background memory maintenance: decay, dedup, archive, sync."""

    def __init__(
        self,
        db: MemoryDatabase,
        workspace_dir: str,
        decay_factor: float = 0.95,
        importance_threshold: float = 0.1,
    ):
        self._db = db
        self._workspace = Path(workspace_dir)
        self._decay_factor = decay_factor
        self._threshold = importance_threshold

    def run_cycle(self) -> dict:
        """Execute one full consolidation cycle. Returns stats."""
        decayed, archived = self.decay_and_archive()
        deduped = self.deduplicate()
        synced = self.sync_to_memory_md()
        stats = {
            "decayed": decayed,
            "archived": archived,
            "deduped": deduped,
            "synced": synced,
        }
        logger.info("Consolidation cycle: %s", stats)
        return stats

    def decay_and_archive(self) -> tuple[int, int]:
        """Decay importance of all active memories, archive those below threshold."""
        return self._db.decay_importance(self._decay_factor, self._threshold)

    def deduplicate(self) -> int:
        """Find and remove near-duplicate memories (keep highest importance)."""
        all_active = self._db.get_all_active(limit=500)
        deleted = 0
        seen_ids: set[int] = set()

        for mem in all_active:
            if mem["id"] in seen_ids:
                continue

            # Search for similar entries using first 6 words
            words = [w for w in mem["content"].lower().split() if len(w) > 2][:6]
            if not words:
                continue

            candidates = self._db.search(
                " ".join(words), limit=10, active_only=True
            )

            # Group duplicates
            cluster: list[dict] = [mem]
            for c in candidates:
                if c["id"] == mem["id"] or c["id"] in seen_ids:
                    continue
                if _token_overlap(mem["content"], c["content"]) >= 0.8:
                    cluster.append(c)

            if len(cluster) <= 1:
                continue

            # Keep the one with highest importance, soft-delete the rest
            cluster.sort(key=lambda x: x["importance"], reverse=True)
            for dupe in cluster[1:]:
                self._db.soft_delete(dupe["id"])
                seen_ids.add(dupe["id"])
                deleted += 1

            seen_ids.add(cluster[0]["id"])

        if deleted:
            logger.info("Deduplicated %d memories", deleted)
        return deleted

    def sync_to_memory_md(self) -> int:
        """Export top memories to MEMORY.md as a human-readable snapshot."""
        entries = self._db.export_top_memories(limit=50)
        if not entries:
            return 0

        memory_file = self._workspace / "MEMORY.md"
        now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")

        lines = [
            "# Long-Term Memory\n",
            f"<!-- Auto-synced from memory database: {now} -->\n",
        ]

        # Group by type
        groups: dict[str, list[dict]] = {}
        for e in entries:
            groups.setdefault(e["type"], []).append(e)

        for type_name, label in [
            ("preference", "Preferences"),
            ("fact", "Facts"),
            ("remember", "Memories"),
            ("conversation_summary", "Conversation Summaries"),
        ]:
            items = groups.get(type_name, [])
            if not items:
                continue
            lines.append(f"\n## {label}\n")
            for e in items:
                date = e["created_at"][:10]
                lines.append(f"- [{date}] {e['content']}")

        memory_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        logger.debug("Synced %d memories to MEMORY.md", len(entries))
        return len(entries)
