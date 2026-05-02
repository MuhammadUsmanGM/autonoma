"""Shared OAuth2 helper used by every connector.

Generic enough for Google and Microsoft identity platforms — both expose
RFC 6749 authorization-code flow with PKCE (RFC 7636). Provider-specific
quirks (token refresh URL, userinfo endpoint, scope serialization) are
parameterized through :class:`OAuthClient`.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# PKCE + signed state
# ---------------------------------------------------------------------------


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def make_pkce_pair() -> tuple[str, str]:
    """Return ``(verifier, challenge)``. Challenge method is S256."""
    verifier = _b64url(secrets.token_bytes(64))[:96]
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def sign_state(secret: bytes, payload: dict[str, Any]) -> str:
    """Produce ``base64url(payload_json).base64url(hmac_sha256)``.

    State carries both the connector name and the PKCE verifier so the
    callback handler can look them up without server-side session state.
    """
    body = _b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = _b64url(hmac.new(secret, body.encode("ascii"), hashlib.sha256).digest())
    return f"{body}.{sig}"


def verify_state(secret: bytes, state: str) -> dict[str, Any]:
    try:
        body, sig = state.split(".", 1)
    except ValueError as exc:
        raise ValueError("Malformed state token") from exc
    expected = _b64url(hmac.new(secret, body.encode("ascii"), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        raise ValueError("State signature mismatch")
    pad = "=" * (-len(body) % 4)
    return json.loads(base64.urlsafe_b64decode(body + pad).decode("utf-8"))


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


@dataclass
class OAuthClient:
    """Provider-agnostic OAuth2 client (auth-code + PKCE)."""

    name: str
    auth_url: str
    token_url: str
    client_id: str
    client_secret: str
    redirect_uri: str
    scopes: list[str] = field(default_factory=list)
    scope_separator: str = " "
    extra_auth_params: dict[str, str] = field(default_factory=dict)

    # ---- authorization request ------------------------------------------

    def build_auth_url(self, state: str, code_challenge: str) -> str:
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": self.scope_separator.join(self.scopes),
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "access_type": "offline",  # Google: get a refresh token.
            "prompt": "consent",       # Force refresh token re-issue on reconnect.
        }
        params.update(self.extra_auth_params)
        return f"{self.auth_url}?{urllib.parse.urlencode(params)}"

    # ---- token endpoint -------------------------------------------------

    def exchange_code(self, code: str, code_verifier: str) -> dict[str, Any]:
        return self._post_token(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.redirect_uri,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "code_verifier": code_verifier,
            }
        )

    def refresh(self, refresh_token: str) -> dict[str, Any]:
        return self._post_token(
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            }
        )

    def _post_token(self, form: dict[str, str]) -> dict[str, Any]:
        body = urllib.parse.urlencode(form).encode("utf-8")
        req = urllib.request.Request(
            self.token_url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if "access_token" not in data:
            raise RuntimeError(f"Token endpoint did not return access_token: {data}")
        # Normalize expiry to absolute epoch.
        if "expires_in" in data and "expires_at" not in data:
            data["expires_at"] = time.time() + float(data["expires_in"])
        return data


# ---------------------------------------------------------------------------
# Generic JSON HTTP helper used by connector tools
# ---------------------------------------------------------------------------


def http_json(
    url: str,
    *,
    method: str = "GET",
    bearer: str | None = None,
    params: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
    timeout: float = 20.0,
) -> dict[str, Any]:
    """Minimal stdlib JSON HTTP client used by connector tools."""
    if params:
        url = f"{url}?{urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
    return json.loads(raw) if raw else {}
