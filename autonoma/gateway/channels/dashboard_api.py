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
    task_queue=None,
    trace_store=None,
    skill_registry=None,
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

    # --- Trace endpoints ---

    async def handle_traces(request: dict) -> tuple[int, dict[str, str], str]:
        headers = {"Content-Type": "application/json"}
        if not trace_store:
            return 200, headers, json.dumps([])
        try:
            path = request.get("path", "")
            clean = path.split("?")[0].strip("/")
            parts = clean.split("/")

            # Detail: /api/traces/<trace_id>
            if len(parts) >= 3 and parts[2] != "stats":
                trace_id = parts[2]
                trace = trace_store.get_trace(trace_id)
                if not trace:
                    return 404, headers, json.dumps({"error": "Trace not found"})
                return 200, headers, json.dumps(trace)

            # List: /api/traces
            limit = 50
            status = None
            if "?" in path:
                qs = path.split("?", 1)[1]
                params = dict(p.split("=", 1) for p in qs.split("&") if "=" in p)
                limit = int(params.get("limit", "50"))
                status = params.get("status")
            traces = trace_store.list_traces(limit=limit, status=status)
            return 200, headers, json.dumps(traces)
        except Exception as e:
            logger.error("Dashboard /api/traces error: %s", e)
            return 500, headers, json.dumps({"error": str(e)})

    async def handle_trace_stats(request: dict) -> tuple[int, dict[str, str], str]:
        headers = {"Content-Type": "application/json"}
        if not trace_store:
            return 200, headers, json.dumps({})
        try:
            return 200, headers, json.dumps(trace_store.get_stats())
        except Exception as e:
            return 500, headers, json.dumps({"error": str(e)})

    # --- Task queue endpoints ---

    async def handle_tasks(request: dict) -> tuple[int, dict[str, str], str]:
        headers = {"Content-Type": "application/json"}
        if not task_queue:
            return 200, headers, json.dumps([])
        try:
            path = request.get("path", "")
            clean = path.split("?")[0].strip("/")
            parts = clean.split("/")

            # Detail: /api/tasks/<task_id>
            if len(parts) >= 3 and parts[2] != "stats":
                task_id = parts[2]
                task = task_queue.get_task(task_id)
                if not task:
                    return 404, headers, json.dumps({"error": "Task not found"})
                return 200, headers, json.dumps(task.to_dict())

            # List: /api/tasks
            status_filter = None
            if "?" in path:
                qs = path.split("?", 1)[1]
                params = dict(p.split("=", 1) for p in qs.split("&") if "=" in p)
                status_filter = params.get("status")
            tasks = task_queue.list_tasks(status=status_filter)
            return 200, headers, json.dumps([t.to_dict() for t in tasks])
        except Exception as e:
            logger.error("Dashboard /api/tasks error: %s", e)
            return 500, headers, json.dumps({"error": str(e)})

    async def handle_task_stats(request: dict) -> tuple[int, dict[str, str], str]:
        headers = {"Content-Type": "application/json"}
        if not task_queue:
            return 200, headers, json.dumps({})
        try:
            return 200, headers, json.dumps(task_queue.get_stats())
        except Exception as e:
            return 500, headers, json.dumps({"error": str(e)})

    async def handle_task_cancel(request: dict) -> tuple[int, dict[str, str], str]:
        headers = {"Content-Type": "application/json"}
        if not task_queue:
            return 404, headers, json.dumps({"error": "Task queue not available"})
        try:
            path = request.get("path", "")
            parts = path.strip("/").split("/")
            if len(parts) < 3:
                return 400, headers, json.dumps({"error": "Missing task ID"})
            task_id = parts[2]
            if task_queue.cancel_task(task_id):
                return 200, headers, json.dumps({"cancelled": task_id})
            return 400, headers, json.dumps({"error": "Task not cancellable"})
        except Exception as e:
            return 500, headers, json.dumps({"error": str(e)})

    # --- Stale memories endpoint ---

    async def handle_stale_memories(request: dict) -> tuple[int, dict[str, str], str]:
        headers = {"Content-Type": "application/json"}
        try:
            stale = await memory_store.get_stale_memories(limit=100)
            return 200, headers, json.dumps(stale)
        except Exception as e:
            logger.error("Dashboard /api/memories/stale error: %s", e)
            return 500, headers, json.dumps({"error": str(e)})

    async def handle_review_memory(request: dict) -> tuple[int, dict[str, str], str]:
        """POST /api/memories/review — mark a stale memory as reviewed."""
        headers = {"Content-Type": "application/json"}
        try:
            data = request.get("json", {})
            memory_id = data.get("memory_id")
            action = data.get("action", "review")  # "review" or "dismiss"
            if not memory_id:
                return 400, headers, json.dumps({"error": "Missing memory_id"})
            if action == "dismiss":
                await asyncio.to_thread(memory_store._db.soft_delete, int(memory_id))
                return 200, headers, json.dumps({"dismissed": memory_id})
            else:
                await memory_store.mark_reviewed(int(memory_id))
                return 200, headers, json.dumps({"reviewed": memory_id})
        except Exception as e:
            logger.error("Dashboard /api/memories/review error: %s", e)
            return 500, headers, json.dumps({"error": str(e)})

    # --- Skill manifest endpoint ---

    async def handle_manifest(request: dict) -> tuple[int, dict[str, str], str]:
        headers = {"Content-Type": "application/json"}
        if not skill_registry:
            return 200, headers, json.dumps([])
        try:
            manifest = skill_registry.get_permission_manifest()
            return 200, headers, json.dumps(manifest)
        except Exception as e:
            return 500, headers, json.dumps({"error": str(e)})

    # Register routes
    http_server.add_route("GET", "/api/skills/manifest", handle_manifest)
    http_server.add_route("GET", "/api/memories/stale", handle_stale_memories)
    http_server.add_route("POST", "/api/memories/review", handle_review_memory)
    http_server.add_route("GET", "/api/stats", handle_stats)
    http_server.add_route("GET", "/api/memories", handle_memories)
    http_server.add_route("GET", "/api/memories/search", handle_memories_search)
    http_server.add_route("DELETE", "/api/memories", handle_memory_delete)
    http_server.add_route("GET", "/api/sessions", handle_sessions)
    http_server.add_route("POST", "/api/chat", handle_chat)
    http_server.add_route("GET", "/api/traces", handle_traces)
    http_server.add_route("GET", "/api/traces/stats", handle_trace_stats)
    http_server.add_route("GET", "/api/tasks", handle_tasks)
    http_server.add_route("GET", "/api/tasks/stats", handle_task_stats)
    http_server.add_route("DELETE", "/api/tasks", handle_task_cancel)

    logger.info("Dashboard API routes registered (%d endpoints)", 14)


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
