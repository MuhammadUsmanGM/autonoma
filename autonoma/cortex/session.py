"""JSONL-based session management."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from autonoma.schema import SessionEntry

logger = logging.getLogger(__name__)


class SessionManager:
    """Manages conversation sessions as JSONL files."""

    def __init__(self, session_dir: str):
        self._dir = Path(session_dir)

    def _session_path(self, session_id: str) -> Path:
        return self._dir / f"{session_id}.jsonl"

    async def create_session(self, channel: str) -> str:
        """Create a new session, return session_id."""
        self._dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        session_id = f"{channel}_{ts}_{uuid4().hex[:6]}"
        # Create the empty file
        path = self._session_path(session_id)
        await asyncio.to_thread(path.touch)
        logger.info("Created session: %s", session_id)
        return session_id

    async def append(self, session_id: str, entry: SessionEntry) -> None:
        """Append a message to the session JSONL file."""
        path = self._session_path(session_id)
        line = entry.to_json() + "\n"
        await asyncio.to_thread(self._append_file, path, line)

    async def load_history(
        self, session_id: str, limit: int = 30
    ) -> list[SessionEntry]:
        """Load the last N entries from a session."""
        path = self._session_path(session_id)
        if not path.exists():
            return []

        text = await asyncio.to_thread(path.read_text, "utf-8")
        entries: list[SessionEntry] = []
        for line in text.strip().split("\n"):
            if not line.strip():
                continue
            try:
                entries.append(SessionEntry.from_json(line))
            except (json.JSONDecodeError, ValueError):
                # Skip corrupted lines (e.g. partial writes)
                logger.warning("Skipping unparseable session line in %s", session_id)
                continue

        return entries[-limit:]

    async def list_sessions(self) -> list[dict]:
        """List all sessions with basic metadata."""
        if not self._dir.exists():
            return []
        sessions = []
        for path in sorted(self._dir.glob("*.jsonl")):
            stat = path.stat()
            sessions.append(
                {
                    "id": path.stem,
                    "created": datetime.fromtimestamp(stat.st_ctime).isoformat(),
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    "size": stat.st_size,
                }
            )
        return sessions

    @staticmethod
    def _append_file(path: Path, content: str) -> None:
        with open(path, "a", encoding="utf-8") as f:
            f.write(content)
