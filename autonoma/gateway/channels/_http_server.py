"""Lightweight async HTTP/1.1 server for REST API and webhooks."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable, Awaitable
from urllib.parse import parse_qs, unquote_plus

logger = logging.getLogger(__name__)

# Route handler signature: (request_dict) -> (status, headers, body)
RouteHandler = Callable[[dict[str, Any]], Awaitable[tuple[int, dict[str, str], str]]]


class HTTPServer:
    """Minimal async HTTP server using asyncio.start_server."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8766):
        self._host = host
        self._port = port
        self._routes: dict[str, RouteHandler] = {}
        self._server: asyncio.Server | None = None

    def add_route(self, method: str, path: str, handler: RouteHandler) -> None:
        """Register a route handler. Key format: 'POST /api/chat'."""
        key = f"{method.upper()} {path}"
        self._routes[key] = handler
        logger.info("HTTP route registered: %s", key)

    async def start(self) -> None:
        self._server = await asyncio.start_server(
            self._handle_connection, self._host, self._port
        )
        logger.info("HTTP server listening on http://%s:%d", self._host, self._port)

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    async def _handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            request = await self._read_request(reader)
            if not request:
                writer.close()
                return

            key = f"{request['method']} {request['path']}"
            handler = self._routes.get(key)

            if handler:
                status, headers, body = await handler(request)
            else:
                status, headers, body = 404, {"Content-Type": "application/json"}, json.dumps({"error": "Not found"})

            self._write_response(writer, status, headers, body)
            await writer.drain()
        except Exception as e:
            logger.error("HTTP handler error: %s", e, exc_info=True)
            try:
                self._write_response(
                    writer, 500,
                    {"Content-Type": "application/json"},
                    json.dumps({"error": "Internal server error"}),
                )
                await writer.drain()
            except Exception:
                pass
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def _read_request(self, reader: asyncio.StreamReader) -> dict[str, Any] | None:
        """Parse an HTTP/1.1 request into a dict."""
        try:
            # Read request line
            request_line = await asyncio.wait_for(reader.readline(), timeout=10.0)
            if not request_line:
                return None
            parts = request_line.decode("utf-8", errors="replace").strip().split(" ", 2)
            if len(parts) < 2:
                return None

            method = parts[0].upper()
            raw_path = parts[1]

            # Read headers
            headers: dict[str, str] = {}
            while True:
                line = await asyncio.wait_for(reader.readline(), timeout=10.0)
                decoded = line.decode("utf-8", errors="replace").strip()
                if not decoded:
                    break
                if ":" in decoded:
                    k, v = decoded.split(":", 1)
                    headers[k.strip().lower()] = v.strip()

            # Read body if Content-Length present
            body = ""
            content_length = int(headers.get("content-length", "0"))
            if content_length > 0:
                raw_body = await asyncio.wait_for(
                    reader.readexactly(content_length), timeout=30.0
                )
                body = raw_body.decode("utf-8", errors="replace")

            # Parse body based on content type
            content_type = headers.get("content-type", "")
            json_body: dict = {}
            form_data: dict = {}

            if "application/json" in content_type and body:
                try:
                    json_body = json.loads(body)
                except json.JSONDecodeError:
                    pass
            elif "application/x-www-form-urlencoded" in content_type and body:
                parsed = parse_qs(body, keep_blank_values=True)
                form_data = {k: v[0] if len(v) == 1 else v for k, v in parsed.items()}

            return {
                "method": method,
                "path": raw_path,
                "headers": headers,
                "body": body,
                "json": json_body,
                "form_data": form_data,
            }
        except (asyncio.TimeoutError, asyncio.IncompleteReadError):
            return None

    def _write_response(
        self,
        writer: asyncio.StreamWriter,
        status: int,
        headers: dict[str, str],
        body: str,
    ) -> None:
        """Write an HTTP/1.1 response."""
        reason = {200: "OK", 400: "Bad Request", 401: "Unauthorized", 404: "Not Found", 500: "Internal Server Error"}.get(status, "OK")
        encoded_body = body.encode("utf-8")
        headers.setdefault("Content-Length", str(len(encoded_body)))
        headers.setdefault("Connection", "close")

        lines = [f"HTTP/1.1 {status} {reason}"]
        for k, v in headers.items():
            lines.append(f"{k}: {v}")
        lines.append("")
        lines.append("")

        writer.write("\r\n".join(lines).encode("utf-8"))
        writer.write(encoded_body)
