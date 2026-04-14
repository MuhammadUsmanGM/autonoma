"""Multi-agent routing (Phase 1: single agent pass-through)."""

from __future__ import annotations

from autonoma.cortex.agent import Agent
from autonoma.schema import AgentResponse, Message


class AgentRouter:
    """Routes messages to the correct agent. Phase 1: always routes to default."""

    def __init__(self):
        self._agents: dict[str, Agent] = {}
        self._default: str | None = None

    def register(self, name: str, agent: Agent, *, default: bool = False) -> None:
        self._agents[name] = agent
        if default or self._default is None:
            self._default = name

    async def route(self, message: Message) -> AgentResponse:
        """Route message to the appropriate agent."""
        if not self._default or self._default not in self._agents:
            return AgentResponse(content="No agent available to handle this message.")
        return await self._agents[self._default].handle_message(message)
