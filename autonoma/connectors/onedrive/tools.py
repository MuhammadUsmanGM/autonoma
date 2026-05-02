"""Tools backed by the OneDrive connector (Microsoft Graph)."""

from __future__ import annotations

import asyncio
import json
import urllib.parse
import urllib.request
from typing import TYPE_CHECKING, Any

from autonoma.connectors.oauth import http_json
from autonoma.executor.path_safety import resolve_within
from autonoma.executor.tools.base import BaseTool, ToolPermission

if TYPE_CHECKING:
    from autonoma.connectors.onedrive.connector import OneDriveConnector

DRIVE_ROOT = "https://graph.microsoft.com/v1.0/me/drive/root"


def _perm(filesystem: bool = False) -> ToolPermission:
    return ToolPermission(
        level="cautious",
        network=True,
        filesystem=filesystem,
        external_api=True,
        secrets=True,
        description="Calls Microsoft Graph (OneDrive) on behalf of a connected account.",
    )


def _to_thread(fn, *args, **kwargs):
    return asyncio.get_event_loop().run_in_executor(None, lambda: fn(*args, **kwargs))


class _BaseOneDriveTool(BaseTool):
    def __init__(self, connector: "OneDriveConnector") -> None:
        self._connector = connector


class OneDriveListTool(_BaseOneDriveTool):
    @property
    def name(self) -> str:
        return "onedrive_list"

    @property
    def description(self) -> str:
        return "List files/folders in a OneDrive folder. Path is relative to the drive root."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "default": "", "description": "Folder path, e.g. 'Documents/Reports'"},
                "top": {"type": "integer", "default": 50, "minimum": 1, "maximum": 200},
            },
        }

    @property
    def permissions(self) -> ToolPermission:
        return _perm()

    async def execute(self, params: dict[str, Any]) -> str:
        path = (params.get("path") or "").strip("/")
        url = DRIVE_ROOT + (f":/{urllib.parse.quote(path)}:/children" if path else "/children")
        token = self._connector.access_token()
        resp = await _to_thread(
            http_json,
            url,
            bearer=token,
            params={"$top": int(params.get("top", 50))},
        )
        items = resp.get("value", [])
        if not items:
            return f"(empty) {path or '/'}"
        lines = [f"{len(items)} item(s) in /{path}:"]
        for it in items:
            kind = "DIR " if "folder" in it else "FILE"
            size = it.get("size", 0)
            lines.append(f"- {kind} {it.get('name','?')}  ({size} bytes)")
        return "\n".join(lines)


class OneDriveDownloadTool(_BaseOneDriveTool):
    @property
    def name(self) -> str:
        return "onedrive_download"

    @property
    def description(self) -> str:
        return "Download a OneDrive file into the local workspace."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "remote_path": {"type": "string", "description": "Path on OneDrive, e.g. 'Documents/note.txt'"},
                "local_path": {"type": "string", "description": "Path inside workspace/ to write to"},
            },
            "required": ["remote_path", "local_path"],
        }

    @property
    def permissions(self) -> ToolPermission:
        return _perm(filesystem=True)

    async def execute(self, params: dict[str, Any]) -> str:
        remote = params["remote_path"].strip("/")
        target = resolve_within("workspace", params["local_path"])
        token = self._connector.access_token()
        url = DRIVE_ROOT + f":/{urllib.parse.quote(remote)}:/content"
        data = await _to_thread(_download_bytes, url, token)
        target.absolute.parent.mkdir(parents=True, exist_ok=True)
        target.absolute.write_bytes(data)
        return f"Downloaded {remote} → {target.relative} ({len(data)} bytes)"


class OneDriveUploadTool(_BaseOneDriveTool):
    @property
    def name(self) -> str:
        return "onedrive_upload"

    @property
    def description(self) -> str:
        return "Upload a local workspace file to OneDrive (small files, <4MB)."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "local_path": {"type": "string", "description": "Path inside workspace/"},
                "remote_path": {"type": "string", "description": "Destination on OneDrive"},
            },
            "required": ["local_path", "remote_path"],
        }

    @property
    def permissions(self) -> ToolPermission:
        return _perm(filesystem=True)

    async def execute(self, params: dict[str, Any]) -> str:
        src = resolve_within("workspace", params["local_path"])
        if not src.absolute.exists():
            raise FileNotFoundError(f"workspace/{src.relative} does not exist")
        body = src.absolute.read_bytes()
        if len(body) > 4 * 1024 * 1024:
            raise ValueError("File too large for simple upload (>4MB).")
        remote = params["remote_path"].strip("/")
        url = DRIVE_ROOT + f":/{urllib.parse.quote(remote)}:/content"
        token = self._connector.access_token()
        resp = await _to_thread(_upload_bytes, url, token, body)
        return f"Uploaded {src.relative} → {remote} ({resp.get('size', len(body))} bytes)"


def _download_bytes(url: str, bearer: str) -> bytes:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {bearer}"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def _upload_bytes(url: str, bearer: str, payload: bytes) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        data=payload,
        method="PUT",
        headers={
            "Authorization": f"Bearer {bearer}",
            "Content-Type": "application/octet-stream",
        },
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        raw = resp.read().decode("utf-8")
    return json.loads(raw) if raw else {}
