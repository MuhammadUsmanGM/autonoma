"""LLM provider abstraction layer."""

from autonoma.config import LLMConfig
from autonoma.models.provider import LLMProvider


def create_provider(config: LLMConfig) -> LLMProvider:
    """Factory: create an LLM provider from config."""
    if config.provider in ("anthropic", "claude"):
        from autonoma.models.anthropic import AnthropicProvider

        return AnthropicProvider(api_key=config.api_key, model=config.model)

    if config.provider == "openrouter":
        from autonoma.models.openrouter import OpenRouterProvider

        return OpenRouterProvider(api_key=config.api_key, model=config.model)

    if config.provider == "google":
        from autonoma.models.google import GoogleProvider

        return GoogleProvider(api_key=config.api_key, model=config.model)

    compatible = {
        "openai": ("https://api.openai.com/v1", "openai"),
        "groq": ("https://api.groq.com/openai/v1", "groq"),
        "mistral": ("https://api.mistral.ai/v1", "mistral"),
    }
    if config.provider in compatible:
        from autonoma.models.compatible import CompatibleProvider

        base_url, name = compatible[config.provider]
        return CompatibleProvider(
            api_key=config.api_key,
            model=config.model,
            base_url=base_url,
            name=name,
        )

    raise ValueError(f"Unknown LLM provider: {config.provider}")
