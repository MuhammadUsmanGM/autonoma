"""Base interface for connectors.

A connector is the glue between an external service (Google Calendar,
OneDrive, ...) and the agent. It is responsible for:

* declaring its OAuth scopes and the auth URL,
* exchanging callback codes for tokens via :mod:`autonoma.connectors.oauth`,
* persisting tokens through :class:`TokenStore`,
* reporting a :class:`ConnectorStatus`, and
* producing a list of :class:`BaseTool` instances the agent can call once
  the connector is connected.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal

from autonoma.executor.tools.base import BaseTool

AuthType = Literal["oauth2", "api_key"]
StatusValue = Literal["disconnected", "connecting", "connected", "expired", "error"]


@dataclass
class ConnectorStatus:
    """Snapshot of a connector's current state."""

    state: StatusValue = "disconnected"
    account_id: str = ""           # Stable identifier (email, oid, etc.)
    account_label: str = ""        # Human-readable (display name / email)
    scopes: list[str] = field(default_factory=list)
    expires_at: float = 0.0        # Unix epoch seconds; 0 = unknown
    last_error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "account_id": self.account_id,
            "account_label": self.account_label,
            "scopes": list(self.scopes),
            "expires_at": self.expires_at,
            "last_error": self.last_error,
        }


@dataclass
class ConnectorManifest:
    """Static description of a connector — surfaced to dashboard / TUI."""

    name: str
    display_name: str
    description: str
    auth_type: AuthType
    scopes: list[str]
    icon: str = ""  # Optional asset key the dashboard can map to an icon

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "auth_type": self.auth_type,
            "scopes": list(self.scopes),
            "icon": self.icon,
        }


class BaseConnector(ABC):
    """Abstract base for all connectors."""

    @property
    @abstractmethod
    def manifest(self) -> ConnectorManifest: ...

    @property
    def name(self) -> str:
        return self.manifest.name

    @abstractmethod
    def status(self) -> ConnectorStatus:
        """Return the live status — must be cheap (no network)."""
        ...

    @abstractmethod
    async def start_auth(self) -> str:
        """Begin the auth flow and return a URL the user should visit."""
        ...

    @abstractmethod
    async def complete_auth(self, params: dict[str, Any]) -> ConnectorStatus:
        """Exchange callback params (code, state, ...) for tokens."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Revoke / forget tokens for the currently connected account."""
        ...

    @abstractmethod
    def tools(self) -> list[BaseTool]:
        """Tools to expose while connected. Empty list when disconnected."""
        ...
