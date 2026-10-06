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


# Newest / best first. Users can always type a custom model ID instead.
PROVIDER_SPECS: tuple[ProviderSpec, ...] = (
    ProviderSpec(
        "openrouter", "OpenRouter", "One key, many models", "OPENROUTER_API_KEY",
        (
            "anthropic/claude-opus-5.5", "anthropic/claude-sonnet-5.5",
            "openai/gpt-6-astra", "openai/gpt-6.1-sol",
            "google/gemini-3.1-pro-preview", "google/gemini-3.8-flash",
            "deepseek/deepseek-v4-pro", "deepseek/deepseek-flash",
            "meta-llama/llama-4-maverick", "qwen/qwen3-235b-a22b",
        ),
    ),
    ProviderSpec(
        "anthropic", "Anthropic", "Direct Claude API", "ANTHROPIC_API_KEY",
        (
            "claude-opus-5-5", "claude-sonnet-5-5", "claude-fable-5-1",
            "claude-haiku-4-5", "claude-opus-4-6", "claude-sonnet-4-6",
        ),
    ),
    ProviderSpec(
        "google", "Google Gemini", "Direct Gemini API", "GOOGLE_API_KEY",
        (
            "gemini-3.8-flash", "gemini-3.1-pro-preview", "gemini-3.7-flash",
            "gemini-3.5-flash", "gemini-3.5-flash-lite",
            "gemini-2.5-flash", "gemini-2.5-pro",
        ),
    ),
    ProviderSpec(
        "openai", "OpenAI", "Direct GPT API", "OPENAI_API_KEY",
        (
            "gpt-6-astra", "gpt-6.1-sol", "gpt-6-sol", "gpt-6-luna",
            "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna",
            "gpt-5.5", "gpt-5.4", "gpt-5.4-mini",
        ),
    ),
    ProviderSpec(
        "groq", "Groq", "Fast open-model inference", "GROQ_API_KEY",
        (
            "openai/gpt-oss-120b", "qwen/qwen3.6-27b", "openai/gpt-oss-20b",
            "llama-3.3-70b-versatile", "llama-3.1-8b-instant",
            "minimaxai/minimax-m2.7",
        ),
    ),
    ProviderSpec(
        "mistral", "Mistral", "Direct Mistral API", "MISTRAL_API_KEY",
        (
            "mistral-medium-latest", "mistral-large-latest",
            "mistral-small-latest", "codestral-latest",
            "ministral-8b-latest", "ministral-3b-latest",
            "devstral-small-latest",
        ),
    ),
    ProviderSpec(
        "deepseek", "DeepSeek", "Cheap OpenAI-compatible reasoning models",
        "DEEPSEEK_API_KEY",
        (
            # DeepSeek's API serves these four names only: two current models
            # plus two legacy aliases it still routes to V4.1 Flash.
            "deepseek-flash", "deepseek-v4-pro",
            "deepseek-v4-flash", "deepseek-v4-flash-vision-exp",
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
