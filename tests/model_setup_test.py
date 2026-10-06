import asyncio
import unittest
from unittest.mock import patch

from autonoma.config import LLMConfig
from autonoma.models import create_provider, verify_model
from autonoma.models.catalog import PROVIDER_SPECS


class _FakeProvider:
    name = "fake"

    def __init__(self) -> None:
        self.closed = False

    async def chat(self, messages, **kwargs):
        self.messages = messages
        self.kwargs = kwargs
        return object()

    async def aclose(self) -> None:
        self.closed = True


class ProviderCatalogTest(unittest.TestCase):
    def test_builtin_providers_offer_more_model_choices(self) -> None:
        # DeepSeek publishes exactly four model names on its API — two current
        # models plus two legacy aliases it still routes — so the six-model
        # floor can't apply there.
        floor = {"deepseek": 4}
        for spec in PROVIDER_SPECS:
            if spec.key != "custom":
                with self.subTest(provider=spec.key):
                    self.assertGreaterEqual(
                        len(spec.models), floor.get(spec.key, 6)
                    )

    def test_custom_provider_is_available(self) -> None:
        custom = next(spec for spec in PROVIDER_SPECS if spec.key == "custom")
        self.assertEqual(custom.env_key, "AUTONOMA_LLM_API_KEY")


class CustomProviderTest(unittest.TestCase):
    def test_uses_name_model_and_base_url(self) -> None:
        config = LLMConfig(
            provider="custom",
            api_key="test-key",
            model="test-model",
            provider_name="Local AI",
            base_url="http://127.0.0.1:9000/v1",
        )
        provider = create_provider(config)
        try:
            self.assertEqual(provider.name, "Local AI")
            self.assertEqual(provider._model, "test-model")
            self.assertEqual(str(provider._client.base_url), "http://127.0.0.1:9000/v1/")
        finally:
            asyncio.run(provider._client.aclose())

    def test_custom_provider_requires_base_url(self) -> None:
        with self.assertRaisesRegex(ValueError, "base URL is required"):
            create_provider(LLMConfig(provider="custom", api_key="key"))

    def test_model_check_sends_one_short_request_and_closes_client(self) -> None:
        provider = _FakeProvider()
        config = LLMConfig(provider="custom", api_key="key", model="model")
        with patch("autonoma.models.create_provider", return_value=provider):
            asyncio.run(verify_model(config))

        self.assertEqual(provider.kwargs["max_tokens"], 1)
        self.assertEqual(provider.kwargs["temperature"], 0)
        self.assertTrue(provider.closed)