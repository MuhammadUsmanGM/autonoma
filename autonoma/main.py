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
from autonoma.cortex.context import ContextAssembler
from autonoma.cortex.router import AgentRouter
from autonoma.cortex.session import SessionManager
from autonoma.cortex.trace_store import TraceStore
from autonoma.executor.sandbox import Sandbox
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

logger = logging.getLogger("autonoma")


async def run(
    config_path: str | None = None,
    log_level: str | None = None,
    agent_runner: Any | None = None
) -> None:
    """Main async entry point — wires everything together and starts the system."""

    # 1. Load config
    config = load_config(config_path)

    # Configure logging
    level = getattr(logging, (log_level or config.log_level).upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    
    from autonoma.logs import setup_log_buffer
    setup_log_buffer()

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

    # 7. Create executor (sandbox + tool runner)
    sandbox = Sandbox(allowed_dirs=[config.workspace_dir], timeout=30.0)
    tool_runner = ToolRunner(sandbox)

    # 8a. Create trace store
    trace_store = TraceStore(persist_dir=str(Path(config.session_dir) / "traces"))

    # 8b. Create task queue
    task_queue = TaskQueue(
        persist_path=str(Path(config.session_dir) / "task_queue.json"),
        max_concurrent=3,
    )

    # 8. Load skills and register tools
    skill_registry = SkillRegistry()
    for tool in load_builtin_tools(workspace_dir=config.workspace_dir):
        tool_runner.register(tool)
        skill_registry.register(tool)

    logger.info("Tools available: %s", ", ".join(skill_registry.get_tool_names()))

    # 9. Create agent
    agent = Agent(
        config, provider, memory_store, session_manager, context_assembler,
        tool_runner=tool_runner, skill_registry=skill_registry,
        trace_store=trace_store,
    )

    # 10. Create agent router
    agent_router = AgentRouter()
    agent_router.register(config.name, agent, default=True)

    # 11. Create gateway router
    gateway_router = GatewayRouter(agent_router)

    # 12. Create HTTP server (always on — needed for dashboard API + channels)
    ch = config.channels
    # Look for dashboard/dist relative to the project root
    static_dir = Path(__file__).parent.parent / "dashboard" / "dist"
    http_server = HTTPServer(
        host=config.gateway.host, 
        port=config.gateway.http_port,
        static_dir=static_dir if static_dir.exists() else None
    )

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
    from autonoma.gateway.channels.dashboard_api import register_dashboard_routes
    register_dashboard_routes(
        http_server, memory_store, session_manager,
        gateway_router, server,
        task_queue=task_queue,
        trace_store=trace_store,
        skill_registry=skill_registry,
        agent_runner=agent_runner,
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
        await server.start()

        try:
            await server.wait_for_channels()
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        finally:
            await task_queue.stop()
            await server.stop()

    logger.info("Autonoma shut down cleanly.")


def cli_entry() -> None:
    """Synchronous entry point for the `autonoma` console script.

    With no arguments, launches the interactive TUI control panel.
    With --start or -c, launches the agent directly (headless / CI mode).
    """
    parser = argparse.ArgumentParser(
        description="Autonoma — AI Agent Platform"
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
