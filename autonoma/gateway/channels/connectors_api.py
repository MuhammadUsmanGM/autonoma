"""HTTP routes for the connectors subsystem.

Three concerns wired here:

* ``GET  /api/connectors`` — list connectors with manifest + live status.
* ``POST /api/connectors/{name}/connect`` — returns the auth URL the user
  must visit; the dashboard opens it in a popup, the TUI prints it.
* ``POST /api/connectors/{name}/disconnect`` — revokes tokens (logout).
* ``GET  /oauth/{name}/start``      — convenience redirect for browser flow.
* ``GET  /oauth/{name}/callback``   — provider redirects here with code+state.

The callback closes the popup and sends a message to the parent dashboard
window so it can refresh the connectors list.
"""

from __future__ import annotations

import json
import logging
from urllib.parse import parse_qs, urlsplit

from autonoma.connectors.registry import ConnectorRegistry

logger = logging.getLogger(__name__)


_CALLBACK_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>Connector authorized</title></head>
<body style="font-family: system-ui; padding: 2rem; max-width: 28rem; margin: auto;">
<h1>{title}</h1>
<p>{message}</p>
<p><small>You can close this tab.</small></p>
<script>
  try {{
    if (window.opener) {{
      window.opener.postMessage({{ type: "autonoma:connector", name: "{name}", status: "{status}" }}, "*");
      setTimeout(() => window.close(), 600);
    }}
  }} catch (e) {{}}
</script>
</body></html>"""


def register_connector_routes(http_server, registry: ConnectorRegistry) -> None:
    """Wire connectors routes onto the running HTTPServer."""

    json_headers = {"Content-Type": "application/json"}

    # ---- /api/connectors ------------------------------------------------

    async def list_connectors(request: dict) -> tuple[int, dict, str]:
        out = []
        for c in registry.all():
            out.append(
                {
                    "manifest": c.manifest.to_dict(),
                    "status": c.status().to_dict(),
                }
            )
        return 200, json_headers, json.dumps(out)

    async def connect(request: dict) -> tuple[int, dict, str]:
        name = _path_param(request["path"], 2)
        c = registry.get(name)
        if c is None:
            return 404, json_headers, json.dumps({"error": f"unknown connector: {name}"})
        try:
            url = await c.start_auth()
        except Exception as e:
            logger.exception("connector %s start_auth failed", name)
            return 400, json_headers, json.dumps({"error": str(e)})
        return 200, json_headers, json.dumps({"auth_url": url})

    async def disconnect(request: dict) -> tuple[int, dict, str]:
        name = _path_param(request["path"], 2)
        c = registry.get(name)
        if c is None:
            return 404, json_headers, json.dumps({"error": f"unknown connector: {name}"})
        try:
            await c.disconnect()
        except Exception as e:
            logger.exception("connector %s disconnect failed", name)
            return 500, json_headers, json.dumps({"error": str(e)})
        registry.notify_tools_changed()
        return 200, json_headers, json.dumps({"status": c.status().to_dict()})

    # ---- OAuth helpers --------------------------------------------------

    async def oauth_start(request: dict) -> tuple[int, dict, str]:
        # Convenience: hitting /oauth/{name}/start in a browser issues a 302.
        name = _oauth_name(request["path"])
        c = registry.get(name)
        if c is None:
            return 404, json_headers, json.dumps({"error": f"unknown connector: {name}"})
        try:
            url = await c.start_auth()
        except Exception as e:
            return 400, json_headers, json.dumps({"error": str(e)})
        return 302, {"Location": url}, ""

    async def oauth_callback(request: dict) -> tuple[int, dict, str]:
        name = _oauth_name(request["path"])
        c = registry.get(name)
        if c is None:
            html = _CALLBACK_HTML.format(
                title="Unknown connector",
                message=f"No connector named <code>{name}</code> is registered.",
                name=name,
                status="error",
            )
            return 404, {"Content-Type": "text/html"}, html
        params = _query(request["path"])
        if "error" in params:
            html = _CALLBACK_HTML.format(
                title="Authorization denied",
                message=params.get("error_description", params["error"]),
                name=name,
                status="error",
            )
            return 400, {"Content-Type": "text/html"}, html
        try:
            status = await c.complete_auth(params)
        except Exception as e:
            logger.exception("connector %s callback failed", name)
            html = _CALLBACK_HTML.format(
                title="Connection failed",
                message=str(e),
                name=name,
                status="error",
            )
            return 400, {"Content-Type": "text/html"}, html
        registry.notify_tools_changed()
        html = _CALLBACK_HTML.format(
            title=f"{c.manifest.display_name} connected",
            message=f"Signed in as <strong>{status.account_label or status.account_id}</strong>.",
            name=name,
            status="connected",
        )
        return 200, {"Content-Type": "text/html"}, html

    http_server.add_route("GET", "/api/connectors", list_connectors)
    # Two registrations per name keep the prefix-match router happy without
    # adding wildcard support: the path includes the connector name.
    for c in registry.all():
        http_server.add_route(
            "POST", f"/api/connectors/{c.name}/connect", connect
        )
        http_server.add_route(
            "POST", f"/api/connectors/{c.name}/disconnect", disconnect
        )
        http_server.add_route(f"GET", f"/oauth/{c.name}/start", oauth_start)
        http_server.add_route(f"GET", f"/oauth/{c.name}/callback", oauth_callback)
    logger.info("Connector API routes registered for: %s",
                ", ".join(c.name for c in registry.all()) or "(none)")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _path_param(path: str, idx: int) -> str:
    bare = path.split("?", 1)[0]
    parts = [p for p in bare.split("/") if p]
    return parts[idx] if idx < len(parts) else ""


def _oauth_name(path: str) -> str:
    bare = path.split("?", 1)[0]
    parts = [p for p in bare.split("/") if p]
    # /oauth/{name}/(start|callback)
    return parts[1] if len(parts) >= 2 else ""


def _query(path: str) -> dict[str, str]:
    if "?" not in path:
        return {}
    qs = path.split("?", 1)[1]
    parsed = parse_qs(qs, keep_blank_values=True)
    return {k: v[0] for k, v in parsed.items()}
