"""Per-contact conversation state machine.

States::

    awaiting_reply    user wrote, agent hasn't replied yet
    followup_needed   agent replied, but committed to a follow-up OR the user
                      has been silent past awaiting_reply_ttl
    resolved          last exchange closed; nothing pending
    snoozed           explicitly deferred until snooze_until
    ignored           triage filtered or user explicitly muted

The state is keyed by ``contact.canonical_id`` (NOT channel_user_id) so a
contact who switches from email to Telegram still has one continuous
state — that's the whole point of the contact registry.

This module owns its own SQLite file. It's intentionally separate from
both the memory store and the contact store: states change very
frequently and benefit from being independently truncatable.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from autonoma.config import ConversationStateConfig
from autonoma.observability.metrics import (
    conversation_state_changes_total,
    followups_due,
    followups_scheduled_total,
)

logger = logging.getLogger(__name__)


STATE_AWAITING_REPLY = "awaiting_reply"
STATE_FOLLOWUP_NEEDED = "followup_needed"
STATE_RESOLVED = "resolved"
STATE_SNOOZED = "snoozed"
STATE_IGNORED = "ignored"


# Tag emitted by the agent in its reply when it wants to schedule a self
# follow-up. Mirrors the [REMEMBER:...] / [FORGET:...] convention already
# used for memory commands so the LLM has one consistent extension point.
FOLLOWUP_RE = re.compile(
    r"\[FOLLOWUP:\s*(?P<spec>[^\]]+)\]",
    re.IGNORECASE,
)
FOLLOWUP_STRIP_RE = re.compile(r"\[FOLLOWUP:[^\]]+\]\s*", re.IGNORECASE)


@dataclass
class ConversationState:
    canonical_id: str
    state: str
    last_inbound_at: float
    last_outbound_at: float
    last_user_message_id: str
    snooze_until: float | None
    followup_due_at: float | None
    metadata: dict[str, Any]


_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversation_states (
    canonical_id          TEXT PRIMARY KEY,
    state                 TEXT NOT NULL,
    last_inbound_at       REAL NOT NULL DEFAULT 0,
    last_outbound_at      REAL NOT NULL DEFAULT 0,
    last_user_message_id  TEXT NOT NULL DEFAULT '',
    snooze_until          REAL,
    followup_due_at       REAL,
    metadata_json         TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_state_due ON conversation_states(state, followup_due_at);
CREATE INDEX IF NOT EXISTS idx_state_snooze ON conversation_states(state, snooze_until);
"""


class ConversationStateStore:
    """Async-friendly state store. One row per canonical contact."""

    def __init__(self, config: ConversationStateConfig):
        self._config = config
        self._db_path = Path(config.db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()
        self._init_schema()

    @contextlib.contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._db_path, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    # ------------------------------------------------------------------ public

    async def record_inbound(
        self, canonical_id: str, message_id: str
    ) -> ConversationState:
        """User sent us a message → state = awaiting_reply."""
        if not self._config.enabled or not canonical_id:
            return self._dummy(canonical_id)
        async with self._lock:
            return await asyncio.to_thread(
                self._record_inbound_sync, canonical_id, message_id
            )

    def _record_inbound_sync(
        self, canonical_id: str, message_id: str
    ) -> ConversationState:
        now = time.time()
        with self._connect() as conn:
            existing = self._fetch(conn, canonical_id)
            old_state = existing.state if existing else None

            # If the contact is snoozed and the snooze hasn't expired, leave
            # them snoozed — but still update last_inbound_at so we remember
            # the message landed.
            if existing and existing.state == STATE_SNOOZED and (
                existing.snooze_until and existing.snooze_until > now
            ):
                conn.execute(
                    "UPDATE conversation_states SET last_inbound_at = ?, "
                    "last_user_message_id = ? WHERE canonical_id = ?",
                    (now, message_id, canonical_id),
                )
                return self._fetch(conn, canonical_id)  # type: ignore[return-value]

            new_state = STATE_AWAITING_REPLY
            conn.execute(
                "INSERT INTO conversation_states "
                "(canonical_id, state, last_inbound_at, last_user_message_id) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(canonical_id) DO UPDATE SET "
                "  state = excluded.state, "
                "  last_inbound_at = excluded.last_inbound_at, "
                "  last_user_message_id = excluded.last_user_message_id, "
                "  snooze_until = NULL",
                (canonical_id, new_state, now, message_id),
            )
            self._record_transition(old_state, new_state)
            return self._fetch(conn, canonical_id)  # type: ignore[return-value]

    async def record_outbound(
        self,
        canonical_id: str,
        *,
        followup_at: float | None = None,
        followup_reason: str = "",
    ) -> ConversationState:
        """Agent replied. Default → resolved; if followup_at given → followup_needed."""
        if not self._config.enabled or not canonical_id:
            return self._dummy(canonical_id)
        async with self._lock:
            return await asyncio.to_thread(
                self._record_outbound_sync,
                canonical_id, followup_at, followup_reason,
            )

    def _record_outbound_sync(
        self, canonical_id: str, followup_at: float | None, followup_reason: str,
    ) -> ConversationState:
        now = time.time()
        with self._connect() as conn:
            existing = self._fetch(conn, canonical_id)
            old_state = existing.state if existing else None

            if followup_at:
                new_state = STATE_FOLLOWUP_NEEDED
                metadata = {"followup_reason": followup_reason} if followup_reason else {}
                conn.execute(
                    "INSERT INTO conversation_states "
                    "(canonical_id, state, last_outbound_at, followup_due_at, metadata_json) "
                    "VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT(canonical_id) DO UPDATE SET "
                    "  state = excluded.state, "
                    "  last_outbound_at = excluded.last_outbound_at, "
                    "  followup_due_at = excluded.followup_due_at, "
                    "  metadata_json = excluded.metadata_json",
                    (canonical_id, new_state, now, followup_at, json.dumps(metadata)),
                )
                try:
                    followups_scheduled_total.inc()
                except Exception:  # pragma: no cover
                    pass
            else:
                new_state = STATE_RESOLVED
                conn.execute(
                    "INSERT INTO conversation_states "
                    "(canonical_id, state, last_outbound_at) "
                    "VALUES (?, ?, ?) "
                    "ON CONFLICT(canonical_id) DO UPDATE SET "
                    "  state = excluded.state, "
                    "  last_outbound_at = excluded.last_outbound_at, "
                    "  followup_due_at = NULL",
                    (canonical_id, new_state, now),
                )
            self._record_transition(old_state, new_state)
            return self._fetch(conn, canonical_id)  # type: ignore[return-value]

    async def snooze(
        self, canonical_id: str, until: float | None = None
    ) -> ConversationState:
        if not self._config.enabled or not canonical_id:
            return self._dummy(canonical_id)
        deadline = until or (time.time() + self._config.snooze_default_hours * 3600)
        async with self._lock:
            return await asyncio.to_thread(self._snooze_sync, canonical_id, deadline)

    def _snooze_sync(self, canonical_id: str, deadline: float) -> ConversationState:
        with self._connect() as conn:
            existing = self._fetch(conn, canonical_id)
            old_state = existing.state if existing else None
            conn.execute(
                "INSERT INTO conversation_states (canonical_id, state, snooze_until) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT(canonical_id) DO UPDATE SET "
                "  state = excluded.state, snooze_until = excluded.snooze_until",
                (canonical_id, STATE_SNOOZED, deadline),
            )
            self._record_transition(old_state, STATE_SNOOZED)
            return self._fetch(conn, canonical_id)  # type: ignore[return-value]

    async def get(self, canonical_id: str) -> ConversationState | None:
        return await asyncio.to_thread(self._get_sync, canonical_id)

    def _get_sync(self, canonical_id: str) -> ConversationState | None:
        with self._connect() as conn:
            return self._fetch(conn, canonical_id)

    async def find_due_followups(self, now: float | None = None) -> list[ConversationState]:
        """Return all contacts whose follow-up is due, plus stale awaiting_reply.

        Two sources:
        * explicit follow-ups whose ``followup_due_at`` has passed
        * awaiting_reply rows older than ``awaiting_reply_ttl_hours``
          (auto-promoted to followup_needed by this call)
        """
        if not self._config.enabled:
            return []
        return await asyncio.to_thread(self._find_due_sync, now or time.time())

    def _find_due_sync(self, now: float) -> list[ConversationState]:
        ttl_seconds = self._config.awaiting_reply_ttl_hours * 3600
        cutoff = now - ttl_seconds
        with self._connect() as conn:
            # Auto-promote stale awaiting_reply rows.
            stale = conn.execute(
                "SELECT canonical_id FROM conversation_states "
                "WHERE state = ? AND last_inbound_at < ? AND last_inbound_at > 0",
                (STATE_AWAITING_REPLY, cutoff),
            ).fetchall()
            for row in stale:
                conn.execute(
                    "UPDATE conversation_states SET state = ?, followup_due_at = ? "
                    "WHERE canonical_id = ?",
                    (STATE_FOLLOWUP_NEEDED, now, row["canonical_id"]),
                )
                self._record_transition(STATE_AWAITING_REPLY, STATE_FOLLOWUP_NEEDED)

            # Wake snoozed rows whose deadline passed → back to awaiting_reply.
            woken = conn.execute(
                "UPDATE conversation_states SET state = ?, snooze_until = NULL "
                "WHERE state = ? AND snooze_until IS NOT NULL AND snooze_until <= ? "
                "RETURNING canonical_id",
                (STATE_AWAITING_REPLY, STATE_SNOOZED, now),
            ).fetchall()
            for _ in woken:
                self._record_transition(STATE_SNOOZED, STATE_AWAITING_REPLY)

            rows = conn.execute(
                "SELECT * FROM conversation_states "
                "WHERE state = ? AND followup_due_at IS NOT NULL AND followup_due_at <= ? "
                "ORDER BY followup_due_at ASC",
                (STATE_FOLLOWUP_NEEDED, now),
            ).fetchall()

        results = [self._row_to_state(r) for r in rows]
        try:
            followups_due.set(len(results))
        except Exception:  # pragma: no cover
            pass
        return results

    # ------------------------------------------------------------------ helpers

    def _fetch(self, conn: sqlite3.Connection, canonical_id: str) -> ConversationState | None:
        row = conn.execute(
            "SELECT * FROM conversation_states WHERE canonical_id = ?",
            (canonical_id,),
        ).fetchone()
        return self._row_to_state(row) if row else None

    @staticmethod
    def _row_to_state(row: sqlite3.Row) -> ConversationState:
        try:
            metadata = json.loads(row["metadata_json"] or "{}")
        except (json.JSONDecodeError, TypeError):
            metadata = {}
        return ConversationState(
            canonical_id=row["canonical_id"],
            state=row["state"],
            last_inbound_at=row["last_inbound_at"] or 0.0,
            last_outbound_at=row["last_outbound_at"] or 0.0,
            last_user_message_id=row["last_user_message_id"] or "",
            snooze_until=row["snooze_until"],
            followup_due_at=row["followup_due_at"],
            metadata=metadata,
        )

    @staticmethod
    def _dummy(canonical_id: str) -> ConversationState:
        return ConversationState(
            canonical_id=canonical_id or "",
            state=STATE_RESOLVED,
            last_inbound_at=0.0,
            last_outbound_at=0.0,
            last_user_message_id="",
            snooze_until=None,
            followup_due_at=None,
            metadata={},
        )

    @staticmethod
    def _record_transition(old: str | None, new: str) -> None:
        try:
            conversation_state_changes_total.inc(labels={
                "from": old or "none",
                "to": new,
            })
        except Exception:  # pragma: no cover
            pass


# --- Tag parsing helpers -----------------------------------------------------


def parse_followup_tag(reply: str) -> tuple[float | None, str, str]:
    """Pull the first [FOLLOWUP: ...] tag out of a reply.

    Returns ``(due_at_unix, reason, cleaned_reply)``.

    Specs accepted:
        [FOLLOWUP: 3d when budget approved]
        [FOLLOWUP: 24h waiting on legal]
        [FOLLOWUP: 30m]
        [FOLLOWUP: tomorrow finish review]
        [FOLLOWUP: 2026-05-10 quarterly check-in]
    """
    match = FOLLOWUP_RE.search(reply or "")
    if not match:
        return None, "", reply or ""

    spec = match.group("spec").strip()
    cleaned = FOLLOWUP_STRIP_RE.sub("", reply, count=1).strip()

    due_at, reason = _parse_spec(spec)
    return due_at, reason, cleaned


_DURATION_RE = re.compile(r"^(\d+)\s*([smhdw])\b", re.IGNORECASE)
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


def _parse_spec(spec: str) -> tuple[float | None, str]:
    """Parse the FOLLOWUP spec body into (due_at, reason).

    Order of attempts: relative duration, named day (today/tomorrow), ISO
    date, fallback (treat whole spec as reason, default 24h offset).
    """
    s = spec.strip()
    now = time.time()

    m = _DURATION_RE.match(s)
    if m:
        amount = int(m.group(1))
        unit = m.group(2).lower()
        due = now + amount * _UNIT_SECONDS[unit]
        reason = s[m.end():].strip()
        return due, reason

    lower = s.lower()
    if lower.startswith("tomorrow"):
        return now + 86400, s.split(None, 1)[1] if " " in s else ""
    if lower.startswith("today"):
        return now + 8 * 3600, s.split(None, 1)[1] if " " in s else ""
    if lower.startswith("next week"):
        return now + 7 * 86400, s.split(None, 2)[2] if s.count(" ") >= 2 else ""

    # ISO date YYYY-MM-DD prefix.
    iso_match = re.match(r"(\d{4}-\d{2}-\d{2})\b", s)
    if iso_match:
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(iso_match.group(1))
            reason = s[iso_match.end():].strip()
            return dt.timestamp(), reason
        except ValueError:
            pass

    # Fallback: 24h default with the whole spec as the reason.
    return now + 86400, s
