"""Background scheduler that turns due follow-ups into agent_prompt tasks.

Runs as a long-lived asyncio task alongside the memory flusher. Every
``followup_check_interval_seconds`` it asks the state store which
contacts have a follow-up due (or have been silently waiting too long),
then enqueues an ``agent_prompt`` task on the existing TaskQueue.

The task drafts a nudge — it does NOT send anything. The agent's reply
lands in the dashboard for the user to review. This deliberately keeps a
human in the loop for proactive outbound messages, since wrong-channel
nudges damage trust faster than missed follow-ups do.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from autonoma.config import ConversationStateConfig
from autonoma.cortex.contacts import ContactStore
from autonoma.cortex.state_machine import (
    STATE_RESOLVED,
    ConversationStateStore,
)

if TYPE_CHECKING:
    from autonoma.executor.task_queue import TaskQueue

logger = logging.getLogger(__name__)


class FollowupScheduler:
    def __init__(
        self,
        config: ConversationStateConfig,
        state_store: ConversationStateStore,
        contact_store: ContactStore,
        task_queue: "TaskQueue",
    ):
        self._config = config
        self._state = state_store
        self._contacts = contact_store
        self._tasks = task_queue
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        if not self._config.enabled:
            logger.info("Followup scheduler disabled by config.")
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="followup_scheduler")
        logger.info(
            "Followup scheduler started (interval=%ds, stale_after=%dh)",
            self._config.followup_check_interval_seconds,
            self._config.awaiting_reply_ttl_hours,
        )

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except asyncio.TimeoutError:
                self._task.cancel()
            self._task = None

    async def _run(self) -> None:
        # Wait one interval before the first scan so startup logs stay quiet
        # on a freshly booted system with no real history yet.
        try:
            await asyncio.wait_for(
                self._stop.wait(),
                timeout=self._config.followup_check_interval_seconds,
            )
            return
        except asyncio.TimeoutError:
            pass

        while not self._stop.is_set():
            try:
                await self._tick()
            except Exception as exc:  # pragma: no cover — defensive
                logger.error("Followup scheduler error: %s", exc, exc_info=True)
            try:
                await asyncio.wait_for(
                    self._stop.wait(),
                    timeout=self._config.followup_check_interval_seconds,
                )
                break
            except asyncio.TimeoutError:
                continue

    async def _tick(self) -> None:
        due = await self._state.find_due_followups()
        if not due:
            return
        logger.info("Followup tick: %d contact(s) due", len(due))
        for state in due:
            contact = await self._contacts.get(state.canonical_id)
            if contact is None:
                continue
            prompt = self._build_prompt(contact, state)
            try:
                await self._tasks.submit(
                    "agent_prompt",
                    payload={
                        "prompt": prompt,
                        "channel": "followup",
                        "channel_id": f"followup:{contact.canonical_id}",
                        "user_id": "scheduler",
                    },
                )
                # Mark resolved so we don't re-fire the same followup every
                # interval. The agent's draft will land on the dashboard;
                # the user re-opens the thread by replying or by hitting
                # "send" on the draft.
                await self._state.record_outbound(
                    contact.canonical_id, followup_at=None, followup_reason="",
                )
            except Exception as exc:  # pragma: no cover — defensive
                logger.error(
                    "Failed to enqueue followup for %s: %s",
                    contact.canonical_id, exc,
                )

    @staticmethod
    def _build_prompt(contact, state) -> str:
        reason = state.metadata.get("followup_reason") or ""
        identities = ", ".join(
            f"{c}:{u}" for c, u in (contact.identities or [])[:2]
        ) or "—"
        return (
            f"Draft a follow-up nudge for {contact.display_name or 'contact'} "
            f"({identities}, tier={contact.tier}). "
            f"Original reason: {reason or '(none — likely a stale awaiting_reply)'}. "
            "Keep it short, polite, and reference the prior thread without re-explaining it. "
            "Do NOT send anything — produce a draft for human review."
        )
