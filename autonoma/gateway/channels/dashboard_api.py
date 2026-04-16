"""Dashboard REST API — endpoints for the web dashboard."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from autonoma.gateway.channels._http_server import HTTPServer
from autonoma.gateway.router import GatewayRouter
from autonoma.memory.store import MemoryStore
from autonoma.cortex.session import SessionManager
from autonoma.schema import Message

logger = logging.getLogger(__name__)

_start_time = time.time()


def register_dashboard_routes(
    http_server: HTTPServer,
    memory_store: MemoryStore,
    session_manager: SessionManager,
    gateway_router: GatewayRouter,
    active_channels: list[str],
) -> None:
    """Register all dashboard API routes on the HTTP server."""

    async def handle_stats(request: dict) -> tuple[int, dict[str, str], str]:
        headers = {"Content-Type": "application/json"}
        try:
            mem_stats = await memory_store.get_stats()
            sessions_list = await session_manager.list_sessions()
            uptime = int(time.time() - _start_time)
            data = {
                "uptime_seconds": uptime,
                "active_channels": active_channels,
                "channel_count": len(active_channels),
                "memory_active": mem_stats["total_active"],
                "memory_archived": mem_stats["total_archived"],
                "session_count": len(sessions_list),
            }
            return 200, headers, json.dumps(data)
        except Exception as e:
            logger.error("Dashboard /api/stats error: %s", e)
            return 500, headers, json.dumps({"error": str(e)})

    async def handle_memories(request: dict) -> tuple[int, dict[str, str], str]:
        headers = {"Content-Type": "application/json"}
        try:
            path = request.get("path", "")
            # Check for search query param: /api/memories/search?q=...
            if "/search" in path and "?" in path:
                query_string = path.split("?", 1)[1]
                params = dict(p.split("=", 1) for p in query_string.split("&") if "=" in p)
                q = params.get("q", "").strip()
                if not q:
                    return 400, headers, json.dumps({"error": "Missing q parameter"})
                from urllib.parse import unquote_plus
                q = unquote_plus(q)
                entries = await memory_store.search(q, limit=50)
                data = [_entry_to_dict(e) for e in entries]
                return 200, headers, json.dumps(data)

            # Default: return all active memories
            all_memories = await asyncio.to_thread(
                memory_store._db.get_all_active, limit=500
            )
            return 200, headers, json.dumps(all_memories)
        except Exception as e:
            logger.error("Dashboard /api/memories error: %s", e)
            return 500, headers, json.dumps({"error": str(e)})

    async def handle_memories_search(request: dict) -> tuple[int, dict[str, str], str]:
        headers = {"Content-Type": "application/json"}
        try:
            path = request.get("path", "")
            q = ""
            if "?" in path:
                query_string = path.split("?", 1)[1]
                params = dict(
                    p.split("=", 1) for p in query_string.split("&") if "=" in p
                )
                q = params.get("q", "").strip()
            if not q:
                return 400, headers, json.dumps({"error": "Missing q parameter"})
            from urllib.parse import unquote_plus
            q = unquote_plus(q)
            entries = await memory_store.search(q, limit=50)
            data = [_entry_to_dict(e) for e in entries]
            return 200, headers, json.dumps(data)
        except Exception as e:
            logger.error("Dashboard /api/memories/search error: %s", e)
            return 500, headers, json.dumps({"error": str(e)})

    async def handle_memory_delete(request: dict) -> tuple[int, dict[str, str], str]:
        headers = {"Content-Type": "application/json"}
        try:
            path = request.get("path", "")
            # Extract ID from path: /api/memories/123
            parts = path.strip("/").split("/")
            if len(parts) < 3:
                return 400, headers, json.dumps({"error": "Missing memory ID"})
            memory_id = int(parts[2])
            await asyncio.to_thread(memory_store._db.soft_delete, memory_id)
            return 200, headers, json.dumps({"deleted": memory_id})
        except (ValueError, IndexError):
            return 400, headers, json.dumps({"error": "Invalid memory ID"})
        except Exception as e:
            logger.error("Dashboard DELETE /api/memories error: %s", e)
            return 500, headers, json.dumps({"error": str(e)})

    async def handle_sessions(request: dict) -> tuple[int, dict[str, str], str]:
        headers = {"Content-Type": "application/json"}
        try:
            path = request.get("path", "").split("?")[0].strip("/")
            parts = path.split("/")  # ["api", "sessions"] or ["api", "sessions", "<id>"]

            # Detail view: /api/sessions/<session_id>
            if len(parts) >= 3:
                session_id = "_".join(parts[2:])
                history = await session_manager.load_history(session_id, limit=200)
                entries = [
                    {
                        "role": e.role,
                        "content": e.content,
                        "channel": e.channel,
                        "user_id": e.user_id,
                        "timestamp": e.timestamp.isoformat(),
                    }
                    for e in history
                ]
                return 200, headers, json.dumps({"session_id": session_id, "messages": entries})

            # List view: /api/sessions
            sessions = await session_manager.list_sessions()
            for s in sessions:
                s_parts = s["id"].split("_")
                s["channel"] = s_parts[0] if s_parts else "unknown"
            return 200, headers, json.dumps(sessions)
        except Exception as e:
            logger.error("Dashboard /api/sessions error: %s", e)
            return 500, headers, json.dumps({"error": str(e)})

    async def handle_chat(request: dict) -> tuple[int, dict[str, str], str]:
        headers = {"Content-Type": "application/json"}
        try:
            data = request.get("json", {})
            content = data.get("message", "").strip()
            if not content:
                return 400, headers, json.dumps({"error": "Missing 'message' field"})

            user_id = data.get("user_id", "dashboard_user")
            channel_id = data.get("channel_id", "dashboard")

            message = Message(
                channel="dashboard",
                channel_id=channel_id,
                user_id=user_id,
                content=content,
            )
            response = await gateway_router.handle_message(message)
            return 200, headers, json.dumps({
                "response": response.content,
                "session_id": channel_id,
            })
        except Exception as e:
            logger.error("Dashboard /api/chat error: %s", e)
            return 500, headers, json.dumps({"error": str(e)})

    # Register routes
    http_server.add_route("GET", "/api/stats", handle_stats)
    http_server.add_route("GET", "/api/memories", handle_memories)
    http_server.add_route("GET", "/api/memories/search", handle_memories_search)
    http_server.add_route("DELETE", "/api/memories", handle_memory_delete)
    http_server.add_route("GET", "/api/sessions", handle_sessions)
    http_server.add_route("POST", "/api/chat", handle_chat)

    logger.info("Dashboard API routes registered (%d endpoints)", 6)


def _entry_to_dict(entry) -> dict[str, Any]:
    """Convert a MemoryEntry to a JSON-safe dict."""
    return {
        "id": entry.id,
        "content": entry.content,
        "type": entry.type,
        "source": entry.source,
        "importance": entry.importance,
        "created_at": entry.created_at,
        "accessed_at": entry.accessed_at,
        "access_count": entry.access_count,
        "active": entry.active,
    }
