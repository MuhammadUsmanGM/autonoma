"""OneDrive connector — Microsoft Graph (auth code + PKCE, common tenant)."""

from __future__ import annotations

import logging
import time
from typing import Any

from autonoma.config import OneDriveConnectorConfig
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

NAME = "onedrive"
ME_URL = "https://graph.microsoft.com/v1.0/me"


def _auth_url(tenant: str) -> str:
    return f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize"


def _token_url(tenant: str) -> str:
    return f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"


class OneDriveConnector(BaseConnector):
    def __init__(
        self,
        cfg: OneDriveConnectorConfig,
        token_store: TokenStore,
        redirect_uri: str,
        state_secret: bytes,
    ) -> None:
        self._cfg = cfg
        self._tokens = token_store
        self._state_secret = state_secret
        self._client = OAuthClient(
            name=NAME,
            auth_url=_auth_url(cfg.tenant),
            token_url=_token_url(cfg.tenant),
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
            display_name="OneDrive",
            description="List, download, and upload files in the user's OneDrive.",
            auth_type="oauth2",
            scopes=list(self._cfg.scopes),
            icon="onedrive",
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
                "OneDrive connector is missing client_id / client_secret. "
                "Set MS_CLIENT_ID and MS_CLIENT_SECRET in your .env."
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
            access_token=token_resp.get("access_token", ""),
            refresh_token=token_resp.get("refresh_token", ""),
            expires_at=token_resp.get("expires_at", time.time() + 3600),
            scopes=list(self._cfg.scopes),
        )
        try:
            me = http_json(ME_URL, bearer=ts.access_token)
            ts.account_id = me.get("id", "") or me.get("userPrincipalName", "")
            ts.account_label = me.get("userPrincipalName", "") or me.get("displayName", "")
        except Exception:
            logger.warning("Could not fetch Microsoft Graph /me", exc_info=True)
        self._tokens.save(ts)
        self._cached = ts
        return self.status()

    async def disconnect(self) -> None:
        # Microsoft does not expose a public token-revocation endpoint for
        # public clients; deleting local tokens is the supported sign-out.
        self._tokens.delete(NAME)
        self._cached = None

    def tools(self) -> list[BaseTool]:
        if self._cached is None:
            self._cached = self._tokens.load(NAME)
        if self._cached is None:
            return []
        from autonoma.connectors.onedrive.tools import (
            OneDriveDownloadTool,
            OneDriveListTool,
            OneDriveUploadTool,
        )
        return [
            OneDriveListTool(self),
            OneDriveDownloadTool(self),
            OneDriveUploadTool(self),
        ]

    def access_token(self) -> str:
        ts = self._ensure_fresh()
        return ts.access_token

    def _ensure_fresh(self) -> TokenSet:
        ts = self._cached or self._tokens.load(NAME)
        if ts is None:
            raise RuntimeError("OneDrive is not connected")
        if not ts.is_expired():
            self._cached = ts
            return ts
        if not ts.refresh_token:
            raise RuntimeError("Microsoft token expired and no refresh token available")
        refreshed = self._client.refresh(ts.refresh_token)
        ts.access_token = refreshed["access_token"]
        ts.expires_at = refreshed.get("expires_at", time.time() + 3600)
        if rt := refreshed.get("refresh_token"):
            ts.refresh_token = rt
        self._tokens.save(ts)
        self._cached = ts
        return ts
