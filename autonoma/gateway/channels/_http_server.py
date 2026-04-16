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


CORS_ORIGINS = {"http://localhost:5173", "http://127.0.0.1:5173"}

CORS_HEADERS = {
    "Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
    "Access-Control-Max-Age": "86400",
}


class HTTPServer:
    """Minimal async HTTP server using asyncio.start_server."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8766):
        self._host = host
        self._port = port
        self._routes: dict[str, RouteHandler] = {}
        self._server: asyncio.Server | None = None

    def add_route(self, method: str, path: str, handler: RouteHandler) -> None:
        """Register a route handler. Key format: 'POST /api/chat'.

        Routes are matched with longest-prefix: '/api/sessions/detail'
        matches before '/api/sessions'.
        """
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

    def _match_route(self, method: str, path: str) -> RouteHandler | None:
        """Find a handler using exact match first, then longest-prefix match."""
        # Strip query string for matching
        clean = path.split("?")[0].rstrip("/") or "/"
        key = f"{method} {clean}"
        if key in self._routes:
            return self._routes[key]
        # Longest-prefix match (e.g. 'GET /api/sessions' matches '/api/sessions/xyz')
        best: str = ""
        for route_key in self._routes:
            r_method, r_path = route_key.split(" ", 1)
            if r_method != method:
                continue
            if clean.startswith(r_path) and len(r_path) > len(best):
                best = r_path
        return self._routes.get(f"{method} {best}") if best else None

    def _cors_headers(self, origin: str) -> dict[str, str]:
        """Return CORS headers if origin is allowed, else empty dict."""
        if origin in CORS_ORIGINS:
            return {"Access-Control-Allow-Origin": origin, **CORS_HEADERS}
        return {}

    async def _handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            request = await self._read_request(reader)
            if not request:
                writer.close()
                return

            origin = request.get("headers", {}).get("origin", "")
            cors = self._cors_headers(origin)

            # Handle CORS preflight
            if request["method"] == "OPTIONS":
                self._write_response(writer, 204, {**cors, "Content-Length": "0"}, "")
                await writer.drain()
                return

            handler = self._match_route(request["method"], request["path"])

            if handler:
                status, headers, body = await handler(request)
            else:
                status, headers, body = 404, {"Content-Type": "application/json"}, json.dumps({"error": "Not found"})

            headers.update(cors)
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
        reason = {200: "OK", 204: "No Content", 400: "Bad Request", 401: "Unauthorized", 404: "Not Found", 500: "Internal Server Error"}.get(status, "OK")
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
