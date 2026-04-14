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

    raise ValueError(f"Unknown LLM provider: {config.provider}")
