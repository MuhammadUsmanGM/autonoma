"""Autonoma — Main entrypoint. Bootstraps and runs the agent platform."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import Any

from autonoma.config import load_config
from autonoma.cortex.agent import Agent
from autonoma.cortex.contacts import ContactStore
from autonoma.cortex.context import ContextAssembler
from autonoma.cortex.followup_scheduler import FollowupScheduler
from autonoma.cortex.router import AgentRouter
from autonoma.cortex.session import SessionManager
from autonoma.cortex.state_machine import ConversationStateStore
from autonoma.cortex.trace_store import TraceStore
from autonoma.executor.sandbox import Sandbox, SandboxConfig
from autonoma.executor.task_queue import TaskQueue, Priority
from autonoma.executor.tool_runner import ToolRunner
from autonoma.gateway.auth import AuthMiddleware
from autonoma.gateway.channels.cli import CLIChannel
from autonoma.gateway.router import GatewayRouter
from autonoma.gateway.server import GatewayServer
from autonoma.gateway.channels._http_server import HTTPServer
from autonoma.memory.flush import MemoryFlusher
from autonoma.memory.store import MemoryStore
from autonoma.models import create_provider
from autonoma.skills.loader import load_builtin_tools
from autonoma.skills.registry import SkillRegistry
from autonoma.connectors.registry import ConnectorRegistry

logger = logging.getLogger("autonoma")


async def run(
    config_path: str | None = None,
    log_level: str | None = None,
    agent_runner: Any | None = None
) -> None:
    """Main async entry point — wires everything together and starts the system."""

    # 1. Load config
    config = load_config(config_path)

    # Configure logging — format is driven by observability config (text|json).
    level = getattr(logging, (log_level or config.log_level).upper(), logging.INFO)
    from autonoma.logs import configure_root_logger, setup_log_buffer
    configure_root_logger(level, config.observability.log_format)
    setup_log_buffer()

    # Initialize OpenTelemetry if configured. No-op when the OTel SDK isn't
    # installed or the endpoint is blank, so core installs are unaffected.
    if config.observability.otel_endpoint:
        from autonoma.observability import otel
        otel.init(
            endpoint=config.observability.otel_endpoint,
            service_name=config.observability.otel_service_name,
            headers=config.observability.otel_headers,
        )

    # 2. Validate API key
    if not config.llm.api_key:
        logger.error(
            "No API key configured. Set ANTHROPIC_API_KEY, OPENROUTER_API_KEY, "
            "or AUTONOMA_LLM_API_KEY in your environment or .env file."
        )
        sys.exit(1)

    logger.info("Starting %s (provider=%s, model=%s)", config.name, config.llm.provider, config.llm.model)

    # 3. Create LLM provider
    provider = create_provider(config.llm)

    # 4. Create memory store
    memory_store = MemoryStore(config.workspace_dir, db_path=config.memory.db_path)

    # 5. Create session manager
    session_manager = SessionManager(config.session_dir)

    # 6. Create context assembler
    context_assembler = ContextAssembler(config.workspace_dir, memory_store)

    # 7. Create executor (sandbox + tool runner) from the configured policy.
    s = config.sandbox
    sandbox_config = SandboxConfig(
        timeout=s.timeout,
        max_output_bytes=s.max_output_bytes,
        max_memory_mb=s.max_memory_mb,
        max_cpu_seconds=s.max_cpu_seconds,
        max_processes=s.max_processes,
        max_file_size_mb=s.max_file_size_mb,
        allow_network=s.allow_network,
        env_allowlist=list(s.env_allowlist),
        shell_allowed_binaries=list(s.shell_allowed_binaries),
        shell_allow_strings=s.shell_allow_strings,
        write_denied_extensions=list(s.write_denied_extensions),
        backend=s.backend if s.backend in ("direct", "docker") else "direct",
        rate_limit_calls=s.rate_limit_calls,
        rate_limit_window=s.rate_limit_window,
    )
    # Validate backend choice early — a typo in autonoma.yaml should fail
    # at startup, not on the first tool call.
    from autonoma.executor.backends import get_backend
    backend_cls = get_backend(sandbox_config.backend)
    if backend_cls.name == "docker":
        # Surfaces the NotImplementedError with guidance before we spin up
        # any channels or touch the LLM.
        backend_cls()
    sandbox = Sandbox(
        allowed_dirs=[config.workspace_dir],
        config=sandbox_config,
    )
    tool_runner = ToolRunner(
        sandbox,
        audit_log_path=str(Path(config.session_dir) / "audit.log"),
    )

    # 8a. Create trace store
    trace_store = TraceStore(persist_dir=str(Path(config.session_dir) / "traces"))

    # 8b. Create task queue
    task_queue = TaskQueue(
        persist_path=str(Path(config.session_dir) / "task_queue.json"),
        max_concurrent=3,
    )

    # 8. Load skills and register tools
    skill_registry = SkillRegistry()
    for tool in load_builtin_tools(workspace_dir=config.workspace_dir, sandbox=sandbox):
        tool_runner.register(tool)
        skill_registry.register(tool)

    logger.info("Tools available: %s", ", ".join(skill_registry.get_tool_names()))

    # 8d. Connectors (Google Calendar, OneDrive, ...). Each one owns its OAuth
    # flow + persisted tokens; their tools are added to the runner only while
    # an account is connected.
    connector_registry = _build_connector_registry(config)
    _refresh_connector_tools(connector_registry, tool_runner, skill_registry)
    connector_registry.on_tools_changed(
        lambda: _refresh_connector_tools(connector_registry, tool_runner, skill_registry)
    )

    # 8c. Contact registry + conversation state store. Both are independent
    # SQLite files so they can be wiped or migrated separately from memory.
    contact_store = ContactStore(config.relationship)
    state_store = ConversationStateStore(config.conversation_state)

    # 9. Create agent
    agent = Agent(
        config, provider, memory_store, session_manager, context_assembler,
        tool_runner=tool_runner, skill_registry=skill_registry,
        trace_store=trace_store,
        contact_store=contact_store,
        state_store=state_store,
    )

    # 9b. Proactive follow-up scheduler (only active when both stores enabled).
    followup_scheduler = FollowupScheduler(
        config.conversation_state, state_store, contact_store, task_queue,
    )

    # 10. Create agent router
    agent_router = AgentRouter()
    agent_router.register(config.name, agent, default=True)

    # 11. Create gateway router (with pre-agent triage)
    from autonoma.cortex.triage import Triage
    triage = Triage(config.triage, session_dir=config.session_dir)
    gateway_router = GatewayRouter(agent_router, triage=triage)

    # 12. Create HTTP server (always on — needed for dashboard API + channels)
    ch = config.channels
    # Look for dashboard/dist relative to the project root
    static_dir = Path(__file__).parent.parent / "dashboard" / "dist"
    http_server = HTTPServer(
        host=config.gateway.host,
        port=config.gateway.http_port,
        static_dir=static_dir if static_dir.exists() else None,
        metrics_enabled=config.observability.metrics_enabled,
    )

    # Seed build_info so `autonoma_build_info` is always populated.
    try:
        import sys as _sys
        from autonoma import __version__ as _version
        from autonoma.observability.metrics import build_info as _build_info
        _build_info.set(
            1,
            labels={
                "version": _version,
                "python": f"{_sys.version_info.major}.{_sys.version_info.minor}",
            },
        )
    except Exception:
        pass

    # 13. Create gateway server
    auth = AuthMiddleware()
    server = GatewayServer(config.gateway, gateway_router, auth, http_server=http_server)

    # 14. Register CLI channel — ONLY when running headless.
    #
    # When the agent is embedded under the TUI (agent_runner is passed in by
    # AgentRunner._thread_main), the TUI owns stdin in raw mode. Registering
    # CLIChannel here would start a second reader on sys.stdin via
    # `input("You > ")`, which races the TUI's read_key() — keystrokes get
    # stolen, the "You > " prompt repaints under the menu on every render,
    # and arrow/enter navigation freezes. The TUI provides its own chat UI
    # (and the web dashboard has /api/chat) so there's nothing to lose by
    # skipping the CLI channel in embedded mode.
    if agent_runner is None:
        cli_channel = CLIChannel(agent_name=config.name)
        server.register_channel(cli_channel)
    else:
        logger.info("Embedded mode — skipping CLI channel (TUI owns stdin).")

    # 15. Register optional channels (deferred imports)
    if ch.rest.enabled:
        from autonoma.gateway.channels.rest import RESTChannel
        server.register_channel(RESTChannel(ch.rest, http_server))
        logger.info("REST API channel enabled on port %d", config.gateway.http_port)

    if ch.telegram.enabled:
        from autonoma.gateway.channels.telegram import TelegramChannel
        server.register_channel(TelegramChannel(ch.telegram))
        logger.info("Telegram channel enabled")

    if ch.discord.enabled:
        from autonoma.gateway.channels.discord_channel import DiscordChannel
        server.register_channel(DiscordChannel(ch.discord))
        logger.info("Discord channel enabled")

    if ch.whatsapp.enabled:
        from autonoma.gateway.channels.whatsapp import WhatsAppChannel
        server.register_channel(WhatsAppChannel(ch.whatsapp, http_server))
        logger.info("WhatsApp channel enabled")

    if ch.gmail.enabled:
        from autonoma.gateway.channels.gmail import GmailChannel
        server.register_channel(GmailChannel(ch.gmail))
        logger.info("Gmail channel enabled")

    # 16. Register dashboard API endpoints
    from autonoma.gateway.channels.connectors_api import register_connector_routes
    register_connector_routes(http_server, connector_registry)
    from autonoma.gateway.channels.dashboard_api import register_dashboard_routes
    register_dashboard_routes(
        http_server, memory_store, session_manager,
        gateway_router, server,
        task_queue=task_queue,
        trace_store=trace_store,
        skill_registry=skill_registry,
        agent_runner=agent_runner,
        contact_store=contact_store,
    )

    # 16b. Register task handlers. ``agent_prompt`` is the default skill for
    # scheduled jobs: payload["prompt"] is fed into the agent loop exactly as
    # if a user had sent it on a dedicated channel, so cron tasks can say
    # things like "check my Gmail and summarize new emails to WhatsApp" and
    # the full tool-using loop answers them.
    async def _agent_prompt_handler(payload: dict) -> str:
        prompt = payload.get("prompt") or ""
        if not prompt:
            raise ValueError("agent_prompt task requires payload.prompt")
        from autonoma.schema import Message
        channel = payload.get("channel", "scheduler")
        channel_id = payload.get("channel_id", f"scheduler:{channel}")
        user_id = payload.get("user_id", "scheduler")
        msg = Message(
            channel=channel,
            channel_id=channel_id,
            user_id=user_id,
            content=prompt,
        )
        response = await agent.handle_message(msg)
        return response.content[:2000] if response.content else ""

    task_queue.register_handler("agent_prompt", _agent_prompt_handler)

    # 17. Start everything
    consolidation_interval = config.memory.decay_interval if config.memory.consolidation_enabled else 0
    async with MemoryFlusher(memory_store, consolidation_interval=consolidation_interval):
        await task_queue.start()
        await followup_scheduler.start()
        await server.start()

        try:
            await server.wait_for_channels()
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        finally:
            await followup_scheduler.stop()
            await task_queue.stop()
            await server.stop()

    logger.info("Autonoma shut down cleanly.")


def _build_connector_registry(config) -> ConnectorRegistry:
    """Construct the connector registry from current config.

    A connector is registered only when its credentials are present — without
    client_id/client_secret the OAuth flow can't even start, so registering
    it would only put a permanently-broken entry in the dashboard.
    """
    from autonoma.connectors.token_store import TokenStore

    cc = config.connectors
    registry = ConnectorRegistry()
    store = TokenStore(db_path=cc.db_path, key_path=cc.key_path)
    # The state-token secret is the same key the token store uses; reusing it
    # avoids a second long-lived secret on disk.
    state_secret = open(cc.key_path, "rb").read().strip()
    base = (
        cc.redirect_base_url.rstrip("/")
        or f"http://{config.gateway.host}:{config.gateway.http_port}"
    )

    if cc.google_calendar.enabled and cc.google_calendar.client_id:
        from autonoma.connectors.google_calendar import GoogleCalendarConnector
        registry.register(
            GoogleCalendarConnector(
                cc.google_calendar,
                store,
                redirect_uri=f"{base}/oauth/google_calendar/callback",
                state_secret=state_secret,
            )
        )
    if cc.onedrive.enabled and cc.onedrive.client_id:
        from autonoma.connectors.onedrive import OneDriveConnector
        registry.register(
            OneDriveConnector(
                cc.onedrive,
                store,
                redirect_uri=f"{base}/oauth/onedrive/callback",
                state_secret=state_secret,
            )
        )
    return registry


def _push_connector_metrics(registry: ConnectorRegistry) -> None:
    """Mirror connector states into Prometheus."""
    from autonoma.observability.metrics import set_connector_status
    for name, status in registry.statuses().items():
        set_connector_status(name, status.state)


def _refresh_connector_tools(
    registry: ConnectorRegistry,
    tool_runner,
    skill_registry,
) -> None:
    """Resync ToolRunner + SkillRegistry to the live set of connector tools.

    Called once at boot, then again whenever a connector is connected /
    disconnected. We track which tools came from connectors via a name prefix
    (``calendar_*``, ``onedrive_*``) so we don't accidentally remove built-in
    tools that share neither prefix.
    """
    desired = {t.name: t for t in registry.active_tools()}
    desired_names = set(desired)
    # Drop connector-owned tools that are no longer active.
    for name in list(skill_registry.get_tool_names()):
        is_connector_tool = name.startswith(("calendar_", "onedrive_"))
        if is_connector_tool and name not in desired_names:
            tool_runner.unregister(name)
            skill_registry.unregister(name)
    # Add / refresh active connector tools.
    for tool in desired.values():
        tool_runner.register(tool)
        skill_registry.register(tool)
    _push_connector_metrics(registry)


def cli_entry() -> None:
    """Synchronous entry point for the `autonoma` console script.

    With no arguments, launches the interactive TUI control panel.
    With --start or -c, launches the agent directly (headless / CI mode).
    """
    from autonoma import __version__

    parser = argparse.ArgumentParser(
        description="Autonoma — AI Agent Platform"
    )
    parser.add_argument(
        "-V", "--version",
        action="version",
        version=f"autonoma {__version__}",
    )
    parser.add_argument(
        "-c", "--config", default=None, help="Path to config YAML file"
    )
    parser.add_argument(
        "--start",
        action="store_true",
        help="Start the agent directly, bypassing the TUI.",
    )
    parser.add_argument(
        "--log-level",
        default=None,
        choices=["debug", "info", "warning", "error"],
        help="Log level override",
    )
    args = parser.parse_args()

    # Direct-start mode (headless / CI) — skip TUI
    if args.start or args.config:
        try:
            asyncio.run(run(config_path=args.config, log_level=args.log_level))
        except KeyboardInterrupt:
            print("\nGoodbye.")
        return

    # Default: launch interactive TUI
    try:
        from autonoma.tui import AutonomaTUI
        AutonomaTUI().run()
    except KeyboardInterrupt:
        print("\nGoodbye.")


if __name__ == "__main__":
    cli_entry()
