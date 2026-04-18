"""Dashboard REST API — endpoints for the web dashboard."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from autonoma.gateway.channels._http_server import HTTPServer
from autonoma.gateway.router import GatewayRouter
from autonoma.gateway.server import GatewayServer
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
    gateway_server: GatewayServer,
    task_queue=None,
    trace_store=None,
    skill_registry=None,
    agent_runner=None,
) -> None:
    """Register all dashboard API routes on the HTTP server."""

    async def handle_stats(request: dict) -> tuple[int, dict[str, str], str]:
        headers = {"Content-Type": "application/json"}
        try:
            mem_stats = await memory_store.get_stats()
            sessions_list = await session_manager.list_sessions()
            uptime = int(time.time() - _start_time)
            active_channels = list(gateway_server._channels.keys())
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

    # --- System Control ---

    async def handle_system_restart(request: dict) -> tuple[int, dict[str, str], str]:
        """POST /api/system/restart — trigger agent reload."""
        headers = {"Content-Type": "application/json"}
        if not agent_runner:
            return 404, headers, json.dumps({"error": "Agent runner not available"})
        try:
            # We must not block the response, as restarting the runner might
            # close the very server handling this request. We schedule it.
            def _restart():
                logger.info("Remote restart triggered from dashboard")
                agent_runner.stop()
                agent_runner.start()
            
            asyncio.get_event_loop().call_later(0.5, _restart)
            return 200, headers, json.dumps({"status": "restarting"})
        except Exception as e:
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

    # --- SOUL.md endpoints ---

    async def handle_soul_get(request: dict) -> tuple[int, dict[str, str], str]:
        """GET /api/soul — return the SOUL.md content."""
        headers = {"Content-Type": "application/json"}
        try:
            from autonoma.config import load_config as _load_config
            cfg = _load_config()
            soul_path = Path(cfg.workspace_dir) / "SOUL.md"
            if not soul_path.exists():
                return 200, headers, json.dumps({"content": "", "exists": False})
            content = soul_path.read_text(encoding="utf-8")
            stat = soul_path.stat()
            return 200, headers, json.dumps({
                "content": content,
                "exists": True,
                "size_bytes": stat.st_size,
                "modified": stat.st_mtime,
            })
        except Exception as e:
            logger.error("Dashboard GET /api/soul error: %s", e)
            return 500, headers, json.dumps({"error": str(e)})

    async def handle_soul_update(request: dict) -> tuple[int, dict[str, str], str]:
        """POST /api/soul — update the SOUL.md content."""
        headers = {"Content-Type": "application/json"}
        try:
            from autonoma.config import load_config as _load_config
            cfg = _load_config()
            data = request.get("json", {})
            content = data.get("content")
            if content is None:
                return 400, headers, json.dumps({"error": "Missing 'content' field"})
            soul_path = Path(cfg.workspace_dir) / "SOUL.md"
            soul_path.parent.mkdir(parents=True, exist_ok=True)
            soul_path.write_text(content, encoding="utf-8")
            return 200, headers, json.dumps({
                "status": "ok",
                "size_bytes": len(content.encode("utf-8")),
            })
        except Exception as e:
            logger.error("Dashboard POST /api/soul error: %s", e)
            return 500, headers, json.dumps({"error": str(e)})

    # --- Config endpoints ---

    async def handle_config_get(request: dict) -> tuple[int, dict[str, str], str]:
        """GET /api/config — return current configuration (secrets masked)."""
        headers = {"Content-Type": "application/json"}
        try:
            from autonoma.config import load_config as _load_config
            cfg = _load_config()
            data = {
                "name": cfg.name,
                "llm": {
                    "provider": cfg.llm.provider,
                    "model": cfg.llm.model,
                    "api_key_configured": bool(cfg.llm.api_key),
                },
                "gateway": {
                    "host": cfg.gateway.host,
                    "port": cfg.gateway.port,
                    "http_port": cfg.gateway.http_port,
                },
                "channels": {
                    "telegram": {"enabled": cfg.channels.telegram.enabled},
                    "discord": {"enabled": cfg.channels.discord.enabled},
                    "whatsapp": {"enabled": cfg.channels.whatsapp.enabled},
                    "gmail": {"enabled": cfg.channels.gmail.enabled},
                    "rest": {"enabled": cfg.channels.rest.enabled},
                },
                "memory": {
                    "max_context_memories": cfg.memory.max_context_memories,
                    "decay_interval": cfg.memory.decay_interval,
                    "importance_threshold": cfg.memory.importance_threshold,
                    "consolidation_enabled": cfg.memory.consolidation_enabled,
                },
                "log_level": cfg.log_level,
            }
            return 200, headers, json.dumps(data)
        except Exception as e:
            logger.error("Dashboard GET /api/config error: %s", e)
            return 500, headers, json.dumps({"error": str(e)})

    async def handle_config_update(request: dict) -> tuple[int, dict[str, str], str]:
        """POST /api/config — update configuration fields.

        Accepts a JSON body with any subset of config fields. Writes changes
        to both autonoma.yaml and .env as appropriate. Requires agent restart
        to take effect.
        """
        headers = {"Content-Type": "application/json"}
        try:
            import os
            from pathlib import Path
            from dotenv import set_key
            from autonoma.config import save_yaml_config

            data = request.get("json", {})
            if not data:
                return 400, headers, json.dumps({"error": "Empty request body"})

            yaml_updates: dict = {}
            env_path = Path(".env")
            env_path.touch(exist_ok=True)

            # LLM settings
            if "llm" in data:
                llm = data["llm"]
                if "provider" in llm:
                    yaml_updates.setdefault("llm", {})["provider"] = llm["provider"]
                    os.environ["AUTONOMA_LLM_PROVIDER"] = llm["provider"]
                    set_key(str(env_path), "AUTONOMA_LLM_PROVIDER", llm["provider"], quote_mode="always")
                if "model" in llm:
                    yaml_updates.setdefault("llm", {})["model"] = llm["model"]
                    os.environ["AUTONOMA_LLM_MODEL"] = llm["model"]
                    set_key(str(env_path), "AUTONOMA_LLM_MODEL", llm["model"], quote_mode="always")
                if "api_key" in llm and llm["api_key"]:
                    provider = llm.get("provider", os.getenv("AUTONOMA_LLM_PROVIDER", "openrouter"))
                    env_key = "OPENROUTER_API_KEY" if provider == "openrouter" else "ANTHROPIC_API_KEY"
                    os.environ[env_key] = llm["api_key"]
                    set_key(str(env_path), env_key, llm["api_key"], quote_mode="always")

            # Channel toggles
            if "channels" in data:
                for ch_name, ch_data in data["channels"].items():
                    if isinstance(ch_data, dict) and "enabled" in ch_data:
                        yaml_updates.setdefault("channels", {}).setdefault(ch_name, {})["enabled"] = ch_data["enabled"]

            # Log level
            if "log_level" in data:
                yaml_updates["log_level"] = data["log_level"]
                os.environ["AUTONOMA_LOG_LEVEL"] = data["log_level"]
                set_key(str(env_path), "AUTONOMA_LOG_LEVEL", data["log_level"], quote_mode="always")

            # Name
            if "name" in data:
                yaml_updates["name"] = data["name"]

            # Memory settings
            if "memory" in data:
                for k, v in data["memory"].items():
                    yaml_updates.setdefault("memory", {})[k] = v

            if yaml_updates:
                yaml_path = Path("autonoma.yaml")
                save_yaml_config(yaml_path, yaml_updates)

            return 200, headers, json.dumps({"status": "ok", "updated": list(data.keys()), "restart_required": True})
        except Exception as e:
            logger.error("Dashboard POST /api/config error: %s", e)
            return 500, headers, json.dumps({"error": str(e)})

    # --- Logs endpoint ---

    async def handle_logs(request: dict) -> tuple[int, dict[str, str], str]:
        """GET /api/logs?level=&since=&q="""
        headers = {"Content-Type": "application/json"}
        try:
            from autonoma.logs import log_buffer
            path = request.get("path", "")
            
            level = None
            since = None
            q = None
            
            if "?" in path:
                qs = path.split("?", 1)[1]
                params = dict(p.split("=", 1) for p in qs.split("&") if "=" in p)
                from urllib.parse import unquote_plus
                level = unquote_plus(params.get("level", "")) or None
                since = unquote_plus(params.get("since", "")) or None
                q = unquote_plus(params.get("q", "")) or None
                
            logs = log_buffer.get_logs(level=level, since=since, q=q, limit=500)
            return 200, headers, json.dumps(logs)
        except Exception as e:
            logger.error("Dashboard GET /api/logs error: %s", e)
            return 500, headers, json.dumps({"error": str(e)})

    # --- Channel endpoints ---

    async def handle_channels(request: dict) -> tuple[int, dict[str, str], str]:
        """GET /api/channels — return list of channels and their exact health status."""
        headers = {"Content-Type": "application/json"}
        try:
            from autonoma.config import load_config as _load_config
            cfg = _load_config()
            ch_cfg = cfg.channels
            
            # Map configurations
            channels_info = {
                "telegram": {"enabled": ch_cfg.telegram.enabled, "name": "Telegram", "has_credentials": bool(ch_cfg.telegram.bot_token)},
                "discord": {"enabled": ch_cfg.discord.enabled, "name": "Discord", "has_credentials": bool(ch_cfg.discord.bot_token)},
                "whatsapp": {"enabled": ch_cfg.whatsapp.enabled, "name": "WhatsApp", "has_credentials": True},  # WhatsApp uses QR
                "gmail": {"enabled": ch_cfg.gmail.enabled, "name": "Gmail", "has_credentials": bool(ch_cfg.gmail.address and ch_cfg.gmail.app_password)},
                "rest": {"enabled": ch_cfg.rest.enabled, "name": "REST API", "has_credentials": True},
            }
            
            # Combine with runtime status
            response_data = []
            for key, info in channels_info.items():
                status_block = gateway_server._channel_status.get(key, {"status": "stopped", "last_error": None})
                if not info["enabled"]:
                    status_block = {"status": "disabled", "last_error": None}
                    
                response_data.append({
                    "id": key,
                    "name": info["name"],
                    "enabled": info["enabled"],
                    "has_credentials": info["has_credentials"],
                    "status": status_block.get("status"),
                    "last_error": status_block.get("last_error"),
                })
                
            return 200, headers, json.dumps(response_data)
        except Exception as e:
            logger.error("Dashboard GET /api/channels error: %s", e)
            return 500, headers, json.dumps({"error": str(e)})

    async def handle_channel_reconnect(request: dict) -> tuple[int, dict[str, str], str]:
        """POST /api/channels/{name}/reconnect — force reconnect an active channel."""
        headers = {"Content-Type": "application/json"}
        try:
            path = request.get("path", "")
            parts = path.strip("/").split("/")
            if len(parts) < 4:
                return 400, headers, json.dumps({"error": "Missing channel name"})
            channel_name = parts[2]
            
            if channel_name not in gateway_server._channels:
                return 400, headers, json.dumps({"error": f"Channel '{channel_name}' is not currently running."})
                
            await gateway_server.reconnect_channel(channel_name)
            return 200, headers, json.dumps({"status": "reconnecting", "channel": channel_name})
        except Exception as e:
            logger.error("Dashboard POST /api/channels/reconnect error: %s", e)
            return 500, headers, json.dumps({"error": str(e)})
            
    async def handle_channel_toggle(request: dict) -> tuple[int, dict[str, str], str]:
        """POST /api/channels/{name}/toggle — enable/disable channel in config."""
        headers = {"Content-Type": "application/json"}
        try:
            path = request.get("path", "")
            parts = path.strip("/").split("/")
            if len(parts) < 4:
                return 400, headers, json.dumps({"error": "Missing channel name"})
            channel_name = parts[2]
            
            data = request.get("json", {})
            enabled = data.get("enabled", False)
            
            import os
            from pathlib import Path
            from autonoma.config import save_yaml_config
            
            yaml_updates = {"channels": {channel_name: {"enabled": enabled}}}
            yaml_path = Path("autonoma.yaml")
            save_yaml_config(yaml_path, yaml_updates)
            
            return 200, headers, json.dumps({"status": "ok", "channel": channel_name, "enabled": enabled, "restart_required": True})
        except Exception as e:
            logger.error("Dashboard POST /api/channels/toggle error: %s", e)
            return 500, headers, json.dumps({"error": str(e)})
            
    async def handle_channel_credentials(request: dict) -> tuple[int, dict[str, str], str]:
        """POST /api/channels/{name}/credentials — update credentials in .env."""
        headers = {"Content-Type": "application/json"}
        try:
            path = request.get("path", "")
            parts = path.strip("/").split("/")
            if len(parts) < 4:
                return 400, headers, json.dumps({"error": "Missing channel name"})
            channel_name = parts[2]
            
            data = request.get("json", {})
            
            import os
            from pathlib import Path
            from dotenv import set_key
            env_path = Path(".env")
            env_path.touch(exist_ok=True)
            
            if channel_name == "telegram":
                token = data.get("bot_token")
                if token:
                    os.environ["TELEGRAM_BOT_TOKEN"] = token
                    set_key(str(env_path), "TELEGRAM_BOT_TOKEN", token, quote_mode="always")
            elif channel_name == "discord":
                token = data.get("bot_token")
                if token:
                    os.environ["DISCORD_BOT_TOKEN"] = token
                    set_key(str(env_path), "DISCORD_BOT_TOKEN", token, quote_mode="always")
            elif channel_name == "gmail":
                address = data.get("address")
                password = data.get("app_password")
                if address:
                    os.environ["GMAIL_ADDRESS"] = address
                    set_key(str(env_path), "GMAIL_ADDRESS", address, quote_mode="always")
                if password:
                    os.environ["GMAIL_APP_PASSWORD"] = password
                    set_key(str(env_path), "GMAIL_APP_PASSWORD", password, quote_mode="always")
            else:
                return 400, headers, json.dumps({"error": f"Credentials update not supported for {channel_name}"})
                
            return 200, headers, json.dumps({"status": "ok", "channel": channel_name, "restart_required": True})
        except Exception as e:
            logger.error("Dashboard POST /api/channels/credentials error: %s", e)
            return 500, headers, json.dumps({"error": str(e)})

    async def handle_webhooks(request: dict) -> tuple[int, dict[str, str], str]:
        """GET /api/webhooks?channel="""
        headers = {"Content-Type": "application/json"}
        try:
            from autonoma.gateway.channels._http_server import webhook_buffer
            
            # optional channel filtering
            path = request.get("path", "")
            channel_filter = ""
            if "?" in path:
                qs = path.split("?", 1)[1]
                params = dict(p.split("=", 1) for p in qs.split("&") if "=" in p)
                channel_filter = params.get("channel", "").lower()

            results = webhook_buffer
            if channel_filter:
                results = [item for item in results if channel_filter in item["path"].lower()]
                
            return 200, headers, json.dumps(results[::-1]) # reverse chronological
        except Exception as e:
            logger.error("Dashboard GET /api/webhooks error: %s", e)
            return 500, headers, json.dumps({"error": str(e)})

    async def handle_webhook_replay(request: dict) -> tuple[int, dict[str, str], str]:
        """POST /api/webhooks/{id}/replay"""
        headers = {"Content-Type": "application/json"}
        try:
            from autonoma.gateway.channels._http_server import webhook_buffer
            path = request.get("path", "")
            parts = path.split("/")
            if len(parts) < 5:
                return 400, headers, json.dumps({"error": "Missing webhook id"})
            
            w_id = parts[3]
            target = next((x for x in webhook_buffer if x["id"] == w_id), None)
            if not target:
                return 404, headers, json.dumps({"error": "Webhook not found"})

            # Bypass socket and invoke handler directly to mimic replay
            handler = http_server._match_route(target["method"], target["path"])
            if handler:
                asyncio.create_task(handler({
                    "method": target["method"],
                    "path": target["path"],
                    "headers": target["headers"],
                    "body": target["body"],
                    "json": target["json"],
                }))
            
            return 200, headers, json.dumps({"status": "Replay triggered"})
        except Exception as e:
            logger.error("Dashboard POST /api/webhooks/replay error: %s", e)
            return 500, headers, json.dumps({"error": str(e)})

    # Register routes
    http_server.add_route("GET", "/api/soul", handle_soul_get)
    http_server.add_route("POST", "/api/soul", handle_soul_update)
    http_server.add_route("GET", "/api/config", handle_config_get)
    http_server.add_route("POST", "/api/config", handle_config_update)
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
    http_server.add_route("POST", "/api/system/restart", handle_system_restart)
    http_server.add_route("GET", "/api/channels", handle_channels)
    http_server.add_route("POST", "/api/channels/telegram/reconnect", handle_channel_reconnect)
    http_server.add_route("POST", "/api/channels/discord/reconnect", handle_channel_reconnect)
    http_server.add_route("POST", "/api/channels/whatsapp/reconnect", handle_channel_reconnect)
    http_server.add_route("POST", "/api/channels/gmail/reconnect", handle_channel_reconnect)
    http_server.add_route("POST", "/api/channels/rest/reconnect", handle_channel_reconnect)
    
    http_server.add_route("POST", "/api/channels/telegram/toggle", handle_channel_toggle)
    http_server.add_route("POST", "/api/channels/discord/toggle", handle_channel_toggle)
    http_server.add_route("POST", "/api/channels/whatsapp/toggle", handle_channel_toggle)
    http_server.add_route("POST", "/api/channels/gmail/toggle", handle_channel_toggle)
    http_server.add_route("POST", "/api/channels/rest/toggle", handle_channel_toggle)

    http_server.add_route("POST", "/api/channels/telegram/credentials", handle_channel_credentials)
    http_server.add_route("POST", "/api/channels/discord/credentials", handle_channel_credentials)
    http_server.add_route("POST", "/api/channels/gmail/credentials", handle_channel_credentials)
    http_server.add_route("GET", "/api/logs", handle_logs)
    http_server.add_route("GET", "/api/webhooks", handle_webhooks)
    http_server.add_route("POST", "/api/webhooks", handle_webhook_replay) # Using wildcard prefix catch since it's dynamic /{id}/replay. Wait, let's just make it a static route, but HTTPServer might not support path params natively.

    logger.info("Dashboard API routes registered (%d endpoints)", 25)


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
