"""Autonoma interactive TUI — setup, channels, status, and agent control."""

from __future__ import annotations

import asyncio
import getpass
import os
import webbrowser
from pathlib import Path

from dotenv import load_dotenv, set_key, unset_key
from rich.align import Align
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
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

# channel name -> list of env vars that enable it
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

PROVIDER_CHOICES = {
    "1": ("openrouter", "OpenRouter (recommended — one key, many models)"),
    "2": ("anthropic", "Anthropic (direct Claude API)"),
}

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


class AutonomaTUI:
    """Interactive control panel for the Autonoma agent."""

    def __init__(self) -> None:
        self.console = Console()
        ENV_PATH.touch(exist_ok=True)
        load_dotenv(ENV_PATH, override=True)

    # ----- Public entry point -----

    def run(self) -> None:
        """Main entrypoint — first-run check, then menu loop."""
        if self._is_first_run():
            self._print_banner()
            self.console.print(
                Panel(
                    "[bold yellow]Welcome to Autonoma![/]\n\n"
                    "Looks like this is your first run. Let's get you set up.",
                    border_style="yellow",
                )
            )
            self._setup_wizard()
        self._main_menu_loop()

    # ----- Menu loop -----

    def _main_menu_loop(self) -> None:
        while True:
            self._print_banner()
            self._print_main_menu()
            choice = Prompt.ask(
                "\n[bold cyan]Select[/]",
                choices=["1", "2", "3", "4", "5", "q"],
                default="1",
            )
            if choice == "1":
                self._start_agent()
            elif choice == "2":
                self._open_dashboard()
            elif choice == "3":
                self._setup_wizard()
            elif choice == "4":
                self._channel_menu()
            elif choice == "5":
                self._show_status()
            elif choice == "q":
                self.console.print("\n[dim]Goodbye.[/]\n")
                return

    def _print_banner(self) -> None:
        self.console.clear()
        banner_text = Text(BANNER, style="bold cyan")
        self.console.print(Align.center(banner_text))
        subtitle = Text("AI Agent Platform · control panel", style="dim")
        self.console.print(Align.center(subtitle))
        self.console.print()

    def _print_main_menu(self) -> None:
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

        menu = Table.grid(padding=(0, 2))
        menu.add_column(style="bold cyan", justify="right")
        menu.add_column()
        menu.add_row("[1]", "Start agent")
        menu.add_row("[2]", "Open dashboard")
        menu.add_row("[3]", "Setup (provider / API key / model)")
        menu.add_row("[4]", "Channels (enable, disable, configure)")
        menu.add_row("[5]", "Status")
        menu.add_row("[q]", "Quit")
        self.console.print(menu)

    # ----- [1] Start agent -----

    def _start_agent(self) -> None:
        cfg = self._safe_load_config()
        if not cfg or not cfg.llm.api_key:
            self.console.print(
                "[red]No API key configured.[/] Run [bold]Setup[/] first."
            )
            self._pause()
            return

        enabled = self._enabled_channels(cfg)
        self.console.print(
            Panel(
                f"Provider: [bold]{cfg.llm.provider}[/] · Model: [bold]{cfg.llm.model}[/]\n"
                f"Channels: {', '.join(enabled) if enabled else '[dim](CLI only)[/]'}\n"
                f"Dashboard: [cyan]http://{cfg.gateway.host}:{cfg.gateway.http_port}[/]\n\n"
                "[dim]Press Ctrl+C to stop and return to this menu.[/]",
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
            # main.run() calls sys.exit(1) on missing API key — catch it
            self.console.print("\n[red]Agent exited with error.[/]")
        except Exception as e:
            self.console.print(f"\n[red]Agent crashed:[/] {e}")
        self._pause()

    # ----- [2] Open dashboard -----

    def _open_dashboard(self) -> None:
        cfg = self._safe_load_config()
        port = cfg.gateway.http_port if cfg else 8766
        url = f"http://localhost:{port}"
        self.console.print(f"Opening [cyan]{url}[/] in your browser…")
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
        self.console.print(Rule("[bold]Setup[/]", style="cyan"))

        # Provider
        self.console.print("\n[bold]LLM provider:[/]")
        for key, (_, label) in PROVIDER_CHOICES.items():
            self.console.print(f"  [cyan]{key}[/] {label}")
        choice = Prompt.ask("Select provider", choices=["1", "2"], default="1")
        provider, _ = PROVIDER_CHOICES[choice]

        # API key
        env_key_name = (
            "OPENROUTER_API_KEY" if provider == "openrouter" else "ANTHROPIC_API_KEY"
        )
        self.console.print(
            f"\n[bold]API key[/] (will be saved to .env as [cyan]{env_key_name}[/]):"
        )
        self.console.print(
            "[dim]Input is hidden. Press Enter to skip and keep current value.[/]"
        )
        api_key = getpass.getpass("API key: ").strip()

        # Model
        self.console.print(f"\n[bold]Model suggestions for {provider}:[/]")
        suggestions = MODEL_SUGGESTIONS[provider]
        for i, m in enumerate(suggestions, 1):
            self.console.print(f"  [cyan]{i}[/] {m}")
        self.console.print(f"  [cyan]c[/] custom (type your own)")
        m_choice = Prompt.ask(
            "Select model",
            choices=[str(i) for i in range(1, len(suggestions) + 1)] + ["c"],
            default="1",
        )
        if m_choice == "c":
            model = Prompt.ask("Model identifier").strip()
        else:
            model = suggestions[int(m_choice) - 1]

        # Persist
        self._set_env("AUTONOMA_LLM_PROVIDER", provider)
        self._set_env("AUTONOMA_LLM_MODEL", model)
        if api_key:
            self._set_env(env_key_name, api_key)
        save_yaml_config(
            YAML_PATH,
            {"llm": {"provider": provider, "model": model}},
        )

        self.console.print(
            Panel(
                f"[green]✓ Saved.[/]\nProvider: [bold]{provider}[/]\nModel: [bold]{model}[/]",
                border_style="green",
            )
        )
        self._pause()

    # ----- [4] Channel menu -----

    def _channel_menu(self) -> None:
        while True:
            self._print_banner()
            self.console.print(Rule("[bold]Channels[/]", style="cyan"))

            table = Table(show_header=True, header_style="bold cyan")
            table.add_column("#", justify="right", style="dim")
            table.add_column("Channel")
            table.add_column("Status")
            table.add_column("Credentials")

            channels = list(CHANNEL_ENV.keys())
            for i, name in enumerate(channels, 1):
                enabled = self._channel_enabled(name)
                creds_preview = self._credential_preview(name)
                status = (
                    "[green]● enabled[/]" if enabled else "[dim]○ disabled[/]"
                )
                table.add_row(str(i), name, status, creds_preview)
            self.console.print(table)

            self.console.print(
                "\n[bold]Actions:[/] [cyan]t<n>[/] toggle · [cyan]c<n>[/] configure · [cyan]b[/] back"
            )
            action = Prompt.ask("Action").strip().lower()
            if action in ("b", "back", "q"):
                return
            if len(action) >= 2 and action[0] in ("t", "c") and action[1:].isdigit():
                idx = int(action[1:]) - 1
                if 0 <= idx < len(channels):
                    name = channels[idx]
                    if action[0] == "t":
                        self._toggle_channel(name)
                    else:
                        self._configure_channel(name)
                    continue
            self.console.print("[red]Unknown action.[/]")
            self._pause(short=True)

    def _channel_enabled(self, name: str) -> bool:
        load_dotenv(ENV_PATH, override=True)
        required = CHANNEL_ENV[name]
        return all(os.getenv(var) for var in required)

    def _credential_preview(self, name: str) -> str:
        load_dotenv(ENV_PATH, override=True)
        parts = []
        for var in CHANNEL_ENV[name]:
            val = os.getenv(var, "")
            if not val:
                parts.append(f"[dim]{var}=?[/]")
            else:
                masked = (
                    val[:4] + "…" + val[-2:] if len(val) > 8 else "***"
                )
                parts.append(f"{var}=[green]{masked}[/]")
        return " ".join(parts)

    def _toggle_channel(self, name: str) -> None:
        if self._channel_enabled(name):
            # Disable by commenting out env vars
            for var in CHANNEL_ENV[name]:
                self._disable_env(var)
            self.console.print(f"[yellow]✓ {name} disabled (credentials preserved).[/]")
        else:
            # If credentials exist as commented lines, re-enable them
            reenabled = False
            for var in CHANNEL_ENV[name]:
                if self._enable_env(var):
                    reenabled = True
            if reenabled:
                self.console.print(f"[green]✓ {name} re-enabled from saved credentials.[/]")
            else:
                self.console.print(
                    f"[dim]No saved credentials for {name}. Launching configuration…[/]"
                )
                self._configure_channel(name)
                return
        self._pause(short=True)

    def _configure_channel(self, name: str) -> None:
        self.console.print(Rule(f"[bold]Configure {name}[/]", style="cyan"))
        self.console.print(f"[dim]{CHANNEL_DESCRIPTIONS.get(name, '')}[/]\n")
        for var in CHANNEL_ENV[name]:
            current = os.getenv(var, "")
            hint = (
                f" [dim](current: {current[:4]}…{current[-2:]})[/]"
                if current and len(current) > 6
                else ""
            )
            # Hide input for secrets; show for things like email address or URL
            is_secret = any(
                s in var for s in ("TOKEN", "PASSWORD", "KEY", "SECRET")
            )
            if is_secret:
                self.console.print(f"[bold]{var}[/]{hint}")
                self.console.print("[dim]Input hidden. Press Enter to keep current.[/]")
                value = getpass.getpass(f"{var}: ").strip()
            else:
                value = Prompt.ask(f"{var}{hint}", default="").strip()
            if value:
                self._set_env(var, value)
        self.console.print(f"[green]✓ {name} configured.[/]")
        self._pause(short=True)

    # ----- [5] Status -----

    def _show_status(self) -> None:
        self.console.print(Rule("[bold]Status[/]", style="cyan"))

        cfg = self._safe_load_config()
        if not cfg:
            self.console.print("[red]Could not load config.[/]")
            self._pause()
            return

        # Config table
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
        cfg_table.add_row(
            "Gateway", f"{cfg.gateway.host}:{cfg.gateway.port}"
        )
        cfg_table.add_row(
            "Dashboard", f"http://{cfg.gateway.host}:{cfg.gateway.http_port}"
        )
        cfg_table.add_row("Workspace", cfg.workspace_dir)
        cfg_table.add_row("Memory DB", cfg.memory.db_path)
        self.console.print(Panel(cfg_table, title="Configuration", border_style="cyan"))

        # Channel table
        ch_table = Table(show_header=True, header_style="bold cyan")
        ch_table.add_column("Channel")
        ch_table.add_column("Enabled")
        for name in CHANNEL_ENV:
            on = self._channel_enabled(name)
            ch_table.add_row(
                name, "[green]✓[/]" if on else "[dim]—[/]"
            )
        self.console.print(Panel(ch_table, title="Channels", border_style="cyan"))

        # Memory stats (without starting the agent)
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
            self.console.print(
                Panel(mem_table, title="Memory", border_style="cyan")
            )
        except Exception as e:
            self.console.print(f"[dim]Memory stats unavailable: {e}[/]")

        self._pause()

    # ----- Helpers -----

    def _is_first_run(self) -> bool:
        """True if neither an API key nor any channel is configured."""
        load_dotenv(ENV_PATH, override=True)
        has_key = any(
            os.getenv(k)
            for k in ("OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "AUTONOMA_LLM_API_KEY")
        )
        return not has_key

    def _safe_load_config(self):
        try:
            load_dotenv(ENV_PATH, override=True)
            return load_config()
        except Exception as e:
            self.console.print(f"[red]Failed to load config:[/] {e}")
            return None

    def _enabled_channels(self, cfg) -> list[str]:
        out = []
        if cfg.channels.telegram.enabled:
            out.append("telegram")
        if cfg.channels.discord.enabled:
            out.append("discord")
        if cfg.channels.whatsapp.enabled:
            out.append("whatsapp")
        if cfg.channels.gmail.enabled:
            out.append("gmail")
        if cfg.channels.rest.enabled:
            out.append("rest")
        return out

    def _set_env(self, key: str, value: str) -> None:
        """Write or overwrite an env var in .env (uncommented)."""
        ENV_PATH.touch(exist_ok=True)
        # Remove any existing commented version first so it doesn't confuse things
        self._enable_env(key)
        set_key(str(ENV_PATH), key, value, quote_mode="never")
        os.environ[key] = value

    def _disable_env(self, key: str) -> bool:
        """Comment out a line in .env. Returns True if the key was present."""
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
        """Uncomment a commented line in .env. Returns True if a line was re-enabled."""
        if not ENV_PATH.exists():
            return False
        lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
        changed = False
        new_lines = []
        for line in lines:
            stripped = line.lstrip()
            # Match: # KEY=... or #KEY=...
            if stripped.startswith("#"):
                body = stripped.lstrip("#").lstrip()
                if body.startswith(f"{key}="):
                    new_lines.append(body)
                    changed = True
                    # Load the re-enabled value into current env
                    _, _, val = body.partition("=")
                    os.environ[key] = val.strip().strip('"').strip("'")
                    continue
            new_lines.append(line)
        if changed:
            ENV_PATH.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        return changed

    def _pause(self, short: bool = False) -> None:
        prompt = "Press Enter to continue…" if not short else "[dim]…[/]"
        try:
            self.console.input(f"\n[dim]{prompt}[/] ")
        except (EOFError, KeyboardInterrupt):
            pass
