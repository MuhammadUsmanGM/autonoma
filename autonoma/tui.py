"""Autonoma interactive TUI — arrow-key navigable control panel."""

from __future__ import annotations

import asyncio
import getpass
import os
import sys
import webbrowser
from pathlib import Path

from dotenv import load_dotenv, set_key
from rich.align import Align
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.prompt import Prompt
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from autonoma.config import load_config, save_yaml_config

BANNER = r"""
    ___         __
   /   | __  __/ /_____  ____  ____  ____ ___  ____ _
  / /| |/ / / / __/ __ \/ __ \/ __ \/ __ `__ \/ __ `/
 / ___ / /_/ / /_/ /_/ / / / / /_/ / / / / / / /_/ /
/_/  |_\__,_/\__/\____/_/ /_/\____/_/ /_/ /_/\__,_/
"""

ENV_PATH = Path(".env")
YAML_PATH = Path("autonoma.yaml")

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

# --- Key codes ---
KEY_UP = "UP"
KEY_DOWN = "DOWN"
KEY_LEFT = "LEFT"
KEY_RIGHT = "RIGHT"
KEY_ENTER = "ENTER"
KEY_ESC = "ESC"
KEY_CTRL_C = "CTRL_C"


def read_key() -> str:
    """Read a single keypress cross-platform. Returns a key code or the raw char."""
    if os.name == "nt":
        import msvcrt
        ch = msvcrt.getch()
        if ch == b"\x03":
            return KEY_CTRL_C
        if ch == b"\x1b":
            return KEY_ESC
        if ch in (b"\r", b"\n"):
            return KEY_ENTER
        if ch in (b"\x00", b"\xe0"):
            # Extended key — next byte identifies the arrow
            ch2 = msvcrt.getch()
            return {
                b"H": KEY_UP,
                b"P": KEY_DOWN,
                b"K": KEY_LEFT,
                b"M": KEY_RIGHT,
            }.get(ch2, "")
        try:
            return ch.decode("utf-8", errors="ignore")
        except Exception:
            return ""
    else:
        import termios
        import tty
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
            if ch == "\x03":
                return KEY_CTRL_C
            if ch == "\r" or ch == "\n":
                return KEY_ENTER
            if ch == "\x1b":
                # Peek for escape sequence (arrow keys are ESC [ A/B/C/D)
                # Use non-blocking read
                import select
                if select.select([sys.stdin], [], [], 0.05)[0]:
                    ch2 = sys.stdin.read(1)
                    if ch2 == "[":
                        ch3 = sys.stdin.read(1)
                        return {
                            "A": KEY_UP,
                            "B": KEY_DOWN,
                            "C": KEY_RIGHT,
                            "D": KEY_LEFT,
                        }.get(ch3, KEY_ESC)
                return KEY_ESC
            return ch
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)


class BackSignal(Exception):
    """Raised to pop back one screen (ESC)."""


class AutonomaTUI:
    """Interactive control panel for the Autonoma agent."""

    def __init__(self) -> None:
        self.console = Console()
        ENV_PATH.touch(exist_ok=True)
        load_dotenv(ENV_PATH, override=True)

    # ----- Public entry point -----

    def run(self) -> None:
        try:
            if self._is_first_run():
                self._print_banner()
                self.console.print(
                    Panel(
                        "[bold yellow]Welcome to Autonoma![/]\n\n"
                        "Looks like this is your first run. Let's get you set up.\n"
                        "[dim](Press ESC at any time to skip, Ctrl+C to quit.)[/]",
                        border_style="yellow",
                    )
                )
                try:
                    self._setup_wizard()
                except BackSignal:
                    pass
            self._main_menu_loop()
        except KeyboardInterrupt:
            self.console.print("\n[dim]Goodbye.[/]\n")

    # ----- Main menu -----

    def _main_menu_loop(self) -> None:
        items = [
            ("Start agent", self._start_agent),
            ("Open dashboard", self._open_dashboard),
            ("Setup (provider / API key / model)", self._setup_wizard),
            ("Channels (enable, disable, configure)", self._channel_menu),
            ("Status", self._show_status),
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
                self.console.print("\n[dim]Goodbye.[/]\n")
                return
            try:
                items[selected][1]()
            except BackSignal:
                continue

    def _render_main_header(self) -> None:
        self._print_banner()
        cfg = self._safe_load_config()
        provider = cfg.llm.provider if cfg else "?"
        model = cfg.llm.model if cfg else "?"
        has_key = bool(cfg and cfg.llm.api_key)
        enabled = self._enabled_channels(cfg) if cfg else []

        info = Table.grid(padding=(0, 2))
        info.add_column(style="dim")
        info.add_column()
        info.add_row("Provider", f"[bold]{provider}[/] · {model}")
        info.add_row(
            "API key", "[green]✓ configured[/]" if has_key else "[red]✗ missing[/]"
        )
        info.add_row(
            "Channels",
            ", ".join(enabled) if enabled else "[dim](none enabled)[/]",
        )
        self.console.print(Panel(info, border_style="dim", title="Current setup"))

    def _print_banner(self) -> None:
        self.console.clear()
        self.console.print(Align.center(Text(BANNER, style="bold cyan")))
        self.console.print(
            Align.center(Text("AI Agent Platform · control panel", style="dim"))
        )
        self.console.print()

    # ----- Arrow-key select primitive -----

    def _arrow_select(
        self,
        *,
        title: str | None,
        items: list[str],
        selected: int = 0,
        header_renderer=None,
        allow_back: bool = True,
        footer: str | None = None,
    ) -> int | None:
        """Render a menu, navigate with ↑/↓, Enter to select, ESC to back, Ctrl+C to quit.

        Returns the selected index, or None if ESC was pressed with allow_back=True.
        Raises KeyboardInterrupt on Ctrl+C.
        """
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
            if footer:
                self.console.print(f"[dim]{footer}[/]")
            self.console.print(hint)

            key = read_key()
            if key == KEY_CTRL_C:
                raise KeyboardInterrupt
            if key == KEY_ESC:
                if allow_back:
                    return None
                continue
            if key == KEY_UP:
                selected = (selected - 1) % len(items)
            elif key == KEY_DOWN:
                selected = (selected + 1) % len(items)
            elif key == KEY_ENTER:
                return selected

    def _prompt_line(
        self, label: str, *, secret: bool = False, default: str = ""
    ) -> str:
        """Read a line of input. ESC returns BackSignal, Ctrl+C propagates.

        Uses native input — arrow keys not handled here, but ESC/Ctrl+C are via stdin tty.
        """
        self.console.print(label)
        if default:
            self.console.print(f"[dim](current: {self._mask(default)} — Enter to keep)[/]")
        try:
            if secret:
                value = getpass.getpass("  › ").strip()
            else:
                value = self.console.input("  › ").strip()
        except EOFError:
            raise BackSignal
        except KeyboardInterrupt:
            raise
        return value if value else default

    @staticmethod
    def _mask(val: str) -> str:
        if len(val) <= 8:
            return "***"
        return val[:4] + "…" + val[-2:]

    # ----- [1] Start agent -----

    def _start_agent(self) -> None:
        cfg = self._safe_load_config()
        if not cfg or not cfg.llm.api_key:
            self.console.print(
                "\n[red]No API key configured.[/] Run [bold]Setup[/] first."
            )
            self._pause()
            return

        self._print_banner()
        enabled = self._enabled_channels(cfg)
        self.console.print(
            Panel(
                f"Provider: [bold]{cfg.llm.provider}[/] · Model: [bold]{cfg.llm.model}[/]\n"
                f"Channels: {', '.join(enabled) if enabled else '[dim](CLI only)[/]'}\n"
                f"Dashboard: [cyan]http://{cfg.gateway.host}:{cfg.gateway.http_port}[/]\n\n"
                "[dim]Press Ctrl+C to stop the agent and return to the menu.[/]",
                title="Starting Autonoma",
                border_style="green",
            )
        )

        from autonoma.main import run
        try:
            asyncio.run(run())
        except KeyboardInterrupt:
            self.console.print("\n[yellow]Agent stopped.[/]")
        except SystemExit:
            self.console.print("\n[red]Agent exited with error.[/]")
        except Exception as e:
            self.console.print(f"\n[red]Agent crashed:[/] {e}")
        self._pause()

    # ----- [2] Open dashboard -----

    def _open_dashboard(self) -> None:
        cfg = self._safe_load_config()
        port = cfg.gateway.http_port if cfg else 8766
        url = f"http://localhost:{port}"
        self.console.print(f"\nOpening [cyan]{url}[/] in your browser…")
        try:
            webbrowser.open(url)
            self.console.print(
                "[dim]Note: dashboard only serves while the agent is running.[/]"
            )
        except Exception as e:
            self.console.print(f"[red]Could not open browser:[/] {e}")
        self._pause()

    # ----- [3] Setup wizard -----

    def _setup_wizard(self) -> None:
        # Step 1: provider
        idx = self._arrow_select(
            title="[bold]Step 1 of 3 — LLM provider[/]",
            items=[f"{name}  —  {desc}" for name, desc in PROVIDERS],
            selected=0,
            header_renderer=self._print_banner,
            allow_back=True,
        )
        if idx is None:
            return
        provider, _ = PROVIDERS[idx]
        env_key_name = (
            "OPENROUTER_API_KEY" if provider == "openrouter" else "ANTHROPIC_API_KEY"
        )

        # Step 2: API key (text input; ESC-to-back handled by empty-Enter)
        self._print_banner()
        self.console.print(Rule("[bold]Step 2 of 3 — API key[/]", style="cyan"))
        self.console.print(f"Will be saved to .env as [cyan]{env_key_name}[/]")
        self.console.print("[dim]Input is hidden. Press Enter with empty input to skip.[/]\n")
        try:
            api_key = getpass.getpass("  › ").strip()
        except KeyboardInterrupt:
            raise

        # Step 3: model
        suggestions = MODEL_SUGGESTIONS[provider]
        options = list(suggestions) + ["Custom (type your own)"]
        idx = self._arrow_select(
            title=f"[bold]Step 3 of 3 — Model[/] [dim](provider: {provider})[/]",
            items=options,
            selected=0,
            header_renderer=self._print_banner,
            allow_back=True,
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

        # Persist
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

    # ----- [4] Channel menu -----

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
                    creds = self._credential_preview(name)
                    status = "[green]● enabled[/]" if on else "[dim]○ disabled[/]"
                    table.add_row(name, status, creds)
                self.console.print(table)
                self.console.print()

            # Build menu items: one per channel + a "Back" row
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
                footer="Enter: toggle   ·   → or 'c': configure credentials",
            )
            if idx is None:
                return
            selected = idx
            # After Enter we need to decide: toggle or configure.
            # We support 'c' or → to configure via a second keypress prompt.
            self._channel_action_prompt(channels[idx])

    def _channel_action_prompt(self, name: str) -> None:
        """Ask: toggle or configure?"""
        idx = self._arrow_select(
            title=f"[bold]{name}[/]",
            items=[
                "Toggle enable/disable",
                "Configure credentials",
            ],
            selected=0,
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
            self.console.print(f"\n[yellow]✓ {name} disabled (credentials preserved).[/]")
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

    # ----- [5] Status -----

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

    # ----- Helpers -----

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
        except Exception as e:
            self.console.print(f"[red]Failed to load config:[/] {e}")
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
