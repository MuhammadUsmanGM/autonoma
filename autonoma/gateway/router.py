"""Gateway-level message router (Stage 1+2: NORMALIZE + ROUTE).

Inserts a triage layer in front of the agent so the agent doesn't waste
inferences (or send embarrassing replies) on noreply mail, newsletters,
auto-confirmations, or group chatter that wasn't directed at it.
"""

from __future__ import annotations

import logging

from autonoma.cortex.agent import Agent
from autonoma.cortex.triage import Triage, TriageDecision
from autonoma.schema import AgentResponse, Message

logger = logging.getLogger(__name__)


class GatewayRouter:
    """Routes incoming channel messages to the agent layer."""

    def __init__(self, triage: Triage | None = None):
        self._agents: dict[str, Agent] = {}
        self._default: str | None = None
        self._triage = triage

    def register(self, name: str, agent: Agent, *, default: bool = False) -> None:
        """Add an agent; ``default`` (or the first registered) answers."""
        self._agents[name] = agent
        if default or self._default is None:
            self._default = name

    async def route(self, message: Message) -> AgentResponse:
        """Dispatch to the default agent (single-agent pass-through today)."""
        if not self._default or self._default not in self._agents:
            return AgentResponse(content="No agent available to handle this message.")
        return await self._agents[self._default].handle_message(message)

    async def handle_message(self, message: Message) -> AgentResponse:
        """Triage the message, then route to the agent if it merits a reply."""
        if self._triage is not None:
            decision = await self._triage.classify(message)
            if decision.decision != "reply":
                return self._build_filtered_response(decision)

            response = await self.route(message)
            response.metadata.setdefault("triage", decision.to_dict())
            return response

        return await self.route(message)

    @staticmethod
    def _build_filtered_response(decision: TriageDecision) -> AgentResponse:
        """Translate a non-reply triage decision into an AgentResponse.

        Channels inspect ``response.metadata['triage']`` to decide whether
        to suppress sending. Content is empty for ignore/archive/escalate
        and a canned line for ``acknowledge``.
        """
        content = ""
        if decision.decision == "acknowledge" and decision.canned_reply:
            content = decision.canned_reply

        return AgentResponse(
            content=content,
            metadata={"triage": decision.to_dict()},
        )
