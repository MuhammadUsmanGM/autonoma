"""Tools backed by the Google Calendar connector."""

from __future__ import annotations

import asyncio
import datetime as dt
from typing import TYPE_CHECKING, Any

from autonoma.connectors.oauth import http_json
from autonoma.executor.tools.base import BaseTool, ToolPermission

if TYPE_CHECKING:  # avoid circular import at runtime
    from autonoma.connectors.google_calendar.connector import GoogleCalendarConnector

EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/{cal}/events"
FREEBUSY_URL = "https://www.googleapis.com/calendar/v3/freeBusy"


def _perm() -> ToolPermission:
    return ToolPermission(
        level="cautious",
        network=True,
        external_api=True,
        secrets=True,
        description="Calls Google Calendar API on behalf of a connected account.",
    )


def _to_thread(fn, *args, **kwargs):
    return asyncio.get_event_loop().run_in_executor(None, lambda: fn(*args, **kwargs))


class _BaseCalendarTool(BaseTool):
    def __init__(self, connector: "GoogleCalendarConnector") -> None:
        self._connector = connector

    @property
    def permissions(self) -> ToolPermission:
        return _perm()


class CalendarListEventsTool(_BaseCalendarTool):
    @property
    def name(self) -> str:
        return "calendar_list_events"

    @property
    def description(self) -> str:
        return (
            "List upcoming events from the user's Google Calendar within a time window. "
            "Defaults to the next 7 days from the primary calendar."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "calendar_id": {"type": "string", "default": "primary"},
                "time_min": {"type": "string", "description": "RFC3339 start (default: now)"},
                "time_max": {"type": "string", "description": "RFC3339 end (default: now+7d)"},
                "max_results": {"type": "integer", "default": 25, "minimum": 1, "maximum": 250},
            },
        }

    async def execute(self, params: dict[str, Any]) -> str:
        cal = params.get("calendar_id") or "primary"
        now = dt.datetime.now(dt.timezone.utc)
        time_min = params.get("time_min") or now.isoformat()
        time_max = (
            params.get("time_max")
            or (now + dt.timedelta(days=7)).isoformat()
        )
        token = self._connector.access_token()
        resp = await _to_thread(
            http_json,
            EVENTS_URL.format(cal=cal),
            bearer=token,
            params={
                "timeMin": time_min,
                "timeMax": time_max,
                "maxResults": int(params.get("max_results", 25)),
                "singleEvents": "true",
                "orderBy": "startTime",
            },
        )
        items = resp.get("items", [])
        if not items:
            return f"No events between {time_min} and {time_max}."
        lines = [f"{len(items)} event(s):"]
        for ev in items:
            start = ev.get("start", {}).get("dateTime") or ev.get("start", {}).get("date", "?")
            summary = ev.get("summary", "(untitled)")
            lines.append(f"- {start} — {summary}")
        return "\n".join(lines)


class CalendarCreateEventTool(_BaseCalendarTool):
    @property
    def name(self) -> str:
        return "calendar_create_event"

    @property
    def description(self) -> str:
        return "Create a new event on the user's Google Calendar."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "calendar_id": {"type": "string", "default": "primary"},
                "summary": {"type": "string"},
                "description": {"type": "string"},
                "start": {"type": "string", "description": "RFC3339 start datetime"},
                "end": {"type": "string", "description": "RFC3339 end datetime"},
                "attendees": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Attendee email addresses.",
                },
                "location": {"type": "string"},
            },
            "required": ["summary", "start", "end"],
        }

    async def execute(self, params: dict[str, Any]) -> str:
        cal = params.get("calendar_id") or "primary"
        body: dict[str, Any] = {
            "summary": params["summary"],
            "start": {"dateTime": params["start"]},
            "end": {"dateTime": params["end"]},
        }
        if desc := params.get("description"):
            body["description"] = desc
        if loc := params.get("location"):
            body["location"] = loc
        if attendees := params.get("attendees"):
            body["attendees"] = [{"email": a} for a in attendees]
        token = self._connector.access_token()
        created = await _to_thread(
            http_json,
            EVENTS_URL.format(cal=cal),
            method="POST",
            bearer=token,
            body=body,
        )
        link = created.get("htmlLink", "")
        return f"Created event '{created.get('summary')}' ({created.get('id','?')}). {link}".strip()


class CalendarFindFreeSlotTool(_BaseCalendarTool):
    @property
    def name(self) -> str:
        return "calendar_find_free_slot"

    @property
    def description(self) -> str:
        return (
            "Find the first free slot of the requested duration within a time window, "
            "across one or more calendars."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "calendar_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "default": ["primary"],
                },
                "time_min": {"type": "string", "description": "RFC3339 start"},
                "time_max": {"type": "string", "description": "RFC3339 end"},
                "duration_minutes": {"type": "integer", "default": 30, "minimum": 5},
            },
            "required": ["time_min", "time_max"],
        }

    async def execute(self, params: dict[str, Any]) -> str:
        cals = params.get("calendar_ids") or ["primary"]
        duration = dt.timedelta(minutes=int(params.get("duration_minutes", 30)))
        token = self._connector.access_token()
        body = {
            "timeMin": params["time_min"],
            "timeMax": params["time_max"],
            "items": [{"id": c} for c in cals],
        }
        resp = await _to_thread(http_json, FREEBUSY_URL, method="POST", bearer=token, body=body)
        # Merge busy intervals across calendars.
        busy: list[tuple[dt.datetime, dt.datetime]] = []
        for c in cals:
            for b in resp.get("calendars", {}).get(c, {}).get("busy", []):
                busy.append((_parse(b["start"]), _parse(b["end"])))
        busy.sort()
        merged: list[tuple[dt.datetime, dt.datetime]] = []
        for s, e in busy:
            if merged and s <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], e))
            else:
                merged.append((s, e))
        cursor = _parse(params["time_min"])
        end_window = _parse(params["time_max"])
        for s, e in merged:
            if s - cursor >= duration:
                slot_end = cursor + duration
                return f"Free: {cursor.isoformat()} → {slot_end.isoformat()}"
            cursor = max(cursor, e)
        if end_window - cursor >= duration:
            return f"Free: {cursor.isoformat()} → {(cursor + duration).isoformat()}"
        return "No free slot of the requested duration in the window."


def _parse(value: str) -> dt.datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return dt.datetime.fromisoformat(value)
