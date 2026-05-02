"""Cross-channel identity resolution.

Channel adapters all populate ``Message.user_id`` differently — Telegram
hands us a numeric ID, Gmail hands us an email, WhatsApp hands us a phone
number. Treated naively, the same human looks like three strangers.

This module turns raw user_ids (and identifiers extracted from message
bodies) into typed :class:`Identifier` records so the contact store can
auto-link across channels when an exact match shows up.

Kinds we track:

* ``email``  — normalized to lowercase, whitespace-stripped.
* ``phone``  — digits only, with a leading ``+`` if E.164-shaped.
* ``handle`` — short name with leading ``@`` stripped, lowercased.
* ``native`` — anything else (Telegram numeric ID, Discord snowflake, …).
                Stays scoped to its own channel; never matched cross-channel.

Extraction is deliberately conservative — we'd rather miss a match than
fuse two unrelated people, since the ``[LINK_IDENTITY: ...]`` tag and the
manual dashboard merge always remain as escape hatches.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

# Identifier kind constants — exported so callers don't pass typos.
KIND_EMAIL = "email"
KIND_PHONE = "phone"
KIND_HANDLE = "handle"
KIND_NATIVE = "native"

_VALID_KINDS = {KIND_EMAIL, KIND_PHONE, KIND_HANDLE, KIND_NATIVE}

# Cross-channel kinds — only these are eligible for auto-merge across
# different channels, since e.g. a Telegram numeric "12345" and a Discord
# numeric "12345" are unrelated.
CROSS_CHANNEL_KINDS = frozenset({KIND_EMAIL, KIND_PHONE, KIND_HANDLE})

# Pragmatic — accepts anything with one ``@`` and a TLD-shaped suffix.
# Avoids RFC 5321 territory; the cost of an over-strict regex is missed
# matches, the cost of a too-loose one is false merges.
_EMAIL_RE = re.compile(
    r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"
)

# E.164-ish: optional ``+``, 8–15 digits, no spaces. Tighter than typical
# phone regexes on purpose — random sequences of digits in a message body
# (order numbers, IDs) shouldn't merge contacts.
_PHONE_RE = re.compile(r"(?<![\w])\+?\d{8,15}(?![\w])")

# WhatsApp's own user_ids look like ``9234XXXXXXXX@c.us`` — strip the
# suffix so the underlying phone matches against an extracted ``+9234…``.
_WHATSAPP_SUFFIX_RE = re.compile(r"@(?:c|s)\.(?:us|whatsapp\.net)$", re.IGNORECASE)


@dataclass(frozen=True)
class Identifier:
    kind: str
    value: str

    def is_cross_channel(self) -> bool:
        return self.kind in CROSS_CHANNEL_KINDS


def normalize_email(raw: str) -> str | None:
    s = raw.strip().lower()
    if "@" not in s or len(s) > 254:
        return None
    return s


def normalize_phone(raw: str) -> str | None:
    """Reduce a phone-shaped string to its canonical digits-only form.

    Returns ``None`` if there aren't enough digits to be a real number.
    Length floor is 8 — keeps short codes (911, 311, hotel extensions)
    out of the cross-channel match pool.

    The ``+`` prefix is *dropped* on purpose: WhatsApp emits phone numbers
    without it (``15555550100@c.us``) while users typing in chat use it
    (``+1 555 555 0100``). Storing digits-only means both forms collide
    on the same canonical value.
    """
    digits = re.sub(r"[^\d]", "", raw or "")
    if len(digits) < 8 or len(digits) > 15:
        return None
    return digits


def normalize_handle(raw: str) -> str | None:
    s = (raw or "").strip().lstrip("@").lower()
    # 2-char floor avoids merging on accidental single letters.
    if len(s) < 2 or " " in s:
        return None
    return s


def classify_user_id(channel: str, user_id: str) -> Identifier:
    """Best guess at the typed identity of a raw ``user_id``.

    The channel name is a strong hint (Gmail → email, WhatsApp → phone)
    so we lean on it before falling back to shape detection.
    """
    raw = (user_id or "").strip()
    if not raw:
        return Identifier(KIND_NATIVE, "")

    ch = (channel or "").lower()

    if ch == "gmail":
        norm = normalize_email(raw)
        if norm:
            return Identifier(KIND_EMAIL, norm)

    if ch == "whatsapp":
        # Strip the ``@c.us`` suffix WhatsApp Web emits, then normalize.
        stripped = _WHATSAPP_SUFFIX_RE.sub("", raw)
        norm = normalize_phone(stripped)
        if norm:
            return Identifier(KIND_PHONE, norm)

    # Shape-based fallbacks — covers REST channel and any future adapters
    # whose identifier kind isn't predictable from the channel name.
    if "@" in raw and _EMAIL_RE.fullmatch(raw):
        norm = normalize_email(raw)
        if norm:
            return Identifier(KIND_EMAIL, norm)

    norm = normalize_phone(raw)
    if norm and _PHONE_RE.fullmatch(raw.strip()):
        return Identifier(KIND_PHONE, norm)

    # Telegram/Discord numeric IDs and CLI/REST opaque strings — keep them
    # scoped to their channel, never matched cross-channel.
    return Identifier(KIND_NATIVE, raw)


def extract_identifiers_from_text(text: str) -> list[Identifier]:
    """Pull emails / phones out of a message body.

    Deduped + normalized. Runs on every inbound message — keep cheap.
    """
    if not text:
        return []
    seen: set[tuple[str, str]] = set()
    out: list[Identifier] = []

    for match in _EMAIL_RE.findall(text):
        norm = normalize_email(match)
        if norm and (KIND_EMAIL, norm) not in seen:
            seen.add((KIND_EMAIL, norm))
            out.append(Identifier(KIND_EMAIL, norm))

    for match in _PHONE_RE.findall(text):
        norm = normalize_phone(match)
        if norm and (KIND_PHONE, norm) not in seen:
            seen.add((KIND_PHONE, norm))
            out.append(Identifier(KIND_PHONE, norm))

    return out


# ---------------------------------------------------------------------------
# [LINK_IDENTITY: kind=value] tag — emitted by the LLM when it concludes
# from conversation that two channels belong to the same person.
# ---------------------------------------------------------------------------

# Accept either ``kind=value`` or ``kind:value``; tolerate surrounding
# whitespace; case-insensitive on the kind name. Multiple tags allowed.
_LINK_TAG_RE = re.compile(
    r"\[LINK_IDENTITY:\s*([a-zA-Z]+)\s*[:=]\s*([^\]\s][^\]]*?)\s*\]",
    re.IGNORECASE,
)


def parse_link_identity_tags(text: str) -> tuple[list[Identifier], str]:
    """Strip ``[LINK_IDENTITY: …]`` tags and return the identifiers + cleaned text.

    Unknown / unparseable tags are dropped silently so a malformed model
    output doesn't raise into the agent loop. The tag is always removed
    from the user-visible reply, even when it can't be parsed — leaking
    bracket-syntax to a human is worse than missing a link.
    """
    if not text or "[LINK_IDENTITY" not in text.upper():
        return [], text

    found: list[Identifier] = []
    seen: set[tuple[str, str]] = set()

    def _replace(m: re.Match) -> str:
        kind = m.group(1).strip().lower()
        value = m.group(2).strip()
        ident = _coerce(kind, value)
        if ident is not None and (ident.kind, ident.value) not in seen:
            seen.add((ident.kind, ident.value))
            found.append(ident)
        return ""

    cleaned = _LINK_TAG_RE.sub(_replace, text).strip()
    return found, cleaned


def _coerce(kind: str, value: str) -> Identifier | None:
    if kind == KIND_EMAIL:
        norm = normalize_email(value)
        return Identifier(KIND_EMAIL, norm) if norm else None
    if kind == KIND_PHONE:
        norm = normalize_phone(value)
        return Identifier(KIND_PHONE, norm) if norm else None
    if kind == KIND_HANDLE:
        norm = normalize_handle(value)
        return Identifier(KIND_HANDLE, norm) if norm else None
    return None


def filter_valid_kinds(kinds: Iterable[str]) -> list[str]:
    return [k for k in kinds if k in _VALID_KINDS]
