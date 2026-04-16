"""The 9-stage agent processing loop — now with ReAct tool execution."""

from __future__ import annotations

import logging
import re
import time
from typing import Any

from autonoma.cortex.context import ContextAssembler
from autonoma.cortex.session import SessionManager
from autonoma.cortex.trace_store import TraceStore
from autonoma.executor.tool_runner import ToolRunner
from autonoma.memory.store import MemoryStore
from autonoma.models.provider import LLMProvider
from autonoma.schema import (
    AgentResponse,
    LLMMessage,
    LLMResponse,
    Message,
    SessionEntry,
    ToolResult,
)
from autonoma.skills.registry import SkillRegistry

logger = logging.getLogger(__name__)

# Basic prompt injection patterns (Stage 0)
INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.IGNORECASE),
    re.compile(r"ignore\s+(all\s+)?above\s+instructions", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+(?:a|an)\s+(?:different|new)", re.IGNORECASE),
    re.compile(r"system\s*:\s*", re.IGNORECASE),
]

MAX_INPUT_LENGTH = 10_000
MAX_REACT_ITERATIONS = 10


class AgentLoop:
    """Orchestrates the 9-stage agent pipeline for each incoming message."""

    def __init__(
        self,
        provider: LLMProvider,
        context_assembler: ContextAssembler,
        memory_store: MemoryStore,
        session_manager: SessionManager,
        tool_runner: ToolRunner | None = None,
        skill_registry: SkillRegistry | None = None,
        trace_store: TraceStore | None = None,
    ):
        self._provider = provider
        self._context = context_assembler
        self._memory = memory_store
        self._sessions = session_manager
        self._tool_runner = tool_runner
        self._skill_registry = skill_registry
        self._trace_store = trace_store

    async def process(self, message: Message, session_id: str) -> AgentResponse:
        """Run the full 9-stage pipeline."""
        start_time = time.time()
        trace: dict = {"session_id": session_id, "stages": {}}
        tool_trace: list[dict] = []

        # Create structured trace if store is available
        live_trace = None
        if self._trace_store:
            live_trace = self._trace_store.create_trace(
                session_id=session_id,
                channel=message.channel,
                user_id=message.user_id,
            )
        self._current_live_trace = live_trace

        try:
            # Stage 0: VALIDATE
            self._observe(trace, "validate", {"input_length": len(message.content)})
            message = await self._validate(message)

            # Stage 1: NORMALIZE (handled by channel adapter — no-op here)
            self._observe(trace, "normalize", {"channel": message.channel})

            # Stage 2: ROUTE (handled by gateway router — no-op here)
            self._observe(trace, "route", {"user_id": message.user_id})

            # Stage 3: ASSEMBLE CONTEXT
            user_entry = SessionEntry(
                role="user",
                content=message.content,
                channel=message.channel,
                user_id=message.user_id,
            )
            await self._sessions.append(session_id, user_entry)

            history = await self._sessions.load_history(session_id)
            system_prompt, messages = await self._context.assemble(history)
            self._observe(
                trace,
                "assemble_context",
                {"history_count": len(history), "system_prompt_len": len(system_prompt)},
            )

            # Stage 6: LOAD SKILLS (get tool definitions for LLM)
            tool_defs = None
            if self._skill_registry:
                tool_defs = self._skill_registry.get_tool_definitions()
                self._observe(trace, "load_skills", {"tool_count": len(tool_defs)})
            else:
                self._observe(trace, "load_skills", {"skipped": True})

            # Stage 4: INFER
            response = await self._infer(system_prompt, messages, tools=tool_defs)
            self._observe(
                trace, "infer", {"stop_reason": response.stop_reason}
            )

            # Stage 5: REACT LOOP
            iteration = 0
            react_messages = list(messages)  # Working copy

            while response.has_tool_calls and iteration < MAX_REACT_ITERATIONS:
                iteration += 1
                logger.info("ReAct iteration %d — %d tool calls", iteration, len(response.tool_calls))

                # Build assistant message with the full response content
                assistant_content = self._build_assistant_content(response)
                react_messages.append(LLMMessage(role="assistant", content=assistant_content))

                # Execute each tool call
                tool_results: list[ToolResult] = []
                for tc in response.tool_calls:
                    if self._tool_runner:
                        result = await self._tool_runner.execute(tc)
                    else:
                        result = ToolResult(
                            tool_use_id=tc.id,
                            content="Error: No tool runner configured.",
                            is_error=True,
                        )
                    tool_results.append(result)
                    tool_trace.append({
                        "iteration": iteration,
                        "tool": tc.name,
                        "input": tc.input,
                        "result": result.content[:200],
                        "is_error": result.is_error,
                    })
                    logger.info(
                        "Tool %s → %s",
                        tc.name,
                        "error" if result.is_error else "ok",
                    )

                # Build tool result message and feed back to LLM
                result_content = self._build_tool_results(tool_results)
                react_messages.append(LLMMessage(role="user", content=result_content))

                # Re-invoke LLM
                response = await self._infer(system_prompt, react_messages, tools=tool_defs)

            self._observe(trace, "react_loop", {"iterations": iteration + 1})

            final_text = response.text

            # Stage 7: PERSIST MEMORY
            cleaned_response = await self._persist(
                session_id, message, final_text
            )
            self._observe(trace, "persist_memory", {"cleaned": True})

            # Stage 8: OBSERVE
            elapsed = time.time() - start_time
            self._observe(trace, "complete", {"elapsed_seconds": round(elapsed, 2)})
            logger.info(
                "Processed message in %.2fs (%d tool calls, session=%s)",
                elapsed, len(tool_trace), session_id,
            )

            if live_trace:
                live_trace.tool_calls = tool_trace
                live_trace.complete(elapsed)
                if self._trace_store:
                    await self._trace_store.persist_trace(live_trace)

            return AgentResponse(
                content=cleaned_response,
                metadata={
                    "session_id": session_id,
                    "elapsed": elapsed,
                    "tool_calls": tool_trace,
                },
            )

        except Exception as e:
            logger.error("Agent loop error: %s", e, exc_info=True)
            self._observe(trace, "error", {"error": str(e)})
            if live_trace:
                live_trace.fail(str(e), time.time() - start_time)
                if self._trace_store:
                    await self._trace_store.persist_trace(live_trace)
            return AgentResponse(
                content="I encountered an error processing your message. Please try again.",
                metadata={"error": str(e)},
            )

    async def _validate(self, message: Message) -> Message:
        """Stage 0: Input sanitization and basic prompt injection check."""
        if len(message.content) > MAX_INPUT_LENGTH:
            message.content = message.content[:MAX_INPUT_LENGTH]
            logger.warning("Input truncated to %d chars", MAX_INPUT_LENGTH)

        message.content = "".join(
            c for c in message.content if c == "\n" or c == "\t" or (ord(c) >= 32)
        )

        for pattern in INJECTION_PATTERNS:
            if pattern.search(message.content):
                logger.warning(
                    "Possible prompt injection detected from user=%s: %s",
                    message.user_id,
                    message.content[:100],
                )
                break

        return message

    async def _infer(
        self,
        system_prompt: str,
        messages: list[LLMMessage],
        *,
        tools: list[dict] | None = None,
    ) -> LLMResponse:
        """Stage 4: Call the LLM provider."""
        return await self._provider.chat(
            messages, system_prompt=system_prompt, tools=tools
        )

    def _build_assistant_content(self, response: LLMResponse) -> list[dict]:
        """Build Anthropic-format assistant content from LLMResponse."""
        content = []
        for block in response.content:
            if block.type == "text" and block.text:
                content.append({"type": "text", "text": block.text})
            elif block.type == "tool_use" and block.tool_call:
                content.append({
                    "type": "tool_use",
                    "id": block.tool_call.id,
                    "name": block.tool_call.name,
                    "input": block.tool_call.input,
                })
        return content

    def _build_tool_results(self, results: list[ToolResult]) -> list[dict]:
        """Build Anthropic-format tool result content blocks."""
        content = []
        for r in results:
            content.append({
                "type": "tool_result",
                "tool_use_id": r.tool_use_id,
                "content": r.content,
                **({"is_error": True} if r.is_error else {}),
            })
        return content

    async def _persist(
        self, session_id: str, message: Message, response: str
    ) -> str:
        """Stage 7: Process memory commands and save to session."""
        cleaned = await self._memory.process_memory_commands(response, message)

        await self._memory.append_daily_log(
            f"User ({message.channel}): {message.content[:100]}"
        )
        await self._memory.append_daily_log(
            f"Agent: {cleaned[:100]}"
        )

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
        # Also populate the structured live trace if available
        if hasattr(self, '_current_live_trace') and self._current_live_trace:
            self._current_live_trace.add_span(stage, data)
        logger.debug("Stage [%s]: %s", stage, data)
