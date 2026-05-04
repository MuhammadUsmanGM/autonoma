"""GitHub connector — OAuth App (authorization code).

GitHub user-to-server tokens for classic OAuth Apps don't expire by default
and don't issue refresh tokens, so the refresh path here is a no-op: we
keep the access token until the API returns 401, at which point the
status flips to ``expired`` and the user must reconnect from the dashboard.
"""

from __future__ import annotations

import logging
import time
import urllib.parse
import urllib.request
from typing import Any

from autonoma.config import GitHubConnectorConfig
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

NAME = "github"
AUTH_URL = "https://github.com/login/oauth/authorize"
TOKEN_URL = "https://github.com/login/oauth/access_token"
USER_URL = "https://api.github.com/user"
API_BASE = "https://api.github.com"


class GitHubConnector(BaseConnector):
    def __init__(
        self,
        cfg: GitHubConnectorConfig,
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
            # GitHub uses space-separated scopes (RFC 6749 default).
        )
        self._cached: TokenSet | None = self._tokens.load(NAME)

    # -- BaseConnector ----------------------------------------------------

    @property
    def manifest(self) -> ConnectorManifest:
        return ConnectorManifest(
            name=NAME,
            display_name="GitHub",
            description="Search issues, read PRs, list notifications, comment on threads.",
            auth_type="oauth2",
            scopes=list(self._cfg.scopes),
            icon="github",
        )

    def status(self) -> ConnectorStatus:
        ts = self._cached or self._tokens.load(NAME)
        if ts is None:
            return ConnectorStatus(state="disconnected")
        # GitHub tokens don't expire by default, but `expires_at` may be set
        # if the org enforces token expiration. Treat as expired only when
        # there's a positive expiry that's already passed.
        is_expired = ts.expires_at > 0 and ts.is_expired()
        state = "expired" if is_expired else "connected"
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
                "GitHub connector is missing client_id / client_secret. "
                "Register an OAuth App at https://github.com/settings/developers "
                "and set GITHUB_CLIENT_ID / GITHUB_CLIENT_SECRET."
            )
        # PKCE is optional on GitHub but supported; sending it costs nothing
        # and protects against authorization-code interception.
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
        # GitHub returns the granted scopes as a comma-separated string, not
        # the space-separated list other providers use. Persist whatever it
        # actually granted, not what we asked for.
        granted_scopes = _parse_github_scopes(
            token_resp.get("scope", ""), fallback=self._cfg.scopes
        )
        ts = TokenSet(
            connector=NAME,
            account_id="",
            account_label="",
            access_token=token_resp.get("access_token", ""),
            refresh_token=token_resp.get("refresh_token", ""),
            expires_at=token_resp.get("expires_at", 0.0),
            scopes=granted_scopes,
        )
        try:
            user = _api_get(USER_URL, ts.access_token)
            ts.account_id = str(user.get("id", "")) or user.get("login", "")
            ts.account_label = user.get("login", "") or user.get("name", "")
        except Exception:
            logger.warning("Could not fetch GitHub /user", exc_info=True)
        self._tokens.save(ts)
        self._cached = ts
        return self.status()

    async def disconnect(self) -> None:
        # Best-effort revocation via DELETE /applications/{client_id}/token
        # (basic-auth with client credentials). If it fails — wrong scope on
        # the OAuth App, network blip — fall through to local deletion so
        # the user's "disconnect" click is never silently a no-op.
        ts = self._cached or self._tokens.load(NAME)
        if ts and ts.access_token and self._cfg.client_id and self._cfg.client_secret:
            try:
                _revoke_github_token(
                    client_id=self._cfg.client_id,
                    client_secret=self._cfg.client_secret,
                    access_token=ts.access_token,
                )
            except Exception:
                logger.warning("GitHub token revocation failed", exc_info=True)
        self._tokens.delete(NAME)
        self._cached = None

    def tools(self) -> list[BaseTool]:
        if self._cached is None:
            self._cached = self._tokens.load(NAME)
        if self._cached is None:
            return []
        from autonoma.connectors.github.tools import (
            GitHubCommentTool,
            GitHubCreateIssueTool,
            GitHubGetIssueTool,
            GitHubGetPRTool,
            GitHubListNotificationsTool,
            GitHubSearchIssuesTool,
        )
        return [
            GitHubSearchIssuesTool(self),
            GitHubGetIssueTool(self),
            GitHubGetPRTool(self),
            GitHubListNotificationsTool(self),
            GitHubCommentTool(self),
            GitHubCreateIssueTool(self),
        ]

    # -- token freshness helper used by tools ----------------------------

    def access_token(self) -> str:
        ts = self._ensure_fresh()
        return ts.access_token

    def _ensure_fresh(self) -> TokenSet:
        ts = self._cached or self._tokens.load(NAME)
        if ts is None:
            raise RuntimeError("GitHub is not connected")
        # Classic OAuth Apps: tokens don't expire and there's no refresh.
        # Only attempt refresh if an expiry was set AND we have a refresh
        # token (GitHub Apps with user-to-server tokens, or future OAuth
        # changes). Otherwise return the cached token and let the API raise
        # 401 → ToolResult error if it's been revoked server-side.
        if ts.expires_at <= 0 or not ts.is_expired():
            self._cached = ts
            return ts
        if not ts.refresh_token:
            raise RuntimeError(
                "GitHub token expired and no refresh token available — "
                "reconnect from the dashboard."
            )
        refreshed = self._client.refresh(ts.refresh_token)
        ts.access_token = refreshed["access_token"]
        ts.expires_at = refreshed.get("expires_at", time.time() + 3600)
        if rt := refreshed.get("refresh_token"):
            ts.refresh_token = rt
        self._tokens.save(ts)
        self._cached = ts
        return ts


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_github_scopes(raw: str, fallback: list[str]) -> list[str]:
    """GitHub serialises granted scopes as ``"repo,read:org,..."``."""
    if not raw:
        return list(fallback)
    items = [s.strip() for s in raw.replace(" ", "").split(",") if s.strip()]
    return items or list(fallback)


def _api_get(url: str, bearer: str) -> dict[str, Any]:
    """Authenticated GET. Used during connect (status_url, /user)."""
    return http_json(
        url,
        bearer=bearer,
    )


def _revoke_github_token(client_id: str, client_secret: str, access_token: str) -> None:
    """DELETE /applications/{client_id}/token with HTTP basic auth.

    https://docs.github.com/en/rest/apps/oauth-applications#delete-an-app-token
    """
    import base64
    import json

    url = f"{API_BASE}/applications/{urllib.parse.quote(client_id, safe='')}/token"
    creds = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")
    body = json.dumps({"access_token": access_token}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="DELETE",
        headers={
            "Authorization": f"Basic {creds}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(req, timeout=20):
        pass
