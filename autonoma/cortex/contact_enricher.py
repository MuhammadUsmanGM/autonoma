"""Enrich :class:`Contact` rows from external connectors.

Currently wires Google Contacts (People API) into ``ContactStore``: when an
inbound message arrives from someone the user has saved in Google
Contacts, we copy across the saved name + organisation and bump the
contact's tier from ``stranger`` to ``acquaintance``. The signal is "the
user bothered to save this person", which is weak — never enough to mark
someone VIP, but plenty to lift them out of the strangers bucket.

The enricher is a no-op when the Google Contacts connector isn't connected,
so wiring it unconditionally in main.py is safe.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from autonoma.cortex.contacts import (
    TIER_ACQUAINTANCE,
    TIER_STRANGER,
    Contact,
    ContactStore,
)
from autonoma.cortex.identity import (
    KIND_EMAIL,
    KIND_PHONE,
    Identifier,
)

if TYPE_CHECKING:
    from autonoma.connectors.google_contacts.connector import GoogleContactsConnector

logger = logging.getLogger(__name__)


class ContactEnricher:
    """Stitches a Google Contacts connector onto :class:`ContactStore`.

    A single instance is held by the agent loop; it caches per-canonical_id
    "we already tried to enrich this contact" markers so that a chatty
    sender doesn't get a People API call on every message.
    """

    # How long to remember "we already tried" for a given canonical_id, so
    # a long-running session doesn't refetch on every inbound message but
    # still picks up new contact saves over time.
    _CACHE_TTL_SECONDS = 24 * 3600

    def __init__(
        self,
        contact_store: ContactStore,
        connector: "GoogleContactsConnector | None" = None,
        *,
        enabled: bool = True,
    ) -> None:
        self._contacts = contact_store
        self._connector = connector
        self._enabled = enabled
        self._tried: dict[str, float] = {}

    def set_connector(self, connector: "GoogleContactsConnector | None") -> None:
        """Update the connector reference, e.g. when the user disconnects.

        Also clears the per-contact "tried" cache so a freshly-connected
        account immediately enriches recently-seen senders.
        """
        if connector is not self._connector:
            self._tried.clear()
        self._connector = connector

    def is_active(self) -> bool:
        if not self._enabled or self._connector is None:
            return False
        try:
            return self._connector.is_connected()
        except Exception:  # pragma: no cover — defensive
            return False

    async def enrich(self, contact: Contact) -> Contact:
        """Best-effort: return an enriched ``Contact`` (or the original).

        Failures are swallowed and logged at DEBUG; enrichment is a "nice
        to have" and must never break message processing.
        """
        if not self.is_active() or contact is None:
            return contact

        # Rate limit per contact — once per day is plenty.
        last = self._tried.get(contact.canonical_id, 0.0)
        if last and (time.time() - last) < self._CACHE_TTL_SECONDS:
            return contact

        idents = _candidate_identifiers(contact)
        if not idents:
            self._tried[contact.canonical_id] = time.time()
            return contact

        try:
            match = await self._lookup_first_match(idents)
        except Exception as exc:  # pragma: no cover — network only
            logger.debug("Contact enrichment lookup failed: %s", exc)
            self._tried[contact.canonical_id] = time.time()
            return contact

        # Always mark as tried — even on miss — so we don't hammer the API.
        self._tried[contact.canonical_id] = time.time()

        if match is None:
            return contact

        display_name = _pick_display_name(match)
        notes = _pick_notes(match)
        # Bump strangers to acquaintance; leave higher tiers alone (the
        # heuristic + manual VIPs already win).
        bump = TIER_ACQUAINTANCE if contact.tier == TIER_STRANGER else ""
        updated = await self._contacts.apply_enrichment(
            contact.canonical_id,
            display_name=display_name,
            notes=notes,
            bump_to_tier=bump,
        )
        return updated or contact

    async def _lookup_first_match(self, idents: list[Identifier]) -> dict | None:
        """Walk identifiers in priority order; first hit wins."""
        if self._connector is None:
            return None
        # Lazy import — keeps this module importable without the connector
        # package installed.
        from autonoma.connectors.google_contacts.tools import _resolve_identifier

        token = self._connector.access_token()
        for ident in idents:
            match = await _resolve_identifier(token, ident.value)
            if match is not None:
                return match
        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _candidate_identifiers(contact: Contact) -> list[Identifier]:
    """Pull cross-channel identifiers off a contact's identity rows."""
    out: list[Identifier] = []
    seen: set[tuple[str, str]] = set()
    for channel, channel_user_id in contact.identities or []:
        # Only the synthetic "extracted" rows carry typed identifier kinds;
        # native channel ids (Telegram numeric, Discord snowflake) are
        # useless to People API. We sniff the synthetic key shape
        # ``"<kind>:<value>"`` here without round-tripping the DB.
        if channel == "extracted" and ":" in channel_user_id:
            kind, value = channel_user_id.split(":", 1)
            if kind in (KIND_EMAIL, KIND_PHONE) and (kind, value) not in seen:
                seen.add((kind, value))
                out.append(Identifier(kind=kind, value=value))
        elif channel == "gmail" and "@" in channel_user_id:
            ident = Identifier(KIND_EMAIL, channel_user_id.lower())
            if (ident.kind, ident.value) not in seen:
                seen.add((ident.kind, ident.value))
                out.append(ident)
    return out


def _pick_display_name(person: dict) -> str:
    """Best display name from a People API person record."""
    for name in person.get("names") or []:
        for key in ("displayName", "unstructuredName"):
            if value := (name.get(key) or "").strip():
                return value
    return ""


def _pick_notes(person: dict) -> str:
    """Compose a one-line note (org/title + bio fragment) for the contact."""
    bits: list[str] = []
    for org in person.get("organizations") or []:
        title = (org.get("title") or "").strip()
        company = (org.get("name") or "").strip()
        if title and company:
            bits.append(f"{title} @ {company}")
        elif company:
            bits.append(company)
        elif title:
            bits.append(title)
        if bits:
            break
    bios = person.get("biographies") or []
    if bios:
        bio = (bios[0].get("value") or "").strip().splitlines()
        if bio:
            line = bio[0].strip()
            if len(line) > 120:
                line = line[:120] + "…"
            if line:
                bits.append(line)
    return " — ".join(bits)
