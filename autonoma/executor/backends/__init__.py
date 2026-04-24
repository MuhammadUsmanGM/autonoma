"""Execution backends for the sandbox.

A backend is the layer that actually spawns tool subprocesses. Today only
the ``direct`` backend is wired in — it runs children on the host with
env scrubbing and POSIX rlimits (see :class:`autonoma.executor.sandbox.Sandbox`).

The ``docker`` backend is scaffolded but not implemented: picking it in
``autonoma.yaml`` will raise a clear error at startup pointing to the
implementation ticket. Operators who need stronger isolation today should
run Autonoma itself inside a container rather than waiting on this.

The indirection exists so we can grow the set (Firejail, gVisor, WASM, a
remote executor) without reshaping :class:`Sandbox` every time.
"""

from __future__ import annotations

from autonoma.executor.backends.base import ExecutionBackend
from autonoma.executor.backends.direct import DirectBackend
from autonoma.executor.backends.docker import DockerBackend

__all__ = ["ExecutionBackend", "DirectBackend", "DockerBackend", "get_backend"]


def get_backend(name: str) -> type[ExecutionBackend]:
    """Resolve a backend name to its implementation class.

    Raises :class:`ValueError` for unknown names so misconfigured YAML fails
    at startup rather than on first tool call.
    """
    name = (name or "direct").lower()
    if name == "direct":
        return DirectBackend
    if name == "docker":
        return DockerBackend
    raise ValueError(
        f"Unknown sandbox backend: {name!r}. Supported: 'direct', 'docker'."
    )
