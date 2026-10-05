import asyncio
import unittest

from autonoma.cortex.triage_classifier import create_llm_classifier
from autonoma.schema import ContentBlock, LLMResponse, Message


class _FakeProvider:
    def __init__(self, response_text: str) -> None:
        self.response_text = response_text
        self.last_call = None

    @property
    def name(self) -> str:
        return "fake"

    async def chat(self, messages, **kwargs) -> LLMResponse:
        self.last_call = (messages, kwargs)
        return LLMResponse(
            content=[ContentBlock(type="text", text=self.response_text)],
            stop_reason="end_turn",
        )


class TriageClassifierTest(unittest.TestCase):
    def test_parses_valid_decision_and_bounds_output(self) -> None:
        provider = _FakeProvider(
            '{"decision":"archive","reason":"bulk mail","confidence":0.9}'
        )
        classify = create_llm_classifier(provider)
        message = Message(
            channel="gmail",
            channel_id="inbox",
            user_id="sender@example.com",
            content="newsletter",
        )

        result = asyncio.run(classify(message))

        self.assertIsNotNone(result)
        self.assertEqual(result.decision, "archive")
        self.assertEqual(result.layer, "llm")
        self.assertEqual(provider.last_call[1]["temperature"], 0)

    def test_rejects_invalid_decision(self) -> None:
        provider = _FakeProvider(
            '{"decision":"delete_account","reason":"bad","confidence":1}'
        )
        classify = create_llm_classifier(provider)
        message = Message(
            channel="gmail",
            channel_id="inbox",
            user_id="sender@example.com",
            content="hello",
        )

        self.assertIsNone(asyncio.run(classify(message)))