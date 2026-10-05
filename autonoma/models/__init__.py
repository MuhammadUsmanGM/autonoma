"""LLM provider abstraction layer."""

import inspect

from autonoma.config import LLMConfig
from autonoma.models.provider import LLMProvider
from autonoma.schema import LLMMessage


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

    if config.provider == "custom":
        from autonoma.models.compatible import CompatibleProvider

        if not config.base_url.strip():
            raise ValueError("A base URL is required for a custom provider.")
        return CompatibleProvider(
            api_key=config.api_key,
            model=config.model,
            base_url=config.base_url,
            name=config.provider_name.strip() or "custom",
        )

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


async def verify_model(config: LLMConfig) -> None:
    """Make one minimal request to confirm a key and model can be used."""
    provider = create_provider(config)
    try:
        await provider.chat(
            [LLMMessage(role="user", content="Reply with OK.")],
            temperature=0,
            max_tokens=1,
        )
    finally:
        client = getattr(provider, "_client", None)
        close = getattr(client, "aclose", None) or getattr(client, "close", None)
        if close is not None:
            result = close()
            if inspect.isawaitable(result):
                await result
