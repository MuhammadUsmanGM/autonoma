"""Google Meet connector — Meet REST API v2 (auth code + PKCE).

Reuses the same Google OAuth client as Calendar/Contacts. The Meet API
itself doesn't expose a "create meeting" endpoint — meetings are still
created as Calendar events with ``conferenceData.createRequest``. The
``meet_create_link`` tool uses Calendar for that step, so users typically
connect Calendar + Meet together.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from autonoma.config import GoogleMeetConnectorConfig
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

NAME = "google_meet"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"


class GoogleMeetConnector(BaseConnector):
    def __init__(
        self,
        cfg: GoogleMeetConnectorConfig,
        token_store: TokenStore,
        redirect_uri: str,
        state_secret: bytes,
        # Soft dependency: the Calendar connector handles meet-link creation
        # (Meet REST API has no "create event" endpoint). Optional — the
        # transcript / list tools work without it.
        calendar_connector: Any | None = None,
        # Optional integration hooks: when transcripts are fetched, scan for
        # action items and emit them into the conversation state machine.
        contact_store: Any | None = None,
        state_store: Any | None = None,
    ) -> None:
        self._cfg = cfg
        self._tokens = token_store
        self._state_secret = state_secret
        self._calendar = calendar_connector
        self._contact_store = contact_store
        self._state_store = state_store
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
            display_name="Google Meet",
            description=(
                "List recent Meet conferences, fetch transcripts, and create new "
                "Meet links via Calendar. Action items in transcripts can auto-emit "
                "follow-up reminders."
            ),
            auth_type="oauth2",
            scopes=list(self._cfg.scopes),
            icon="google-meet",
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
                "Google Meet connector is missing client_id / client_secret. "
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
        from autonoma.connectors.google_meet.tools import (
            MeetCreateLinkTool,
            MeetGetTranscriptTool,
            MeetListConferencesTool,
        )
        return [
            MeetListConferencesTool(self),
            MeetGetTranscriptTool(self),
            MeetCreateLinkTool(self),
        ]

    # -- helpers for tools ------------------------------------------------

    def access_token(self) -> str:
        ts = self._ensure_fresh()
        return ts.access_token

    def calendar_connector(self) -> Any | None:
        return self._calendar

    def state_store(self):  # noqa: D401 — simple accessor
        return self._state_store

    def contact_store(self):
        return self._contact_store

    def extract_action_items_enabled(self) -> bool:
        return bool(self._cfg.extract_action_items)

    def _ensure_fresh(self) -> TokenSet:
        ts = self._cached or self._tokens.load(NAME)
        if ts is None:
            raise RuntimeError("Google Meet is not connected")
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
