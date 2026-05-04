"""Tools backed by the Google Meet connector (Meet REST API v2)."""

from __future__ import annotations

import asyncio
import re
import uuid
from typing import TYPE_CHECKING, Any

from autonoma.connectors.oauth import http_json
from autonoma.executor.tools.base import BaseTool, ToolPermission

if TYPE_CHECKING:
    from autonoma.connectors.google_meet.connector import GoogleMeetConnector

API_BASE = "https://meet.googleapis.com/v2"
CALENDAR_EVENTS = "https://www.googleapis.com/calendar/v3/calendars/{cal}/events"

# Action-item heuristics. Compiled once; used by extract_action_items().
# Each pattern captures the verb-phrase / owner so we can phrase the
# follow-up reminder ("@alice will draft the spec").
_ACTION_ITEM_PATTERNS = [
    re.compile(r"\b(?:action item|TODO|TO DO|to-?do)\s*[:\-]\s*(?P<text>.+)", re.I),
    re.compile(r"@(?P<owner>[A-Za-z][\w.-]*)\s+(?:will|to)\s+(?P<text>.+)", re.I),
    re.compile(r"\b(?P<owner>[A-Z][a-z]+)\s+will\s+(?P<text>.+)", re.I),
]
# Cap length of any extracted action item, in characters.
_ACTION_ITEM_MAX = 220


def _perm() -> ToolPermission:
    return ToolPermission(
        level="cautious",
        network=True,
        external_api=True,
        secrets=True,
        description="Calls Google Meet REST API on behalf of a connected account.",
    )


def _write_perm() -> ToolPermission:
    return ToolPermission(
        level="dangerous",
        network=True,
        external_api=True,
        secrets=True,
        description="Creates Google Meet links via Calendar on behalf of a connected account.",
    )


def _to_thread(fn, *args, **kwargs):
    return asyncio.get_event_loop().run_in_executor(None, lambda: fn(*args, **kwargs))


class _BaseMeetTool(BaseTool):
    def __init__(self, connector: "GoogleMeetConnector") -> None:
        self._connector = connector


class MeetListConferencesTool(_BaseMeetTool):
    @property
    def name(self) -> str:
        return "meet_list_conferences"

    @property
    def description(self) -> str:
        return (
            "List the user's recent Meet conference records (past meetings with "
            "available transcripts/recordings)."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "page_size": {"type": "integer", "default": 10, "minimum": 1, "maximum": 50},
                "filter": {
                    "type": "string",
                    "description": (
                        "Meet API filter expression, e.g. "
                        "\"start_time>=\\\"2026-04-01T00:00:00Z\\\"\""
                    ),
                },
            },
        }

    @property
    def permissions(self) -> ToolPermission:
        return _perm()

    async def execute(self, params: dict[str, Any]) -> str:
        token = self._connector.access_token()
        query: dict[str, Any] = {
            "pageSize": int(params.get("page_size", 10)),
        }
        if f := params.get("filter"):
            query["filter"] = f
        resp = await _to_thread(
            http_json, f"{API_BASE}/conferenceRecords", bearer=token, params=query
        )
        records = resp.get("conferenceRecords", []) or []
        if not records:
            return "(no recent Meet conferences)"
        lines = [f"{len(records)} conference record(s):"]
        for rec in records:
            name = rec.get("name", "?")  # e.g. "conferenceRecords/abc-123"
            start = rec.get("startTime", "?")
            end = rec.get("endTime", "(in progress)")
            space = (rec.get("space", "") or "").rsplit("/", 1)[-1]
            lines.append(f"- {name}  start={start}  end={end}  space={space}")
        return "\n".join(lines)


class MeetGetTranscriptTool(_BaseMeetTool):
    @property
    def name(self) -> str:
        return "meet_get_transcript"

    @property
    def description(self) -> str:
        return (
            "Fetch the transcript of a past Meet conference. Returns speaker-labeled "
            "lines with timestamps. If extract_action_items is enabled, action items "
            "discovered in the transcript are also written to the conversation state "
            "machine as follow-up reminders."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "conference_record": {
                    "type": "string",
                    "description": "Resource name, e.g. 'conferenceRecords/abc-123'",
                },
                "max_entries": {
                    "type": "integer",
                    "default": 500,
                    "minimum": 10,
                    "maximum": 2000,
                },
            },
            "required": ["conference_record"],
        }

    @property
    def permissions(self) -> ToolPermission:
        return _perm()

    async def execute(self, params: dict[str, Any]) -> str:
        rec = params["conference_record"].strip()
        if not re.match(r"^conferenceRecords/[A-Za-z0-9_-]+$", rec):
            raise ValueError(
                "conference_record must look like 'conferenceRecords/<id>'"
            )
        max_entries = max(10, min(int(params.get("max_entries", 500)), 2000))
        token = self._connector.access_token()
        # Step 1: list transcripts attached to this conference.
        ts_list = await _to_thread(
            http_json, f"{API_BASE}/{rec}/transcripts", bearer=token
        )
        transcripts = ts_list.get("transcripts", []) or []
        if not transcripts:
            return f"(no transcripts available for {rec})"
        # Step 2: pull all entries across transcripts, paginated.
        all_lines: list[str] = []
        action_items: list[tuple[str | None, str]] = []
        for t in transcripts:
            entries = await _fetch_all_entries(
                token, t.get("name", ""), cap=max_entries - len(all_lines)
            )
            for e in entries:
                speaker = (
                    (e.get("participant", "") or "").rsplit("/", 1)[-1] or "speaker"
                )
                start = e.get("startTime", "")
                text = (e.get("text", "") or "").strip()
                if not text:
                    continue
                all_lines.append(f"[{start}] {speaker}: {text}")
                action_items.extend(_extract_action_items(text))
                if len(all_lines) >= max_entries:
                    break
            if len(all_lines) >= max_entries:
                break

        out = [f"Transcript {rec} — {len(all_lines)} line(s):"]
        out.extend(all_lines)

        # Side-effect: emit action items to state machine if wired.
        if (
            self._connector.extract_action_items_enabled()
            and action_items
            and self._connector.state_store() is not None
        ):
            try:
                emitted = await _emit_action_items(
                    self._connector, rec, action_items
                )
                if emitted:
                    out.append("")
                    out.append(
                        f"({emitted} action item(s) extracted into follow-up state)"
                    )
            except Exception:
                # Action-item extraction is a side benefit — never let it
                # take down the transcript fetch.
                pass

        return "\n".join(out)


class MeetCreateLinkTool(_BaseMeetTool):
    @property
    def name(self) -> str:
        return "meet_create_link"

    @property
    def description(self) -> str:
        return (
            "Create a Google Meet link by scheduling a Calendar event with "
            "Meet conferencing attached. Requires the Google Calendar connector "
            "to also be connected."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "title": {"type": "string", "minLength": 1},
                "start": {"type": "string", "description": "RFC3339 start datetime"},
                "end": {"type": "string", "description": "RFC3339 end datetime"},
                "attendees": {
                    "type": "array",
                    "items": {"type": "string"},
                    "default": [],
                },
                "description": {"type": "string", "default": ""},
                "calendar_id": {"type": "string", "default": "primary"},
            },
            "required": ["title", "start", "end"],
        }

    @property
    def permissions(self) -> ToolPermission:
        return _write_perm()

    async def execute(self, params: dict[str, Any]) -> str:
        cal_conn = self._connector.calendar_connector()
        if cal_conn is None:
            raise RuntimeError(
                "Google Meet link creation requires the Google Calendar connector "
                "to be connected (Meet has no standalone create-event endpoint). "
                "Connect Calendar from the dashboard first."
            )
        # Calendar must actually be connected, not merely registered.
        try:
            cal_status = cal_conn.status().state
        except Exception:
            cal_status = "error"
        if cal_status != "connected":
            raise RuntimeError(
                f"Google Calendar connector is registered but not connected "
                f"(state={cal_status}). Connect it from the dashboard first."
            )

        token = cal_conn.access_token()
        cal = params.get("calendar_id") or "primary"
        body: dict[str, Any] = {
            "summary": params["title"],
            "description": params.get("description", ""),
            "start": {"dateTime": params["start"]},
            "end": {"dateTime": params["end"]},
            "conferenceData": {
                "createRequest": {
                    "requestId": str(uuid.uuid4()),
                    "conferenceSolutionKey": {"type": "hangoutsMeet"},
                }
            },
        }
        if attendees := params.get("attendees"):
            body["attendees"] = [{"email": a} for a in attendees]
        created = await _to_thread(
            http_json,
            CALENDAR_EVENTS.format(cal=cal),
            method="POST",
            bearer=token,
            params={"conferenceDataVersion": 1},
            body=body,
        )
        meet_url = ""
        for ep in (created.get("conferenceData", {}) or {}).get("entryPoints", []) or []:
            if ep.get("entryPointType") == "video":
                meet_url = ep.get("uri", "")
                break
        link = meet_url or created.get("hangoutLink", "")
        return (
            f"Created Meet event '{created.get('summary')}' "
            f"({created.get('id','?')}). Meet: {link or '(pending)'}"
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _fetch_all_entries(
    token: str, transcript_name: str, *, cap: int
) -> list[dict[str, Any]]:
    """Page through ``conferenceRecords/.../transcripts/.../entries``."""
    if not transcript_name or cap <= 0:
        return []
    out: list[dict[str, Any]] = []
    page_token = None
    while len(out) < cap:
        params: dict[str, Any] = {"pageSize": min(200, cap - len(out))}
        if page_token:
            params["pageToken"] = page_token
        resp = await _to_thread(
            http_json,
            f"{API_BASE}/{transcript_name}/entries",
            bearer=token,
            params=params,
        )
        entries = resp.get("transcriptEntries", []) or []
        out.extend(entries)
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return out[:cap]


def _extract_action_items(text: str) -> list[tuple[str | None, str]]:
    """Return ``(owner_or_None, action_text)`` tuples found in ``text``."""
    matches: list[tuple[str | None, str]] = []
    for pat in _ACTION_ITEM_PATTERNS:
        for m in pat.finditer(text):
            owner = None
            if "owner" in m.groupdict():
                owner = m.group("owner")
            action_text = (m.group("text") or "").strip().rstrip(".!?,;:")
            if not action_text:
                continue
            if len(action_text) > _ACTION_ITEM_MAX:
                action_text = action_text[:_ACTION_ITEM_MAX] + "…"
            matches.append((owner, action_text))
    return matches


async def _emit_action_items(
    connector: "GoogleMeetConnector",
    conference_record: str,
    items: list[tuple[str | None, str]],
) -> int:
    """Push extracted action items into the conversation state machine.

    Returns the number of items that were actually written. Failures are
    swallowed by the caller — this is a side benefit, never a hard
    requirement.
    """
    state_store = connector.state_store()
    contact_store = connector.contact_store()
    if state_store is None:
        return 0

    # Action items are anchored to either:
    #   * the named owner (if we can resolve them via contact_store), or
    #   * a synthetic "meeting/<id>" canonical_id when no owner is named.
    # In both cases we record an outbound state with `followup_at=now+2d`
    # so the followup_scheduler picks them up.
    import time

    DEFAULT_FOLLOWUP_HOURS = 48
    followup_at = time.time() + DEFAULT_FOLLOWUP_HOURS * 3600

    emitted = 0
    seen: set[str] = set()
    for owner, action_text in items:
        canonical_id = None
        if owner and contact_store is not None:
            try:
                canonical_id = await _resolve_owner(contact_store, owner)
            except Exception:
                canonical_id = None
        if canonical_id is None:
            canonical_id = f"meeting:{conference_record}"
        key = f"{canonical_id}|{action_text.lower()}"
        if key in seen:
            continue
        seen.add(key)
        reason = f"meeting action item: {action_text}"
        if owner:
            reason = f"{owner}: {reason}"
        try:
            await state_store.record_outbound(
                canonical_id,
                followup_at=followup_at,
                followup_reason=reason[:500],
            )
            emitted += 1
        except Exception:
            continue
    return emitted


async def _resolve_owner(contact_store, owner: str) -> str | None:
    """Best-effort: map a free-form owner name to a canonical_id."""
    # ContactStore APIs vary, so try the most likely lookup methods in order
    # and return as soon as one succeeds.
    for method_name in ("find_by_name", "lookup", "get_by_name"):
        method = getattr(contact_store, method_name, None)
        if not method:
            continue
        try:
            result = method(owner)
            if asyncio.iscoroutine(result):
                result = await result
        except Exception:
            continue
        if not result:
            continue
        # Result might be a Contact dataclass or a dict
        cid = (
            getattr(result, "canonical_id", None)
            or (result.get("canonical_id") if isinstance(result, dict) else None)
        )
        if cid:
            return cid
    return None
