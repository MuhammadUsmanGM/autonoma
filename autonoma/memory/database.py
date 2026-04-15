"""SQLite + FTS5 storage backend for agent memory."""

from __future__ import annotations

import sqlite3
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

SCHEMA_SQL = """
-- Main memory table
CREATE TABLE IF NOT EXISTS memories (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    content      TEXT NOT NULL,
    type         TEXT NOT NULL DEFAULT 'remember',
    source       TEXT DEFAULT '',
    importance   REAL NOT NULL DEFAULT 1.0,
    created_at   TEXT NOT NULL,
    accessed_at  TEXT NOT NULL,
    access_count INTEGER NOT NULL DEFAULT 0,
    active       INTEGER NOT NULL DEFAULT 1
);

-- FTS5 virtual table for ranked full-text search
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    content,
    type,
    content='memories',
    content_rowid='id',
    tokenize='porter unicode61'
);

-- Triggers to keep FTS index in sync
CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid, content, type)
    VALUES (new.id, new.content, new.type);
END;

CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content, type)
    VALUES ('delete', old.id, old.content, old.type);
END;

CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content, type)
    VALUES ('delete', old.id, old.content, old.type);
    INSERT INTO memories_fts(rowid, content, type)
    VALUES (new.id, new.content, new.type);
END;

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_memories_type ON memories(type);
CREATE INDEX IF NOT EXISTS idx_memories_active ON memories(active);
CREATE INDEX IF NOT EXISTS idx_memories_importance ON memories(importance DESC);

-- Schema version
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);
INSERT OR IGNORE INTO schema_version VALUES (1);
"""


class MemoryDatabase:
    """SQLite + FTS5 storage backend for agent memory."""

    def __init__(self, db_path: str | Path):
        self._db_path = str(db_path)
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = self._connect()
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _ensure_schema(self) -> None:
        self._conn.executescript(SCHEMA_SQL)
        self._conn.commit()

    def insert(
        self,
        content: str,
        type: str = "remember",
        source: str = "",
        importance: float = 1.0,
        created_at: str | None = None,
    ) -> int:
        """Insert a memory row, return its id."""
        now = created_at or datetime.utcnow().isoformat()
        cur = self._conn.execute(
            """INSERT INTO memories (content, type, source, importance, created_at, accessed_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (content, type, source, importance, now, now),
        )
        self._conn.commit()
        return cur.lastrowid

    def search(
        self,
        query: str,
        *,
        limit: int = 10,
        type_filter: str | None = None,
        active_only: bool = True,
    ) -> list[dict]:
        """FTS5 ranked search. Returns dicts with bm25_score."""
        if not query or not query.strip():
            return []

        # Escape FTS5 special characters by quoting each term
        safe_query = " ".join(
            f'"{w}"' for w in query.split() if w.strip()
        )
        if not safe_query:
            return []

        sql = """
            SELECT m.*, bm25(memories_fts) AS bm25_score
            FROM memories_fts fts
            JOIN memories m ON m.id = fts.rowid
            WHERE memories_fts MATCH ?
        """
        params: list = [safe_query]

        if active_only:
            sql += " AND m.active = 1"
        if type_filter:
            sql += " AND m.type = ?"
            params.append(type_filter)

        sql += " ORDER BY bm25(memories_fts) LIMIT ?"
        params.append(limit)

        try:
            rows = self._conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]
        except sqlite3.OperationalError as e:
            logger.warning("FTS5 search error for query %r: %s", query, e)
            return []

    def get_recent(self, limit: int = 5, active_only: bool = True) -> list[dict]:
        """Return the N most recently created memories."""
        sql = "SELECT * FROM memories"
        if active_only:
            sql += " WHERE active = 1"
        sql += " ORDER BY created_at DESC LIMIT ?"
        rows = self._conn.execute(sql, (limit,)).fetchall()
        return [dict(r) for r in rows]

    def get_by_type(
        self, type: str, *, limit: int = 50, active_only: bool = True
    ) -> list[dict]:
        """Return memories of a specific type, ordered by importance DESC."""
        sql = "SELECT * FROM memories WHERE type = ?"
        params: list = [type]
        if active_only:
            sql += " AND active = 1"
        sql += " ORDER BY importance DESC LIMIT ?"
        params.append(limit)
        rows = self._conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def get_all_active(self, *, limit: int = 500) -> list[dict]:
        """Return all active memories ordered by importance DESC."""
        rows = self._conn.execute(
            "SELECT * FROM memories WHERE active = 1 ORDER BY importance DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def update_access(self, memory_id: int) -> None:
        """Bump accessed_at and access_count for a retrieved memory."""
        now = datetime.utcnow().isoformat()
        self._conn.execute(
            "UPDATE memories SET accessed_at = ?, access_count = access_count + 1 WHERE id = ?",
            (now, memory_id),
        )
        self._conn.commit()

    def update_importance(self, memory_id: int, new_importance: float) -> None:
        """Set a new importance score."""
        self._conn.execute(
            "UPDATE memories SET importance = ? WHERE id = ?",
            (new_importance, memory_id),
        )
        self._conn.commit()

    def soft_delete(self, memory_id: int) -> None:
        """Set active=0 (soft delete)."""
        self._conn.execute(
            "UPDATE memories SET active = 0 WHERE id = ?", (memory_id,)
        )
        self._conn.commit()

    def soft_delete_matching(self, query: str) -> int:
        """FTS5 search for matching memories and soft-delete them. Return count."""
        matches = self.search(query, limit=50, active_only=True)
        count = 0
        for m in matches:
            self.soft_delete(m["id"])
            count += 1
        return count

    def find_duplicates(self, content: str, threshold: float = 0.7) -> list[dict]:
        """Search FTS5 for very similar entries. Used for dedup before insert."""
        # Use first 8 significant words as search query
        words = [w for w in content.lower().split() if len(w) > 2][:8]
        if not words:
            return []

        candidates = self.search(" ".join(words), limit=5, active_only=True)
        dupes = []
        for c in candidates:
            if _token_overlap(content, c["content"]) >= threshold:
                dupes.append(c)
        return dupes

    def decay_importance(
        self, decay_factor: float = 0.95, min_threshold: float = 0.1
    ) -> tuple[int, int]:
        """Reduce importance of active memories. Archive those below threshold.

        Returns (decayed_count, archived_count).
        """
        # Decay all active memories
        self._conn.execute(
            "UPDATE memories SET importance = importance * ? WHERE active = 1",
            (decay_factor,),
        )
        # Archive those below threshold
        cur = self._conn.execute(
            "UPDATE memories SET active = 0 WHERE active = 1 AND importance < ?",
            (min_threshold,),
        )
        archived = cur.rowcount
        self._conn.commit()

        total = self._conn.execute(
            "SELECT COUNT(*) FROM memories WHERE active = 1"
        ).fetchone()[0]
        return total, archived

    def export_top_memories(self, limit: int = 50) -> list[dict]:
        """Return top memories by importance for MEMORY.md sync."""
        return self.get_all_active(limit=limit)

    def count(self, active_only: bool = True) -> int:
        """Return total memory count."""
        if active_only:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM memories WHERE active = 1"
            ).fetchone()
        else:
            row = self._conn.execute("SELECT COUNT(*) FROM memories").fetchone()
        return row[0]

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()


def _token_overlap(a: str, b: str) -> float:
    """Jaccard similarity of lowercased word sets."""
    set_a = set(a.lower().split())
    set_b = set(b.lower().split())
    if not set_a or not set_b:
        return 0.0
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union)
