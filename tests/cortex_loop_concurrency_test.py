import asyncio
import unittest
from contextvars import ContextVar
from unittest.mock import patch

from autonoma.cortex.loop import AgentLoop


class _Trace:
    def __init__(self) -> None:
        self.spans: list[tuple[str, dict]] = []

    def add_span(self, stage: str, data: dict) -> None:
        self.spans.append((stage, data))


class AgentLoopContextTest(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_observations_stay_with_their_trace(self) -> None:
        loop = object.__new__(AgentLoop)
        loop._current_live_trace = ContextVar("test_live_trace", default=None)
        loop._current_otel_span = ContextVar("test_otel_span", default=None)
        first = _Trace()
        second = _Trace()

        async def observe(trace: _Trace, label: str) -> None:
            token = loop._current_live_trace.set(trace)
            try:
                await asyncio.sleep(0)
                loop._observe({}, "test", {"label": label})
            finally:
                loop._current_live_trace.reset(token)

        with patch("autonoma.cortex.loop.otel.add_trace_event"):
            await asyncio.gather(
                observe(first, "first"),
                observe(second, "second"),
            )

        self.assertEqual(first.spans, [("test", {"label": "first"})])
        self.assertEqual(second.spans, [("test", {"label": "second"})])