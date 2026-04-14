"""Gateway-level message router (Stage 1+2: NORMALIZE + ROUTE)."""

from __future__ import annotations

from autonoma.cortex.router import AgentRouter
from autonoma.schema import AgentResponse, Message


class GatewayRouter:
    """Routes incoming channel messages to the agent layer."""

    def __init__(self, agent_router: AgentRouter):
        self._agent_router = agent_router

    async def handle_message(self, message: Message) -> AgentResponse:
        """Normalize and route a message. Phase 1: pass-through."""
        return await self._agent_router.route(message)
