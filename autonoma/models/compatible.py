"""OpenAI-compatible provider adapter for OpenAI, Groq, and Mistral."""

from __future__ import annotations

from autonoma.models.openrouter import OpenRouterProvider


class CompatibleProvider(OpenRouterProvider):
    """Reuse the OpenAI-compatible translation with a provider-specific URL."""

    def __init__(self, api_key: str, model: str, base_url: str, name: str):
        super().__init__(api_key=api_key, model=model, app_name="Autonoma")
        self._client.base_url = base_url.rstrip("/") + "/"
        self._provider_name = name

    @property
    def name(self) -> str:
        return self._provider_name