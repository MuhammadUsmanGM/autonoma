"""Core agent class — owns the loop and manages sessions."""

from __future__ import annotations

import logging

from autonoma.config import Config
from autonoma.cortex.context import ContextAssembler
from autonoma.cortex.loop import AgentLoop
from autonoma.cortex.session import SessionManager
from autonoma.cortex.trace_store import TraceStore
from autonoma.executor.tool_runner import ToolRunner
from autonoma.memory.store import MemoryStore
from autonoma.models.provider import LLMProvider
from autonoma.schema import AgentResponse, Message
from autonoma.skills.registry import SkillRegistry

logger = logging.getLogger(__name__)


class Agent:
    """The core agent — routes messages through the processing loop."""

    def __init__(
        self,
        config: Config,
        provider: LLMProvider,
        memory_store: MemoryStore,
        session_manager: SessionManager,
        context_assembler: ContextAssembler,
        tool_runner: ToolRunner | None = None,
        skill_registry: SkillRegistry | None = None,
        trace_store: TraceStore | None = None,
    ):
        self.name = config.name
        self._loop = AgentLoop(
            provider, context_assembler, memory_store, session_manager,
            tool_runner=tool_runner, skill_registry=skill_registry,
            trace_store=trace_store,
        )
        self._sessions = session_manager
        self._active_sessions: dict[str, str] = {}  # channel_id -> session_id

    async def handle_message(self, message: Message) -> AgentResponse:
        """Entry point for all incoming messages."""
        session_id = await self._get_or_create_session(
            message.channel_id, message.channel
        )
        return await self._loop.process(message, session_id)

    async def _get_or_create_session(
        self, channel_id: str, channel: str
    ) -> str:
        """Get existing session for this channel, or create a new one."""
        if channel_id not in self._active_sessions:
            session_id = await self._sessions.create_session(channel)
            self._active_sessions[channel_id] = session_id
            logger.info(
                "New session %s for channel %s", session_id, channel_id
            )
        return self._active_sessions[channel_id]
