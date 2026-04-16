"""SQLite + FTS5 storage backend for agent memory."""

from __future__ import annotations

import json
import sqlite3
import struct
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

-- Memory expiry and staleness tracking
CREATE TABLE IF NOT EXISTS memory_expiry (
    memory_id     INTEGER PRIMARY KEY REFERENCES memories(id),
    expires_at    TEXT,              -- ISO datetime, NULL = never expires
    stale_at      TEXT,              -- when the memory was flagged stale
    review_status TEXT NOT NULL DEFAULT 'active',  -- active, stale, expired, reviewed
    last_reviewed TEXT,              -- when a user last confirmed/dismissed
    staleness_reason TEXT DEFAULT '' -- why it was flagged
);

CREATE INDEX IF NOT EXISTS idx_expiry_status ON memory_expiry(review_status);
CREATE INDEX IF NOT EXISTS idx_expiry_expires ON memory_expiry(expires_at);

-- Embeddings table for vector search
CREATE TABLE IF NOT EXISTS memory_embeddings (
    memory_id    INTEGER PRIMARY KEY REFERENCES memories(id),
    embedding    BLOB NOT NULL,
    dimensions   INTEGER NOT NULL,
    provider     TEXT NOT NULL DEFAULT 'local',
    created_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_embeddings_memory ON memory_embeddings(memory_id);

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
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
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

    # --- Expiry / staleness methods ---

    def set_expiry(
        self,
        memory_id: int,
        expires_at: str | None = None,
    ) -> None:
        """Set or update expiry for a memory."""
        now = datetime.utcnow().isoformat()
        self._conn.execute(
            """INSERT INTO memory_expiry (memory_id, expires_at, review_status)
               VALUES (?, ?, 'active')
               ON CONFLICT(memory_id) DO UPDATE SET expires_at = ?""",
            (memory_id, expires_at, expires_at),
        )
        self._conn.commit()

    def flag_stale(
        self, memory_id: int, reason: str = ""
    ) -> None:
        """Flag a memory as stale and needing review."""
        now = datetime.utcnow().isoformat()
        self._conn.execute(
            """INSERT INTO memory_expiry (memory_id, stale_at, review_status, staleness_reason)
               VALUES (?, ?, 'stale', ?)
               ON CONFLICT(memory_id) DO UPDATE SET
                   stale_at = ?, review_status = 'stale', staleness_reason = ?""",
            (memory_id, now, reason, now, reason),
        )
        self._conn.commit()

    def mark_reviewed(self, memory_id: int) -> None:
        """Mark a stale memory as reviewed (confirmed still valid)."""
        now = datetime.utcnow().isoformat()
        self._conn.execute(
            """UPDATE memory_expiry
               SET review_status = 'reviewed', last_reviewed = ?, stale_at = NULL
               WHERE memory_id = ?""",
            (now, memory_id),
        )
        self._conn.commit()

    def get_stale_memories(self, limit: int = 50) -> list[dict]:
        """Return memories flagged as stale, joined with memory data."""
        rows = self._conn.execute(
            """SELECT m.*, e.stale_at, e.expires_at, e.review_status, e.staleness_reason
               FROM memory_expiry e
               JOIN memories m ON m.id = e.memory_id
               WHERE e.review_status = 'stale' AND m.active = 1
               ORDER BY e.stale_at ASC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_expired_memories(self) -> list[dict]:
        """Return memories that have passed their expiry date."""
        now = datetime.utcnow().isoformat()
        rows = self._conn.execute(
            """SELECT m.*, e.expires_at, e.review_status
               FROM memory_expiry e
               JOIN memories m ON m.id = e.memory_id
               WHERE e.expires_at IS NOT NULL AND e.expires_at < ?
                 AND m.active = 1 AND e.review_status != 'expired'
               ORDER BY e.expires_at ASC""",
            (now,),
        ).fetchall()
        return [dict(r) for r in rows]

    def expire_old_memories(self) -> int:
        """Archive memories that have passed their expiry date. Returns count."""
        now = datetime.utcnow().isoformat()
        expired = self.get_expired_memories()
        count = 0
        for mem in expired:
            self.soft_delete(mem["id"])
            self._conn.execute(
                "UPDATE memory_expiry SET review_status = 'expired' WHERE memory_id = ?",
                (mem["id"],),
            )
            count += 1
        if count:
            self._conn.commit()
        return count

    def detect_stale_by_age(
        self, max_age_days: int = 30, min_access_count: int = 0
    ) -> int:
        """Flag memories as stale if they haven't been accessed in N days
        and have low access counts. Returns count flagged."""
        from datetime import timedelta
        cutoff = (datetime.utcnow() - timedelta(days=max_age_days)).isoformat()
        # Find old, low-access memories not already flagged
        rows = self._conn.execute(
            """SELECT m.id, m.content, m.accessed_at, m.access_count
               FROM memories m
               LEFT JOIN memory_expiry e ON m.id = e.memory_id
               WHERE m.active = 1
                 AND m.accessed_at < ?
                 AND m.access_count <= ?
                 AND (e.review_status IS NULL OR e.review_status = 'active')""",
            (cutoff, min_access_count),
        ).fetchall()

        count = 0
        for row in rows:
            reason = f"Not accessed in {max_age_days}+ days (last: {row['accessed_at'][:10]}, accesses: {row['access_count']})"
            self.flag_stale(row["id"], reason)
            count += 1
        return count

    def detect_stale_by_importance(self, threshold: float = 0.2) -> int:
        """Flag low-importance memories as stale. Returns count flagged."""
        rows = self._conn.execute(
            """SELECT m.id, m.importance
               FROM memories m
               LEFT JOIN memory_expiry e ON m.id = e.memory_id
               WHERE m.active = 1
                 AND m.importance < ?
                 AND m.importance > 0.1
                 AND (e.review_status IS NULL OR e.review_status = 'active')""",
            (threshold,),
        ).fetchall()

        count = 0
        for row in rows:
            reason = f"Low importance score: {row['importance']:.2f}"
            self.flag_stale(row["id"], reason)
            count += 1
        return count

    def get_expiry_stats(self) -> dict:
        """Return expiry/staleness statistics."""
        total_with_expiry = self._conn.execute(
            "SELECT COUNT(*) FROM memory_expiry"
        ).fetchone()[0]
        stale = self._conn.execute(
            "SELECT COUNT(*) FROM memory_expiry WHERE review_status = 'stale'"
        ).fetchone()[0]
        expired = self._conn.execute(
            "SELECT COUNT(*) FROM memory_expiry WHERE review_status = 'expired'"
        ).fetchone()[0]
        reviewed = self._conn.execute(
            "SELECT COUNT(*) FROM memory_expiry WHERE review_status = 'reviewed'"
        ).fetchone()[0]
        return {
            "total_tracked": total_with_expiry,
            "stale": stale,
            "expired": expired,
            "reviewed": reviewed,
        }

    # --- Embedding / vector search methods ---

    def store_embedding(
        self, memory_id: int, embedding: list[float], provider: str = "local"
    ) -> None:
        """Store an embedding vector for a memory."""
        blob = _floats_to_blob(embedding)
        now = datetime.utcnow().isoformat()
        self._conn.execute(
            """INSERT OR REPLACE INTO memory_embeddings
               (memory_id, embedding, dimensions, provider, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (memory_id, blob, len(embedding), provider, now),
        )
        self._conn.commit()

    def get_embedding(self, memory_id: int) -> list[float] | None:
        """Retrieve embedding for a memory."""
        row = self._conn.execute(
            "SELECT embedding, dimensions FROM memory_embeddings WHERE memory_id = ?",
            (memory_id,),
        ).fetchone()
        if not row:
            return None
        return _blob_to_floats(row[0], row[1])

    def vector_search(
        self,
        query_embedding: list[float],
        limit: int = 10,
        active_only: bool = True,
    ) -> list[dict]:
        """Brute-force cosine similarity search over stored embeddings.

        Returns memory rows with added 'cosine_score' field.
        """
        # Fetch all embeddings
        sql = """
            SELECT e.memory_id, e.embedding, e.dimensions, m.*
            FROM memory_embeddings e
            JOIN memories m ON m.id = e.memory_id
        """
        if active_only:
            sql += " WHERE m.active = 1"

        rows = self._conn.execute(sql).fetchall()
        if not rows:
            return []

        scored = []
        for row in rows:
            row_dict = dict(row)
            stored = _blob_to_floats(row_dict["embedding"], row_dict["dimensions"])
            score = _cosine_similarity(query_embedding, stored)
            row_dict["cosine_score"] = score
            # Clean up embedding fields from result
            del row_dict["embedding"]
            del row_dict["dimensions"]
            del row_dict["provider"]
            scored.append(row_dict)

        scored.sort(key=lambda x: x["cosine_score"], reverse=True)
        return scored[:limit]

    def get_memories_without_embeddings(self, limit: int = 100) -> list[dict]:
        """Find active memories that don't have embeddings yet."""
        rows = self._conn.execute(
            """SELECT m.* FROM memories m
               LEFT JOIN memory_embeddings e ON m.id = e.memory_id
               WHERE m.active = 1 AND e.memory_id IS NULL
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()


def _floats_to_blob(floats: list[float]) -> bytes:
    """Pack a list of floats into a compact binary blob."""
    return struct.pack(f"{len(floats)}f", *floats)


def _blob_to_floats(blob: bytes, dimensions: int) -> list[float]:
    """Unpack a binary blob back to floats."""
    return list(struct.unpack(f"{dimensions}f", blob))


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _token_overlap(a: str, b: str) -> float:
    """Jaccard similarity of lowercased word sets."""
    set_a = set(a.lower().split())
    set_b = set(b.lower().split())
    if not set_a or not set_b:
        return 0.0
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union)
