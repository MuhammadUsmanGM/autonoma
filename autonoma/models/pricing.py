"""Per-model LLM pricing — used to turn token counts into USD cost.

Prices are expressed per 1M tokens in USD and reflect public list pricing at
the time of writing. They are deliberately a plain dict rather than loaded
from config: users who want to override should edit this file or overlay a
key. Missing models fall through to ``(0.0, 0.0)`` so cost tracking never
crashes the loop — we'd rather show "$0.00" than drop a response.

The keys match exactly what a provider reports via its ``model`` response
field / what we pass in ``LLMConfig.model``. OpenRouter models keep their
``vendor/model`` slug; Anthropic-native models use the bare model ID.
"""

from __future__ import annotations

# (input_per_1m, output_per_1m) in USD.
MODEL_PRICING: dict[str, tuple[float, float]] = {
    # --- Anthropic (direct) ---
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-sonnet-4-5": (3.00, 15.00),
    "claude-haiku-4-5": (0.25, 1.25),
    "claude-haiku-4-5-20251001": (0.25, 1.25),
    "claude-opus-4-6": (15.00, 75.00),

    # --- OpenRouter slugs ---
    "anthropic/claude-sonnet-4.6": (3.00, 15.00),
    "anthropic/claude-sonnet-4.5": (3.00, 15.00),
    "anthropic/claude-haiku-4.5": (0.25, 1.25),
    "anthropic/claude-opus-4.6": (15.00, 75.00),
    "openai/gpt-4o": (2.50, 10.00),
    "openai/gpt-4o-mini": (0.15, 0.60),
    "openai/gpt-4-turbo": (10.00, 30.00),
    "google/gemini-2.0-flash-exp": (0.0, 0.0),   # free tier at time of writing
    "google/gemini-1.5-pro": (1.25, 5.00),
    "google/gemini-1.5-flash": (0.075, 0.30),
    "meta-llama/llama-3.1-70b-instruct": (0.52, 0.75),
    "meta-llama/llama-3.1-8b-instruct": (0.055, 0.055),
}


def price_for(model: str) -> tuple[float, float]:
    """Return (input_per_1m, output_per_1m) for *model*, or (0.0, 0.0) if unknown."""
    return MODEL_PRICING.get(model, (0.0, 0.0))


def cost_for(model: str, tokens_in: int, tokens_out: int) -> float:
    """Compute USD cost for a single call.

    Returns 0.0 when the model is unknown rather than raising — cost tracking
    is advisory, not load-bearing, so a missing entry should never take down
    the agent loop.
    """
    in_rate, out_rate = price_for(model)
    return (tokens_in * in_rate + tokens_out * out_rate) / 1_000_000.0
