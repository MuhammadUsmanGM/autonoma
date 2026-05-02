"""Connectors — third-party integrations (Google Calendar, OneDrive, ...).

A connector wraps an external service: it owns the OAuth dance, persists its
token set, reports a status, and exposes one or more :class:`BaseTool`
instances that the agent can call once the user has connected an account.
"""

from autonoma.connectors.base import (
    BaseConnector,
    ConnectorManifest,
    ConnectorStatus,
)
from autonoma.connectors.registry import ConnectorRegistry

__all__ = [
    "BaseConnector",
    "ConnectorManifest",
    "ConnectorStatus",
    "ConnectorRegistry",
]
