"""Memory flush mechanism for safe shutdown."""

from __future__ import annotations

import logging

from autonoma.memory.store import MemoryStore

logger = logging.getLogger(__name__)


class MemoryFlusher:
    """Ensures memory is safely written to disk before shutdown."""

    def __init__(self, store: MemoryStore):
        self._store = store

    async def flush(self) -> None:
        """Force any pending writes to disk."""
        # In Phase 1, MemoryStore writes are immediate (no buffering).
        # This becomes critical in Phase 4 with vector compaction.
        logger.debug("Memory flush completed.")

    async def __aenter__(self) -> MemoryFlusher:
        return self

    async def __aexit__(self, *exc) -> None:
        await self.flush()
