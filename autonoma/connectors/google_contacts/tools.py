"""Tools backed by the Google Contacts connector (People API v1)."""

from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING, Any

from autonoma.connectors.oauth import http_json
from autonoma.executor.tools.base import BaseTool, ToolPermission

if TYPE_CHECKING:
    from autonoma.connectors.google_contacts.connector import GoogleContactsConnector

API_BASE = "https://people.googleapis.com/v1"
PERSON_FIELDS = (
    "names,emailAddresses,phoneNumbers,organizations,photos,biographies,memberships"
)


def _perm() -> ToolPermission:
    return ToolPermission(
        level="cautious",
        network=True,
        external_api=True,
        secrets=True,
        description="Calls Google People API on behalf of a connected account.",
    )


def _to_thread(fn, *args, **kwargs):
    return asyncio.get_event_loop().run_in_executor(None, lambda: fn(*args, **kwargs))


def _format_person(p: dict[str, Any]) -> str:
    name = ""
    names = p.get("names") or []
    if names:
        name = names[0].get("displayName", "") or names[0].get("unstructuredName", "")
    emails = ", ".join(e.get("value", "") for e in (p.get("emailAddresses") or []))
    phones = ", ".join(ph.get("value", "") for ph in (p.get("phoneNumbers") or []))
    org_lines = []
    for o in p.get("organizations") or []:
        bits = [o.get("name", ""), o.get("title", "")]
        s = " — ".join(b for b in bits if b)
        if s:
            org_lines.append(s)
    bio = ""
    bios = p.get("biographies") or []
    if bios:
        bio = (bios[0].get("value", "") or "").strip()
        if len(bio) > 200:
            bio = bio[:200] + "…"
    rn = p.get("resourceName", "")
    parts = [
        f"{name or '(no name)'}  [{rn}]",
        f"  email: {emails or '(none)'}",
        f"  phone: {phones or '(none)'}",
    ]
    if org_lines:
        parts.append(f"  org:   {'; '.join(org_lines)}")
    if bio:
        parts.append(f"  bio:   {bio}")
    return "\n".join(parts)


class _BaseContactsTool(BaseTool):
    def __init__(self, connector: "GoogleContactsConnector") -> None:
        self._connector = connector


class ContactsSearchTool(_BaseContactsTool):
    @property
    def name(self) -> str:
        return "contacts_search"

    @property
    def description(self) -> str:
        return (
            "Search the user's Google Contacts (and optionally 'other contacts' — "
            "people they've emailed but not saved) by name, email, or phone."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "minLength": 1},
                "include_other_contacts": {
                    "type": "boolean",
                    "default": True,
                    "description": "Also search 'otherContacts' (auto-saved from emails).",
                },
                "limit": {"type": "integer", "default": 10, "minimum": 1, "maximum": 30},
            },
            "required": ["query"],
        }

    @property
    def permissions(self) -> ToolPermission:
        return _perm()

    async def execute(self, params: dict[str, Any]) -> str:
        query = params["query"].strip()
        if not query:
            raise ValueError("query must not be empty")
        limit = max(1, min(int(params.get("limit", 10)), 30))
        token = self._connector.access_token()

        results = await _to_thread(
            http_json,
            f"{API_BASE}/people:searchContacts",
            bearer=token,
            params={
                "query": query,
                "readMask": PERSON_FIELDS,
                "pageSize": limit,
            },
        )
        people = [r.get("person") for r in (results.get("results") or []) if r.get("person")]

        if params.get("include_other_contacts", True):
            other = await _to_thread(
                http_json,
                f"{API_BASE}/otherContacts:search",
                bearer=token,
                params={
                    "query": query,
                    "readMask": "names,emailAddresses,phoneNumbers",
                    "pageSize": limit,
                },
            )
            for r in other.get("results") or []:
                if r.get("person"):
                    people.append(r["person"])

        if not people:
            return f"No contacts match: {query}"

        out = [f"{len(people)} contact match(es) for {query!r}:"]
        for p in people[:limit]:
            out.append("- " + _format_person(p).replace("\n", "\n  "))
        return "\n".join(out)


class ContactsGetTool(_BaseContactsTool):
    @property
    def name(self) -> str:
        return "contacts_get"

    @property
    def description(self) -> str:
        return "Fetch a full Google contact record by resourceName (e.g. 'people/c12345')."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "resource_name": {
                    "type": "string",
                    "pattern": "^(people|otherContacts)/[A-Za-z0-9_-]+$",
                    "description": "e.g. 'people/c1234567890'",
                },
            },
            "required": ["resource_name"],
        }

    @property
    def permissions(self) -> ToolPermission:
        return _perm()

    async def execute(self, params: dict[str, Any]) -> str:
        rn = params["resource_name"].strip()
        if not re.match(r"^(people|otherContacts)/[A-Za-z0-9_-]+$", rn):
            raise ValueError("Invalid resource_name; expected 'people/...' or 'otherContacts/...'")
        token = self._connector.access_token()
        person = await _to_thread(
            http_json,
            f"{API_BASE}/{rn}",
            bearer=token,
            params={"personFields": PERSON_FIELDS},
        )
        return _format_person(person)


class ContactsResolveTool(_BaseContactsTool):
    """Look up a contact by email or phone — used for inline enrichment."""

    @property
    def name(self) -> str:
        return "contacts_resolve"

    @property
    def description(self) -> str:
        return (
            "Resolve an email address or phone number to a Google contact, if any. "
            "Returns the matching contact's name, organisation, and resourceName, "
            "or '(no match)'."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "identifier": {
                    "type": "string",
                    "description": "Email address or phone number to look up.",
                    "minLength": 3,
                },
            },
            "required": ["identifier"],
        }

    @property
    def permissions(self) -> ToolPermission:
        return _perm()

    async def execute(self, params: dict[str, Any]) -> str:
        ident = params["identifier"].strip()
        if not ident:
            raise ValueError("identifier must not be empty")
        token = self._connector.access_token()
        match = await _resolve_identifier(token, ident)
        if match is None:
            return f"(no match) {ident}"
        return _format_person(match)


# ---------------------------------------------------------------------------
# Internal helper — also used by ContactEnricher (cortex/contact_enricher.py).
# ---------------------------------------------------------------------------


async def _resolve_identifier(token: str, identifier: str) -> dict[str, Any] | None:
    """Search saved + other contacts for a given email / phone, returning the
    first matching person record (or None).

    Searches both endpoints concurrently — Google's People API has separate
    search APIs for saved vs. other contacts and the results don't overlap.
    """

    async def _search(url: str, read_mask: str) -> list[dict[str, Any]]:
        try:
            resp = await _to_thread(
                http_json,
                url,
                bearer=token,
                params={"query": identifier, "readMask": read_mask, "pageSize": 5},
            )
        except Exception:
            return []
        return [r.get("person") for r in (resp.get("results") or []) if r.get("person")]

    saved, other = await asyncio.gather(
        _search(f"{API_BASE}/people:searchContacts", PERSON_FIELDS),
        _search(
            f"{API_BASE}/otherContacts:search",
            "names,emailAddresses,phoneNumbers",
        ),
    )
    candidates = list(saved) + list(other)
    if not candidates:
        return None

    # Exact match wins over substring; saved contacts win over otherContacts
    # (already ordered above). Compare normalized email/phone.
    norm_target = _normalize_identifier(identifier)
    for p in candidates:
        for e in p.get("emailAddresses") or []:
            if _normalize_identifier(e.get("value", "")) == norm_target:
                return p
        for ph in p.get("phoneNumbers") or []:
            if _normalize_identifier(ph.get("value", "")) == norm_target:
                return p
    # No exact match, but People API thought it was relevant — return the
    # top hit anyway. The caller (enricher) decides whether to trust it.
    return candidates[0]


def _normalize_identifier(value: str) -> str:
    v = value.strip().lower()
    if "@" in v:
        return v  # email
    # phone: strip everything except digits and a leading '+'
    digits = re.sub(r"[^\d+]", "", v)
    return digits
