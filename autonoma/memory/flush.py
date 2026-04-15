"""Memory flusher — consolidation on shutdown and periodic background task."""

from __future__ import annotations

import asyncio
import logging

from autonoma.memory.consolidation import MemoryConsolidator
from autonoma.memory.store import MemoryStore

logger = logging.getLogger(__name__)


class MemoryFlusher:
    """Memory consolidation and safe shutdown."""

    def __init__(
        self, store: MemoryStore, consolidation_interval: int = 3600
    ):
        self._store = store
        self._interval = consolidation_interval  # 0 = disabled
        self._consolidator: MemoryConsolidator | None = None
        self._task: asyncio.Task | None = None

    async def flush(self) -> None:
        """Run consolidation cycle and ensure all writes are committed."""
        if self._consolidator:
            stats = await asyncio.to_thread(self._consolidator.run_cycle)
            logger.info("Memory consolidation: %s", stats)
        logger.debug("Memory flush completed.")

    async def __aenter__(self) -> MemoryFlusher:
        # Initialize store (runs migration if needed)
        await self._store.initialize()

        # Create consolidator
        self._consolidator = MemoryConsolidator(
            self._store._db, str(self._store._workspace)
        )

        # Start periodic consolidation if enabled
        if self._interval > 0:
            self._task = asyncio.create_task(
                self._periodic_consolidation(),
                name="memory-consolidation",
            )
        return self

    async def __aexit__(self, *exc) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self.flush()

    async def _periodic_consolidation(self) -> None:
        """Background loop: run consolidation every N seconds."""
        while True:
            await asyncio.sleep(self._interval)
            try:
                await self.flush()
            except Exception:
                logger.exception("Periodic consolidation failed")
