"""Pre-agent triage — decide whether an inbound message deserves a reply.

Runs BEFORE the agent loop. Three layers, cheapest first:

* **Layer 1 — Rules**: deterministic checks on headers, sender patterns,
  and channel metadata. Free, instant, catches the bulk of "fool"
  behavior (replying to noreply addresses, newsletters, auto-confirms).
* **Layer 2 — LLM classifier (optional)**: a small/cheap model gets the
  subject + first 200 chars and returns an intent label. Only invoked
  when Layer 1 returns a low-confidence verdict and the operator has
  opted in via ``triage.llm_classifier_enabled``.
* **Cache**: per-sender LRU keyed by ``(channel, user_id)``. A newsletter
  from the same address within ``sender_cache_ttl`` reuses its decision.

Outcomes are richer than yes/no:

* ``reply``       — run the agent loop as today.
* ``acknowledge`` — short canned reply (confirmations).
* ``archive``     — silently log to memory, no reply (newsletters worth keeping).
* ``ignore``      — drop entirely.
* ``escalate``    — surface to the dashboard HUD for human triage.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from autonoma.config import TriageConfig
from autonoma.observability.metrics import triage_total
from autonoma.schema import Message

logger = logging.getLogger(__name__)


Decision = str  # "reply" | "acknowledge" | "archive" | "ignore" | "escalate"


@dataclass
class TriageDecision:
    decision: Decision
    reason: str
    confidence: float  # 0..1
    layer: str  # "rule" | "llm" | "cache" | "default"
    canned_reply: str | None = None  # used when decision == "acknowledge"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "decision": self.decision,
            "reason": self.reason,
            "confidence": self.confidence,
            "layer": self.layer,
            "metadata": self.metadata,
        }


# ---- Layer 1 patterns -------------------------------------------------------

# Local-part regex for noreply-style addresses (case-insensitive). Matches the
# canonical variants without being so loose it catches "reply@" or "preply@".
_NOREPLY_LOCAL = re.compile(
    r"^(?:no[\-_.]?reply|do[\-_.]?not[\-_.]?reply|donotreply|noreply|"
    r"mailer[\-_.]?daemon|postmaster|bounces?|notifications?|alerts?|"
    r"updates?|news|newsletter|marketing|info|support[\-_.]?bot)\b",
    re.IGNORECASE,
)

# Subject/body keywords that strongly imply transactional or marketing intent.
# These are signals, not verdicts — we combine them with header evidence.
_PROMO_KEYWORDS = re.compile(
    r"\b(unsubscribe|view in browser|view this email|"
    r"limited time offer|exclusive deal|sale ends|newsletter|"
    r"%\s*off|free shipping|webinar|promotional)\b",
    re.IGNORECASE,
)

_CONFIRMATION_KEYWORDS = re.compile(
    r"\b(your (order|booking|payment|appointment|reservation) "
    r"(has been |is )?confirmed|otp|verification code|"
    r"password reset|two[- ]factor|2fa code)\b",
    re.IGNORECASE,
)


# ---- Triage -----------------------------------------------------------------


class Triage:
    """Routes inbound messages through layered filters.

    The class is deliberately framework-light: it has no knowledge of the
    agent loop or channel adapters. Callers invoke ``classify(message)``
    and act on the returned ``TriageDecision``.
    """

    def __init__(
        self,
        config: TriageConfig,
        *,
        session_dir: Path | str | None = None,
        llm_classifier=None,  # async callable: (message) -> TriageDecision | None
    ):
        self._config = config
        self._llm_classifier = llm_classifier
        self._cache: dict[tuple[str, str], tuple[float, TriageDecision]] = {}
        self._audit_path: Path | None = None
        if session_dir:
            self._audit_path = Path(session_dir) / "triage.log"
            self._audit_path.parent.mkdir(parents=True, exist_ok=True)

    async def classify(self, message: Message) -> TriageDecision:
        """Return a triage decision for the given message."""
        if not self._config.enabled:
            return self._record(message, TriageDecision(
                decision="reply", reason="triage disabled",
                confidence=1.0, layer="default",
            ))

        cached = self._cache_get(message)
        if cached is not None:
            return self._record(message, TriageDecision(
                decision=cached.decision,
                reason=f"cached: {cached.reason}",
                confidence=cached.confidence,
                layer="cache",
                canned_reply=cached.canned_reply,
                metadata=cached.metadata,
            ))

        rule_decision = self._rule_check(message)
        if rule_decision is not None and rule_decision.confidence >= 0.8:
            self._cache_put(message, rule_decision)
            return self._record(message, rule_decision)

        if self._llm_classifier and self._config.llm_classifier_enabled:
            try:
                llm_decision = await self._llm_classifier(message)
                if llm_decision is not None:
                    self._cache_put(message, llm_decision)
                    return self._record(message, llm_decision)
            except Exception as exc:  # pragma: no cover — advisory
                logger.debug("Triage LLM classifier failed: %s", exc)

        # Fall through: low-confidence rule decision wins, else default reply.
        if rule_decision is not None:
            self._cache_put(message, rule_decision)
            return self._record(message, rule_decision)

        return self._record(message, TriageDecision(
            decision="reply", reason="no triage signal",
            confidence=0.5, layer="default",
        ))

    # ---- Layer 1 ------------------------------------------------------------

    def _rule_check(self, message: Message) -> TriageDecision | None:
        """Run deterministic rules. Returns None if nothing fired."""
        # Channel-specific signals first; they're the highest-precision.
        if message.channel == "gmail":
            decision = self._gmail_rules(message)
            if decision is not None:
                return decision

        # Cross-channel: noreply local-part on the user_id.
        local = (message.user_id or "").split("@", 1)[0]
        if local and _NOREPLY_LOCAL.match(local):
            return TriageDecision(
                decision="ignore",
                reason=f"noreply sender pattern: {local}",
                confidence=0.95,
                layer="rule",
            )

        # Group-chat hygiene for Telegram/Discord — only reply when addressed.
        if message.channel in {"telegram", "discord"}:
            md = message.metadata or {}
            if md.get("is_group") and not md.get("is_mention") and not md.get("is_reply_to_bot"):
                return TriageDecision(
                    decision="ignore",
                    reason="group message without mention",
                    confidence=0.9,
                    layer="rule",
                )

        # Last-resort body keyword check — only fires if BOTH the subject and
        # body look promotional. Confidence stays moderate so Layer 2 can
        # override when enabled.
        text = (message.metadata or {}).get("subject", "") + "\n" + (message.content or "")
        if _PROMO_KEYWORDS.search(text):
            return TriageDecision(
                decision="archive",
                reason="promotional keywords without bulk headers",
                confidence=0.6,
                layer="rule",
            )

        if _CONFIRMATION_KEYWORDS.search(text):
            return TriageDecision(
                decision="archive",
                reason="transactional confirmation",
                confidence=0.75,
                layer="rule",
            )

        return None

    def _gmail_rules(self, message: Message) -> TriageDecision | None:
        headers = (message.metadata or {}).get("headers", {}) or {}

        if headers.get("auto_submitted") and headers["auto_submitted"].lower() != "no":
            return TriageDecision(
                decision="ignore",
                reason=f"Auto-Submitted: {headers['auto_submitted']}",
                confidence=0.98, layer="rule",
            )

        precedence = (headers.get("precedence") or "").lower()
        if precedence in {"bulk", "list", "junk"}:
            return TriageDecision(
                decision="archive",
                reason=f"Precedence: {precedence}",
                confidence=0.95, layer="rule",
            )

        if headers.get("list_unsubscribe") or headers.get("list_id"):
            return TriageDecision(
                decision="archive",
                reason="List-Unsubscribe / List-Id header present (bulk mail)",
                confidence=0.95, layer="rule",
            )

        if headers.get("x_auto_response_suppress"):
            return TriageDecision(
                decision="ignore",
                reason="X-Auto-Response-Suppress requests no auto-reply",
                confidence=0.98, layer="rule",
            )

        return None

    # ---- Cache --------------------------------------------------------------

    def _cache_key(self, message: Message) -> tuple[str, str]:
        return (message.channel, (message.user_id or "").lower())

    def _cache_get(self, message: Message) -> TriageDecision | None:
        key = self._cache_key(message)
        entry = self._cache.get(key)
        if entry is None:
            return None
        ts, decision = entry
        if time.time() - ts > self._config.sender_cache_ttl:
            self._cache.pop(key, None)
            return None
        return decision

    def _cache_put(self, message: Message, decision: TriageDecision) -> None:
        # Only cache filter outcomes — never cache "reply" so a newsletter
        # sender who later sends a real personal email still gets through.
        if decision.decision in {"ignore", "archive"}:
            self._cache[self._cache_key(message)] = (time.time(), decision)

    # ---- Audit + metrics ----------------------------------------------------

    def _record(self, message: Message, decision: TriageDecision) -> TriageDecision:
        try:
            triage_total.inc(labels={
                "decision": decision.decision,
                "channel": message.channel or "unknown",
                "layer": decision.layer,
            })
        except Exception:  # pragma: no cover
            pass

        if self._audit_path is not None:
            try:
                line = json.dumps({
                    "ts": time.time(),
                    "channel": message.channel,
                    "user_id": message.user_id,
                    "content_hash": _hash_content(message.content),
                    **decision.to_dict(),
                })
                with open(self._audit_path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except Exception as exc:  # pragma: no cover — advisory
                logger.debug("Triage audit log write failed: %s", exc)

        logger.info(
            "Triage [%s/%s] %s: %s (conf=%.2f, layer=%s)",
            message.channel, message.user_id,
            decision.decision, decision.reason,
            decision.confidence, decision.layer,
        )
        return decision


def _hash_content(content: str) -> str:
    return hashlib.sha256((content or "").encode("utf-8")).hexdigest()[:16]
