"""Tests for ContactStore — identity resolution + tier escalation."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from autonoma.config import RelationshipConfig
from autonoma.cortex.contacts import (
    TIER_ACQUAINTANCE,
    TIER_COLLEAGUE,
    TIER_STRANGER,
    TIER_VIP,
    ContactStore,
)
from autonoma.schema import Message


def _run(coro):
    return asyncio.run(coro)


def _msg(channel: str, user_id: str, name: str = "", content: str = "hi") -> Message:
    return Message(
        channel=channel, channel_id=f"ch-{user_id}",
        user_id=user_id, user_name=name, content=content,
    )


class ContactStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        cfg = RelationshipConfig(
            enabled=True,
            db_path=str(Path(self.tmp.name) / "contacts.db"),
            stranger_max_messages=1,
            colleague_min_messages=4,
        )
        self.store = ContactStore(cfg)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_first_message_is_stranger(self):
        contact = _run(self.store.upsert(_msg("gmail", "alice@example.com", "Alice")))
        self.assertEqual(contact.tier, TIER_STRANGER)
        self.assertEqual(contact.message_count, 1)

    def test_tier_escalates_with_volume(self):
        for _ in range(5):
            contact = _run(self.store.upsert(_msg("gmail", "alice@example.com", "Alice")))
        self.assertEqual(contact.tier, TIER_COLLEAGUE)
        self.assertEqual(contact.message_count, 5)

    def test_intermediate_acquaintance(self):
        for _ in range(3):
            contact = _run(self.store.upsert(_msg("gmail", "alice@example.com", "Alice")))
        self.assertEqual(contact.tier, TIER_ACQUAINTANCE)

    def test_vip_address_overrides(self):
        cfg = RelationshipConfig(
            enabled=True,
            db_path=str(Path(self.tmp.name) / "vip.db"),
            vip_addresses=["boss@example.com"],
        )
        store = ContactStore(cfg)
        contact = _run(store.upsert(_msg("gmail", "boss@example.com", "Boss")))
        self.assertEqual(contact.tier, TIER_VIP)

    def test_vip_keyword_in_signature(self):
        cfg = RelationshipConfig(
            enabled=True,
            db_path=str(Path(self.tmp.name) / "vk.db"),
            vip_keywords=["CEO"],
        )
        store = ContactStore(cfg)
        contact = _run(store.upsert(_msg(
            "gmail", "x@example.com", "Sam",
            content="Quick note from the CEO desk — please prioritize.",
        )))
        self.assertEqual(contact.tier, TIER_VIP)

    def test_cross_channel_merge_by_name(self):
        a = _run(self.store.upsert(_msg("gmail", "bob@example.com", "Bob Smith")))
        b = _run(self.store.upsert(_msg("telegram", "@bobsmith", "Bob Smith")))
        self.assertEqual(a.canonical_id, b.canonical_id)
        self.assertEqual(b.message_count, 2)

    def test_short_or_generic_names_not_merged(self):
        a = _run(self.store.upsert(_msg("gmail", "u1@x.com", "user")))
        b = _run(self.store.upsert(_msg("telegram", "u2", "user")))
        self.assertNotEqual(a.canonical_id, b.canonical_id)

    def test_explicit_link_identity(self):
        a = _run(self.store.upsert(_msg("gmail", "carol@example.com", "Carol")))
        _run(self.store.link_identity(a.canonical_id, "telegram", "@carol_t"))
        b = _run(self.store.lookup("telegram", "@carol_t"))
        self.assertIsNotNone(b)
        self.assertEqual(b.canonical_id, a.canonical_id)

    def test_set_vip_flag_promotes(self):
        c = _run(self.store.upsert(_msg("gmail", "dave@example.com", "Dave")))
        _run(self.store.set_vip(c.canonical_id, True))
        c2 = _run(self.store.upsert(_msg("gmail", "dave@example.com", "Dave")))
        self.assertEqual(c2.tier, TIER_VIP)


if __name__ == "__main__":
    unittest.main()
