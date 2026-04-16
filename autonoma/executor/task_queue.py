"""Async task queue with priority levels and persistence."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import IntEnum
from pathlib import Path
from typing import Any, Callable, Awaitable, Literal
from uuid import uuid4

logger = logging.getLogger(__name__)


class Priority(IntEnum):
    """Task priority — lower value = higher priority."""
    CRITICAL = 0
    HIGH = 1
    NORMAL = 2
    BACKGROUND = 3


TaskStatus = Literal["pending", "running", "completed", "failed", "cancelled"]


@dataclass
class TaskItem:
    """A queued task."""
    id: str
    name: str
    priority: int
    payload: dict[str, Any]
    status: TaskStatus = "pending"
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    started_at: str | None = None
    completed_at: str | None = None
    result: str | None = None
    error: str | None = None
    retries: int = 0
    max_retries: int = 2

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> TaskItem:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# Type for task handler coroutines
TaskHandler = Callable[[dict[str, Any]], Awaitable[str]]


class TaskQueue:
    """Priority-based async task queue with SQLite persistence."""

    def __init__(
        self,
        persist_path: str | None = None,
        max_concurrent: int = 3,
    ):
        self._queue: asyncio.PriorityQueue[tuple[int, float, TaskItem]] = (
            asyncio.PriorityQueue()
        )
        self._handlers: dict[str, TaskHandler] = {}
        self._tasks: dict[str, TaskItem] = {}  # id -> task
        self._persist_path = Path(persist_path) if persist_path else None
        self._max_concurrent = max_concurrent
        self._semaphore: asyncio.Semaphore | None = None
        self._workers: list[asyncio.Task] = []
        self._running = False

    def register_handler(self, task_name: str, handler: TaskHandler) -> None:
        """Register a handler for a named task type."""
        self._handlers[task_name] = handler
        logger.info("Task handler registered: %s", task_name)

    async def submit(
        self,
        name: str,
        payload: dict[str, Any] | None = None,
        priority: Priority = Priority.NORMAL,
        max_retries: int = 2,
    ) -> str:
        """Submit a task to the queue. Returns task ID."""
        task = TaskItem(
            id=uuid4().hex[:12],
            name=name,
            priority=int(priority),
            payload=payload or {},
            max_retries=max_retries,
        )
        self._tasks[task.id] = task
        # Priority queue sorts by (priority, timestamp) — lower = higher priority
        await self._queue.put((task.priority, time.monotonic(), task))
        self._persist()
        logger.info(
            "Task submitted: %s (id=%s, priority=%s)",
            name, task.id, Priority(priority).name,
        )
        return task.id

    async def start(self, num_workers: int | None = None) -> None:
        """Start worker coroutines to process the queue."""
        if self._running:
            return
        self._running = True
        n = num_workers or self._max_concurrent
        self._semaphore = asyncio.Semaphore(n)

        # Restore persisted tasks
        self._restore()

        for i in range(n):
            worker = asyncio.create_task(
                self._worker(i), name=f"task-worker-{i}"
            )
            self._workers.append(worker)
        logger.info("Task queue started with %d workers", n)

    async def stop(self) -> None:
        """Gracefully stop the queue — finish current tasks, cancel workers."""
        self._running = False
        for w in self._workers:
            w.cancel()
        if self._workers:
            await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        self._persist()
        logger.info("Task queue stopped")

    def get_task(self, task_id: str) -> TaskItem | None:
        return self._tasks.get(task_id)

    def list_tasks(
        self,
        status: TaskStatus | None = None,
        limit: int = 50,
    ) -> list[TaskItem]:
        """List tasks, optionally filtered by status."""
        tasks = sorted(
            self._tasks.values(),
            key=lambda t: (t.priority, t.created_at),
        )
        if status:
            tasks = [t for t in tasks if t.status == status]
        return tasks[:limit]

    def cancel_task(self, task_id: str) -> bool:
        """Cancel a pending task. Returns True if cancelled."""
        task = self._tasks.get(task_id)
        if task and task.status == "pending":
            task.status = "cancelled"
            task.completed_at = datetime.utcnow().isoformat()
            self._persist()
            return True
        return False

    def get_stats(self) -> dict[str, int]:
        counts: dict[str, int] = {
            "pending": 0, "running": 0, "completed": 0, "failed": 0, "cancelled": 0,
        }
        for t in self._tasks.values():
            counts[t.status] = counts.get(t.status, 0) + 1
        counts["total"] = len(self._tasks)
        return counts

    async def _worker(self, worker_id: int) -> None:
        """Worker loop — pull tasks from queue and execute."""
        while self._running:
            try:
                priority, _, task = await asyncio.wait_for(
                    self._queue.get(), timeout=2.0
                )
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            if task.status == "cancelled":
                continue

            handler = self._handlers.get(task.name)
            if not handler:
                task.status = "failed"
                task.error = f"No handler registered for task type: {task.name}"
                task.completed_at = datetime.utcnow().isoformat()
                logger.error("No handler for task %s (id=%s)", task.name, task.id)
                self._persist()
                continue

            task.status = "running"
            task.started_at = datetime.utcnow().isoformat()
            logger.info("Worker-%d executing: %s (id=%s)", worker_id, task.name, task.id)

            try:
                result = await handler(task.payload)
                task.status = "completed"
                task.result = result
                task.completed_at = datetime.utcnow().isoformat()
                logger.info("Task completed: %s (id=%s)", task.name, task.id)
            except Exception as e:
                task.retries += 1
                if task.retries <= task.max_retries:
                    logger.warning(
                        "Task %s failed (attempt %d/%d): %s — retrying",
                        task.id, task.retries, task.max_retries, e,
                    )
                    task.status = "pending"
                    await self._queue.put((task.priority, time.monotonic(), task))
                else:
                    task.status = "failed"
                    task.error = str(e)
                    task.completed_at = datetime.utcnow().isoformat()
                    logger.error(
                        "Task %s failed permanently: %s", task.id, e
                    )

            self._persist()

    def _persist(self) -> None:
        """Save incomplete tasks to disk for restart recovery."""
        if not self._persist_path:
            return
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            recoverable = [
                t.to_dict() for t in self._tasks.values()
                if t.status in ("pending", "running")
            ]
            self._persist_path.write_text(
                json.dumps(recoverable, indent=2), encoding="utf-8"
            )
        except Exception as e:
            logger.warning("Failed to persist task queue: %s", e)

    def _restore(self) -> None:
        """Restore tasks from disk on startup."""
        if not self._persist_path or not self._persist_path.exists():
            return
        try:
            data = json.loads(self._persist_path.read_text("utf-8"))
            restored = 0
            for item in data:
                task = TaskItem.from_dict(item)
                task.status = "pending"  # Reset running tasks to pending
                self._tasks[task.id] = task
                self._queue.put_nowait((task.priority, time.monotonic(), task))
                restored += 1
            if restored:
                logger.info("Restored %d tasks from disk", restored)
            # Clean up the persistence file
            self._persist_path.unlink(missing_ok=True)
        except Exception as e:
            logger.warning("Failed to restore task queue: %s", e)
