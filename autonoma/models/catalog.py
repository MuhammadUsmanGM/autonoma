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
        (
            "anthropic/claude-sonnet-4.5", "anthropic/claude-haiku-4.5",
            "anthropic/claude-opus-4.1", "openai/gpt-4.1",
            "openai/gpt-4.1-mini", "openai/gpt-4o", "openai/gpt-4o-mini",
            "google/gemini-2.5-pro", "google/gemini-2.5-flash",
            "deepseek/deepseek-r1", "meta-llama/llama-4-maverick",
            "qwen/qwen3-235b-a22b",
        ),
    ),
    ProviderSpec(
        "anthropic", "Anthropic", "Direct Claude API", "ANTHROPIC_API_KEY",
        (
            "claude-sonnet-4-6", "claude-sonnet-4-5",
            "claude-haiku-4-5-20251001", "claude-haiku-4-5",
            "claude-opus-4-6", "claude-opus-4-5",
        ),
    ),
    ProviderSpec(
        "google", "Google Gemini", "Direct Gemini API", "GOOGLE_API_KEY",
        (
            "gemini-2.5-flash", "gemini-2.5-flash-lite",
            "gemini-2.5-pro", "gemini-2.0-flash",
            "gemini-2.0-flash-lite", "gemini-1.5-pro",
            "gemini-1.5-flash",
        ),
    ),
    ProviderSpec(
        "openai", "OpenAI", "Direct GPT API", "OPENAI_API_KEY",
        (
            "gpt-4.1", "gpt-4.1-mini", "gpt-4.1-nano",
            "gpt-4o", "gpt-4o-mini", "o3", "o3-mini", "o4-mini",
        ),
    ),
    ProviderSpec(
        "groq", "Groq", "Fast open-model inference", "GROQ_API_KEY",
        (
            "llama-3.3-70b-versatile", "llama-3.1-8b-instant",
            "openai/gpt-oss-120b", "openai/gpt-oss-20b",
            "qwen/qwen3-32b", "meta-llama/llama-4-scout-17b-16e-instruct",
        ),
    ),
    ProviderSpec(
        "mistral", "Mistral", "Direct Mistral API", "MISTRAL_API_KEY",
        (
            "mistral-large-latest", "mistral-medium-latest",
            "mistral-small-latest", "ministral-8b-latest",
            "ministral-3b-latest", "codestral-latest", "devstral-small-latest",
        ),
    ),
    ProviderSpec(
        "custom", "Custom provider", "OpenAI-compatible API", "AUTONOMA_LLM_API_KEY",
        (),
    ),
)

PROVIDERS_BY_KEY = {spec.key: spec for spec in PROVIDER_SPECS}


def provider_spec(provider: str) -> ProviderSpec | None:
    """Return setup metadata for a provider alias."""
    return PROVIDERS_BY_KEY.get(provider.lower())