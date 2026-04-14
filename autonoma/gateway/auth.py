"""Token-based auth middleware (Phase 1: stub for loopback-only)."""

from __future__ import annotations


class AuthMiddleware:
    """Authenticate incoming connections. Phase 1: always accepts on loopback."""

    def __init__(self, token: str | None = None):
        self._token = token

    async def authenticate(self, headers: dict) -> bool:
        if self._token is None:
            return True
        return headers.get("Authorization") == f"Bearer {self._token}"
