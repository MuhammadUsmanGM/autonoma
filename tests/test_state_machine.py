"""Tests for ConversationStateStore + parse_followup_tag."""

from __future__ import annotations

import asyncio
import tempfile
import time
import unittest
from pathlib import Path

from autonoma.config import ConversationStateConfig
from autonoma.cortex.state_machine import (
    STATE_AWAITING_REPLY,
    STATE_FOLLOWUP_NEEDED,
    STATE_RESOLVED,
    STATE_SNOOZED,
    ConversationStateStore,
    parse_followup_tag,
)


def _run(coro):
    return asyncio.run(coro)


class StateMachineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        cfg = ConversationStateConfig(
            enabled=True,
            db_path=str(Path(self.tmp.name) / "state.db"),
            awaiting_reply_ttl_hours=1,  # 1h TTL for fast TTL test
        )
        self.store = ConversationStateStore(cfg)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_inbound_sets_awaiting_reply(self):
        s = _run(self.store.record_inbound("c_1", "m1"))
        self.assertEqual(s.state, STATE_AWAITING_REPLY)
        self.assertGreater(s.last_inbound_at, 0)

    def test_outbound_resolves_by_default(self):
        _run(self.store.record_inbound("c_1", "m1"))
        s = _run(self.store.record_outbound("c_1"))
        self.assertEqual(s.state, STATE_RESOLVED)

    def test_outbound_with_followup_marks_followup_needed(self):
        _run(self.store.record_inbound("c_1", "m1"))
        future = time.time() + 60
        s = _run(self.store.record_outbound(
            "c_1", followup_at=future, followup_reason="waiting on legal",
        ))
        self.assertEqual(s.state, STATE_FOLLOWUP_NEEDED)
        self.assertAlmostEqual(s.followup_due_at, future, delta=2)
        self.assertEqual(s.metadata.get("followup_reason"), "waiting on legal")

    def test_find_due_returns_only_past_due(self):
        _run(self.store.record_outbound(
            "c_past", followup_at=time.time() - 60, followup_reason="r",
        ))
        _run(self.store.record_outbound(
            "c_future", followup_at=time.time() + 3600, followup_reason="r",
        ))
        due = _run(self.store.find_due_followups())
        ids = {d.canonical_id for d in due}
        self.assertIn("c_past", ids)
        self.assertNotIn("c_future", ids)

    def test_stale_awaiting_reply_promoted(self):
        # Backdate last_inbound_at by directly inserting an old timestamp.
        _run(self.store.record_inbound("c_old", "m1"))
        with self.store._connect() as conn:
            conn.execute(
                "UPDATE conversation_states SET last_inbound_at = ? WHERE canonical_id = ?",
                (time.time() - 3 * 3600, "c_old"),
            )
        due = _run(self.store.find_due_followups())
        ids = {d.canonical_id for d in due}
        self.assertIn("c_old", ids)

    def test_snooze_blocks_inbound_state_change(self):
        _run(self.store.snooze("c_1", until=time.time() + 600))
        s = _run(self.store.record_inbound("c_1", "m2"))
        self.assertEqual(s.state, STATE_SNOOZED)

    def test_snooze_expires_to_awaiting_reply(self):
        _run(self.store.record_inbound("c_1", "m1"))
        _run(self.store.snooze("c_1", until=time.time() - 1))
        _run(self.store.find_due_followups())  # triggers expiration sweep
        s = _run(self.store.get("c_1"))
        self.assertEqual(s.state, STATE_AWAITING_REPLY)

    def test_disabled_returns_dummy_resolved(self):
        cfg = ConversationStateConfig(enabled=False, db_path=str(Path(self.tmp.name) / "off.db"))
        store = ConversationStateStore(cfg)
        s = _run(store.record_inbound("c_1", "m1"))
        self.assertEqual(s.state, STATE_RESOLVED)


class FollowupTagTest(unittest.TestCase):
    def test_relative_duration(self):
        due, reason, cleaned = parse_followup_tag(
            "Sure, I'll check back. [FOLLOWUP: 3d budget approval]"
        )
        self.assertIsNotNone(due)
        self.assertGreater(due, time.time() + 2 * 86400)
        self.assertLess(due, time.time() + 4 * 86400)
        self.assertEqual(reason, "budget approval")
        self.assertNotIn("FOLLOWUP", cleaned)

    def test_minutes(self):
        due, reason, _ = parse_followup_tag("ok [FOLLOWUP: 30m]")
        self.assertGreater(due, time.time() + 25 * 60)
        self.assertLess(due, time.time() + 35 * 60)
        self.assertEqual(reason, "")

    def test_iso_date(self):
        due, reason, _ = parse_followup_tag("[FOLLOWUP: 2030-01-15 quarterly review]")
        self.assertGreater(due, time.time())
        self.assertEqual(reason, "quarterly review")

    def test_no_tag(self):
        due, reason, cleaned = parse_followup_tag("just a normal reply")
        self.assertIsNone(due)
        self.assertEqual(reason, "")
        self.assertEqual(cleaned, "just a normal reply")

    def test_tag_stripped_from_reply(self):
        _, _, cleaned = parse_followup_tag(
            "Reply body. [FOLLOWUP: 24h waiting on legal] More text."
        )
        self.assertNotIn("FOLLOWUP", cleaned)
        self.assertIn("Reply body.", cleaned)
        self.assertIn("More text.", cleaned)


if __name__ == "__main__":
    unittest.main()
