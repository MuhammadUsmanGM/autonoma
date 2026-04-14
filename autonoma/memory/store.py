"""File-based memory store: MEMORY.md + daily logs + memory command extraction."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import date, datetime
from pathlib import Path

from autonoma.schema import Message

logger = logging.getLogger(__name__)

# Regex patterns for memory commands in LLM responses
REMEMBER_RE = re.compile(r"\[REMEMBER:\s*(.+?)\]", re.IGNORECASE)
FACT_RE = re.compile(r"\[FACT:\s*(.+?)\]", re.IGNORECASE)
PREFERENCE_RE = re.compile(r"\[PREFERENCE:\s*(.+?)\]", re.IGNORECASE)
ALL_TAGS_RE = re.compile(
    r"\[(?:REMEMBER|FACT|PREFERENCE):\s*.+?\]", re.IGNORECASE
)


class MemoryStore:
    """Read/write interface for file-based memory."""

    def __init__(self, workspace_dir: str):
        self._workspace = Path(workspace_dir)
        self._memory_file = self._workspace / "MEMORY.md"
        self._daily_dir = self._workspace / "memory"
        self._write_lock = asyncio.Lock()

    async def read_long_term(self) -> str:
        """Read MEMORY.md content."""
        if not self._memory_file.exists():
            return ""
        text = await asyncio.to_thread(self._memory_file.read_text, "utf-8")
        return text

    async def append_long_term(self, fact: str) -> None:
        """Append a fact to MEMORY.md."""
        async with self._write_lock:
            timestamp = datetime.utcnow().strftime("%Y-%m-%d")
            line = f"\n- [{timestamp}] {fact}\n"
            await asyncio.to_thread(self._append_file, self._memory_file, line)
        logger.info("Stored long-term memory: %s", fact[:80])

    async def read_daily_log(self, target_date: date | None = None) -> str:
        """Read a daily log file. Defaults to today."""
        d = target_date or date.today()
        path = self._daily_dir / f"{d.isoformat()}.md"
        if not path.exists():
            return ""
        return await asyncio.to_thread(path.read_text, "utf-8")

    async def append_daily_log(self, entry: str) -> None:
        """Append an entry to today's daily log."""
        async with self._write_lock:
            self._daily_dir.mkdir(parents=True, exist_ok=True)
            path = self._daily_dir / f"{date.today().isoformat()}.md"

            if not path.exists():
                header = f"# Daily Log — {date.today().isoformat()}\n\n"
                await asyncio.to_thread(self._write_file, path, header)

            timestamp = datetime.utcnow().strftime("%H:%M")
            line = f"- [{timestamp}] {entry}\n"
            await asyncio.to_thread(self._append_file, path, line)

    async def process_memory_commands(
        self, response: str, message: Message
    ) -> str:
        """
        Extract [REMEMBER:], [FACT:], [PREFERENCE:] tags from LLM response.
        Store them, then return the cleaned response with tags stripped.
        """
        # Extract and store REMEMBER tags
        for match in REMEMBER_RE.finditer(response):
            fact = match.group(1).strip()
            await self.append_long_term(fact)
            await self.append_daily_log(f"Remembered: {fact}")

        # Extract and store FACT tags
        for match in FACT_RE.finditer(response):
            fact = match.group(1).strip()
            await self.append_long_term(f"[Fact] {fact}")
            await self.append_daily_log(f"Learned fact: {fact}")

        # Extract and store PREFERENCE tags
        for match in PREFERENCE_RE.finditer(response):
            pref = match.group(1).strip()
            await self.append_long_term(f"[Preference] {pref}")
            await self.append_daily_log(f"Preference noted: {pref}")

        # Strip all memory tags from the visible response
        cleaned = ALL_TAGS_RE.sub("", response).strip()
        # Clean up extra whitespace left by tag removal
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned

    async def get_memory_context(self) -> str:
        """Build the memory context string for prompt assembly."""
        long_term = await self.read_long_term()
        # Strip the header line from MEMORY.md for context injection
        lines = long_term.strip().split("\n")
        facts = [l for l in lines if l.startswith("- ")]
        if not facts:
            return "(No stored memories yet.)"
        return "\n".join(facts)

    async def get_daily_context(self) -> str:
        """Get today's daily log for context injection."""
        log = await self.read_daily_log()
        if not log.strip():
            return "(No activity logged today.)"
        return log

    @staticmethod
    def _append_file(path: Path, content: str) -> None:
        with open(path, "a", encoding="utf-8") as f:
            f.write(content)

    @staticmethod
    def _write_file(path: Path, content: str) -> None:
        path.write_text(content, encoding="utf-8")
