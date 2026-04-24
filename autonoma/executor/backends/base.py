"""Backend abstract base — the contract every execution backend honors.

A backend receives an already-policy-checked argv list from
:class:`autonoma.executor.sandbox.Sandbox` and is responsible for running it
with the requested env and working directory. Policy (allowlists, rlimits,
output caps, timeouts) stays in the sandbox so a new backend only has to
decide *where* the process runs — inside a container, under Firejail, on a
remote worker — not *what* is safe.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Sequence

from autonoma.executor.sandbox import SubprocessResult


class ExecutionBackend(ABC):
    """Interface for sandbox execution backends."""

    name: str = "abstract"

    @abstractmethod
    async def run(
        self,
        argv: Sequence[str],
        *,
        cwd: str | None,
        env: dict[str, str],
        timeout: float,
        max_output_bytes: int,
        stdin: bytes | None = None,
    ) -> SubprocessResult:
        """Run *argv* and return a :class:`SubprocessResult`.

        Implementations must honor ``timeout`` (wall-clock kill) and
        ``max_output_bytes`` (combined stdout+stderr cap). Environment
        scrubbing has already been done by the sandbox — pass ``env`` through
        verbatim.
        """
        raise NotImplementedError
