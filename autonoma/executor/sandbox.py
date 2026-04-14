"""Sandbox — enforces permissions, paths, and timeouts for tool execution."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class Sandbox:
    """Security boundary for tool execution."""

    def __init__(
        self,
        allowed_dirs: list[str] | None = None,
        timeout: float = 30.0,
    ):
        self._allowed_dirs = [
            Path(d).resolve() for d in (allowed_dirs or ["workspace"])
        ]
        self.timeout = timeout

    def validate_file_path(self, path: str | Path) -> bool:
        """Check if a file path is within allowed directories."""
        resolved = Path(path).resolve()
        return any(
            str(resolved).startswith(str(allowed))
            for allowed in self._allowed_dirs
        )

    def get_allowed_dirs(self) -> list[Path]:
        return list(self._allowed_dirs)
