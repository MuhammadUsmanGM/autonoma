"""Contact registry — identity resolution + relationship tiering.

Every inbound message gets attached to a ``Contact`` row keyed by a stable
``canonical_id``. Multiple ``(channel, channel_user_id)`` pairs can resolve
to the same contact, so context follows the human across Telegram /
Gmail / WhatsApp / etc.

The tier — ``stranger | acquaintance | colleague | vip`` — is computed
from message volume plus explicit overrides in :class:`RelationshipConfig`.
The agent loop injects a relationship summary into the system prompt so
tone calibration is automatic: a stranger gets formal+brief, a VIP gets
polished+thorough.

Storage is a small SQLite database, separate from the main memory DB so
it can be wiped/exported independently.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

from autonoma.config import RelationshipConfig
from autonoma.cortex.identity import (
    CROSS_CHANNEL_KINDS,
    KIND_NATIVE,
    Identifier,
    classify_user_id,
    extract_identifiers_from_text,
)
from autonoma.observability.metrics import contact_tier_total
from autonoma.schema import Message

logger = logging.getLogger(__name__)


# Tier constants — exported so other modules don't pass typo'd strings.
TIER_STRANGER = "stranger"
TIER_ACQUAINTANCE = "acquaintance"
TIER_COLLEAGUE = "colleague"
TIER_VIP = "vip"

_VALID_TIERS = {TIER_STRANGER, TIER_ACQUAINTANCE, TIER_COLLEAGUE, TIER_VIP}


@dataclass
class Contact:
    canonical_id: str
    display_name: str
    tier: str
    message_count: int
    first_seen: float  # unix ts
    last_seen: float
    vip_flag: bool
    notes: str = ""
    # All (channel, channel_user_id) pairs that resolve to this contact.
    identities: list[tuple[str, str]] | None = None


_SCHEMA = """
CREATE TABLE IF NOT EXISTS contacts (
    canonical_id      TEXT PRIMARY KEY,
    display_name      TEXT NOT NULL DEFAULT '',
    tier              TEXT NOT NULL DEFAULT 'stranger',
    message_count     INTEGER NOT NULL DEFAULT 0,
    first_seen        REAL NOT NULL,
    last_seen         REAL NOT NULL,
    vip_flag          INTEGER NOT NULL DEFAULT 0,
    notes             TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS contact_identities (
    channel           TEXT NOT NULL,
    channel_user_id   TEXT NOT NULL,
    canonical_id      TEXT NOT NULL,
    identifier_kind   TEXT NOT NULL DEFAULT 'native',
    identifier_value  TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (channel, channel_user_id),
    FOREIGN KEY (canonical_id) REFERENCES contacts(canonical_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_identities_canonical ON contact_identities(canonical_id);
"""

# Migration: older DBs are missing identifier_kind / identifier_value. Added
# in _init_schema with explicit ALTERs since SQLite has no ``ADD COLUMN IF
# NOT EXISTS``. The cross-channel-match index is also created post-migration
# so it can reference the columns regardless of schema vintage.


class ContactStore:
    """Async-friendly SQLite-backed contact + identity registry."""

    def __init__(self, config: RelationshipConfig):
        self._config = config
        self._db_path = Path(config.db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()
        self._init_schema()

    # ------------------------------------------------------------------ schema

    @contextlib.contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._db_path, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            # Migrate older DBs that predate identity-kind columns. Probing
            # PRAGMA is cheaper than catching the IntegrityError per insert.
            cols = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(contact_identities)")
            }
            if "identifier_kind" not in cols:
                conn.execute(
                    "ALTER TABLE contact_identities ADD COLUMN "
                    "identifier_kind TEXT NOT NULL DEFAULT 'native'"
                )
            if "identifier_value" not in cols:
                conn.execute(
                    "ALTER TABLE contact_identities ADD COLUMN "
                    "identifier_value TEXT NOT NULL DEFAULT ''"
                )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_identities_kind_value "
                "ON contact_identities(identifier_kind, identifier_value)"
            )

    # ------------------------------------------------------------------ public

    async def upsert(self, message: Message) -> Contact:
        """Resolve (or create) the contact for an inbound message and update tier.

        This is the single hot path the agent loop calls per message — keep
        it cheap. Tier recomputation is a few comparisons; identity lookup
        is one indexed read.

        Body-extracted identifiers (emails / phones found in
        ``message.content``) are part of the resolution: an inbound
        Telegram message that mentions a known email gets attached to that
        same contact instead of forking a new one.
        """
        if not self._config.enabled:
            return self._synthetic_contact(message)

        body_idents = extract_identifiers_from_text(message.content or "")
        async with self._lock:
            return await asyncio.to_thread(self._upsert_sync, message, body_idents)

    def _upsert_sync(
        self, message: Message, body_idents: list[Identifier] | None = None
    ) -> Contact:
        now = time.time()
        channel = message.channel or "unknown"
        channel_user_id = (message.user_id or "").strip()
        display_name = (message.user_name or "").strip()

        # Typed identity for the inbound (channel, user_id). Email/phone
        # kinds participate in cross-channel auto-link; native stays scoped
        # to its own channel.
        ident = classify_user_id(channel, channel_user_id)

        with self._connect() as conn:
            row = conn.execute(
                "SELECT canonical_id FROM contact_identities "
                "WHERE channel = ? AND channel_user_id = ?",
                (channel, channel_user_id),
            ).fetchone()

            if row is None:
                # Resolution priority for a brand-new (channel, user_id):
                #   1. Same typed identifier on the channel-native key (e.g.
                #      Gmail user_id is itself an email already known).
                #   2. Same identifier extracted from the message body
                #      (Telegram message that mentions a known email).
                #   3. Same display_name (existing generic fallback).
                #   4. Brand-new contact.
                canonical_id = (
                    self._maybe_merge_by_identifier(conn, ident)
                    or self._maybe_merge_by_body_idents(conn, body_idents or [])
                    or self._maybe_merge_by_name(conn, display_name)
                    or f"c_{uuid.uuid4().hex[:8]}"
                )
                conn.execute(
                    "INSERT OR IGNORE INTO contacts "
                    "(canonical_id, display_name, tier, message_count, first_seen, last_seen, vip_flag) "
                    "VALUES (?, ?, ?, 0, ?, ?, 0)",
                    (canonical_id, display_name, self._config.default_tier, now, now),
                )
                conn.execute(
                    "INSERT OR REPLACE INTO contact_identities "
                    "(channel, channel_user_id, canonical_id, identifier_kind, identifier_value) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (channel, channel_user_id, canonical_id, ident.kind, ident.value),
                )
            else:
                canonical_id = row["canonical_id"]
                # Backfill the typed columns for rows that predate the
                # identity-kind migration. Cheap (no-op if already set).
                conn.execute(
                    "UPDATE contact_identities SET identifier_kind = ?, identifier_value = ? "
                    "WHERE channel = ? AND channel_user_id = ? "
                    "AND (identifier_kind = '' OR identifier_kind = 'native' AND identifier_value = '')",
                    (ident.kind, ident.value, channel, channel_user_id),
                )

            # Bump counters and recompute tier.
            conn.execute(
                "UPDATE contacts SET "
                "  message_count = message_count + 1, "
                "  last_seen = ?, "
                "  display_name = COALESCE(NULLIF(?, ''), display_name) "
                "WHERE canonical_id = ?",
                (now, display_name, canonical_id),
            )

            contact = self._fetch(conn, canonical_id)
            new_tier = self._compute_tier(contact, message)
            if new_tier != contact.tier:
                conn.execute(
                    "UPDATE contacts SET tier = ? WHERE canonical_id = ?",
                    (new_tier, canonical_id),
                )
                contact.tier = new_tier
                logger.info(
                    "Contact %s tier → %s (msgs=%d)",
                    canonical_id, new_tier, contact.message_count,
                )

        try:
            contact_tier_total.inc(labels={
                "tier": contact.tier,
                "channel": channel,
            })
        except Exception:  # pragma: no cover
            pass
        return contact

    async def get(self, canonical_id: str) -> Contact | None:
        return await asyncio.to_thread(self._get_sync, canonical_id)

    def _get_sync(self, canonical_id: str) -> Contact | None:
        with self._connect() as conn:
            return self._fetch(conn, canonical_id)

    async def lookup(self, channel: str, channel_user_id: str) -> Contact | None:
        return await asyncio.to_thread(self._lookup_sync, channel, channel_user_id)

    def _lookup_sync(self, channel: str, channel_user_id: str) -> Contact | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT canonical_id FROM contact_identities "
                "WHERE channel = ? AND channel_user_id = ?",
                (channel, channel_user_id),
            ).fetchone()
            if row is None:
                return None
            return self._fetch(conn, row["canonical_id"])

    async def link_identity(
        self,
        canonical_id: str,
        channel: str,
        channel_user_id: str,
        *,
        identifier_kind: str = KIND_NATIVE,
        identifier_value: str = "",
    ) -> None:
        """Explicitly link a (channel, user_id) pair to an existing contact.

        Called when the dashboard merges contacts manually, or when the
        agent emits a ``[LINK_IDENTITY: ...]`` tag in its reply.
        """
        await asyncio.to_thread(
            self._link_identity_sync,
            canonical_id, channel, channel_user_id, identifier_kind, identifier_value,
        )

    def _link_identity_sync(
        self,
        canonical_id: str,
        channel: str,
        channel_user_id: str,
        identifier_kind: str,
        identifier_value: str,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO contact_identities "
                "(channel, channel_user_id, canonical_id, identifier_kind, identifier_value) "
                "VALUES (?, ?, ?, ?, ?)",
                (channel, channel_user_id, canonical_id, identifier_kind, identifier_value),
            )

    async def add_extracted_identifiers(
        self, canonical_id: str, identifiers: Iterable[Identifier]
    ) -> int:
        """Attach identifiers extracted from message bodies to a contact.

        Stored as ``contact_identities`` rows where ``channel = "extracted"``
        and ``channel_user_id = "{kind}:{value}"`` — a synthetic key that
        keeps the existing PRIMARY KEY constraint intact while letting the
        cross-channel match index find them. Returns the count actually
        inserted (existing identifiers are skipped).
        """
        idents = [i for i in identifiers if i.is_cross_channel() and i.value]
        if not idents:
            return 0
        return await asyncio.to_thread(
            self._add_extracted_sync, canonical_id, idents
        )

    def _add_extracted_sync(
        self, canonical_id: str, identifiers: list[Identifier]
    ) -> int:
        added = 0
        with self._connect() as conn:
            for ident in identifiers:
                synthetic_key = f"{ident.kind}:{ident.value}"
                # If the identifier is already attached to *some* contact,
                # don't claim it for this one — preserves whichever contact
                # got there first; explicit merge is the way to override.
                existing = conn.execute(
                    "SELECT canonical_id FROM contact_identities "
                    "WHERE identifier_kind = ? AND identifier_value = ? LIMIT 1",
                    (ident.kind, ident.value),
                ).fetchone()
                if existing is not None:
                    continue
                try:
                    conn.execute(
                        "INSERT INTO contact_identities "
                        "(channel, channel_user_id, canonical_id, identifier_kind, identifier_value) "
                        "VALUES (?, ?, ?, ?, ?)",
                        ("extracted", synthetic_key, canonical_id, ident.kind, ident.value),
                    )
                    added += 1
                except sqlite3.IntegrityError:
                    # Race: another worker inserted the same synthetic key.
                    # Safe to ignore — the row is in place either way.
                    pass
        return added

    async def merge_contacts(self, keep_id: str, drop_id: str) -> Contact | None:
        """Merge two contacts: move all identities and counters into ``keep_id``,
        delete ``drop_id``. Used by the dashboard "merge" action.

        Returns the merged contact, or ``None`` if either id is unknown.
        """
        if keep_id == drop_id:
            return await self.get(keep_id)
        async with self._lock:
            return await asyncio.to_thread(self._merge_contacts_sync, keep_id, drop_id)

    def _merge_contacts_sync(self, keep_id: str, drop_id: str) -> Contact | None:
        with self._connect() as conn:
            keep_row = conn.execute(
                "SELECT canonical_id FROM contacts WHERE canonical_id = ?",
                (keep_id,),
            ).fetchone()
            drop_row = conn.execute(
                "SELECT canonical_id, message_count, first_seen, last_seen, vip_flag, notes "
                "FROM contacts WHERE canonical_id = ?",
                (drop_id,),
            ).fetchone()
            if keep_row is None or drop_row is None:
                return None

            # Re-point identities. ``OR REPLACE`` because the keep contact
            # might already own an identity row for the same (channel, uid)
            # — preserve the keep side's mapping rather than failing.
            conn.execute(
                "UPDATE OR REPLACE contact_identities SET canonical_id = ? "
                "WHERE canonical_id = ?",
                (keep_id, drop_id),
            )
            # Roll counters forward; vip_flag is sticky (either side VIP → keep VIP).
            conn.execute(
                "UPDATE contacts SET "
                "  message_count = message_count + ?, "
                "  first_seen = MIN(first_seen, ?), "
                "  last_seen = MAX(last_seen, ?), "
                "  vip_flag = MAX(vip_flag, ?), "
                "  notes = TRIM(COALESCE(notes, '') || CASE WHEN ? != '' THEN char(10) || ? ELSE '' END) "
                "WHERE canonical_id = ?",
                (
                    drop_row["message_count"],
                    drop_row["first_seen"],
                    drop_row["last_seen"],
                    drop_row["vip_flag"],
                    drop_row["notes"] or "",
                    drop_row["notes"] or "",
                    keep_id,
                ),
            )
            conn.execute(
                "DELETE FROM contacts WHERE canonical_id = ?", (drop_id,)
            )
            logger.info("Merged contact %s → %s", drop_id, keep_id)
            return self._fetch(conn, keep_id)

    async def list_contacts(self, limit: int = 200) -> list[Contact]:
        return await asyncio.to_thread(self._list_contacts_sync, limit)

    def _list_contacts_sync(self, limit: int) -> list[Contact]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT canonical_id FROM contacts "
                "ORDER BY last_seen DESC LIMIT ?",
                (limit,),
            ).fetchall()
            out: list[Contact] = []
            for r in rows:
                c = self._fetch(conn, r["canonical_id"])
                if c is not None:
                    out.append(c)
            return out

    async def set_vip(self, canonical_id: str, flag: bool = True) -> None:
        await asyncio.to_thread(self._set_vip_sync, canonical_id, flag)

    def _set_vip_sync(self, canonical_id: str, flag: bool) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE contacts SET vip_flag = ?, tier = CASE "
                "  WHEN ? = 1 THEN 'vip' ELSE tier END WHERE canonical_id = ?",
                (1 if flag else 0, 1 if flag else 0, canonical_id),
            )

    # ------------------------------------------------------------------ helpers

    def _fetch(self, conn: sqlite3.Connection, canonical_id: str) -> Contact | None:
        row = conn.execute(
            "SELECT * FROM contacts WHERE canonical_id = ?",
            (canonical_id,),
        ).fetchone()
        if row is None:
            return None
        ids = [
            (r["channel"], r["channel_user_id"])
            for r in conn.execute(
                "SELECT channel, channel_user_id FROM contact_identities "
                "WHERE canonical_id = ?",
                (canonical_id,),
            ).fetchall()
        ]
        return Contact(
            canonical_id=row["canonical_id"],
            display_name=row["display_name"],
            tier=row["tier"],
            message_count=row["message_count"],
            first_seen=row["first_seen"],
            last_seen=row["last_seen"],
            vip_flag=bool(row["vip_flag"]),
            notes=row["notes"],
            identities=ids,
        )

    def _maybe_merge_by_identifier(
        self, conn: sqlite3.Connection, ident: Identifier
    ) -> str | None:
        """Return the canonical_id that owns this typed identifier, if any.

        Only cross-channel kinds (email/phone/handle) are looked up — a
        Telegram numeric ID matching a Discord numeric ID is coincidence,
        not identity, so ``native`` rows stay scoped to their own
        ``(channel, channel_user_id)`` lookup.
        """
        if ident.kind not in CROSS_CHANNEL_KINDS or not ident.value:
            return None
        row = conn.execute(
            "SELECT canonical_id FROM contact_identities "
            "WHERE identifier_kind = ? AND identifier_value = ? "
            "ORDER BY rowid LIMIT 1",
            (ident.kind, ident.value),
        ).fetchone()
        return row["canonical_id"] if row else None

    def _maybe_merge_by_body_idents(
        self, conn: sqlite3.Connection, idents: list[Identifier]
    ) -> str | None:
        """First body-extracted identifier that matches an existing contact.

        Stops at the first hit — if a single message mentions two known
        identifiers belonging to different contacts, we don't try to be
        clever; the manual merge UI is the right tool for that.
        """
        for ident in idents:
            cid = self._maybe_merge_by_identifier(conn, ident)
            if cid:
                return cid
        return None

    def _maybe_merge_by_name(
        self, conn: sqlite3.Connection, display_name: str
    ) -> str | None:
        """Best-effort cross-channel merge: same display_name → same person.

        Conservative on purpose. Empty / very short / generic names ("user",
        "bot") are skipped so we don't collapse strangers into one row.
        """
        name = display_name.strip()
        if len(name) < 3 or name.lower() in {"user", "bot", "admin", "guest"}:
            return None
        row = conn.execute(
            "SELECT canonical_id FROM contacts "
            "WHERE LOWER(TRIM(display_name)) = LOWER(?) LIMIT 1",
            (name,),
        ).fetchone()
        return row["canonical_id"] if row else None

    def _compute_tier(self, contact: Contact, message: Message) -> str:
        cfg = self._config
        if contact.vip_flag:
            return TIER_VIP

        # Explicit VIP overrides.
        candidates = {
            (message.user_id or "").lower(),
            (message.user_name or "").lower(),
        }
        for vip in cfg.vip_addresses:
            if vip.lower() in candidates:
                return TIER_VIP
        haystack = f"{message.user_name or ''} {message.content or ''}".lower()
        for kw in cfg.vip_keywords:
            if kw and kw.lower() in haystack:
                return TIER_VIP

        if contact.message_count <= cfg.stranger_max_messages:
            return TIER_STRANGER
        if contact.message_count >= cfg.colleague_min_messages:
            return TIER_COLLEAGUE
        return TIER_ACQUAINTANCE

    def _synthetic_contact(self, message: Message) -> Contact:
        """Used when the registry is disabled — looks like a stranger."""
        now = time.time()
        return Contact(
            canonical_id="c_synthetic",
            display_name=message.user_name or "",
            tier=self._config.default_tier,
            message_count=1,
            first_seen=now,
            last_seen=now,
            vip_flag=False,
            identities=[(message.channel, message.user_id or "")],
        )


# --- Prompt rendering --------------------------------------------------------

# Tone hints injected into the system prompt per tier. Kept short so they
# don't eat into the model's working context — the goal is to nudge style,
# not micromanage every reply.
_TIER_TONE = {
    TIER_STRANGER: "Tone: formal, polite, brief. Don't assume context. Confirm before committing to actions.",
    TIER_ACQUAINTANCE: "Tone: neutral and professional. Standard reply length.",
    TIER_COLLEAGUE: "Tone: direct, candid, can use shorthand. Skip pleasantries.",
    TIER_VIP: "Tone: polished, thorough, anticipatory. Match their precision. Triple-check facts before sending.",
}


def render_relationship_block(contact: Contact, last_seen_human: str = "") -> str:
    """Build the {relationship_context} block injected into SOUL.md.

    Keep this dense — the model reads it on every turn. Layout matches the
    daily-log block style so the prompt stays visually consistent.
    """
    if contact is None:
        return "Sender: unknown — treat as stranger. Tone: formal, polite, brief."

    name = contact.display_name or "(unknown name)"
    ids = ", ".join(f"{c}:{u}" for c, u in (contact.identities or [])[:4]) or "—"
    tone = _TIER_TONE.get(contact.tier, _TIER_TONE[TIER_ACQUAINTANCE])
    last = last_seen_human or "first contact"

    lines = [
        f"Sender: {name} [{contact.tier}]",
        f"Channels: {ids}",
        f"History: {contact.message_count} prior message(s); last seen {last}.",
    ]
    if contact.notes:
        lines.append(f"Notes: {contact.notes}")
    lines.append(tone)
    return "\n".join(lines)


def humanize_age(ts: float, now: float | None = None) -> str:
    if not ts:
        return "first contact"
    delta = (now or time.time()) - ts
    if delta < 60:
        return "just now"
    if delta < 3600:
        return f"{int(delta / 60)} min ago"
    if delta < 86400:
        return f"{int(delta / 3600)}h ago"
    return f"{int(delta / 86400)}d ago"


def filter_valid_tiers(tiers: Iterable[str]) -> list[str]:
    return [t for t in tiers if t in _VALID_TIERS]
