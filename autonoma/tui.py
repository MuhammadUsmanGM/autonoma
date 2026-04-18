"""Autonoma TUI — control tower: auto-start agent, live log panel, hotkey actions."""

from __future__ import annotations

import asyncio
import getpass
import os
import re
import sys
import time
import webbrowser
from pathlib import Path

from dotenv import load_dotenv, set_key
from rich.align import Align
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from autonoma.config import load_config, save_yaml_config
from autonoma.runtime import AgentRunner, LogRingBuffer, install_logging

BANNER = r"""
    ___         __
   /   | __  __/ /_____  ____  ____  ____ ___  ____ _
  / /| |/ / / / __/ __ \/ __ \/ __ \/ __ `__ \/ __ `/
 / ___ / /_/ / /_/ /_/ / / / / /_/ / / / / / / /_/ /
/_/  |_\__,_/\__/\____/_/ /_/\____/_/ /_/ /_/\__,_/
"""

def _resolve_workspace() -> Path:
    """Pick the directory that holds .env / autonoma.yaml / .session/ for this
    run. $AUTONOMA_HOME wins if set; otherwise use the cwd captured at import
    time. The path is resolved ONCE at module load so later os.chdir() calls
    cannot split a single session across two workspaces.
    """
    override = os.environ.get("AUTONOMA_HOME")
    if override:
        return Path(override).expanduser().resolve()
    return Path(os.getcwd()).resolve()


WORKSPACE = _resolve_workspace()
ENV_PATH = WORKSPACE / ".env"
YAML_PATH = WORKSPACE / "autonoma.yaml"
LOG_FILE = WORKSPACE / ".session" / "autonoma.log"

CHANNEL_ENV = {
    "telegram": ["TELEGRAM_BOT_TOKEN"],
    "discord": ["DISCORD_BOT_TOKEN"],
    "whatsapp": ["WHATSAPP_BRIDGE_URL"],
    "gmail": ["GMAIL_ADDRESS", "GMAIL_APP_PASSWORD"],
    "rest": ["AUTONOMA_REST_API_TOKEN"],
}

CHANNEL_DESCRIPTIONS = {
    "telegram": "Telegram bot",
    "discord": "Discord bot",
    "whatsapp": "WhatsApp via local bridge",
    "gmail": "Gmail IMAP/SMTP",
    "rest": "REST API (HTTP token)",
}

PROVIDERS = [
    ("openrouter", "OpenRouter (recommended — one key, many models)"),
    ("anthropic", "Anthropic (direct Claude API)"),
]

MODEL_SUGGESTIONS = {
    "openrouter": [
        "anthropic/claude-sonnet-4.5",
        "anthropic/claude-haiku-4.5",
        "openai/gpt-4o-mini",
        "google/gemini-2.0-flash-exp",
    ],
    "anthropic": [
        "claude-sonnet-4-6",
        "claude-haiku-4-5-20251001",
        "claude-opus-4-6",
    ],
}

# --- Keys ---
KEY_UP = "UP"
KEY_DOWN = "DOWN"
KEY_LEFT = "LEFT"
KEY_RIGHT = "RIGHT"
KEY_ENTER = "ENTER"
KEY_ESC = "ESC"
KEY_CTRL_C = "CTRL_C"
KEY_PGUP = "PGUP"
KEY_PGDN = "PGDN"
KEY_HOME = "HOME"
KEY_END = "END"


def read_key(timeout: float | None = None) -> str:
    """Read a keypress. Returns key code or raw char. timeout=None blocks."""
    if os.name == "nt":
        import msvcrt

        def _peek(ms: int = 50) -> bool:
            """Wait up to `ms` for more input. Returns True if available."""
            end = time.time() + ms / 1000.0
            while not msvcrt.kbhit():
                if time.time() >= end:
                    return False
                time.sleep(0.002)
            return True

        if timeout is not None:
            deadline = time.time() + timeout
            while not msvcrt.kbhit():
                if time.time() >= deadline:
                    return ""
                time.sleep(0.02)
        ch = msvcrt.getch()
        if ch == b"\x03":
            return KEY_CTRL_C
        if ch in (b"\r", b"\n"):
            return KEY_ENTER
        # Old-style extended key: scan-code pair (legacy conhost / no VT)
        if ch in (b"\x00", b"\xe0"):
            ch2 = msvcrt.getch()
            return {
                b"H": KEY_UP, b"P": KEY_DOWN,
                b"K": KEY_LEFT, b"M": KEY_RIGHT,
                b"I": KEY_PGUP, b"Q": KEY_PGDN,
                b"G": KEY_HOME, b"O": KEY_END,
            }.get(ch2, "")
        # VT escape sequence (Windows Terminal / VT input mode)
        if ch == b"\x1b":
            if not _peek(50):
                return KEY_ESC  # standalone ESC
            ch2 = msvcrt.getch()
            if ch2 != b"[":
                return KEY_ESC
            if not _peek(50):
                return KEY_ESC
            ch3 = msvcrt.getch()
            arrows = {
                b"A": KEY_UP, b"B": KEY_DOWN,
                b"C": KEY_RIGHT, b"D": KEY_LEFT,
                b"H": KEY_HOME, b"F": KEY_END,
            }
            if ch3 in arrows:
                return arrows[ch3]
            # PgUp/PgDn: ESC [ 5 ~ / ESC [ 6 ~
            if ch3 == b"5":
                if _peek(50):
                    msvcrt.getch()
                return KEY_PGUP
            if ch3 == b"6":
                if _peek(50):
                    msvcrt.getch()
                return KEY_PGDN
            return KEY_ESC
        try:
            return ch.decode("utf-8", errors="ignore").lower()
        except Exception:
            return ""
    else:
        import select
        import termios
        import tty
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            if timeout is not None:
                if not select.select([sys.stdin], [], [], timeout)[0]:
                    return ""
            ch = sys.stdin.read(1)
            if ch == "\x03": return KEY_CTRL_C
            if ch in ("\r", "\n"): return KEY_ENTER
            if ch == "\x1b":
                # Look for a CSI (ESC [) sequence. If the next byte is NOT '[',
                # the user pressed either standalone ESC or Alt+<letter>. In
                # either case we treat the keystroke as ESC and do NOT consume
                # the follow-up byte, so the menu gets its "back" semantics
                # without silently eating an Alt-combination's letter.
                if not select.select([sys.stdin], [], [], 0.05)[0]:
                    return KEY_ESC
                # Peek: only advance past '[' once we know a CSI is starting.
                # We can't unread on a raw tty, so we take the '[' (committing
                # to CSI) and then read ch3. If ch3 is unrecognized we still
                # return KEY_ESC but only one stray byte was consumed.
                ch2 = sys.stdin.read(1)
                if ch2 != "[":
                    return KEY_ESC  # Alt+ch2 or lone ESC — drop ch2 quietly
                if not select.select([sys.stdin], [], [], 0.05)[0]:
                    return KEY_ESC
                ch3 = sys.stdin.read(1)
                arrows = {
                    "A": KEY_UP, "B": KEY_DOWN,
                    "C": KEY_RIGHT, "D": KEY_LEFT,
                }
                if ch3 in arrows:
                    return arrows[ch3]
                if ch3 == "5":
                    # Consume trailing '~' if present
                    if select.select([sys.stdin], [], [], 0.05)[0]:
                        sys.stdin.read(1)
                    return KEY_PGUP
                if ch3 == "6":
                    if select.select([sys.stdin], [], [], 0.05)[0]:
                        sys.stdin.read(1)
                    return KEY_PGDN
                if ch3 == "H": return KEY_HOME
                if ch3 == "F": return KEY_END
                return KEY_ESC
            return ch.lower()
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)


class BackSignal(Exception):
    """Pop back one screen (ESC)."""


class AutonomaTUI:
    """Control tower TUI — auto-starts agent, shows live logs, hotkey actions."""

    def __init__(self) -> None:
        self.console = Console()
        # Snapshot the workspace paths on this instance so every method routes
        # through the same directory, regardless of any later os.chdir() calls
        # or external module-level patching.
        self.workspace: Path = WORKSPACE
        self.env_path: Path = ENV_PATH
        self.yaml_path: Path = YAML_PATH
        self.log_file: Path = LOG_FILE
        self.env_path.parent.mkdir(parents=True, exist_ok=True)
        self.env_path.touch(exist_ok=True)
        load_dotenv(self.env_path, override=True)
        self.log_ring: LogRingBuffer | None = None
        self.runner: AgentRunner | None = None
        # Config cache: (env_mtime, yaml_mtime) -> Config | None. Invalidated
        # automatically when either file changes on disk, and explicitly by
        # _invalidate_config_cache() after we mutate them.
        self._config_cache_key: tuple[float, float] | None = None
        self._config_cache_value = None
        # .env load cache: keyed by mtime. Avoids hitting disk 5× per
        # channel-menu frame when rendering the credentials column.
        self._env_loaded_mtime: float | None = None

    # ----- Entry point -----

    def run(self) -> None:
        try:
            # Forced first-run setup
            if self._is_first_run():
                self._print_banner()
                self.console.print(
                    Panel(
                        "[bold yellow]Welcome to Autonoma![/]\n\n"
                        "No API key found — you must complete setup before the agent can start.\n"
                        "[dim]Press Ctrl+C to quit without setting up.[/]",
                        border_style="yellow",
                    )
                )
                self._setup_wizard(forced=True)

            # Install logging (before agent starts)
            self.log_ring = install_logging(
                log_file=str(self.log_file), level="INFO"
            )

            # Auto-start the agent in a background thread
            self.runner = AgentRunner()
            self.runner.start()

            # Enter the control tower
            self._control_tower()
        except KeyboardInterrupt:
            pass
        finally:
            self._shutdown()

    def _shutdown(self) -> None:
        if self.runner and self.runner.status() not in ("stopped",):
            self.console.clear()
            self.console.print("[yellow]Stopping agent…[/]")
            self.runner.stop()
        self.console.print("[dim]Goodbye.[/]\n")

    # ----- Main menu -----

    def _control_tower(self) -> None:
        """Arrow-key navigable main menu. Agent runs in background."""
        items = [
            ("Live logs", self._logs_viewer),
            ("Manage configuration", self._manage_menu),
            ("Manage channels", self._manage_channels),
            ("Open web dashboard", self._open_dashboard),
            ("Check status", self._show_status),
            ("Restart Autonoma", self._restart_agent),
            ("Quit", None),
        ]
        selected = 0
        while True:
            selected = self._arrow_select(
                title=None,
                items=[label for label, _ in items],
                selected=selected,
                header_renderer=self._render_main_header,
                allow_back=False,
            )
            if selected is None or items[selected][1] is None:
                return
            try:
                items[selected][1]()
            except BackSignal:
                continue

    def _render_main_header(self) -> None:
        """Banner + compact status panel at top of the main menu."""
        self._print_banner()

        cfg = self._safe_load_config()
        runner = self.runner
        status = runner.status() if runner else "stopped"
        err = runner.error() if runner else None
        uptime = runner.uptime() if runner else 0

        status_colors = {
            "running": "green",
            "starting": "yellow",
            "stopping": "yellow",
            "stopped": "dim",
            "error": "red",
        }
        status_color = status_colors.get(status, "white")
        status_text = Text()
        status_text.append("● ", style=status_color)
        status_text.append(status.upper(), style=f"bold {status_color}")
        if err:
            status_text.append(f"  {err}", style="red")

        info = Table.grid(padding=(0, 2))
        info.add_column(style="dim")
        info.add_column()
        info.add_row("Status", status_text)
        info.add_row("Uptime", self._fmt_uptime(uptime))
        if cfg:
            info.add_row(
                "Provider", f"[bold]{cfg.llm.provider}[/] · {cfg.llm.model}"
            )
            enabled = self._enabled_channels(cfg)
            info.add_row(
                "Channels",
                ", ".join(enabled) if enabled else "[dim](none — CLI only)[/]",
            )
            info.add_row(
                "Dashboard",
                f"[cyan]http://{cfg.gateway.host}:{cfg.gateway.http_port}[/]",
            )
        self.console.print(Panel(info, border_style=status_color, title="Autonoma"))
        self.console.print()

    # ----- [L] Logs viewer -----

    def _logs_viewer(self) -> None:
        """Fullscreen live-tailing log view. ESC or Q to exit."""
        refresh_hz = 6
        tick = 1.0 / refresh_hz
        with Live(
            self._render_logs(tail_only=True, scroll=0),
            console=self.console,
            refresh_per_second=refresh_hz,
            screen=True,
        ) as live:
            scroll = 0
            follow = True  # auto-scroll to bottom
            while True:
                # Key poll timeout matches the refresh tick so we always hand
                # Live a fresh renderable on every frame — without this, logs
                # appear frozen between keypresses because Live re-renders the
                # same Group it was last handed.
                key = read_key(timeout=tick)

                if key == KEY_ESC or key == "q":
                    break
                if key == KEY_CTRL_C:
                    raise KeyboardInterrupt
                if key == KEY_UP:
                    scroll += 1; follow = False
                elif key == KEY_DOWN:
                    scroll = max(0, scroll - 1)
                    if scroll == 0:
                        follow = True
                elif key == KEY_PGUP:
                    scroll += 20; follow = False
                elif key == KEY_PGDN:
                    scroll = max(0, scroll - 20)
                    if scroll == 0:
                        follow = True
                elif key == KEY_HOME:
                    scroll = 10_000_000; follow = False
                elif key == KEY_END:
                    scroll = 0; follow = True
                elif key == "c":
                    if self.log_ring:
                        self.log_ring.clear()
                    scroll = 0; follow = True

                # Always push a fresh renderable — whether a key was pressed
                # or the timeout fired — so newly arrived log lines stream in.
                live.update(self._render_logs(tail_only=follow, scroll=scroll))
        # Live(screen=True) exits the alt-screen which can leave stray bytes
        # (cursor reports, the ESC we just read, etc.) in stdin. Drain them
        # so the next menu frame doesn't consume a stale keystroke.
        self._drain_stdin()

    def _render_logs(self, *, tail_only: bool, scroll: int):
        size = self.console.size
        body_height = max(5, size.height - 4)

        all_lines = self.log_ring.all() if self.log_ring else []
        if not all_lines:
            body = "[dim](no log entries yet — waiting for agent activity…)[/]"
        else:
            if tail_only:
                shown = all_lines[-body_height:]
            else:
                end = len(all_lines) - scroll
                start = max(0, end - body_height)
                shown = all_lines[start:end]
            body = "\n".join(shown)

        title = f"Logs ({len(all_lines)} entries)"
        if not tail_only:
            title += f" · scrolled {scroll}"

        footer = Text(
            " ↑/↓ scroll · PgUp/PgDn page · End tail · C clear · ESC back ",
            style="dim",
        )
        return Group(
            Panel(body, title=title, border_style="cyan"),
            Align.center(footer),
        )

    # ----- [D] Dashboard -----

    def _open_dashboard(self) -> None:
        cfg = self._safe_load_config()
        port = cfg.gateway.http_port if cfg else 8766
        host = cfg.gateway.host if cfg else "127.0.0.1"
        url = f"http://localhost:{port}"
        self.console.clear()
        self._print_banner()
        self.console.print(Rule("[bold]Dashboard[/]", style="cyan"))

        # Probe before opening the browser so the user sees a useful message
        # when the HTTP server isn't up yet (e.g. agent still starting).
        import socket
        try:
            with socket.create_connection((host, port), timeout=0.5):
                reachable = True
        except OSError:
            reachable = False

        self.console.print(f"\nOpening [cyan]{url}[/]…")
        if not reachable:
            self.console.print(
                "[yellow]⚠ Dashboard not reachable yet — the agent may still "
                "be starting. Opening anyway.[/]"
            )
        try:
            webbrowser.open(url)
            self.console.print("[green]✓ Browser launched.[/]")
        except Exception as e:
            self.console.print(f"[red]Could not open browser:[/] {e}")
        # Brief dwell so the message is visible, then auto-return to the
        # main menu. No "press any key" gate — ESC would otherwise be eaten
        # by _pause and the user would have to press it twice to go back.
        time.sleep(0.9)
        self._drain_stdin()

    # ----- [M] Manage (stops agent, shows menu, restarts) -----

    def _manage_menu(self) -> None:
        """Manage configuration submenu. Stops the agent for the duration
        so YAML/env writes can't race with the running channels."""
        def body() -> None:
            while True:
                idx = self._arrow_select(
                    title="[bold]Manage[/]",
                    items=[
                        "Setup (provider / API key / model)",
                        "Channels (enable, disable, configure)",
                        "Back to control tower",
                    ],
                    header_renderer=self._print_banner,
                    allow_back=True,
                )
                if idx is None or idx == 2:
                    break
                if idx == 0:
                    try:
                        self._setup_wizard()
                    except BackSignal:
                        pass
                elif idx == 1:
                    try:
                        self._channel_menu()
                    except BackSignal:
                        pass
        self._with_agent_stopped(body)

    def _manage_channels(self) -> None:
        """Top-level shortcut straight into the channel menu.

        Same safety wrapper as `_manage_menu` — we stop the agent before
        editing .env / autonoma.yaml so toggles/credential writes apply
        cleanly on restart, then relaunch the agent on exit.
        """
        def body() -> None:
            try:
                self._channel_menu()
            except BackSignal:
                pass
        self._with_agent_stopped(body)

    def _with_agent_stopped(self, body) -> None:
        """Run `body()` with the agent stopped, then restart it if it had
        been running. Any exception in body still triggers the restart."""
        was_running = self.runner is not None and self.runner.is_running()
        if was_running and self.runner is not None:
            self.console.clear()
            self.console.print(
                Panel(
                    "[yellow]Stopping agent to safely change configuration…[/]",
                    border_style="yellow",
                )
            )
            self.runner.stop()
        try:
            body()
        finally:
            if was_running:
                self.console.clear()
                self.console.print("[green]Restarting agent with new config…[/]")
                self.runner = AgentRunner()
                self.runner.start()
                time.sleep(0.5)

    # ----- [R] Restart -----

    def _restart_agent(self) -> None:
        if not self.runner:
            return
        self.console.clear()
        self.console.print("[yellow]Restarting agent…[/]")
        self.runner.stop()
        self.runner = AgentRunner()
        self.runner.start()
        time.sleep(0.5)

    # ----- [S] Status -----

    def _show_status(self) -> None:
        self._print_banner()
        self.console.print(Rule("[bold]Status[/]", style="cyan"))
        cfg = self._safe_load_config()
        if not cfg:
            self.console.print("[red]Could not load config.[/]")
            self._pause()
            return

        cfg_table = Table(show_header=False, box=None, padding=(0, 2))
        cfg_table.add_column(style="dim")
        cfg_table.add_column()
        cfg_table.add_row("Name", cfg.name)
        cfg_table.add_row("Provider", cfg.llm.provider)
        cfg_table.add_row("Model", cfg.llm.model)
        cfg_table.add_row(
            "API key",
            "[green]✓ configured[/]" if cfg.llm.api_key else "[red]✗ missing[/]",
        )
        cfg_table.add_row("Gateway", f"{cfg.gateway.host}:{cfg.gateway.port}")
        cfg_table.add_row(
            "Dashboard", f"http://{cfg.gateway.host}:{cfg.gateway.http_port}"
        )
        cfg_table.add_row("Workspace", cfg.workspace_dir)
        cfg_table.add_row("Memory DB", cfg.memory.db_path)
        cfg_table.add_row("Log file", str(self.log_file))
        self.console.print(Panel(cfg_table, title="Configuration", border_style="cyan"))

        ch_table = Table(show_header=True, header_style="bold cyan", box=None)
        ch_table.add_column("Channel")
        ch_table.add_column("Enabled")
        for name in CHANNEL_ENV:
            ch_table.add_row(
                name, "[green]✓[/]" if self._channel_enabled(name) else "[dim]—[/]"
            )
        self.console.print(Panel(ch_table, title="Channels", border_style="cyan"))

        try:
            from autonoma.memory.database import MemoryDatabase
            Path(cfg.memory.db_path).parent.mkdir(parents=True, exist_ok=True)
            db = MemoryDatabase(cfg.memory.db_path)
            total_active = db.count(active_only=True)
            total_all = db.count(active_only=False)
            expiry = db.get_expiry_stats()
            db.close()
            mem_table = Table(show_header=False, box=None, padding=(0, 2))
            mem_table.add_column(style="dim")
            mem_table.add_column()
            mem_table.add_row("Active memories", str(total_active))
            mem_table.add_row("Archived", str(total_all - total_active))
            mem_table.add_row("Stale (needs review)", str(expiry.get("stale", 0)))
            mem_table.add_row("Expired", str(expiry.get("expired", 0)))
            self.console.print(Panel(mem_table, title="Memory", border_style="cyan"))
        except Exception as e:
            self.console.print(f"[dim]Memory stats unavailable: {e}[/]")

        self._pause()

    # ----- Setup wizard -----

    def _setup_wizard(self, forced: bool = False) -> None:
        idx = self._arrow_select(
            title="[bold]Step 1 of 3 — LLM provider[/]",
            items=[f"{name}  —  {desc}" for name, desc in PROVIDERS],
            header_renderer=self._print_banner,
            allow_back=not forced,
        )
        if idx is None:
            return
        provider, _ = PROVIDERS[idx]
        env_key_name = (
            "OPENROUTER_API_KEY" if provider == "openrouter" else "ANTHROPIC_API_KEY"
        )

        self._print_banner()
        self.console.print(Rule("[bold]Step 2 of 3 — API key[/]", style="cyan"))
        self.console.print(f"Will be saved to .env as [cyan]{env_key_name}[/]")
        if forced:
            # On first run we MUST get a key — the agent cannot start without
            # one and the TUI would otherwise sit on a permanent ERROR status.
            self.console.print(
                "[dim]Input is hidden. Ctrl+C to quit without setting up.[/]\n"
            )
        else:
            self.console.print(
                "[dim]Input is hidden. Press Enter with empty input to skip.[/]\n"
            )

        while True:
            try:
                api_key = getpass.getpass("  › ").strip()
            except (EOFError, KeyboardInterrupt):
                # Forced first-run: let the outer run() handler quit the TUI
                # cleanly — the user explicitly chose to abort setup.
                if forced:
                    raise
                return

            if api_key or not forced:
                break

            # Forced + empty: re-prompt rather than saving a half-configured
            # provider with no key (which would leave _is_first_run lying).
            self.console.print(
                "[red]An API key is required to continue.[/] "
                "[dim]Press Ctrl+C to quit instead.[/]"
            )

        suggestions = MODEL_SUGGESTIONS[provider]
        options = list(suggestions) + ["Custom (type your own)"]
        idx = self._arrow_select(
            title=f"[bold]Step 3 of 3 — Model[/] [dim](provider: {provider})[/]",
            items=options,
            header_renderer=self._print_banner,
            allow_back=not forced,
        )
        if idx is None:
            return
        if idx == len(suggestions):
            self._print_banner()
            self.console.print(Rule("[bold]Custom model[/]", style="cyan"))
            try:
                model = self.console.input("Model identifier: ").strip()
            except (EOFError, KeyboardInterrupt):
                return
            if not model:
                return
        else:
            model = suggestions[idx]

        self._set_env("AUTONOMA_LLM_PROVIDER", provider)
        self._set_env("AUTONOMA_LLM_MODEL", model)
        if api_key:
            self._set_env(env_key_name, api_key)
        save_yaml_config(self.yaml_path, {"llm": {"provider": provider, "model": model}})
        self._invalidate_config_cache()

        self._print_banner()
        self.console.print(
            Panel(
                f"[green]✓ Saved.[/]\nProvider: [bold]{provider}[/]\nModel: [bold]{model}[/]",
                border_style="green",
            )
        )
        self._pause()

    # ----- Channel menu -----

    def _channel_menu(self) -> None:
        channels = list(CHANNEL_ENV.keys())
        selected = 0
        while True:
            def header():
                self._print_banner()
                self.console.print(Rule("[bold]Channels[/]", style="cyan"))
                table = Table(show_header=True, header_style="bold cyan", box=None)
                table.add_column("Channel")
                table.add_column("Status")
                table.add_column("Credentials")
                for name in channels:
                    on = self._channel_enabled(name)
                    table.add_row(
                        name,
                        "[green]● enabled[/]" if on else "[dim]○ disabled[/]",
                        self._credential_preview(name),
                    )
                self.console.print(table)
                self.console.print()

            items = [
                f"{name:<10} — {'disable' if self._channel_enabled(name) else 'enable'} / configure"
                for name in channels
            ]
            idx = self._arrow_select(
                title=None,
                items=items,
                selected=selected,
                header_renderer=header,
                allow_back=True,
            )
            if idx is None:
                return
            selected = idx
            self._channel_action_prompt(channels[idx])

    def _channel_action_prompt(self, name: str) -> None:
        idx = self._arrow_select(
            title=f"[bold]{name}[/]",
            items=[
                "Toggle enable/disable",
                "Configure credentials",
                "Reconnect (clear session & re-auth)",
            ],
            header_renderer=self._print_banner,
            allow_back=True,
        )
        if idx == 0:
            self._toggle_channel(name)
        elif idx == 1:
            self._configure_channel(name)
        elif idx == 2:
            self._reconnect_channel(name)

    def _reconnect_channel(self, name: str) -> None:
        """Force a fresh login for `name`.

        Covers the case where the remote side has dropped us (phone logged
        out of WhatsApp, bot token revoked, Gmail app password rotated) but
        local state still looks valid. For WhatsApp we wipe the persisted
        whatsapp-web.js session directory — otherwise the bridge will try
        to resume a dead session forever. For token-only channels we reopen
        the credential prompt so the user can paste a fresh token.
        """
        self._print_banner()
        self.console.print(Rule(f"[bold]Reconnect {name}[/]", style="cyan"))

        cleared_paths: list[Path] = []
        if name == "whatsapp":
            # whatsapp-web.js LocalAuth persists under whatsapp-bridge/.
            # Wipe both auth and cache so the bridge shows a new QR on
            # next launch.
            bridge_dir = self.workspace / "whatsapp-bridge"
            import shutil
            for sub in (".wwebjs_auth", ".wwebjs_cache"):
                target = bridge_dir / sub
                if target.exists():
                    try:
                        shutil.rmtree(target)
                        cleared_paths.append(target)
                    except OSError as e:
                        self.console.print(
                            f"[red]Could not remove {target}: {e}[/]"
                        )
            if cleared_paths:
                self.console.print(
                    "[green]✓ Cleared local WhatsApp session:[/]"
                )
                for p in cleared_paths:
                    self.console.print(f"  [dim]{p}[/]")
            else:
                self.console.print(
                    "[dim]No cached WhatsApp session found on disk — nothing to wipe.[/]"
                )
            self.console.print(
                "\n[bold]Next:[/] restart Autonoma and watch the bridge output — "
                "it will print a fresh QR code for your phone to scan."
            )
            # Make sure the bridge URL is present so the agent actually
            # starts the bridge. If the user cleared it, reprompt.
            if not os.getenv("WHATSAPP_BRIDGE_URL"):
                self.console.print(
                    "\n[yellow]WHATSAPP_BRIDGE_URL is not set — configure it now:[/]"
                )
                self._configure_channel(name)
            self._pause()
            return

        # Token/password channels: the "reconnect" story is just
        # "re-enter the credential". Walk the user through configure, then
        # flip the channel off-and-on so the runtime picks up the new
        # values on next start.
        self.console.print(
            f"[dim]Reconnect for [bold]{name}[/] means re-entering its "
            f"credentials. The old values will be overwritten.[/]\n"
        )
        self._configure_channel(name)
        # Force a disable→enable cycle so the runtime re-initializes the
        # client with the new credential on next agent start.
        if self._channel_enabled(name):
            for var in CHANNEL_ENV[name]:
                self._disable_env(var)
            for var in CHANNEL_ENV[name]:
                self._enable_env(var)
            self._set_channel_enabled_in_yaml(name, True)
            self.console.print(
                f"\n[green]✓ {name} credentials rotated. "
                f"Restart Autonoma to apply.[/]"
            )
        self._pause(short=True)

    def _ensure_env_loaded(self) -> None:
        """Reload .env into os.environ only if the file changed on disk."""
        try:
            mtime = self.env_path.stat().st_mtime if self.env_path.exists() else 0.0
        except OSError:
            mtime = 0.0
        if mtime != self._env_loaded_mtime:
            load_dotenv(self.env_path, override=True)
            self._env_loaded_mtime = mtime

    def _channel_enabled(self, name: str) -> bool:
        self._ensure_env_loaded()
        return all(os.getenv(v) for v in CHANNEL_ENV[name])

    def _credential_preview(self, name: str) -> str:
        self._ensure_env_loaded()
        parts = []
        for var in CHANNEL_ENV[name]:
            val = os.getenv(var, "")
            if not val:
                parts.append(f"[dim]{var}=?[/]")
            else:
                parts.append(f"{var}=[green]{self._mask(val)}[/]")
        return " ".join(parts)

    def _set_channel_enabled_in_yaml(self, name: str, enabled: bool) -> None:
        """Persist cfg.channels.<name>.enabled so the agent honors the toggle
        on its next start. The env-var flip alone is not enough — the runtime
        reads this yaml field to decide which channels to wire up."""
        save_yaml_config(
            self.yaml_path,
            {"channels": {name: {"enabled": bool(enabled)}}},
        )
        self._invalidate_config_cache()

    def _toggle_channel(self, name: str) -> None:
        if self._channel_enabled(name):
            for var in CHANNEL_ENV[name]:
                self._disable_env(var)
            self._set_channel_enabled_in_yaml(name, False)
            self.console.print(f"\n[yellow]✓ {name} disabled.[/]")
        else:
            reenabled = False
            for var in CHANNEL_ENV[name]:
                if self._enable_env(var):
                    reenabled = True
            if reenabled:
                self._set_channel_enabled_in_yaml(name, True)
                self.console.print(f"\n[green]✓ {name} re-enabled.[/]")
            else:
                self.console.print(
                    f"\n[dim]No saved credentials. Launching configuration…[/]"
                )
                self._configure_channel(name)
                # After credentials are saved, mirror the enable flag to yaml
                # only if the user actually provided the required vars.
                if self._channel_enabled(name):
                    self._set_channel_enabled_in_yaml(name, True)
                return
        self._pause(short=True)

    def _configure_channel(self, name: str) -> None:
        self._print_banner()
        self.console.print(Rule(f"[bold]Configure {name}[/]", style="cyan"))
        self.console.print(f"[dim]{CHANNEL_DESCRIPTIONS.get(name, '')}[/]\n")
        for var in CHANNEL_ENV[name]:
            current = os.getenv(var, "")
            is_secret = any(s in var for s in ("TOKEN", "PASSWORD", "KEY", "SECRET"))
            label = f"[bold]{var}[/]"
            if current:
                label += f" [dim](current: {self._mask(current)})[/]"
            self.console.print(label)
            try:
                if is_secret:
                    self.console.print("[dim]Input hidden. Enter to keep current.[/]")
                    value = getpass.getpass("  › ").strip()
                else:
                    value = self.console.input("  › ").strip()
            except (EOFError, KeyboardInterrupt):
                return
            if value:
                self._set_env(var, value)
        self.console.print(f"\n[green]✓ {name} configured.[/]")
        self._pause(short=True)

    # ----- Primitives -----

    def _arrow_select(
        self,
        *,
        title: str | None,
        items: list[str],
        selected: int = 0,
        header_renderer=None,
        allow_back: bool = True,
    ) -> int | None:
        if not items:
            return None
        # Clamp into range. Accepts negative indices (Python-style from the
        # end) for completeness and guards against any caller passing a
        # stale index after items were filtered down.
        if selected < 0:
            selected = max(0, len(items) + selected)
        if selected >= len(items):
            selected = 0
        while True:
            self.console.clear()
            if header_renderer:
                header_renderer()
            if title:
                self.console.print(Rule(title, style="cyan"))
                self.console.print()
            for i, label in enumerate(items):
                if i == selected:
                    self.console.print(f"  [bold cyan]▶ {label}[/]")
                else:
                    self.console.print(f"    [dim]{label}[/]")
            self.console.print()
            hint = "[dim]↑/↓ navigate · Enter select"
            if allow_back:
                hint += " · ESC back"
            hint += " · Ctrl+C quit[/]"
            self.console.print(hint)

            key = read_key()
            if key == KEY_CTRL_C:
                raise KeyboardInterrupt
            if key == KEY_ESC and allow_back:
                return None
            if key == KEY_UP:
                selected = (selected - 1) % len(items)
            elif key == KEY_DOWN:
                selected = (selected + 1) % len(items)
            elif key == KEY_ENTER:
                return selected

    def _print_banner(self) -> None:
        self.console.clear()
        self.console.print(Align.center(Text(BANNER, style="bold cyan")))
        self.console.print(
            Align.center(Text("AI Agent Platform · control panel", style="dim"))
        )
        self.console.print()

    # ----- Helpers -----

    @staticmethod
    def _mask(val: str) -> str:
        if len(val) <= 8:
            return "***"
        return val[:4] + "…" + val[-2:]

    @staticmethod
    def _fmt_uptime(sec: int) -> str:
        if sec <= 0:
            return "[dim]—[/]"
        h, rem = divmod(sec, 3600)
        m, s = divmod(rem, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"

    def _is_first_run(self) -> bool:
        load_dotenv(self.env_path, override=True)
        if any(
            os.getenv(k)
            for k in ("OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "AUTONOMA_LLM_API_KEY")
        ):
            return False
        # Also accept an inline api_key in autonoma.yaml — the config loader
        # supports it (cfg.llm.api_key), so a user who hand-configured the
        # YAML should not be pushed through the wizard again.
        cfg = self._safe_load_config()
        if cfg and getattr(cfg.llm, "api_key", None):
            return False
        return True

    def _safe_load_config(self):
        # Cache by (env_mtime, yaml_mtime) so repeat renders skip the disk +
        # YAML parse. A missing file mtime is reported as 0.0.
        try:
            env_m = self.env_path.stat().st_mtime if self.env_path.exists() else 0.0
            yaml_m = self.yaml_path.stat().st_mtime if self.yaml_path.exists() else 0.0
        except OSError:
            env_m = yaml_m = 0.0
        key = (env_m, yaml_m)
        if key == self._config_cache_key:
            return self._config_cache_value
        try:
            load_dotenv(self.env_path, override=True)
            cfg = load_config(str(self.yaml_path) if self.yaml_path.exists() else None)
        except Exception:
            cfg = None
        self._config_cache_key = key
        self._config_cache_value = cfg
        return cfg

    def _invalidate_config_cache(self) -> None:
        """Force both the config and .env caches to re-read on their next call.
        Call after any method that mutates .env or autonoma.yaml."""
        self._config_cache_key = None
        self._config_cache_value = None
        self._env_loaded_mtime = None

    def _enabled_channels(self, cfg) -> list[str]:
        out = []
        if cfg.channels.telegram.enabled: out.append("telegram")
        if cfg.channels.discord.enabled: out.append("discord")
        if cfg.channels.whatsapp.enabled: out.append("whatsapp")
        if cfg.channels.gmail.enabled: out.append("gmail")
        if cfg.channels.rest.enabled: out.append("rest")
        return out

    def _set_env(self, key: str, value: str) -> None:
        self.env_path.parent.mkdir(parents=True, exist_ok=True)
        self.env_path.touch(exist_ok=True)
        self._enable_env(key)
        # quote_mode="always" — unquoted values with spaces break `source .env`
        # in bash, and values containing '#' get parsed as comments by dotenv
        # itself. Always quoting preserves credentials with #, $, ", spaces, etc.
        set_key(str(self.env_path), key, value, quote_mode="always")
        os.environ[key] = value
        self._invalidate_config_cache()

    @staticmethod
    def _env_line_pattern(key: str) -> re.Pattern[str]:
        """Match a dotenv assignment for `key` with optional `export ` prefix
        and optional whitespace around `=`. Returns a compiled pattern whose
        match() anchors at the start of a stripped line."""
        return re.compile(rf"^(?:export\s+)?{re.escape(key)}\s*=")

    def _disable_env(self, key: str) -> bool:
        if not self.env_path.exists():
            return False
        lines = self.env_path.read_text(encoding="utf-8").splitlines()
        pattern = self._env_line_pattern(key)
        changed = False
        new_lines = []
        for line in lines:
            stripped = line.lstrip()
            if stripped.startswith("#"):
                new_lines.append(line)
                continue
            if pattern.match(stripped):
                new_lines.append(f"# {line}")
                changed = True
            else:
                new_lines.append(line)
        if changed:
            self.env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
            os.environ.pop(key, None)
            self._invalidate_config_cache()
        return changed

    @staticmethod
    def _unquote_dotenv_value(raw: str) -> str:
        """Decode a dotenv-style RHS into its literal string value.

        Handles double-quoted (with backslash escapes), single-quoted (literal),
        and bare values. Strips inline `# comment` tails from bare values only,
        matching python-dotenv's behavior.
        """
        s = raw.strip()
        if len(s) >= 2 and s[0] == s[-1] and s[0] in ('"', "'"):
            inner = s[1:-1]
            if s[0] == '"':
                # Minimal escape handling: \\ \" \n \r \t
                return (
                    inner.replace("\\\\", "\x00")
                         .replace('\\"', '"')
                         .replace("\\n", "\n")
                         .replace("\\r", "\r")
                         .replace("\\t", "\t")
                         .replace("\x00", "\\")
                )
            return inner  # single-quoted: literal
        # Bare: strip inline comment `  # ...`
        hash_idx = s.find(" #")
        if hash_idx >= 0:
            s = s[:hash_idx].rstrip()
        return s

    def _enable_env(self, key: str) -> bool:
        if not self.env_path.exists():
            return False
        lines = self.env_path.read_text(encoding="utf-8").splitlines()
        pattern = self._env_line_pattern(key)
        changed = False
        new_lines = []
        for line in lines:
            stripped = line.lstrip()
            if not stripped.startswith("#"):
                new_lines.append(line)
                continue
            body = stripped.lstrip("#").lstrip()
            if pattern.match(body):
                # Preserve the original body verbatim in the file so the user's
                # chosen quoting style survives round-trips. os.environ gets the
                # decoded literal so runtime code sees the true value.
                new_lines.append(body)
                changed = True
                _, _, raw_val = body.partition("=")
                os.environ[key] = self._unquote_dotenv_value(raw_val)
                continue
            new_lines.append(line)
        if changed:
            self.env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
            self._invalidate_config_cache()
        return changed

    def _pause(self, short: bool = False) -> None:
        """Wait for a keypress before returning to the caller.

        Any key (including ESC and Ctrl+C) dismisses the prompt and returns
        normally — we intentionally swallow Ctrl+C here so the user doesn't
        nuke the whole TUI just to dismiss an info screen. The caller can
        still exit from the main menu with Ctrl+C the next iteration.
        """
        self.console.print(
            "\n[dim]Press any key to continue…[/]" if not short else "[dim]…[/]"
        )
        try:
            read_key()
        except KeyboardInterrupt:
            # Stdin in raw mode can raise this despite our handler; treat it
            # as "dismiss the prompt" rather than propagating and tearing down
            # the TUI. The main menu will honour a follow-up Ctrl+C.
            pass
        # Drain any trailing bytes (bracketed paste, mouse reports, double
        # keypresses) so the next _arrow_select frame doesn't consume them
        # silently — this is the reason the user had to press Enter+Up+Enter
        # multiple times after exiting a sub-screen.
        self._drain_stdin()

    @staticmethod
    def _drain_stdin() -> None:
        """Non-blocking flush of any bytes sitting in the TTY input buffer.

        Called after Live(screen=True) exits and after _pause returns, to
        clear orphaned bytes produced by the alt-screen transition or held
        keypresses. Without this, the next read_key() in _arrow_select gets
        a stale byte and the user has to re-issue the keystroke.
        """
        if os.name == "nt":
            try:
                import msvcrt
                while msvcrt.kbhit():
                    msvcrt.getch()
            except Exception:
                pass
            return
        try:
            import select
            import termios
            fd = sys.stdin.fileno()
            # tcflush purges anything queued at the kernel layer; the select
            # loop mops up anything already pulled into Python buffers.
            try:
                termios.tcflush(fd, termios.TCIFLUSH)
            except Exception:
                pass
            while select.select([sys.stdin], [], [], 0)[0]:
                try:
                    sys.stdin.read(1)
                except Exception:
                    break
        except Exception:
            pass
