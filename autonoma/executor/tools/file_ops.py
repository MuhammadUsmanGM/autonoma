"""File operation tools — read, write, and list files in workspace."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from autonoma.executor.tools.base import BaseTool


class FileReadTool(BaseTool):
    """Read the contents of a file."""

    def __init__(self, sandbox_dir: str = "workspace"):
        self._sandbox = Path(sandbox_dir).resolve()

    @property
    def name(self) -> str:
        return "file_read"

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
        path = self._resolve(params.get("path", ""))
        if isinstance(path, str):
            return path  # Error message

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

    def _resolve(self, rel_path: str) -> Path | str:
        if not rel_path:
            return "Error: No file path provided."
        resolved = (self._sandbox / rel_path).resolve()
        if not str(resolved).startswith(str(self._sandbox)):
            return "Error: Path is outside workspace directory."
        return resolved


class FileWriteTool(BaseTool):
    """Write content to a file."""

    def __init__(self, sandbox_dir: str = "workspace"):
        self._sandbox = Path(sandbox_dir).resolve()

    @property
    def name(self) -> str:
        return "file_write"

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
        path = self._resolve(params.get("path", ""))
        if isinstance(path, str):
            return path

        content = params.get("content", "")
        append = params.get("append", False)

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            mode = "a" if append else "w"
            with open(path, mode, encoding="utf-8") as f:
                f.write(content)
            action = "Appended to" if append else "Wrote"
            return f"{action} file: {params['path']} ({len(content)} chars)"
        except Exception as e:
            return f"Error writing file: {e}"

    def _resolve(self, rel_path: str) -> Path | str:
        if not rel_path:
            return "Error: No file path provided."
        resolved = (self._sandbox / rel_path).resolve()
        if not str(resolved).startswith(str(self._sandbox)):
            return "Error: Path is outside workspace directory."
        return resolved


class FileListTool(BaseTool):
    """List files in a directory."""

    def __init__(self, sandbox_dir: str = "workspace"):
        self._sandbox = Path(sandbox_dir).resolve()

    @property
    def name(self) -> str:
        return "file_list"

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
        rel = params.get("path", ".")
        target = (self._sandbox / rel).resolve()

        if not str(target).startswith(str(self._sandbox)):
            return "Error: Path is outside workspace directory."
        if not target.exists():
            return f"Error: Directory not found: {rel}"
        if not target.is_dir():
            return f"Error: Not a directory: {rel}"

        entries = []
        for item in sorted(target.iterdir()):
            rel_item = item.relative_to(self._sandbox)
            if item.is_dir():
                entries.append(f"  {rel_item}/")
            else:
                size = item.stat().st_size
                entries.append(f"  {rel_item}  ({size} bytes)")

        if not entries:
            return f"Directory is empty: {rel}"

        return f"Files in {rel}:\n" + "\n".join(entries)
