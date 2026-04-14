"""Autonoma — Main entrypoint. Bootstraps and runs the agent platform."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from autonoma.config import load_config
from autonoma.cortex.agent import Agent
from autonoma.cortex.context import ContextAssembler
from autonoma.cortex.router import AgentRouter
from autonoma.cortex.session import SessionManager
from autonoma.gateway.auth import AuthMiddleware
from autonoma.gateway.channels.cli import CLIChannel
from autonoma.gateway.router import GatewayRouter
from autonoma.gateway.server import GatewayServer
from autonoma.memory.flush import MemoryFlusher
from autonoma.memory.store import MemoryStore
from autonoma.models import create_provider

logger = logging.getLogger("autonoma")


async def run(config_path: str | None = None, log_level: str | None = None) -> None:
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

    # 2. Validate API key
    if not config.llm.api_key:
        logger.error(
            "No API key configured. Set ANTHROPIC_API_KEY or AUTONOMA_LLM_API_KEY "
            "in your environment or .env file."
        )
        sys.exit(1)

    logger.info("Starting %s (provider=%s, model=%s)", config.name, config.llm.provider, config.llm.model)

    # 3. Create LLM provider
    provider = create_provider(config.llm)

    # 4. Create memory store
    memory_store = MemoryStore(config.workspace_dir)

    # 5. Create session manager
    session_manager = SessionManager(config.session_dir)

    # 6. Create context assembler
    context_assembler = ContextAssembler(config.workspace_dir, memory_store)

    # 7. Create agent
    agent = Agent(config, provider, memory_store, session_manager, context_assembler)

    # 8. Create agent router
    agent_router = AgentRouter()
    agent_router.register(config.name, agent, default=True)

    # 9. Create gateway router
    gateway_router = GatewayRouter(agent_router)

    # 10. Create gateway server
    auth = AuthMiddleware()
    server = GatewayServer(config.gateway, gateway_router, auth)

    # 11. Register CLI channel
    cli_channel = CLIChannel(agent_name=config.name)
    server.register_channel(cli_channel)

    # 12. Start everything
    async with MemoryFlusher(memory_store):
        await server.start()

        try:
            # Wait for the CLI channel to finish (user types /quit)
            await server.wait_for_channels()
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        finally:
            await server.stop()

    logger.info("Autonoma shut down cleanly.")


def cli_entry() -> None:
    """Synchronous entry point for the `autonoma` console script."""
    parser = argparse.ArgumentParser(
        description="Autonoma — AI Agent Platform"
    )
    parser.add_argument(
        "-c", "--config", default=None, help="Path to config YAML file"
    )
    parser.add_argument(
        "--log-level",
        default=None,
        choices=["debug", "info", "warning", "error"],
        help="Log level override",
    )
    args = parser.parse_args()

    try:
        asyncio.run(run(config_path=args.config, log_level=args.log_level))
    except KeyboardInterrupt:
        print("\nGoodbye.")


if __name__ == "__main__":
    cli_entry()
