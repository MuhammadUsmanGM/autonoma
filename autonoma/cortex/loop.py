"""The 9-stage agent processing loop — now with ReAct tool execution."""

from __future__ import annotations

import logging
import re
import time
from typing import Any

from autonoma.cortex.contacts import ContactStore
from autonoma.cortex.context import ContextAssembler
from autonoma.cortex.identity import (
    extract_identifiers_from_text,
    parse_link_identity_tags,
)
from autonoma.cortex.session import SessionManager
from autonoma.cortex.state_machine import (
    ConversationStateStore,
    parse_followup_tag,
)
from autonoma.cortex.trace_store import TraceStore
from autonoma.executor.tool_runner import ToolRunner
from autonoma.memory.store import MemoryStore
from autonoma.models.provider import LLMProvider
from autonoma.observability import otel
from autonoma.observability.metrics import (
    agent_loop_duration_seconds,
    agent_loop_total,
    llm_cost_usd_total,
    llm_tokens_total,
)
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
        contact_store: ContactStore | None = None,
        state_store: ConversationStateStore | None = None,
    ):
        self._provider = provider
        self._context = context_assembler
        self._memory = memory_store
        self._sessions = session_manager
        self._tool_runner = tool_runner
        self._skill_registry = skill_registry
        self._trace_store = trace_store
        self._contacts = contact_store
        self._state_store = state_store

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

        # Start an OpenTelemetry span for this loop invocation. No-op when
        # OTel is not configured, so there's no cost for local / dev runs.
        otel_span = otel.start_trace_span(
            "autonoma.agent.loop",
            attributes={
                "autonoma.session_id": session_id,
                "autonoma.channel": message.channel,
                "autonoma.user_id": message.user_id,
                "autonoma.trace_id": live_trace.id if live_trace else "",
            },
        )
        self._current_otel_span = otel_span

        try:
            # Stage 0: VALIDATE
            self._observe(trace, "validate", {"input_length": len(message.content)})
            message = await self._validate(message)

            # Stage 1: NORMALIZE (handled by channel adapter — no-op here)
            self._observe(trace, "normalize", {"channel": message.channel})

            # Stage 2: ROUTE (handled by gateway router — no-op here)
            self._observe(trace, "route", {"user_id": message.user_id})

            # Stage 2.5: RESOLVE CONTACT + STATE (relationship + conversation state)
            contact = None
            state = None
            if self._contacts is not None:
                contact = await self._contacts.upsert(message)
                # Cross-channel identity hints: pull emails / phones out of
                # the message body and attach them to this contact. Same
                # email later spotted in a Telegram message → that Telegram
                # conversation auto-merges into this contact.
                extracted = extract_identifiers_from_text(message.content)
                added = 0
                if extracted:
                    added = await self._contacts.add_extracted_identifiers(
                        contact.canonical_id, extracted
                    )
                self._observe(trace, "resolve_contact", {
                    "canonical_id": contact.canonical_id,
                    "tier": contact.tier,
                    "message_count": contact.message_count,
                    "extracted_identifiers": len(extracted),
                    "extracted_added": added,
                })
            if self._state_store is not None and contact is not None:
                state = await self._state_store.record_inbound(
                    contact.canonical_id, message.id
                )
                self._observe(trace, "update_state", {
                    "state": state.state,
                    "canonical_id": contact.canonical_id,
                })

            # Stage 3: ASSEMBLE CONTEXT
            user_entry = SessionEntry(
                role="user",
                content=message.content,
                channel=message.channel,
                user_id=message.user_id,
            )
            await self._sessions.append(session_id, user_entry)

            history = await self._sessions.load_history(session_id)
            system_prompt, messages = await self._context.assemble(
                history, contact=contact, state=state,
            )
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
                        result = await self._tool_runner.execute(tc, session_id=session_id)
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

            # Extract [FOLLOWUP: ...] tag before memory tag stripping so we
            # can transition state. The tag is removed from the user-visible
            # reply at the same time.
            followup_at, followup_reason, final_text = parse_followup_tag(final_text)

            # Extract [LINK_IDENTITY: kind=value] tags. The LLM emits these
            # when it concludes from conversation context that the current
            # contact also owns another identifier ("by the way, my email
            # is alice@…"). Tags are stripped from the visible reply.
            link_idents, final_text = parse_link_identity_tags(final_text)
            if link_idents and contact is not None and self._contacts is not None:
                added = await self._contacts.add_extracted_identifiers(
                    contact.canonical_id, link_idents
                )
                self._observe(trace, "link_identity", {
                    "canonical_id": contact.canonical_id,
                    "tag_count": len(link_idents),
                    "added": added,
                })

            # Stage 7: PERSIST MEMORY
            cleaned_response = await self._persist(
                session_id, message, final_text
            )
            self._observe(trace, "persist_memory", {"cleaned": True})

            # Stage 7.5: STATE TRANSITION (outbound)
            if self._state_store is not None and contact is not None:
                await self._state_store.record_outbound(
                    contact.canonical_id,
                    followup_at=followup_at,
                    followup_reason=followup_reason,
                )
                self._observe(trace, "state_outbound", {
                    "followup_scheduled": followup_at is not None,
                    "followup_reason": followup_reason[:120],
                })

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

            self._record_loop_metric("completed", message.channel, elapsed)
            otel.end_trace_span(
                otel_span,
                status="ok",
                attributes={
                    "autonoma.elapsed_seconds": elapsed,
                    "autonoma.tool_calls": len(tool_trace),
                    "autonoma.tokens_in": live_trace.tokens_in if live_trace else 0,
                    "autonoma.tokens_out": live_trace.tokens_out if live_trace else 0,
                    "autonoma.cost_usd": live_trace.cost_usd if live_trace else 0,
                    "autonoma.model": live_trace.model if live_trace else "",
                },
            )

            return AgentResponse(
                content=cleaned_response,
                metadata={
                    "session_id": session_id,
                    "elapsed": elapsed,
                    "tool_calls": tool_trace,
                },
            )

        except Exception as e:
            elapsed = time.time() - start_time
            logger.error("Agent loop error: %s", e, exc_info=True)
            self._observe(trace, "error", {"error": str(e)})
            if live_trace:
                live_trace.fail(str(e), elapsed)
                if self._trace_store:
                    await self._trace_store.persist_trace(live_trace)
            self._record_loop_metric("error", message.channel, elapsed)
            otel.end_trace_span(
                otel_span,
                status="error",
                error=str(e),
                attributes={"autonoma.elapsed_seconds": elapsed},
            )
            return AgentResponse(
                content="I encountered an error processing your message. Please try again.",
                metadata={"error": str(e)},
            )

    @staticmethod
    def _record_loop_metric(status: str, channel: str, elapsed: float) -> None:
        """Best-effort emission of agent loop outcome metrics.

        Split out so it can be called from both success and error branches
        without repeating the try/except defensive pattern.
        """
        try:
            agent_loop_total.inc(labels={"status": status, "channel": channel or "unknown"})
            agent_loop_duration_seconds.observe(
                elapsed, labels={"status": status}
            )
        except Exception:  # pragma: no cover
            pass

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
        """Stage 4: Call the LLM provider, then bill the live trace."""
        response = await self._provider.chat(
            messages, system_prompt=system_prompt, tools=tools
        )
        self._record_usage(response)
        return response

    def _record_usage(self, response: LLMResponse) -> None:
        """Fold one LLM call's token usage + cost into the active trace.

        Intentionally defensive: if the provider didn't return usage, if no
        live trace is attached, or if the pricing lookup fails, we silently
        skip. Cost tracking is an observability nice-to-have — it must never
        take down the loop."""
        if not response.usage:
            return
        try:
            from autonoma.models.pricing import cost_for
            model = response.model or getattr(self._provider, "_model", "")
            tin = int(response.usage.get("input_tokens", 0) or 0)
            tout = int(response.usage.get("output_tokens", 0) or 0)
            cost = cost_for(model, tin, tout)

            live = getattr(self, "_current_live_trace", None)
            if live:
                live.add_usage(tin, tout, cost, model=model)

            # Prometheus counters run even if there's no live trace (e.g.
            # a background agent_prompt invocation with trace_store disabled).
            model_label = model or "unknown"
            if tin:
                llm_tokens_total.inc(tin, labels={"direction": "input", "model": model_label})
            if tout:
                llm_tokens_total.inc(tout, labels={"direction": "output", "model": model_label})
            if cost:
                llm_cost_usd_total.inc(cost, labels={"model": model_label})
        except Exception as e:  # pragma: no cover — advisory only
            logger.debug("Cost tracking skipped: %s", e)

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
        # Mirror the stage as an OTel span event so pipeline shape is visible
        # to any OpenTelemetry backend.
        otel.add_trace_event(
            getattr(self, "_current_otel_span", None),
            f"stage.{stage}",
            data,
        )
        logger.debug("Stage [%s]: %s", stage, data)
