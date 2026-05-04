"""Google Meet connector tool tests — mock http_json, no network."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from autonoma.connectors.google_meet import tools as gm_tools


def _run(coro):
    return asyncio.run(coro)


class _FakeMeetConnector:
    def __init__(
        self,
        *,
        token: str = "tok",
        extract_action_items: bool = False,
        state_store=None,
        contact_store=None,
        calendar=None,
    ) -> None:
        self._token = token
        self._extract = extract_action_items
        self._state = state_store
        self._contacts = contact_store
        self._cal = calendar

    def access_token(self) -> str:
        return self._token

    def extract_action_items_enabled(self) -> bool:
        return self._extract

    def state_store(self):
        return self._state

    def contact_store(self):
        return self._contacts

    def calendar_connector(self):
        return self._cal


class _FakeStateStore:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def record_outbound(self, canonical_id, *, followup_at, followup_reason):
        self.calls.append({
            "canonical_id": canonical_id,
            "followup_at": followup_at,
            "followup_reason": followup_reason,
        })


class ActionItemExtractionTest(unittest.TestCase):
    def test_matches_explicit_action_item(self) -> None:
        items = gm_tools._extract_action_items(
            "Action item: write the migration script"
        )
        self.assertTrue(any("migration script" in t for _, t in items))

    def test_matches_owner_will(self) -> None:
        items = gm_tools._extract_action_items("@bob will draft the spec")
        self.assertTrue(any(o == "bob" for o, _ in items))

    def test_capitalized_name_will(self) -> None:
        items = gm_tools._extract_action_items("Carol will follow up with legal")
        self.assertTrue(any(o == "Carol" for o, _ in items))

    def test_skips_empty_text(self) -> None:
        self.assertEqual(gm_tools._extract_action_items(""), [])

    def test_truncates_long_text(self) -> None:
        long = "Action item: " + ("x" * 500)
        items = gm_tools._extract_action_items(long)
        self.assertTrue(items)
        self.assertLessEqual(len(items[0][1]), gm_tools._ACTION_ITEM_MAX + 1)


class EmitActionItemsTest(unittest.TestCase):
    def test_dedupes_and_records_outbound(self) -> None:
        store = _FakeStateStore()
        connector = _FakeMeetConnector(
            extract_action_items=True, state_store=store, contact_store=None,
        )
        items = [
            (None, "draft the spec"),
            (None, "draft the spec"),  # dup
            ("bob", "review the PR"),
        ]
        emitted = _run(gm_tools._emit_action_items(
            connector, "conferenceRecords/abc-123", items,
        ))
        # Two unique items.
        self.assertEqual(emitted, 2)
        self.assertEqual(len(store.calls), 2)
        for call in store.calls:
            self.assertIn(call["canonical_id"], (
                "meeting:conferenceRecords/abc-123",
            ))

    def test_no_state_store_returns_zero(self) -> None:
        connector = _FakeMeetConnector(extract_action_items=True, state_store=None)
        emitted = _run(gm_tools._emit_action_items(
            connector, "conferenceRecords/x", [(None, "x")],
        ))
        self.assertEqual(emitted, 0)


class ListConferencesTest(unittest.TestCase):
    def test_formats_records(self) -> None:
        def fake(url, **kw):
            return {"conferenceRecords": [
                {"name": "conferenceRecords/abc",
                 "startTime": "2026-05-01T10:00:00Z",
                 "endTime":   "2026-05-01T10:30:00Z",
                 "space": "spaces/space-1"},
            ]}

        tool = gm_tools.MeetListConferencesTool(_FakeMeetConnector())
        with patch.object(gm_tools, "http_json", side_effect=fake):
            out = _run(tool.execute({"page_size": 5}))
        self.assertIn("conferenceRecords/abc", out)
        self.assertIn("space=space-1", out)


class GetTranscriptTest(unittest.TestCase):
    def test_validates_conference_record_path(self) -> None:
        tool = gm_tools.MeetGetTranscriptTool(_FakeMeetConnector())
        with self.assertRaises(ValueError):
            _run(tool.execute({"conference_record": "../etc"}))


if __name__ == "__main__":
    unittest.main()
