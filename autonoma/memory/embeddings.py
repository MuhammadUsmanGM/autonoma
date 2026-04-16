"""Embedding provider abstraction — pluggable backends for vector search."""

from __future__ import annotations

import hashlib
import json
import logging
from abc import ABC, abstractmethod
from pathlib import Path

logger = logging.getLogger(__name__)


class EmbeddingProvider(ABC):
    """Base class for embedding providers."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def dimensions(self) -> int: ...

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a batch of texts."""
        ...

    async def embed_one(self, text: str) -> list[float]:
        """Convenience: embed a single text."""
        results = await self.embed([text])
        return results[0]


class OpenAIEmbeddings(EmbeddingProvider):
    """OpenAI text-embedding-3-small via httpx (no openai SDK required)."""

    def __init__(self, api_key: str, model: str = "text-embedding-3-small"):
        self._api_key = api_key
        self._model = model
        self._dims = 1536

    @property
    def name(self) -> str:
        return "openai"

    @property
    def dimensions(self) -> int:
        return self._dims

    async def embed(self, texts: list[str]) -> list[list[float]]:
        import httpx

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://api.openai.com/v1/embeddings",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={"input": texts, "model": self._model},
            )
            resp.raise_for_status()
            data = resp.json()
            # Sort by index to ensure order matches input
            sorted_data = sorted(data["data"], key=lambda x: x["index"])
            return [item["embedding"] for item in sorted_data]


class LocalEmbeddings(EmbeddingProvider):
    """Simple local embeddings using TF-IDF style hashing.

    No external API needed — useful for offline/development.
    Not as good as neural embeddings but works without API keys.
    """

    def __init__(self, dimensions: int = 256):
        self._dims = dimensions

    @property
    def name(self) -> str:
        return "local"

    @property
    def dimensions(self) -> int:
        return self._dims

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._hash_embed(t) for t in texts]

    def _hash_embed(self, text: str) -> list[float]:
        """Generate a deterministic pseudo-embedding via feature hashing.

        Each word gets hashed to a dimension bucket and contributes +/-1
        based on a secondary hash. The result is L2-normalized.
        """
        import math

        vec = [0.0] * self._dims
        words = text.lower().split()
        if not words:
            return vec

        for word in words:
            # Primary hash: which dimension
            h1 = int(hashlib.md5(word.encode()).hexdigest(), 16)
            idx = h1 % self._dims
            # Secondary hash: sign
            h2 = int(hashlib.sha1(word.encode()).hexdigest(), 16)
            sign = 1.0 if h2 % 2 == 0 else -1.0
            vec[idx] += sign

        # L2 normalize
        norm = math.sqrt(sum(x * x for x in vec))
        if norm > 0:
            vec = [x / norm for x in vec]
        return vec


class EmbeddingCache:
    """Simple file-based cache for embeddings to avoid redundant API calls."""

    def __init__(self, cache_path: str | Path):
        self._path = Path(cache_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, list[float]] = {}
        self._load()

    def get(self, text: str) -> list[float] | None:
        key = self._key(text)
        return self._cache.get(key)

    def put(self, text: str, embedding: list[float]) -> None:
        key = self._key(text)
        self._cache[key] = embedding

    def save(self) -> None:
        try:
            self._path.write_text(json.dumps(self._cache), encoding="utf-8")
        except Exception as e:
            logger.warning("Failed to save embedding cache: %s", e)

    def _load(self) -> None:
        if self._path.exists():
            try:
                self._cache = json.loads(self._path.read_text("utf-8"))
            except Exception:
                self._cache = {}

    @staticmethod
    def _key(text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()[:16]


def create_embedding_provider(
    provider: str = "local", api_key: str = "", **kwargs
) -> EmbeddingProvider:
    """Factory for embedding providers."""
    if provider == "openai" and api_key:
        return OpenAIEmbeddings(api_key=api_key, **kwargs)
    return LocalEmbeddings(**kwargs)
