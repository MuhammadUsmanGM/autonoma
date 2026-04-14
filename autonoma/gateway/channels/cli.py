"""Terminal channel adapter using rich for formatted output."""

from __future__ import annotations

import asyncio
import logging

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

from autonoma.gateway.channels.base import ChannelAdapter, MessageHandler
from autonoma.schema import AgentResponse, Message

logger = logging.getLogger(__name__)


class CLIChannel(ChannelAdapter):
    """Interactive terminal channel with tool execution display."""

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

            # Clear thinking indicator
            self._console.print(" " * 60, end="\r")

            # Show tool execution trace if any
            self._display_tool_trace(response)

            # Show final response
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
        try:
            return input("You > ")
        except EOFError:
            return None

    def _display_tool_trace(self, response: AgentResponse) -> None:
        """Show tool calls that were executed during processing."""
        tool_calls = response.metadata.get("tool_calls", [])
        if not tool_calls:
            return

        for tc in tool_calls:
            tool_name = tc.get("tool", "unknown")
            tool_input = tc.get("input", {})
            is_error = tc.get("is_error", False)
            result_preview = tc.get("result", "")[:150]

            # Tool call header
            icon = "[red]x[/red]" if is_error else "[green]v[/green]"
            input_summary = self._summarize_input(tool_input)

            self._console.print(
                f"  {icon} [bold yellow]{tool_name}[/bold yellow] {input_summary}",
            )
            if result_preview:
                # Show a short preview of the result
                preview = result_preview.replace("\n", " ")[:100]
                self._console.print(f"    [dim]{preview}[/dim]")

        self._console.print()

    def _display_response(self, content: str) -> None:
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

    @staticmethod
    def _summarize_input(params: dict) -> str:
        """Create a short summary of tool input params."""
        if not params:
            return ""
        parts = []
        for k, v in params.items():
            val = str(v)
            if len(val) > 40:
                val = val[:40] + "..."
            parts.append(f"{k}={val}")
        return "[dim](" + ", ".join(parts) + ")[/dim]"
