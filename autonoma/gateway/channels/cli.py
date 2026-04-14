"""Terminal channel adapter using rich for formatted output."""

from __future__ import annotations

import asyncio
import logging
import sys

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

from autonoma.gateway.channels.base import ChannelAdapter, MessageHandler
from autonoma.schema import Message

logger = logging.getLogger(__name__)


class CLIChannel(ChannelAdapter):
    """Interactive terminal channel — the primary interface for Phase 1."""

    def __init__(self, agent_name: str = "Autonoma"):
        self._console = Console()
        self._running = False
        self._agent_name = agent_name

    @property
    def name(self) -> str:
        return "cli"

    async def start(self, message_handler: MessageHandler) -> None:
        """Run the interactive terminal loop."""
        self._running = True
        self._print_welcome()

        while self._running:
            try:
                user_input = await asyncio.to_thread(self._read_input)
            except (EOFError, KeyboardInterrupt):
                break

            if user_input is None:
                break
            if user_input.strip().lower() in ("/quit", "/exit"):
                self._console.print("\n[dim]Goodbye.[/dim]\n")
                break
            if not user_input.strip():
                continue

            message = Message(
                channel="cli",
                channel_id="cli_main",
                user_id="cli_user",
                user_name="User",
                content=user_input,
            )

            # Show thinking indicator
            self._console.print(
                f"[dim]{self._agent_name} is thinking...[/dim]", end="\r"
            )

            response = await message_handler(message)
            self._display_response(response.content)

        self._running = False

    async def stop(self) -> None:
        self._running = False

    async def send(self, content: str) -> None:
        self._console.print(Markdown(content))

    def _print_welcome(self) -> None:
        banner = Text()
        banner.append(f"\n  {self._agent_name}", style="bold cyan")
        banner.append(" v0.1.0\n", style="dim")
        banner.append("  Digital FTE — Ready to work\n", style="dim")
        banner.append("  Type /quit to exit\n", style="dim italic")

        self._console.print(Panel(banner, border_style="cyan", expand=False))
        self._console.print()

    def _read_input(self) -> str | None:
        """Blocking stdin read — runs in a thread via asyncio.to_thread."""
        try:
            return input("You > ")
        except EOFError:
            return None

    def _display_response(self, content: str) -> None:
        # Clear the "thinking" line
        self._console.print(" " * 60, end="\r")
        # Render response as markdown
        self._console.print()
        self._console.print(
            Panel(
                Markdown(content),
                title=self._agent_name,
                title_align="left",
                border_style="green",
                padding=(1, 2),
            )
        )
        self._console.print()
