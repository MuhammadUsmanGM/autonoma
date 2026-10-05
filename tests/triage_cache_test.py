import unittest

from autonoma.config import TriageConfig
from autonoma.cortex.triage import Triage, TriageDecision
from autonoma.schema import Message


class TriageCacheTest(unittest.TestCase):
    def setUp(self) -> None:
        self.triage = Triage(TriageConfig(sender_cache_ttl=3600))
        self.decision = TriageDecision(
            decision="archive",
            reason="newsletter",
            confidence=0.95,
            layer="rule",
        )

    def test_different_message_from_sender_does_not_reuse_decision(self) -> None:
        original = Message(
            channel="gmail",
            channel_id="inbox",
            user_id="person@example.com",
            content="weekly newsletter",
        )
        later = Message(
            channel="gmail",
            channel_id="inbox",
            user_id="person@example.com",
            content="Can we talk about the project?",
        )
        self.triage._cache_put(original, self.decision)

        self.assertIsNone(self.triage._cache_get(later))

    def test_exact_duplicate_can_reuse_decision(self) -> None:
        original = Message(
            channel="gmail",
            channel_id="inbox",
            user_id="person@example.com",
            content="weekly newsletter",
        )
        duplicate = Message(
            channel="gmail",
            channel_id="inbox",
            user_id="PERSON@example.com",
            content="weekly newsletter",
        )
        self.triage._cache_put(original, self.decision)

        self.assertIs(self.triage._cache_get(duplicate), self.decision)