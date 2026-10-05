"""Shared helpers for connector tool modules."""

from __future__ import annotations

import asyncio
from typing import Any, Callable


def to_thread(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Run a blocking callable on the default executor.

    Connector tool modules import this as ``_to_thread`` so their call sites
    read exactly as they did when each module carried its own copy.
    """
    return asyncio.get_event_loop().run_in_executor(None, lambda: fn(*args, **kwargs))
