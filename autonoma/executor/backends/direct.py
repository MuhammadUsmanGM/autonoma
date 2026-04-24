"""Direct backend — run children on the host process tree.

This is what :meth:`Sandbox.run_subprocess` already does inline. The class
exists so the backend selector in :mod:`executor.backends` has something to
return; consolidating the inline implementation here is a follow-up refactor
and explicitly out of scope for the initial scaffold.
"""

from __future__ import annotations

from typing import Sequence

from autonoma.executor.backends.base import ExecutionBackend
from autonoma.executor.sandbox import SubprocessResult


class DirectBackend(ExecutionBackend):
    """Marker for the in-process direct execution path.

    The actual execution lives in :meth:`Sandbox.run_subprocess`. When the
    multi-backend refactor lands, that method will delegate to
    :meth:`DirectBackend.run`.
    """

    name = "direct"

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
        raise NotImplementedError(
            "DirectBackend.run is a scaffold — execution currently lives in "
            "Sandbox.run_subprocess. Wire this up in the backend refactor."
        )
