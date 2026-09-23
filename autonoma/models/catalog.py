"""Supported LLM providers and their setup metadata."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderSpec:
    key: str
    label: str
    description: str
    env_key: str
    models: tuple[str, ...]


PROVIDER_SPECS: tuple[ProviderSpec, ...] = (
    ProviderSpec(
        "openrouter", "OpenRouter", "One key, many models", "OPENROUTER_API_KEY",
        ("anthropic/claude-sonnet-4.5", "openai/gpt-4o-mini", "google/gemini-2.0-flash-exp"),
    ),
    ProviderSpec(
        "anthropic", "Anthropic", "Direct Claude API", "ANTHROPIC_API_KEY",
        ("claude-sonnet-4-6", "claude-haiku-4-5-20251001", "claude-opus-4-6"),
    ),
    ProviderSpec(
        "google", "Google Gemini", "Direct Gemini API", "GOOGLE_API_KEY",
        ("gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"),
    ),
    ProviderSpec(
        "openai", "OpenAI", "Direct GPT API", "OPENAI_API_KEY",
        ("gpt-4o", "gpt-4o-mini", "gpt-4.1-mini"),
    ),
    ProviderSpec(
        "groq", "Groq", "Fast open-model inference", "GROQ_API_KEY",
        ("llama-3.3-70b-versatile", "llama-3.1-8b-instant", "openai/gpt-oss-120b"),
    ),
    ProviderSpec(
        "mistral", "Mistral", "Direct Mistral API", "MISTRAL_API_KEY",
        ("mistral-large-latest", "mistral-small-latest", "codestral-latest"),
    ),
)

PROVIDERS_BY_KEY = {spec.key: spec for spec in PROVIDER_SPECS}


def provider_spec(provider: str) -> ProviderSpec | None:
    """Return setup metadata for a provider alias."""
    return PROVIDERS_BY_KEY.get(provider.lower())