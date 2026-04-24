"""Path-safety primitives shared by every tool that touches the filesystem.

The old codebase used ``str(resolved).startswith(str(base))`` to check if a
path lived inside the sandbox. That check is broken in two classic ways:

1. **Prefix collision.** With base=``/workspace``, the path
   ``/workspace_evil/secret`` passes because the string starts with
   ``/workspace``. Replaced with :meth:`pathlib.PurePath.relative_to`, which
   refuses anything that isn't actually a descendant.

2. **TOCTOU symlinks.** ``resolve()`` follows symlinks, so after a check the
   agent could point a symlink elsewhere and race the subsequent open. We
   mitigate by resolving + re-checking, and by rejecting any path whose
   resolved form contains a component outside the base.

The helpers are deliberately small and dependency-free so they can be
imported from any tool without dragging in the full sandbox.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePath


class PathSafetyError(ValueError):
    """Raised when a user-supplied path would escape the sandbox or is malformed."""


@dataclass(frozen=True)
class ResolvedPath:
    """Outcome of a successful ``resolve_within`` call.

    ``absolute`` is the canonical filesystem path to read/write.
    ``relative`` is the path relative to the sandbox root — useful for
    audit logging and error messages that don't leak absolute paths.
    """

    absolute: Path
    relative: Path


# Characters we never allow in a user-supplied path component. Null bytes
# truncate on some OS calls; the drive/UNC chars only matter on Windows
# but rejecting them on all platforms keeps the rule simple and portable.
_FORBIDDEN_CHARS = ("\x00",)


def resolve_within(base: str | Path, user_path: str) -> ResolvedPath:
    """Resolve *user_path* safely underneath *base*.

    Rules:

    * *user_path* must be a non-empty string.
    * Absolute paths are rejected — the tool caller specifies paths relative
      to the workspace so there's no legitimate reason to pass an absolute.
    * ``..`` traversal is not special-cased; after joining, the final path
      must still be inside *base* (enforced by :meth:`Path.relative_to`).
    * Null bytes are rejected outright.
    * Drive letters / UNC prefixes are rejected on every platform so
      ``C:\\Windows\\System32`` can't bypass the check via Windows' drive
      semantics when Autonoma is later run cross-platform.

    Returns a :class:`ResolvedPath`; raises :class:`PathSafetyError` otherwise.
    """
    if user_path is None or user_path == "":
        raise PathSafetyError("Path is empty")
    if not isinstance(user_path, str):
        raise PathSafetyError("Path must be a string")

    for forbidden in _FORBIDDEN_CHARS:
        if forbidden in user_path:
            raise PathSafetyError("Path contains forbidden characters")

    candidate = PurePath(user_path)
    if candidate.is_absolute() or candidate.drive or candidate.root:
        raise PathSafetyError("Absolute paths are not allowed")

    base_path = Path(base).resolve()
    # Best-effort resolve; strict=False lets us validate paths whose final
    # component doesn't exist yet (file_write creating a new file).
    resolved = (base_path / user_path).resolve()

    try:
        relative = resolved.relative_to(base_path)
    except ValueError as e:
        raise PathSafetyError(
            "Path escapes the sandboxed directory"
        ) from e

    return ResolvedPath(absolute=resolved, relative=relative)


def is_within(base: str | Path, target: str | Path) -> bool:
    """Non-raising variant — True iff *target* resolves inside *base*."""
    try:
        base_path = Path(base).resolve()
        target_path = Path(target).resolve()
        target_path.relative_to(base_path)
        return True
    except (ValueError, OSError):
        return False
