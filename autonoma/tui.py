"""Autonoma TUI — control tower: auto-start agent, live log panel, hotkey actions."""

from __future__ import annotations

import asyncio
import getpass
import os
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

ENV_PATH = Path(".env")
YAML_PATH = Path("autonoma.yaml")
LOG_FILE = Path(".session") / "autonoma.log"

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
                if select.select([sys.stdin], [], [], 0.05)[0]:
                    ch2 = sys.stdin.read(1)
                    if ch2 == "[":
                        ch3 = sys.stdin.read(1)
                        arrows = {"A": KEY_UP, "B": KEY_DOWN}
                        if ch3 in arrows:
                            return arrows[ch3]
                        if ch3 == "5":
                            sys.stdin.read(1); return KEY_PGUP
                        if ch3 == "6":
                            sys.stdin.read(1); return KEY_PGDN
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
        ENV_PATH.touch(exist_ok=True)
        load_dotenv(ENV_PATH, override=True)
        self.log_ring: LogRingBuffer | None = None
        self.runner: AgentRunner | None = None

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
                log_file=str(LOG_FILE), level="INFO"
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
        with Live(
            self._render_logs(tail_only=True, scroll=0),
            console=self.console,
            refresh_per_second=6,
            screen=True,
        ) as live:
            scroll = 0
            follow = True  # auto-scroll to bottom
            while True:
                key = read_key(timeout=0.3)
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

                live.update(self._render_logs(tail_only=follow, scroll=scroll))

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
        url = f"http://localhost:{port}"
        self.console.clear()
        self.console.print(f"\nOpening [cyan]{url}[/]…")
        try:
            webbrowser.open(url)
            self.console.print("[green]✓ Browser launched.[/]")
        except Exception as e:
            self.console.print(f"[red]Could not open browser:[/] {e}")
        self._pause()

    # ----- [M] Manage (stops agent, shows menu, restarts) -----

    def _manage_menu(self) -> None:
        """Open the manage menu. Agent must be stopped to change config safely."""
        was_running = self.runner and self.runner.is_running()
        if was_running:
            self.console.clear()
            self.console.print(
                Panel(
                    "[yellow]Stopping agent to safely change configuration…[/]",
                    border_style="yellow",
                )
            )
            self.runner.stop()

        try:
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
        cfg_table.add_row("Log file", str(LOG_FILE))
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
        self.console.print("[dim]Input is hidden. Press Enter with empty input to skip.[/]\n")
        try:
            api_key = getpass.getpass("  › ").strip()
        except KeyboardInterrupt:
            raise

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
        save_yaml_config(YAML_PATH, {"llm": {"provider": provider, "model": model}})

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
            items=["Toggle enable/disable", "Configure credentials"],
            header_renderer=self._print_banner,
            allow_back=True,
        )
        if idx == 0:
            self._toggle_channel(name)
        elif idx == 1:
            self._configure_channel(name)

    def _channel_enabled(self, name: str) -> bool:
        load_dotenv(ENV_PATH, override=True)
        return all(os.getenv(v) for v in CHANNEL_ENV[name])

    def _credential_preview(self, name: str) -> str:
        load_dotenv(ENV_PATH, override=True)
        parts = []
        for var in CHANNEL_ENV[name]:
            val = os.getenv(var, "")
            if not val:
                parts.append(f"[dim]{var}=?[/]")
            else:
                parts.append(f"{var}=[green]{self._mask(val)}[/]")
        return " ".join(parts)

    def _toggle_channel(self, name: str) -> None:
        if self._channel_enabled(name):
            for var in CHANNEL_ENV[name]:
                self._disable_env(var)
            self.console.print(f"\n[yellow]✓ {name} disabled.[/]")
        else:
            reenabled = False
            for var in CHANNEL_ENV[name]:
                if self._enable_env(var):
                    reenabled = True
            if reenabled:
                self.console.print(f"\n[green]✓ {name} re-enabled.[/]")
            else:
                self.console.print(
                    f"\n[dim]No saved credentials. Launching configuration…[/]"
                )
                self._configure_channel(name)
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
        load_dotenv(ENV_PATH, override=True)
        return not any(
            os.getenv(k)
            for k in ("OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "AUTONOMA_LLM_API_KEY")
        )

    def _safe_load_config(self):
        try:
            load_dotenv(ENV_PATH, override=True)
            return load_config()
        except Exception:
            return None

    def _enabled_channels(self, cfg) -> list[str]:
        out = []
        if cfg.channels.telegram.enabled: out.append("telegram")
        if cfg.channels.discord.enabled: out.append("discord")
        if cfg.channels.whatsapp.enabled: out.append("whatsapp")
        if cfg.channels.gmail.enabled: out.append("gmail")
        if cfg.channels.rest.enabled: out.append("rest")
        return out

    def _set_env(self, key: str, value: str) -> None:
        ENV_PATH.touch(exist_ok=True)
        self._enable_env(key)
        set_key(str(ENV_PATH), key, value, quote_mode="never")
        os.environ[key] = value

    def _disable_env(self, key: str) -> bool:
        if not ENV_PATH.exists():
            return False
        lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
        changed = False
        new_lines = []
        for line in lines:
            stripped = line.lstrip()
            if stripped.startswith(f"{key}=") and not stripped.startswith("#"):
                new_lines.append(f"# {line}")
                changed = True
            else:
                new_lines.append(line)
        if changed:
            ENV_PATH.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
            os.environ.pop(key, None)
        return changed

    def _enable_env(self, key: str) -> bool:
        if not ENV_PATH.exists():
            return False
        lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
        changed = False
        new_lines = []
        for line in lines:
            stripped = line.lstrip()
            if stripped.startswith("#"):
                body = stripped.lstrip("#").lstrip()
                if body.startswith(f"{key}="):
                    new_lines.append(body)
                    changed = True
                    _, _, val = body.partition("=")
                    os.environ[key] = val.strip().strip('"').strip("'")
                    continue
            new_lines.append(line)
        if changed:
            ENV_PATH.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        return changed

    def _pause(self, short: bool = False) -> None:
        self.console.print(
            "\n[dim]Press any key to continue…[/]" if not short else "[dim]…[/]"
        )
        try:
            key = read_key()
            if key == KEY_CTRL_C:
                raise KeyboardInterrupt
        except KeyboardInterrupt:
            raise
