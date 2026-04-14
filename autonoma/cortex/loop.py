"""The 9-stage agent processing loop."""

from __future__ import annotations

import logging
import re
import time

from autonoma.cortex.context import ContextAssembler
from autonoma.cortex.session import SessionManager
from autonoma.memory.store import MemoryStore
from autonoma.models.provider import LLMProvider
from autonoma.schema import AgentResponse, Message, SessionEntry

logger = logging.getLogger(__name__)

# Basic prompt injection patterns (Stage 0)
INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.IGNORECASE),
    re.compile(r"ignore\s+(all\s+)?above\s+instructions", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+(?:a|an)\s+(?:different|new)", re.IGNORECASE),
    re.compile(r"system\s*:\s*", re.IGNORECASE),
]

MAX_INPUT_LENGTH = 10_000


class AgentLoop:
    """Orchestrates the 9-stage agent pipeline for each incoming message."""

    def __init__(
        self,
        provider: LLMProvider,
        context_assembler: ContextAssembler,
        memory_store: MemoryStore,
        session_manager: SessionManager,
    ):
        self._provider = provider
        self._context = context_assembler
        self._memory = memory_store
        self._sessions = session_manager

    async def process(self, message: Message, session_id: str) -> AgentResponse:
        """Run the full 9-stage pipeline."""
        start_time = time.time()
        trace: dict = {"session_id": session_id, "stages": {}}

        try:
            # Stage 0: VALIDATE
            self._observe(trace, "validate", {"input_length": len(message.content)})
            message = await self._validate(message)

            # Stage 1: NORMALIZE (handled by channel adapter — no-op here)
            self._observe(trace, "normalize", {"channel": message.channel})

            # Stage 2: ROUTE (handled by gateway router — no-op here)
            self._observe(trace, "route", {"user_id": message.user_id})

            # Stage 3: ASSEMBLE CONTEXT
            # First, save the user message to session
            user_entry = SessionEntry(
                role="user",
                content=message.content,
                channel=message.channel,
                user_id=message.user_id,
            )
            await self._sessions.append(session_id, user_entry)

            # Load history and assemble prompt
            history = await self._sessions.load_history(session_id)
            system_prompt, messages = await self._context.assemble(history)
            self._observe(
                trace,
                "assemble_context",
                {"history_count": len(history), "system_prompt_len": len(system_prompt)},
            )

            # Stage 4: INFER
            raw_response = await self._infer(system_prompt, messages)
            self._observe(
                trace, "infer", {"response_length": len(raw_response)}
            )

            # Stage 5: REACT LOOP (Phase 1: single pass, no tool calls)
            # In Phase 2, this will check for tool_use blocks and loop.
            final_response = raw_response
            self._observe(trace, "react_loop", {"iterations": 1})

            # Stage 6: LOAD SKILLS (Phase 1: skipped)
            self._observe(trace, "load_skills", {"skipped": True})

            # Stage 7: PERSIST MEMORY
            cleaned_response = await self._persist(
                session_id, message, final_response
            )
            self._observe(trace, "persist_memory", {"cleaned": True})

            # Stage 8: OBSERVE
            elapsed = time.time() - start_time
            self._observe(trace, "complete", {"elapsed_seconds": round(elapsed, 2)})
            logger.info(
                "Processed message in %.2fs (session=%s)", elapsed, session_id
            )

            return AgentResponse(
                content=cleaned_response,
                metadata={"session_id": session_id, "elapsed": elapsed},
            )

        except Exception as e:
            logger.error("Agent loop error: %s", e, exc_info=True)
            self._observe(trace, "error", {"error": str(e)})
            return AgentResponse(
                content="I encountered an error processing your message. Please try again.",
                metadata={"error": str(e)},
            )

    async def _validate(self, message: Message) -> Message:
        """Stage 0: Input sanitization and basic prompt injection check."""
        # Enforce max length
        if len(message.content) > MAX_INPUT_LENGTH:
            message.content = message.content[:MAX_INPUT_LENGTH]
            logger.warning("Input truncated to %d chars", MAX_INPUT_LENGTH)

        # Strip control characters (keep newlines and tabs)
        message.content = "".join(
            c for c in message.content if c == "\n" or c == "\t" or (ord(c) >= 32)
        )

        # Check for prompt injection patterns
        for pattern in INJECTION_PATTERNS:
            if pattern.search(message.content):
                logger.warning(
                    "Possible prompt injection detected from user=%s: %s",
                    message.user_id,
                    message.content[:100],
                )
                break

        return message

    async def _infer(self, system_prompt: str, messages: list) -> str:
        """Stage 4: Call the LLM provider."""
        return await self._provider.chat(
            messages, system_prompt=system_prompt
        )

    async def _persist(
        self, session_id: str, message: Message, response: str
    ) -> str:
        """Stage 7: Process memory commands and save to session."""
        # Extract and store memory commands, get cleaned response
        cleaned = await self._memory.process_memory_commands(response, message)

        # Log to daily log
        await self._memory.append_daily_log(
            f"User ({message.channel}): {message.content[:100]}"
        )
        await self._memory.append_daily_log(
            f"Agent: {cleaned[:100]}"
        )

        # Save assistant response to session
        assistant_entry = SessionEntry(
            role="assistant",
            content=cleaned,
            channel=message.channel,
            user_id="agent",
        )
        await self._sessions.append(session_id, assistant_entry)

        return cleaned

    def _observe(self, trace: dict, stage: str, data: dict) -> None:
        """Stage 8: Emit trace event (logged in Phase 1)."""
        trace["stages"][stage] = data
        logger.debug("Stage [%s]: %s", stage, data)
