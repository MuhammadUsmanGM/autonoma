"""File operation tools — read, write, and list files in the sandbox.

All path resolution goes through :func:`autonoma.executor.path_safety.resolve_within`
which fixes the earlier prefix-match bug that let ``../workspace_evil/secret``
escape a ``workspace``-rooted sandbox. Writes are additionally gated by an
extension denylist and a per-file size cap drawn from the sandbox config.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from autonoma.executor.path_safety import PathSafetyError, resolve_within
from autonoma.executor.sandbox import Sandbox
from autonoma.executor.tools.base import BaseTool, ToolPermission

logger = logging.getLogger(__name__)


from autonoma.observability.metrics import record_sandbox_denial as _record_denial


class _SandboxedFileTool(BaseTool):
    """Common base for file tools that share a sandbox instance."""

    def __init__(self, sandbox: Sandbox):
        self._sandbox = sandbox

    @property
    def _base_dir(self) -> Path:
        return self._sandbox.get_allowed_dirs()[0]

    def _resolve(self, rel_path: str, tool_name: str) -> Path | str:
        """Return a resolved, in-sandbox :class:`Path` — or an error string."""
        try:
            resolved = resolve_within(self._base_dir, rel_path)
        except PathSafetyError as e:
            logger.warning("%s denied: %s", tool_name, e)
            _record_denial(tool_name, str(e))
            return f"Error: {e}"
        return resolved.absolute


class FileReadTool(_SandboxedFileTool):
    """Read the contents of a file."""

    @property
    def name(self) -> str:
        return "file_read"

    @property
    def permissions(self) -> ToolPermission:
        return ToolPermission(
            level="safe", filesystem=True,
            description="Reads files within the sandboxed workspace directory.",
        )

    @property
    def description(self) -> str:
        return "Read the contents of a file. Path is relative to the workspace directory."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path relative to workspace (e.g., 'notes.txt')",
                },
            },
            "required": ["path"],
        }

    async def execute(self, params: dict[str, Any]) -> str:
        path = self._resolve(params.get("path", ""), "file_read")
        if isinstance(path, str):
            return path

        if not path.exists():
            return f"Error: File not found: {params['path']}"
        if not path.is_file():
            return f"Error: Not a file: {params['path']}"

        try:
            content = path.read_text(encoding="utf-8")
            if len(content) > 10_000:
                content = content[:10_000] + f"\n\n... (truncated, {len(content)} chars total)"
            return content
        except Exception as e:
            return f"Error reading file: {e}"


class FileWriteTool(_SandboxedFileTool):
    """Write content to a file."""

    @property
    def name(self) -> str:
        return "file_write"

    @property
    def permissions(self) -> ToolPermission:
        return ToolPermission(
            level="cautious", filesystem=True,
            description="Writes files within the sandboxed workspace directory.",
        )

    @property
    def description(self) -> str:
        return "Write content to a file. Creates the file if it doesn't exist. Path is relative to workspace."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path relative to workspace",
                },
                "content": {
                    "type": "string",
                    "description": "Content to write to the file",
                },
                "append": {
                    "type": "boolean",
                    "description": "If true, append instead of overwrite. Defaults to false.",
                },
            },
            "required": ["path", "content"],
        }

    async def execute(self, params: dict[str, Any]) -> str:
        rel = params.get("path", "")
        path = self._resolve(rel, "file_write")
        if isinstance(path, str):
            return path

        cfg = self._sandbox.config
        ext = path.suffix.lower()
        if ext in {e.lower() for e in cfg.write_denied_extensions}:
            _record_denial("file_write", f"denied extension {ext}")
            return f"Error: writing '{ext}' files is blocked by sandbox policy."

        content = params.get("content", "")
        if not isinstance(content, str):
            content = str(content)
        max_bytes = cfg.max_file_size_mb * 1024 * 1024
        if max_bytes > 0 and len(content.encode("utf-8", errors="replace")) > max_bytes:
            _record_denial("file_write", "content exceeds max_file_size_mb")
            return (
                f"Error: content exceeds max_file_size_mb "
                f"({cfg.max_file_size_mb} MiB) limit."
            )

        append = bool(params.get("append", False))

        try:
            # Re-resolve the *parent* after creating intermediate dirs so a
            # symlink planted between initial resolve and write can't redirect
            # us outside the sandbox. If resolution fails the second time we
            # bail out.
            path.parent.mkdir(parents=True, exist_ok=True)
            parent_resolved = path.parent.resolve()
            try:
                parent_resolved.relative_to(self._base_dir)
            except ValueError:
                _record_denial("file_write", "parent escaped after mkdir (symlink?)")
                return "Error: refused to write — parent directory escaped sandbox."

            mode = "a" if append else "w"
            with open(path, mode, encoding="utf-8") as f:
                f.write(content)
            action = "Appended to" if append else "Wrote"
            return f"{action} file: {rel} ({len(content)} chars)"
        except Exception as e:
            return f"Error writing file: {e}"


class FileListTool(_SandboxedFileTool):
    """List files in a directory."""

    @property
    def name(self) -> str:
        return "file_list"

    @property
    def permissions(self) -> ToolPermission:
        return ToolPermission(
            level="safe", filesystem=True,
            description="Lists files within the sandboxed workspace directory.",
        )

    @property
    def description(self) -> str:
        return "List files and directories in the workspace. Path is relative to workspace."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directory path relative to workspace. Defaults to root.",
                },
            },
        }

    async def execute(self, params: dict[str, Any]) -> str:
        rel = params.get("path", ".") or "."
        # Special-case "." / "" as the sandbox root.
        if rel in (".", "./", ""):
            target = self._base_dir
        else:
            resolved = self._resolve(rel, "file_list")
            if isinstance(resolved, str):
                return resolved
            target = resolved

        if not target.exists():
            return f"Error: Directory not found: {rel}"
        if not target.is_dir():
            return f"Error: Not a directory: {rel}"

        entries = []
        base = self._base_dir
        for item in sorted(target.iterdir()):
            try:
                rel_item = item.relative_to(base)
            except ValueError:
                # Should not happen post-resolve, but skip rather than leak
                # absolute paths if it does.
                continue
            if item.is_dir():
                entries.append(f"  {rel_item}/")
            else:
                try:
                    size = item.stat().st_size
                except OSError:
                    size = -1
                entries.append(f"  {rel_item}  ({size} bytes)")

        if not entries:
            return f"Directory is empty: {rel}"

        return f"Files in {rel}:\n" + "\n".join(entries)
