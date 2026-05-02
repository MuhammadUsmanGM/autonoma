"""Connector registry — owns connector instances and their exposed tools.

The registry is the single source of truth the gateway and TUI consult to
list available connectors, kick off OAuth flows, and refresh the agent's
tool list when a connector connects or disconnects.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from autonoma.connectors.base import BaseConnector, ConnectorStatus
from autonoma.executor.tools.base import BaseTool

logger = logging.getLogger(__name__)

ToolsChangedHook = Callable[[], None]


class ConnectorRegistry:
    """Holds connector instances; notifies listeners when tool set changes."""

    def __init__(self) -> None:
        self._connectors: dict[str, BaseConnector] = {}
        self._listeners: list[ToolsChangedHook] = []

    def register(self, connector: BaseConnector) -> None:
        self._connectors[connector.name] = connector
        logger.info("Registered connector: %s", connector.name)

    def get(self, name: str) -> BaseConnector | None:
        return self._connectors.get(name)

    def all(self) -> list[BaseConnector]:
        return list(self._connectors.values())

    def manifests(self) -> list[dict[str, Any]]:
        return [c.manifest.to_dict() for c in self._connectors.values()]

    def statuses(self) -> dict[str, ConnectorStatus]:
        return {c.name: c.status() for c in self._connectors.values()}

    def active_tools(self) -> list[BaseTool]:
        """All tools exposed by currently-connected connectors."""
        out: list[BaseTool] = []
        for c in self._connectors.values():
            if c.status().state == "connected":
                out.extend(c.tools())
        return out

    def on_tools_changed(self, hook: ToolsChangedHook) -> None:
        """Subscribe to tool-set changes (connect / disconnect)."""
        self._listeners.append(hook)

    def notify_tools_changed(self) -> None:
        """Connectors call this after a successful connect / disconnect."""
        for hook in list(self._listeners):
            try:
                hook()
            except Exception:
                logger.exception("Connector tools-changed listener failed")
