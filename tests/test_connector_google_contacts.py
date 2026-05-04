"""Google Contacts connector + enricher tests — mock http_json, no network."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from autonoma.config import RelationshipConfig
from autonoma.connectors.google_contacts import tools as gc_tools
from autonoma.cortex.contact_enricher import ContactEnricher
from autonoma.cortex.contacts import (
    TIER_ACQUAINTANCE,
    TIER_STRANGER,
    TIER_VIP,
    ContactStore,
)
from autonoma.schema import Message


def _run(coro):
    return asyncio.run(coro)


class _FakeConnector:
    def __init__(self, connected: bool = True, token: str = "tok") -> None:
        self._connected = connected
        self._token = token

    def is_connected(self) -> bool:
        return self._connected

    def access_token(self) -> str:
        return self._token


class NormalizeIdentifierTest(unittest.TestCase):
    def test_email_lowercased(self) -> None:
        self.assertEqual(
            gc_tools._normalize_identifier("Alice@Example.COM"),
            "alice@example.com",
        )

    def test_phone_strips_formatting(self) -> None:
        self.assertEqual(
            gc_tools._normalize_identifier("+1 (415) 555-2671"),
            "+14155552671",
        )


class ResolveIdentifierTest(unittest.TestCase):
    def test_exact_email_match_wins(self) -> None:
        people_saved = {
            "results": [
                {"person": {"resourceName": "people/x",
                            "names": [{"displayName": "Other"}],
                            "emailAddresses": [{"value": "other@x"}]}},
                {"person": {"resourceName": "people/a",
                            "names": [{"displayName": "Alice"}],
                            "emailAddresses": [{"value": "alice@example.com"}]}},
            ]
        }
        other = {"results": []}

        def fake(url, **kw):
            return people_saved if "searchContacts" in url else other

        with patch.object(gc_tools, "http_json", side_effect=fake):
            match = _run(gc_tools._resolve_identifier("tok", "alice@example.com"))
        self.assertIsNotNone(match)
        self.assertEqual(match["resourceName"], "people/a")

    def test_no_match_returns_none(self) -> None:
        with patch.object(
            gc_tools,
            "http_json",
            side_effect=lambda url, **kw: {"results": []},
        ):
            self.assertIsNone(_run(gc_tools._resolve_identifier("tok", "nope@x")))


class ContactEnricherTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        cfg = RelationshipConfig(
            enabled=True,
            db_path=str(Path(self.tmp.name) / "contacts.db"),
            stranger_max_messages=5,
        )
        self.store = ContactStore(cfg)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _seed_contact(self, email: str = "alice@example.com") -> str:
        contact = _run(self.store.upsert(Message(
            channel="gmail", channel_id=f"ch-{email}",
            user_id=email, user_name="", content="hi",
        )))
        return contact.canonical_id

    def test_inactive_when_disconnected(self) -> None:
        enricher = ContactEnricher(self.store, _FakeConnector(connected=False))
        self.assertFalse(enricher.is_active())

    def test_disabled_short_circuits(self) -> None:
        enricher = ContactEnricher(
            self.store, _FakeConnector(), enabled=False,
        )
        self.assertFalse(enricher.is_active())

    def test_strangers_bumped_to_acquaintance(self) -> None:
        cid = self._seed_contact()
        # Pre-condition: stranger.
        contact = _run(self.store.get(cid))
        self.assertEqual(contact.tier, TIER_STRANGER)

        people = {"resourceName": "people/a",
                  "names": [{"displayName": "Alice Smith"}],
                  "emailAddresses": [{"value": "alice@example.com"}],
                  "organizations": [{"name": "Acme", "title": "CTO"}]}

        def fake(url, **kw):
            if "searchContacts" in url:
                return {"results": [{"person": people}]}
            return {"results": []}

        enricher = ContactEnricher(self.store, _FakeConnector())
        with patch.object(gc_tools, "http_json", side_effect=fake):
            updated = _run(enricher.enrich(contact))
        self.assertEqual(updated.tier, TIER_ACQUAINTANCE)
        self.assertEqual(updated.display_name, "Alice Smith")
        self.assertIn("CTO @ Acme", updated.notes or "")

    def test_vip_tier_not_downgraded(self) -> None:
        cid = self._seed_contact()
        # Manually promote to VIP (vip_flag=True so apply_enrichment refuses).
        _run(self.store.set_vip(cid, True))
        contact = _run(self.store.get(cid))
        self.assertEqual(contact.tier, TIER_VIP)

        people = {"resourceName": "people/a",
                  "names": [{"displayName": "Alice"}],
                  "emailAddresses": [{"value": "alice@example.com"}]}

        def fake(url, **kw):
            if "searchContacts" in url:
                return {"results": [{"person": people}]}
            return {"results": []}

        enricher = ContactEnricher(self.store, _FakeConnector())
        with patch.object(gc_tools, "http_json", side_effect=fake):
            updated = _run(enricher.enrich(contact))
        # Still VIP.
        self.assertEqual(updated.tier, TIER_VIP)

    def test_rate_limit_skips_second_call(self) -> None:
        cid = self._seed_contact()
        contact = _run(self.store.get(cid))
        calls = {"n": 0}

        def fake(url, **kw):
            calls["n"] += 1
            return {"results": []}

        enricher = ContactEnricher(self.store, _FakeConnector())
        with patch.object(gc_tools, "http_json", side_effect=fake):
            _run(enricher.enrich(contact))
            _run(enricher.enrich(contact))
        # Two http_json calls per enrich (saved + other) but only ONE enrich
        # round-trip should fire — the second is rate-limited.
        self.assertEqual(calls["n"], 2)


if __name__ == "__main__":
    unittest.main()
