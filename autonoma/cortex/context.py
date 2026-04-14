"""Context assembly — builds the full prompt from SOUL.md + memory + history."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from autonoma.memory.store import MemoryStore
from autonoma.schema import LLMMessage, SessionEntry

logger = logging.getLogger(__name__)


class ContextAssembler:
    """Assembles the full prompt context for LLM calls (Stage 3: ASSEMBLE_CONTEXT)."""

    def __init__(self, workspace_dir: str, memory_store: MemoryStore):
        self._workspace = Path(workspace_dir)
        self._memory = memory_store
        self._soul_cache: str | None = None
        self._soul_mtime: float = 0

    async def assemble(
        self, session_history: list[SessionEntry]
    ) -> tuple[str, list[LLMMessage]]:
        """
        Build the system prompt and message list for the LLM.

        Returns:
            (system_prompt, messages) — system prompt is separate for Anthropic API.
        """
        # Load and fill SOUL.md template
        soul_template = await self._load_soul()
        memory_context = await self._memory.get_memory_context()
        daily_log = await self._memory.get_daily_context()

        system_prompt = soul_template.replace(
            "{memory_context}", memory_context
        ).replace("{daily_log}", daily_log)

        # Convert session history to LLM messages
        messages = [
            LLMMessage(role=entry.role, content=entry.content)
            for entry in session_history
        ]

        return system_prompt, messages

    async def _load_soul(self) -> str:
        """Load SOUL.md with mtime-based cache invalidation."""
        soul_path = self._workspace / "SOUL.md"
        if not soul_path.exists():
            logger.warning("SOUL.md not found at %s, using empty prompt", soul_path)
            return ""

        stat = await asyncio.to_thread(soul_path.stat)
        if self._soul_cache is None or stat.st_mtime != self._soul_mtime:
            self._soul_cache = await asyncio.to_thread(
                soul_path.read_text, "utf-8"
            )
            self._soul_mtime = stat.st_mtime
            logger.debug("Loaded SOUL.md (mtime=%s)", stat.st_mtime)

        return self._soul_cache
