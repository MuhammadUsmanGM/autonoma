"""Runtime helpers for the TUI: log ring buffer + background agent runner."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections import deque
from pathlib import Path


class LogRingBuffer(logging.Handler):
    """Thread-safe bounded in-memory log handler.

    Stores the last N formatted records in a deque. The TUI renders
    a tail of this buffer and can stream it into a fullscreen log viewer.
    """

    def __init__(self, capacity: int = 2000) -> None:
        super().__init__()
        self._records: deque[logging.LogRecord] = deque(maxlen=capacity)
        self._lock = threading.Lock()
        self.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%H:%M:%S",
            )
        )

    def emit(self, record: logging.LogRecord) -> None:
        with self._lock:
            self._records.append(record)

    def tail(self, n: int) -> list[str]:
        """Return the last N formatted log lines."""
        with self._lock:
            records = list(self._records)[-n:]
        return [self.format(r) for r in records]

    def all(self) -> list[str]:
        """Return all buffered log lines."""
        with self._lock:
            records = list(self._records)
        return [self.format(r) for r in records]

    def clear(self) -> None:
        with self._lock:
            self._records.clear()


def install_logging(log_file: str | None = None, level: str = "INFO") -> LogRingBuffer:
    """Install a ring buffer + optional file handler on the root logger.

    Call this BEFORE importing / running autonoma.main.run — because
    `logging.basicConfig` in main.run is a no-op once handlers exist, so the
    agent's logs will route only to our handlers, keeping stdout clean for the TUI.
    """
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Clear any pre-existing stream handlers (basicConfig from a prior run)
    for h in list(root.handlers):
        if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler):
            root.removeHandler(h)

    ring = LogRingBuffer(capacity=2000)
    root.addHandler(ring)

    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
            )
        )
        root.addHandler(fh)

    return ring


class AgentRunner:
    """Manages the agent's asyncio loop in a background thread.

    Lifecycle:
        runner = AgentRunner()
        runner.start()         # non-blocking; returns once thread is up
        runner.is_running()    # -> bool
        runner.status()        # -> 'stopped' | 'starting' | 'running' | 'stopping' | 'error'
        runner.error()         # -> str | None
        runner.uptime()        # -> seconds since start, or 0 if not running
        runner.stop()          # blocks until the agent shuts down cleanly
    """

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task | None = None
        self._status: str = "stopped"
        self._error: str | None = None
        self._start_time: float = 0.0
        self._lock = threading.Lock()

    # ----- Public API -----

    def start(self) -> None:
        with self._lock:
            if self._status in ("starting", "running"):
                return
            self._status = "starting"
            self._error = None
            self._start_time = time.time()

        self._thread = threading.Thread(
            target=self._thread_main, name="autonoma-agent", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 15.0) -> None:
        with self._lock:
            if self._status == "stopped":
                return
            self._status = "stopping"
            loop = self._loop
            task = self._task

        if loop and task and not task.done():
            try:
                loop.call_soon_threadsafe(task.cancel)
            except RuntimeError:
                pass  # loop already closed

        if self._thread:
            self._thread.join(timeout=timeout)

        with self._lock:
            self._status = "stopped" if not self._error else "error"
            self._start_time = 0.0

    def is_running(self) -> bool:
        with self._lock:
            return self._status == "running"

    def status(self) -> str:
        with self._lock:
            return self._status

    def error(self) -> str | None:
        with self._lock:
            return self._error

    def uptime(self) -> int:
        with self._lock:
            if not self._start_time or self._status != "running":
                return 0
            return int(time.time() - self._start_time)

    # ----- Thread body -----

    def _thread_main(self) -> None:
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            with self._lock:
                self._loop = loop

            # Import lazily — config load, etc. should happen on the worker thread
            from autonoma.main import run

            task = loop.create_task(run())
            with self._lock:
                self._task = task
                self._status = "running"

            try:
                loop.run_until_complete(task)
            except (asyncio.CancelledError, KeyboardInterrupt):
                pass
            finally:
                # Let pending cleanup tasks finish
                try:
                    pending = asyncio.all_tasks(loop)
                    for t in pending:
                        t.cancel()
                    if pending:
                        loop.run_until_complete(
                            asyncio.gather(*pending, return_exceptions=True)
                        )
                except Exception:
                    pass
                loop.close()
        except SystemExit as e:
            with self._lock:
                self._error = f"agent exited with code {e.code}"
                self._status = "error"
        except Exception as e:
            with self._lock:
                self._error = f"{type(e).__name__}: {e}"
                self._status = "error"
        finally:
            with self._lock:
                self._loop = None
                self._task = None
                if self._status not in ("error",):
                    self._status = "stopped"
