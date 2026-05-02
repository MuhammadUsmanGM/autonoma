"""Encrypted token store for connectors.

Tokens (access + refresh) are persisted in ``workspace/connectors.db`` —
SQLite with one row per connector. We hold at most one account per
connector at a time; reconnecting with a different account replaces the
row.

The encryption key lives at ``workspace/.connector_key`` (chmod 600).
On first run the key is auto-generated. If ``cryptography`` is installed
we use Fernet (AES-128-CBC + HMAC-SHA256). Otherwise we fall back to a
stdlib-only encrypt-then-MAC scheme (HMAC-SHA256 derived keystream + a
separate HMAC tag) — adequate for at-rest token storage on a
single-tenant workstation, and the key file permissions remain the
primary defense in either mode.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:  # Optional — stronger primitives when available.
    from cryptography.fernet import Fernet, InvalidToken  # type: ignore

    _HAS_FERNET = True
except Exception:  # pragma: no cover — Termux / minimal env path.
    Fernet = None  # type: ignore[assignment]
    InvalidToken = Exception  # type: ignore[assignment,misc]
    _HAS_FERNET = False

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS connector_tokens (
    connector       TEXT PRIMARY KEY,
    account_id      TEXT NOT NULL,
    account_label   TEXT NOT NULL DEFAULT '',
    payload         BLOB NOT NULL,
    expires_at      REAL NOT NULL DEFAULT 0,
    scopes_json     TEXT NOT NULL DEFAULT '[]',
    created_at      REAL NOT NULL,
    updated_at      REAL NOT NULL
);
"""


@dataclass
class TokenSet:
    """A connector's token bundle as returned to callers (decrypted)."""

    connector: str
    account_id: str
    account_label: str = ""
    access_token: str = ""
    refresh_token: str = ""
    expires_at: float = 0.0
    scopes: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def is_expired(self, skew_seconds: float = 30.0) -> bool:
        if self.expires_at <= 0:
            return False
        return time.time() + skew_seconds >= self.expires_at


# ---------------------------------------------------------------------------
# Key management
# ---------------------------------------------------------------------------


def _ensure_key(key_path: Path) -> bytes:
    """Return the encryption key, generating one on first run.

    The key file is created with mode 0o600. On POSIX the parent directory
    must already exist (caller's responsibility).
    """
    if key_path.exists():
        data = key_path.read_bytes().strip()
        if not data:
            raise RuntimeError(f"Connector key file {key_path} is empty.")
        return data

    raw = secrets.token_bytes(32)
    key = base64.urlsafe_b64encode(raw)
    key_path.write_bytes(key)
    try:
        os.chmod(key_path, 0o600)
    except OSError:  # Windows / restricted FS — best-effort.
        logger.warning("Could not chmod 600 %s; ensure it is protected.", key_path)
    logger.info("Generated new connector encryption key at %s", key_path)
    return key


# ---------------------------------------------------------------------------
# Encryption primitives
# ---------------------------------------------------------------------------


def _encrypt(key: bytes, plaintext: bytes) -> bytes:
    if _HAS_FERNET:
        return Fernet(key).encrypt(plaintext)
    return _stdlib_encrypt(key, plaintext)


def _decrypt(key: bytes, blob: bytes) -> bytes:
    if _HAS_FERNET and blob.startswith(b"gAAAA"):  # Fernet magic prefix.
        return Fernet(key).decrypt(blob)
    return _stdlib_decrypt(key, blob)


# Stdlib fallback. Layout: b"v1$" | nonce(16) | ciphertext | mac(32).
# - keystream = HMAC-SHA256(key, nonce || counter) chained per 32-byte block.
# - mac = HMAC-SHA256(key, b"mac" || nonce || ciphertext).
# Encrypt-then-MAC; key is reused for both halves via domain-separated HMAC.

_FALLBACK_PREFIX = b"v1$"


def _stream(key: bytes, nonce: bytes, length: int) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < length:
        block = hmac.new(
            key,
            b"stream" + nonce + counter.to_bytes(8, "big"),
            hashlib.sha256,
        ).digest()
        out.extend(block)
        counter += 1
    return bytes(out[:length])


def _stdlib_encrypt(key: bytes, plaintext: bytes) -> bytes:
    nonce = secrets.token_bytes(16)
    keystream = _stream(key, nonce, len(plaintext))
    ciphertext = bytes(p ^ k for p, k in zip(plaintext, keystream))
    mac = hmac.new(key, b"mac" + nonce + ciphertext, hashlib.sha256).digest()
    return _FALLBACK_PREFIX + nonce + ciphertext + mac


def _stdlib_decrypt(key: bytes, blob: bytes) -> bytes:
    if not blob.startswith(_FALLBACK_PREFIX):
        raise ValueError("Unknown token blob format")
    body = blob[len(_FALLBACK_PREFIX):]
    if len(body) < 16 + 32:
        raise ValueError("Token blob truncated")
    nonce, rest = body[:16], body[16:]
    ciphertext, mac = rest[:-32], rest[-32:]
    expected = hmac.new(key, b"mac" + nonce + ciphertext, hashlib.sha256).digest()
    if not hmac.compare_digest(mac, expected):
        raise ValueError("Token MAC mismatch — file tampered or wrong key")
    keystream = _stream(key, nonce, len(ciphertext))
    return bytes(c ^ k for c, k in zip(ciphertext, keystream))


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class TokenStore:
    """SQLite-backed encrypted token store."""

    def __init__(
        self,
        db_path: str | Path = "workspace/connectors.db",
        key_path: str | Path = "workspace/.connector_key",
    ) -> None:
        self.db_path = Path(db_path)
        self.key_path = Path(key_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._key = _ensure_key(self.key_path)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # -- public API ---------------------------------------------------------

    def save(self, ts: TokenSet) -> None:
        payload = json.dumps(
            {
                "access_token": ts.access_token,
                "refresh_token": ts.refresh_token,
                "extra": ts.extra,
            }
        ).encode("utf-8")
        blob = _encrypt(self._key, payload)
        now = time.time()
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO connector_tokens
                    (connector, account_id, account_label, payload,
                     expires_at, scopes_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(connector) DO UPDATE SET
                    account_id    = excluded.account_id,
                    account_label = excluded.account_label,
                    payload       = excluded.payload,
                    expires_at    = excluded.expires_at,
                    scopes_json   = excluded.scopes_json,
                    updated_at    = excluded.updated_at
                """,
                (
                    ts.connector,
                    ts.account_id,
                    ts.account_label,
                    blob,
                    ts.expires_at,
                    json.dumps(ts.scopes),
                    now,
                    now,
                ),
            )

    def load(self, connector: str) -> TokenSet | None:
        row = self._conn.execute(
            """
            SELECT account_id, account_label, payload, expires_at, scopes_json
            FROM connector_tokens WHERE connector = ?
            """,
            (connector,),
        ).fetchone()
        if row is None:
            return None
        account_id, account_label, blob, expires_at, scopes_json = row
        try:
            payload = json.loads(_decrypt(self._key, blob).decode("utf-8"))
        except (InvalidToken, ValueError) as exc:
            logger.error("Failed to decrypt tokens for %s: %s", connector, exc)
            return None
        return TokenSet(
            connector=connector,
            account_id=account_id,
            account_label=account_label or "",
            access_token=payload.get("access_token", ""),
            refresh_token=payload.get("refresh_token", ""),
            expires_at=expires_at,
            scopes=json.loads(scopes_json or "[]"),
            extra=payload.get("extra", {}) or {},
        )

    def delete(self, connector: str) -> bool:
        with self._conn:
            cur = self._conn.execute(
                "DELETE FROM connector_tokens WHERE connector = ?",
                (connector,),
            )
        return cur.rowcount > 0

    def list_connected(self) -> list[str]:
        rows = self._conn.execute(
            "SELECT connector FROM connector_tokens"
        ).fetchall()
        return [r[0] for r in rows]

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass
