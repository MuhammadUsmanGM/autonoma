"""Context assembly — builds the full prompt from SOUL.md + memory + history."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from autonoma.cortex.contacts import (
    Contact,
    humanize_age,
    render_relationship_block,
)
from autonoma.cortex.state_machine import ConversationState
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
        self,
        session_history: list[SessionEntry],
        *,
        contact: Contact | None = None,
        state: ConversationState | None = None,
    ) -> tuple[str, list[LLMMessage]]:
        """Build the system prompt and message list for the LLM."""
        soul_template = await self._load_soul()

        user_query = ""
        for entry in reversed(session_history):
            if entry.role == "user":
                user_query = entry.content
                break

        memory_context = await self._memory.get_memory_context(query=user_query)
        daily_log = await self._memory.get_daily_context()

        relationship_block = render_relationship_block(
            contact,
            humanize_age(contact.last_seen) if contact else "",
        )
        state_block = _render_state_block(state)

        system_prompt = (
            soul_template
            .replace("{memory_context}", memory_context)
            .replace("{daily_log}", daily_log)
            .replace("{relationship_context}", relationship_block)
            .replace("{conversation_state}", state_block)
        )

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


_STATE_HINTS = {
    "awaiting_reply": "This message is the user's latest turn — reply now.",
    "followup_needed": (
        "We owed this contact a follow-up. Acknowledge the delay if any, "
        "and either resolve the open thread or set a new [FOLLOWUP: ...] tag."
    ),
    "resolved": "No prior open threads with this contact.",
    "snoozed": "Contact was snoozed; respond only if this message is urgent.",
    "ignored": "Contact previously filtered. Reply only if their tone changed.",
}


def _render_state_block(state: ConversationState | None) -> str:
    """Compact state summary injected next to the relationship block.

    The agent uses this to know whether it's catching up on a stale thread
    or starting fresh. The instruction tag list ([FOLLOWUP: ...]) is
    documented inline so the model uses it without needing tool docs.
    """
    if state is None:
        return (
            "State: new conversation.\n"
            "If your reply commits to checking back later, append a "
            "[FOLLOWUP: <duration> <reason>] tag (e.g. [FOLLOWUP: 3d budget approval])."
        )

    hint = _STATE_HINTS.get(state.state, "")
    last_in = humanize_age(state.last_inbound_at) if state.last_inbound_at else "—"
    last_out = humanize_age(state.last_outbound_at) if state.last_outbound_at else "—"
    reason = state.metadata.get("followup_reason", "")
    extra = f"\nPending follow-up reason: {reason}" if reason else ""
    return (
        f"State: {state.state}\n"
        f"Last user msg: {last_in}; last agent reply: {last_out}.\n"
        f"{hint}{extra}\n"
        "If you commit to a follow-up, append [FOLLOWUP: <duration> <reason>] "
        "(e.g. [FOLLOWUP: 24h waiting on legal])."
    )
