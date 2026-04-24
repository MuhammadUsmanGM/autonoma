"""Docker backend — scaffold only.

Selecting ``sandbox.backend: docker`` in ``autonoma.yaml`` reaches this
stub. It raises :class:`NotImplementedError` with instructions rather than
silently falling back to direct execution: an operator who asked for
container isolation should not get a process on the host instead.

Design sketch for the eventual implementation:

* One-shot containers per tool call (``docker run --rm``) — cold-start cost
  is the price of isolation.
* ``--network=none`` by default; respect ``SandboxConfig.allow_network``.
* ``--read-only`` root fs + a tmpfs ``/tmp`` + a bind-mount for the sandbox
  workspace dir.
* Drop all caps (``--cap-drop=ALL``), no-new-privileges, a non-root user.
* ``--memory``, ``--cpus``, ``--pids-limit`` from :class:`SandboxConfig`.
* Image choice is operator-configured; default suggestion is
  ``python:3.12-slim`` with ``coreutils`` installed.

Until this ships, operators who need containerization should run the whole
Autonoma process inside a container — the sandbox's rlimits + env scrubbing
still apply and there's no per-call startup penalty.
"""

from __future__ import annotations

from typing import Sequence

from autonoma.executor.backends.base import ExecutionBackend
from autonoma.executor.sandbox import SubprocessResult


_DOCS_URL = "https://github.com/anthropics/autonoma/issues (tag: sandbox-docker)"


class DockerBackend(ExecutionBackend):
    """Placeholder that fails loudly when selected."""

    name = "docker"

    def __init__(self) -> None:
        raise NotImplementedError(
            "Docker sandbox backend is not implemented yet. Either set "
            "`sandbox.backend: direct` in autonoma.yaml (default), or run "
            "Autonoma itself inside a container. Tracking / design: "
            f"{_DOCS_URL}"
        )

    async def run(
        self,
        argv: Sequence[str],
        *,
        cwd: str | None,
        env: dict[str, str],
        timeout: float,
        max_output_bytes: int,
        stdin: bytes | None = None,
    ) -> SubprocessResult:  # pragma: no cover — unreachable
        raise NotImplementedError
