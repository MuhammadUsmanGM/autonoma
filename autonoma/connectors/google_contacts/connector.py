"""Google Contacts connector — Google People API (auth code + PKCE).

Uses the same Google OAuth client as Calendar/Meet. Token rows are scoped
by the connector ``name`` field, so connecting multiple Google connectors
results in independent ``TokenSet`` rows even when the underlying client
credentials are shared.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from autonoma.config import GoogleContactsConnectorConfig
from autonoma.connectors.base import (
    BaseConnector,
    ConnectorManifest,
    ConnectorStatus,
)
from autonoma.connectors.oauth import (
    OAuthClient,
    http_json,
    make_pkce_pair,
    sign_state,
    verify_state,
)
from autonoma.connectors.token_store import TokenSet, TokenStore
from autonoma.executor.tools.base import BaseTool

logger = logging.getLogger(__name__)

NAME = "google_contacts"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"


class GoogleContactsConnector(BaseConnector):
    def __init__(
        self,
        cfg: GoogleContactsConnectorConfig,
        token_store: TokenStore,
        redirect_uri: str,
        state_secret: bytes,
    ) -> None:
        self._cfg = cfg
        self._tokens = token_store
        self._state_secret = state_secret
        self._client = OAuthClient(
            name=NAME,
            auth_url=AUTH_URL,
            token_url=TOKEN_URL,
            client_id=cfg.client_id,
            client_secret=cfg.client_secret,
            redirect_uri=redirect_uri,
            scopes=cfg.scopes,
        )
        self._cached: TokenSet | None = self._tokens.load(NAME)

    @property
    def manifest(self) -> ConnectorManifest:
        return ConnectorManifest(
            name=NAME,
            display_name="Google Contacts",
            description=(
                "Search saved contacts and people you've recently emailed. "
                "Enriches inbound senders with their saved name, organisation, "
                "and bumps unknown senders to 'acquaintance' tier."
            ),
            auth_type="oauth2",
            scopes=list(self._cfg.scopes),
            icon="google-contacts",
        )

    def status(self) -> ConnectorStatus:
        ts = self._cached or self._tokens.load(NAME)
        if ts is None:
            return ConnectorStatus(state="disconnected")
        state = "expired" if ts.is_expired() and not ts.refresh_token else "connected"
        return ConnectorStatus(
            state=state,
            account_id=ts.account_id,
            account_label=ts.account_label,
            scopes=list(ts.scopes),
            expires_at=ts.expires_at,
        )

    async def start_auth(self) -> str:
        if not self._cfg.client_id or not self._cfg.client_secret:
            raise RuntimeError(
                "Google Contacts connector is missing client_id / client_secret. "
                "Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in your .env."
            )
        verifier, challenge = make_pkce_pair()
        state = sign_state(
            self._state_secret,
            {"connector": NAME, "verifier": verifier, "ts": int(time.time())},
        )
        return self._client.build_auth_url(state=state, code_challenge=challenge)

    async def complete_auth(self, params: dict[str, Any]) -> ConnectorStatus:
        code = params.get("code")
        state = params.get("state")
        if not code or not state:
            raise ValueError("OAuth callback missing code or state")
        payload = verify_state(self._state_secret, state)
        if payload.get("connector") != NAME:
            raise ValueError("State token does not match this connector")
        verifier = payload.get("verifier", "")
        token_resp = self._client.exchange_code(code=code, code_verifier=verifier)
        ts = TokenSet(
            connector=NAME,
            account_id="",
            account_label="",
            access_token=token_resp.get("access_token", ""),
            refresh_token=token_resp.get("refresh_token", ""),
            expires_at=token_resp.get(
                "expires_at", time.time() + float(token_resp.get("expires_in", 3600))
            ),
            scopes=list(self._cfg.scopes),
        )
        try:
            user = http_json(USERINFO_URL, bearer=ts.access_token)
            ts.account_id = user.get("sub", "") or user.get("email", "")
            ts.account_label = user.get("email", "") or user.get("name", "")
        except Exception:
            logger.warning("Could not fetch Google userinfo", exc_info=True)
        self._tokens.save(ts)
        self._cached = ts
        return self.status()

    async def disconnect(self) -> None:
        ts = self._cached or self._tokens.load(NAME)
        if ts and ts.refresh_token:
            try:
                http_json(
                    REVOKE_URL,
                    method="POST",
                    params={"token": ts.refresh_token},
                )
            except Exception:
                logger.warning("Google token revocation failed", exc_info=True)
        self._tokens.delete(NAME)
        self._cached = None

    def tools(self) -> list[BaseTool]:
        if self._cached is None:
            self._cached = self._tokens.load(NAME)
        if self._cached is None:
            return []
        from autonoma.connectors.google_contacts.tools import (
            ContactsGetTool,
            ContactsResolveTool,
            ContactsSearchTool,
        )
        return [
            ContactsSearchTool(self),
            ContactsGetTool(self),
            ContactsResolveTool(self),
        ]

    # -- token freshness helper used by tools / enricher -----------------

    def access_token(self) -> str:
        ts = self._ensure_fresh()
        return ts.access_token

    def is_connected(self) -> bool:
        return self.status().state == "connected"

    def _ensure_fresh(self) -> TokenSet:
        ts = self._cached or self._tokens.load(NAME)
        if ts is None:
            raise RuntimeError("Google Contacts is not connected")
        if not ts.is_expired():
            self._cached = ts
            return ts
        if not ts.refresh_token:
            raise RuntimeError("Google token expired and no refresh token available")
        refreshed = self._client.refresh(ts.refresh_token)
        ts.access_token = refreshed["access_token"]
        ts.expires_at = refreshed.get("expires_at", time.time() + 3600)
        if rt := refreshed.get("refresh_token"):
            ts.refresh_token = rt
        self._tokens.save(ts)
        self._cached = ts
        return ts
