"""Autonoma TUI — control tower: auto-start agent, live log panel, hotkey actions."""

from __future__ import annotations

import asyncio
import atexit
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
from rich.prompt import Confirm
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from autonoma.config import load_config, save_yaml_config
from autonoma.runtime import AgentRunner, LogRingBuffer, install_logging

BANNER = r"""
 █████╗ ██╗   ██╗████████╗ ██████╗ ███╗   ██╗ ██████╗ ███╗   ███╗ █████╗
██╔══██╗██║   ██║╚══██╔══╝██╔═══██╗████╗  ██║██╔═══██╗████╗ ████║██╔══██╗
███████║██║   ██║   ██║   ██║   ██║██╔██╗ ██║██║   ██║██╔████╔██║███████║
██╔══██║██║   ██║   ██║   ██║   ██║██║╚██╗██║██║   ██║██║╚██╔╝██║██╔══██║
██║  ██║╚██████╔╝   ██║   ╚██████╔╝██║ ╚████║╚██████╔╝██║ ╚═╝ ██║██║  ██║
╚═╝  ╚═╝ ╚═════╝    ╚═╝    ╚═════╝ ╚═╝  ╚═══╝ ╚═════╝ ╚═╝     ╚═╝╚═╝  ╚═╝
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

# Termios guard state (POSIX only). Populated the first time read_key flips
# stdin into raw mode so an atexit handler can restore it on any exit path
# that bypasses our try/finally (SIGTERM, os._exit, unhandled C-level crash).
_TERMIOS_GUARD_INSTALLED = False
_TERMIOS_GUARD_FD: int | None = None
_TERMIOS_GUARD_OLD = None


def _install_termios_guard(fd: int, old) -> None:
    """Register a one-shot atexit restore of stdin termios. Safe to call many
    times — only the first call registers the handler, and it uses the very
    first `old` attrs it sees (i.e. the true pre-raw state)."""
    global _TERMIOS_GUARD_INSTALLED, _TERMIOS_GUARD_FD, _TERMIOS_GUARD_OLD
    if _TERMIOS_GUARD_INSTALLED:
        return
    _TERMIOS_GUARD_FD = fd
    _TERMIOS_GUARD_OLD = old

    def _restore():
        try:
            import termios
            if _TERMIOS_GUARD_FD is not None and _TERMIOS_GUARD_OLD is not None:
                termios.tcsetattr(
                    _TERMIOS_GUARD_FD, termios.TCSADRAIN, _TERMIOS_GUARD_OLD
                )
        except Exception:
            # atexit must never raise; a dead fd or missing termios is fine.
            pass

    atexit.register(_restore)
    _TERMIOS_GUARD_INSTALLED = True


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
        # Register an atexit restore the FIRST time we flip to raw mode, so a
        # SIGTERM / os._exit / uncaught crash can't leave the user's terminal
        # stuck in raw mode after the process dies. Idempotent.
        _install_termios_guard(fd, old)
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
        # Tracks whether run() made it past setup and into the main loop. Used
        # to decide whether _shutdown should print "Goodbye." — if the user
        # Ctrl+C's out of the forced first-run wizard, we want a quiet exit.
        self._entered_main_loop: bool = False

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
            self._entered_main_loop = True
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
        # Only greet the user goodbye if they actually made it into the app.
        # Aborting the forced first-run wizard should exit silently — there's
        # nothing to say goodbye to.
        if self._entered_main_loop:
            self.console.print("[dim]Goodbye.[/]\n")

    # ----- Main menu -----

    def _control_tower(self) -> None:
        """Arrow-key navigable main menu. Agent runs in background."""
        items = [
            ("Live logs", self._logs_viewer),
            ("Manage configuration", self._manage_menu),
            ("Manage channels", self._manage_channels),
            ("Manage connectors", self._manage_connectors),
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
                header_renderable=self._main_header_renderable,
                allow_back=False,
            )
            if selected is None or items[selected][1] is None:
                return
            try:
                items[selected][1]()
            except BackSignal:
                continue

    def _render_main_header(self) -> None:
        """Legacy print-based header (kept for non-Live screens like Status).
        For menu screens use _main_header_renderable() which returns a Group
        so Live(screen=True) can update in place without scrollback stacking."""
        self.console.print(self._main_header_renderable())

    def _banner_renderable(self):
        """Banner + subtitle as a single renderable (no clear, no print)."""
        return Group(
            Align.center(Text(BANNER, style="bold cyan")),
            Align.center(Text("AI Agent Platform · control panel", style="dim")),
            Text(""),
        )

    def _main_header_renderable(self):
        """Full main-menu header (banner + status panel) as a renderable.

        Returns a Group rather than printing so _arrow_select can hand it
        to Live(screen=True), which paints into the terminal's alt-screen
        buffer — no scrollback, no stacked frames on each keypress.
        """
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
        return Group(
            self._banner_renderable(),
            Panel(info, border_style=status_color, title="Autonoma"),
            Text(""),
        )

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

                # Compute scrollback ceiling now so UP/PGUP/HOME can't drift
                # past the oldest log line. body_height mirrors _render_logs.
                total = len(self.log_ring.all()) if self.log_ring else 0
                body_height = max(5, self.console.size.height - 4)
                max_scroll = max(0, total - body_height)

                if key == KEY_UP:
                    scroll = min(max_scroll, scroll + 1); follow = False
                elif key == KEY_DOWN:
                    scroll = max(0, scroll - 1)
                    if scroll == 0:
                        follow = True
                elif key == KEY_PGUP:
                    scroll = min(max_scroll, scroll + 20); follow = False
                elif key == KEY_PGDN:
                    scroll = max(0, scroll - 20)
                    if scroll == 0:
                        follow = True
                elif key == KEY_HOME:
                    scroll = max_scroll; follow = False
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
                    header_renderable=self._banner_renderable,
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

    # ----- Connectors menu (no agent restart needed — HTTP-only) -----

    def _manage_connectors(self) -> None:
        """List connectors, kick off OAuth, and log out.

        Talks to the running agent over the local HTTP API instead of poking
        the registry directly: that way the connect/disconnect flow works the
        same whether the user is in the TUI or the dashboard, and we don't
        need to stop the agent the way ``_channel_menu`` does — there is no
        on-disk config to write here, only the encrypted token store the
        running gateway already owns.
        """
        cfg = self._safe_load_config()
        host = cfg.gateway.host if cfg else "127.0.0.1"
        port = cfg.gateway.http_port if cfg else 8766
        base = f"http://{host}:{port}"

        while True:
            entries = self._fetch_connectors(base)
            if entries is None:
                self.console.print(
                    "[red]Could not reach the gateway HTTP API. Is the agent running?[/]"
                )
                self._pause()
                return
            if not entries:
                self.console.print(
                    "[yellow]No connectors are registered. Set GOOGLE_CLIENT_ID / "
                    "MS_CLIENT_ID (and matching secrets) in your .env, then enable "
                    "the connector in autonoma.yaml.[/]"
                )
                self._pause()
                return

            labels: list[str] = []
            for e in entries:
                m = e["manifest"]
                s = e["status"]
                state = s.get("state", "?")
                acct = s.get("account_label") or s.get("account_id") or ""
                tail = f" — {acct}" if state == "connected" and acct else ""
                labels.append(f"{m['display_name']}  [{state}]{tail}")
            labels.append("Back")

            idx = self._arrow_select(
                title="[bold]Connectors[/]",
                items=labels,
                header_renderable=self._banner_renderable,
                allow_back=True,
            )
            if idx is None or idx == len(labels) - 1:
                return
            chosen = entries[idx]
            self._connector_actions(base, chosen)

    def _connector_actions(self, base: str, entry: dict) -> None:
        name = entry["manifest"]["name"]
        display = entry["manifest"]["display_name"]
        connected = entry["status"].get("state") == "connected"
        items = (
            [f"Sign out of {display}", "Back"]
            if connected
            else [f"Connect {display}", "Back"]
        )
        idx = self._arrow_select(
            title=f"[bold]{display}[/]",
            items=items,
            header_renderable=self._banner_renderable,
            allow_back=True,
        )
        if idx is None or idx == 1:
            return
        if connected:
            ok, err = self._http_post(f"{base}/api/connectors/{name}/disconnect")
            if ok:
                self.console.print(f"[green]Signed out of {display}.[/]")
            else:
                self.console.print(f"[red]Disconnect failed:[/] {err}")
        else:
            ok, payload = self._http_post(f"{base}/api/connectors/{name}/connect")
            if not ok:
                self.console.print(f"[red]Connect failed:[/] {payload}")
            else:
                url = (payload or {}).get("auth_url", "")
                if not url:
                    self.console.print("[red]No auth URL returned.[/]")
                else:
                    self.console.print(
                        f"[cyan]Open this URL in your browser to authorize "
                        f"{display}:[/]\n{url}"
                    )
                    try:
                        webbrowser.open(url)
                    except Exception:
                        pass
                    self.console.print(
                        "[dim]Waiting for the OAuth callback to complete…[/]"
                    )
                    self._wait_for_connection(base, name, timeout=180.0)
        self._pause()

    def _fetch_connectors(self, base: str):
        ok, data = self._http_get(f"{base}/api/connectors")
        return data if ok else None

    def _wait_for_connection(self, base: str, name: str, timeout: float) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            ok, data = self._http_get(f"{base}/api/connectors")
            if ok and isinstance(data, list):
                for e in data:
                    if e["manifest"]["name"] == name:
                        state = e["status"].get("state")
                        if state == "connected":
                            label = e["status"].get("account_label", "")
                            self.console.print(
                                f"[green]✓ Connected as {label or 'authorized account'}.[/]"
                            )
                            return
                        if state == "error":
                            self.console.print(
                                f"[red]Connection failed:[/] {e['status'].get('last_error','unknown')}"
                            )
                            return
            time.sleep(1.0)
        self.console.print("[yellow]Timed out waiting for the OAuth callback.[/]")

    def _http_get(self, url: str):
        import urllib.error
        import urllib.request
        try:
            with urllib.request.urlopen(url, timeout=5.0) as resp:
                return True, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                return False, json.loads(e.read().decode("utf-8")).get("error", str(e))
            except Exception:
                return False, str(e)
        except Exception as e:
            return False, str(e)

    def _http_post(self, url: str):
        import urllib.error
        import urllib.request
        req = urllib.request.Request(url, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                return True, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                return False, json.loads(e.read().decode("utf-8")).get("error", str(e))
            except Exception:
                return False, str(e)
        except Exception as e:
            return False, str(e)

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
        self.console.print("[green]✓ Agent restarted.[/]")
        # Brief dwell so the user actually sees the confirmation before the
        # next menu frame clears the screen; drain stdin so keys pressed
        # during the sleep don't get consumed by the menu's next _arrow_select.
        time.sleep(0.6)
        self._drain_stdin()

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

        self._render_proxy_panel(cfg)

        self._pause()

    def _render_proxy_panel(self, cfg) -> None:
        """Probe each configured channel proxy and render the results.

        Kept off the hot Status path behind its own method so a slow probe
        (up to `timeout` seconds per proxy) doesn't blow up the whole status
        screen if someone's upstream SOCKS server is slow. The probe module
        never raises — worst case we render an OFFLINE row with the error."""
        try:
            from autonoma.gateway.proxy_health import check_proxy, mask_proxy_url
        except Exception as e:
            self.console.print(f"[dim]Proxy health module unavailable: {e}[/]")
            return

        # Enumerate what we have wired up today. Telegram is the only channel
        # that exposes a user-configurable proxy; WhatsApp uses its own bridge
        # and Gmail/Discord/REST don't route through SOCKS. When more channels
        # learn to use proxies, add them here.
        configured: list[tuple[str, str]] = []
        if cfg.channels.telegram.proxy_url:
            configured.append(("telegram", cfg.channels.telegram.proxy_url))

        if not configured:
            self.console.print(
                Panel(
                    "[dim]No proxies configured. "
                    "Set TELEGRAM_PROXY_URL in .env to route Telegram through SOCKS/HTTP.[/]",
                    title="Proxy Health",
                    border_style="cyan",
                )
            )
            return

        self.console.print("[dim]Probing proxies (this may take a few seconds)…[/]")
        try:
            results = asyncio.run(
                asyncio.gather(
                    *(check_proxy(url, channel=ch, timeout=6.0) for ch, url in configured),
                    return_exceptions=True,
                )
            )
        except Exception as e:
            self.console.print(f"[dim]Proxy probe failed: {e}[/]")
            return

        table = Table(show_header=True, header_style="bold cyan", box=None)
        table.add_column("Channel")
        table.add_column("Proxy")
        table.add_column("Status")
        table.add_column("Latency")
        table.add_column("Detail")
        any_down = False
        for (channel, url), res in zip(configured, results):
            masked = mask_proxy_url(url)
            if isinstance(res, Exception):
                table.add_row(channel, masked, "[red]●[/] DOWN", "-", f"probe error: {res}")
                any_down = True
                continue
            if res.ok:
                table.add_row(
                    channel, masked, "[green]●[/] OK",
                    f"{res.latency_ms} ms", f"→ {res.target}",
                )
            else:
                table.add_row(
                    channel, masked, "[red]●[/] DOWN",
                    "-", res.error or "unknown error",
                )
                any_down = True

        self.console.print(Panel(table, title="Proxy Health", border_style="cyan"))

        if any_down:
            # Actionable hint — a dead free proxy is the single most common
            # reason Telegram stops working, so point at the fix before the
            # user has to go hunt for one.
            self.console.print(
                "[dim]Hint: if a proxy keeps dying, consider a permanent replacement — "
                "an SSH dynamic tunnel ([cyan]ssh -D 1080 user@vps[/]) or "
                "Cloudflare WARP in proxy mode. See docs for setup.[/]"
            )

    # ----- Setup wizard -----

    def _setup_wizard(self, forced: bool = False) -> None:
        idx = self._arrow_select(
            title="[bold]Step 1 of 3 — LLM provider[/]",
            items=[f"{name}  —  {desc}" for name, desc in PROVIDERS],
            header_renderable=self._banner_renderable,
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
            header_renderable=self._banner_renderable,
            allow_back=not forced,
        )
        if idx is None:
            return
        if idx == len(suggestions):
            self._print_banner()
            self.console.print(Rule("[bold]Custom model[/]", style="cyan"))
            # In forced first-run we re-prompt on empty input instead of
            # returning — an empty model ID here would throw away the API key
            # the user just typed, send them back to the main loop with the
            # agent still unable to start, and _is_first_run would still be
            # True. Loop until we get something or the user Ctrl+Cs.
            while True:
                try:
                    model = self.console.input("Model identifier: ").strip()
                except (EOFError, KeyboardInterrupt):
                    if forced:
                        raise
                    return
                if model:
                    break
                if not forced:
                    return
                self.console.print(
                    "[red]A model identifier is required.[/] "
                    "[dim]Press Ctrl+C to quit instead.[/]"
                )
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
            def header_renderable():
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
                return Group(
                    self._banner_renderable(),
                    Rule("[bold]Channels[/]", style="cyan"),
                    table,
                    Text(""),
                )

            items = [
                f"{name:<10} — {'disable' if self._channel_enabled(name) else 'enable'} / configure"
                for name in channels
            ]
            idx = self._arrow_select(
                title=None,
                items=items,
                selected=selected,
                header_renderable=header_renderable,
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
            header_renderable=self._banner_renderable,
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
            # Make sure the bridge URL is present so the agent actually
            # starts the bridge. If the user cleared it, reprompt.
            if not os.getenv("WHATSAPP_BRIDGE_URL"):
                self.console.print(
                    "\n[yellow]WHATSAPP_BRIDGE_URL is not set — configure it now:[/]"
                )
                self._configure_channel(name)

            # Try to pull a live QR from the bridge's /qr endpoint so the
            # user can scan right here instead of hunting through bridge logs.
            self._show_whatsapp_qr()
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

            # If the agent is running, ask it to rebuild the channel in
            # place so the new credentials take effect immediately — no
            # restart required. If it's not running, fall back to the old
            # "restart to apply" message.
            if self._rebuild_channel_live(name):
                self.console.print(
                    f"\n[green]✓ {name} credentials rotated and channel "
                    f"rebuilt live — no restart needed.[/]"
                )
            else:
                self.console.print(
                    f"\n[green]✓ {name} credentials rotated. "
                    f"Restart Autonoma to apply.[/]"
                )
        self._pause(short=True)

    def _rebuild_channel_live(self, name: str) -> bool:
        """Ask a running gateway to rebuild `name` with the current .env.

        Returns True on a successful 2xx from the gateway, False otherwise
        (gateway not running, channel not registered, network blip). Caller
        uses the return value to decide between "applied live" vs "restart
        required" messaging — we intentionally don't raise so the TUI never
        dead-ends if the agent happens to be down.
        """
        import json
        import urllib.error
        import urllib.request

        cfg = self._safe_load_config()
        if cfg is None:
            return False
        host = cfg.gateway.host or "127.0.0.1"
        # 127.0.0.1 is more reliable than "0.0.0.0" for client connects on
        # Windows, which is what the gateway binds to by default.
        if host in ("0.0.0.0", "::"):
            host = "127.0.0.1"
        port = cfg.gateway.http_port
        url = f"http://{host}:{port}/api/channels/{name}/reconnect"

        req = urllib.request.Request(
            url,
            data=b"{}",
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                return 200 <= resp.getcode() < 300
        except urllib.error.HTTPError:
            # 400 means the channel isn't currently registered — treat as
            # "can't apply live", not an error. Anything else is a real
            # failure we want the fallback path to surface.
            return False
        except (urllib.error.URLError, OSError, json.JSONDecodeError):
            # Gateway not running or unreachable — fall back to restart hint.
            return False

    def _show_whatsapp_qr(self) -> None:
        """Poll the local whatsapp-web.js bridge for its latest QR and render it.

        The bridge is a separate Node sidecar that the user (or the agent
        process via run_in_background) has to start. If it's not reachable
        we bail fast with an explicit hint + an option to auto-spawn the
        sidecar from here — otherwise users are left staring at a silent
        spinner for 30 s wondering whether anything is happening.
        """
        import json
        import socket
        import urllib.error
        import urllib.parse
        import urllib.request
        from rich.panel import Panel

        bridge_url = (os.getenv("WHATSAPP_BRIDGE_URL") or "http://localhost:3001").rstrip("/")
        qr_url = f"{bridge_url}/qr"

        # Fast TCP probe first — if the port is closed there's no point
        # polling for 30 s. Users reported the TUI hanging here because
        # they hadn't started the bridge yet, and the silent wait looked
        # like the UI was frozen.
        parsed = urllib.parse.urlparse(bridge_url)
        host = parsed.hostname or "localhost"
        port = parsed.port or (443 if parsed.scheme == "https" else 3001)
        try:
            with socket.create_connection((host, port), timeout=1.0):
                bridge_up = True
        except OSError:
            bridge_up = False

        if not bridge_up:
            self._bridge_unreachable_prompt(bridge_url)
            return

        self.console.print(
            f"\n[dim]Bridge is up at {bridge_url} — waiting for a fresh QR "
            "(puppeteer takes a few seconds to warm up)…[/]"
        )

        # Poll gently. 15 attempts × 2s = 30 s budget, longer than puppeteer's
        # usual cold start. Abort early on any 200 with a QR.
        deadline_attempts = 15
        last_error: str | None = None
        for attempt in range(deadline_attempts):
            try:
                with urllib.request.urlopen(qr_url, timeout=3.0) as resp:
                    raw = resp.read().decode("utf-8", errors="replace")
                    payload = json.loads(raw)
                    status_code = resp.getcode()
                if status_code == 200 and payload.get("qr"):
                    self._render_qr_panel(payload["qr"], payload.get("age_seconds"))
                    return
                # 404 means bridge is up but either already logged in or not
                # ready yet — surface the distinction rather than spin silently.
                if payload.get("status") == "ready":
                    self.console.print(
                        Panel(
                            "[green]WhatsApp session is already authenticated — "
                            "no QR needed.[/]\n"
                            "[dim]If you wanted a fresh login, wipe the session "
                            "first via Reconnect, then try again.[/]",
                            title="WhatsApp",
                            border_style="green",
                        )
                    )
                    return
                last_error = payload.get("message") or f"bridge responded {status_code}"
            except urllib.error.HTTPError as e:
                # 404 during warmup is normal — bridge is up but puppeteer
                # hasn't emitted a QR yet. Keep polling.
                if e.code == 404:
                    last_error = "bridge has not emitted a QR yet"
                else:
                    last_error = f"bridge returned HTTP {e.code}"
            except urllib.error.URLError as e:
                last_error = f"bridge unreachable: {e.reason}"
            except (json.JSONDecodeError, ValueError) as e:
                last_error = f"bad bridge response: {e}"
            except Exception as e:  # pragma: no cover — defensive
                last_error = str(e)
            # Show a heartbeat so the user doesn't think we're frozen.
            self.console.print(
                f"[dim]  · attempt {attempt + 1}/{deadline_attempts}: {last_error}[/]"
            )
            time.sleep(2.0)

        # Fell through the polling budget — tell the user what to do next.
        self.console.print(
            Panel(
                f"[yellow]Bridge is reachable but did not emit a QR within 30s.[/]\n"
                f"[dim]Last error: {last_error or 'timeout'}[/]\n\n"
                "This usually means puppeteer is still booting or the bridge "
                "is stuck. Check the bridge's own log window — whatsapp-web.js "
                "prints the QR payload there. Close this panel and re-run "
                "Reconnect once the bridge has settled.",
                title="WhatsApp QR",
                border_style="yellow",
            )
        )

    def _bridge_unreachable_prompt(self, bridge_url: str) -> None:
        """Explain that the bridge sidecar isn't running and offer to start it.

        Called by _show_whatsapp_qr when the TCP probe fails. The bridge is
        a Node sidecar under whatsapp-bridge/ — `npm start` in that dir
        spawns it. We try to auto-spawn it here so the user doesn't have
        to juggle a second terminal.
        """
        import shutil
        import subprocess
        from rich.panel import Panel

        bridge_dir = self.workspace / "whatsapp-bridge"
        has_bridge_dir = bridge_dir.exists() and (bridge_dir / "package.json").exists()
        has_node_modules = has_bridge_dir and (bridge_dir / "node_modules").exists()

        lines = [
            f"[yellow]The WhatsApp bridge at {bridge_url} is not running.[/]",
            "",
            "The bridge is a separate Node sidecar that speaks to WhatsApp "
            "Web via puppeteer. It must be running for QR scanning and "
            "message send/receive to work.",
        ]
        if not has_bridge_dir:
            lines.append(
                f"\n[red]No bridge found at {bridge_dir}.[/] "
                "Reinstall Autonoma with the whatsapp-bridge/ folder in place."
            )
            self.console.print(Panel("\n".join(lines), title="WhatsApp bridge", border_style="yellow"))
            return

        if not has_node_modules:
            lines.append(
                f"\n[yellow]node_modules/ is missing.[/] Run [cyan]npm install[/] in "
                f"[cyan]{bridge_dir}[/] first, then retry Reconnect."
            )
            self.console.print(Panel("\n".join(lines), title="WhatsApp bridge", border_style="yellow"))
            return

        lines.append(
            f"\nTo start it manually: [cyan]cd {bridge_dir} && npm start[/]"
        )
        self.console.print(Panel("\n".join(lines), title="WhatsApp bridge", border_style="yellow"))

        # Offer to spawn it for them. Detached on Windows so it survives
        # the TUI closing; on POSIX we start a new session for the same
        # reason. stdout/stderr go to a log file the user can tail.
        if not Confirm.ask(
            "\n[bold]Start the bridge sidecar now?[/]",
            default=True,
            console=self.console,
        ):
            return

        npm = shutil.which("npm") or shutil.which("npm.cmd")
        if not npm:
            self.console.print(
                "[red]Could not find `npm` on PATH. Install Node.js "
                "(https://nodejs.org) and try again.[/]"
            )
            return

        log_path = bridge_dir / "bridge.log"
        try:
            log_handle = open(log_path, "a", buffering=1, encoding="utf-8")
            log_handle.write(f"\n\n=== Bridge spawned by TUI at {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
            log_handle.flush()
            kwargs: dict = {
                "cwd": str(bridge_dir),
                "stdout": log_handle,
                "stderr": subprocess.STDOUT,
                "stdin": subprocess.DEVNULL,
            }
            if os.name == "nt":
                # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP so the child
                # outlives the TUI and doesn't share its console.
                kwargs["creationflags"] = 0x00000008 | 0x00000200  # type: ignore[assignment]
            else:
                kwargs["start_new_session"] = True
            subprocess.Popen([npm, "start"], **kwargs)  # noqa: S603
        except OSError as e:
            self.console.print(f"[red]Failed to spawn bridge:[/] {e}")
            return

        self.console.print(
            f"[green]✓ Bridge starting in the background.[/] "
            f"[dim]Log: {log_path}[/]\n"
            "[dim]Give it ~10 s to initialize, then continue…[/]"
        )
        # Wait for the port to come up, then try again once. If it still
        # isn't up after 15 s, give up rather than recursing forever.
        import socket as _socket
        import urllib.parse as _urlparse
        parsed = _urlparse.urlparse(bridge_url)
        host = parsed.hostname or "localhost"
        port = parsed.port or 3001
        for _ in range(30):  # 30 × 0.5 s = 15 s
            try:
                with _socket.create_connection((host, port), timeout=0.5):
                    self.console.print("[green]✓ Bridge is up. Fetching QR…[/]")
                    self._show_whatsapp_qr()
                    return
            except OSError:
                time.sleep(0.5)
        self.console.print(
            "[yellow]Bridge didn't come online within 15s. Check "
            f"{log_path} for errors.[/]"
        )

    def _render_qr_panel(self, qr_string: str, age_seconds: int | None) -> None:
        """Render a scannable QR in the terminal from the raw WA payload.

        whatsapp-web.js emits the literal string that must be encoded into
        the QR image — we use qrcode-terminal-equivalent output via the
        `qrcode` Python package. Falls back to printing the raw string (so
        the user can paste it into any QR generator) if qrcode is missing."""
        from rich.panel import Panel

        age_note = (
            f"[dim]QR age: {age_seconds}s — rotates every ~20s, will refresh on next Reconnect.[/]"
            if age_seconds is not None
            else ""
        )

        try:
            import qrcode  # type: ignore

            qr = qrcode.QRCode(border=1)
            qr.add_data(qr_string)
            qr.make(fit=True)
            # Render into a string buffer so Rich owns the final output.
            import io
            buf = io.StringIO()
            qr.print_ascii(out=buf, invert=True)
            art = buf.getvalue().rstrip("\n")
            body = f"{art}\n\n{age_note}\n\n[dim]Open WhatsApp → Settings → Linked devices → Link a device.[/]"
            self.console.print(
                Panel(body, title="Scan this with WhatsApp", border_style="green")
            )
        except ImportError:
            # Graceful fallback — user can paste this into any online QR
            # generator or run `pip install qrcode` to get inline rendering.
            self.console.print(
                Panel(
                    f"[dim]Install [cyan]qrcode[/] for inline rendering: "
                    f"[cyan]pip install qrcode[/][/]\n\n"
                    f"[bold]Raw QR payload:[/]\n"
                    f"[cyan]{qr_string}[/]\n\n{age_note}",
                    title="WhatsApp QR (raw)",
                    border_style="yellow",
                )
            )

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
        header_renderable=None,
        allow_back: bool = True,
    ) -> int | None:
        """Render an arrow-key menu.

        Prefers `header_renderable` (a zero-arg callable returning a Rich
        renderable) which drives a Live(screen=True) loop — alt-screen means
        no scrollback stacking, so the menu updates in place on every key.

        Falls back to the legacy `header_renderer` (print-based) only when
        no renderable is provided; that path still uses console.clear() and
        will visibly stack frames on terminals with persistent scrollback.
        """
        if not items:
            return None
        # Clamp into range. Accepts negative indices (Python-style from the
        # end) for completeness and guards against any caller passing a
        # stale index after items were filtered down.
        if selected < 0:
            selected = max(0, len(items) + selected)
        if selected >= len(items):
            selected = 0

        # Preferred path: alt-screen Live rendering.
        if header_renderable is not None:
            return self._arrow_select_live(
                title=title,
                items=items,
                selected=selected,
                header_renderable=header_renderable,
                allow_back=allow_back,
            )

        # Legacy path — kept only so we don't have to retrofit every caller
        # at once. Anything passing header_renderer= still works; it just
        # won't get the in-place redraw benefit.
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

    def _arrow_select_live(
        self,
        *,
        title: str | None,
        items: list[str],
        selected: int,
        header_renderable,
        allow_back: bool,
    ) -> int | None:
        """Alt-screen Live-driven arrow menu. See _arrow_select for docs."""
        def build_frame() -> Group:
            parts: list = [header_renderable()]
            if title:
                parts.append(Rule(title, style="cyan"))
                parts.append(Text(""))
            for i, label in enumerate(items):
                if i == selected:
                    parts.append(Text.from_markup(f"  [bold cyan]▶ {label}[/]"))
                else:
                    parts.append(Text.from_markup(f"    [dim]{label}[/]"))
            parts.append(Text(""))
            hint = "[dim]↑/↓ navigate · Enter select"
            if allow_back:
                hint += " · ESC back"
            hint += " · Ctrl+C quit[/]"
            parts.append(Text.from_markup(hint))
            return Group(*parts)

        # refresh_per_second matched to a modest 10Hz — the frame only
        # repaints on keypress, but Live needs a nonzero rate to cope with
        # terminal size changes and auto-refresh the renderable if the
        # header's own state (e.g. running uptime) changes under it.
        with Live(
            build_frame(),
            console=self.console,
            refresh_per_second=10,
            screen=True,
            transient=False,
        ) as live:
            while True:
                key = read_key()
                if key == KEY_CTRL_C:
                    # Leaving the Live context first ensures the alt-screen
                    # is dropped before KeyboardInterrupt propagates, so the
                    # user's shell history is restored cleanly.
                    live.stop()
                    self._drain_stdin()
                    raise KeyboardInterrupt
                if key == KEY_ESC and allow_back:
                    self._drain_stdin()
                    return None
                if key == KEY_UP:
                    selected = (selected - 1) % len(items)
                elif key == KEY_DOWN:
                    selected = (selected + 1) % len(items)
                elif key == KEY_ENTER:
                    self._drain_stdin()
                    return selected
                live.update(build_frame())

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
        # Drop any commented-out versions of this key before writing — uncommenting
        # them would momentarily push a stale value into os.environ (and, if an
        # active line also exists, create a duplicate that set_key wouldn't
        # clean up). Stripping first means set_key always writes exactly one
        # active assignment with the new value.
        self._strip_commented_env(key)
        # quote_mode="always" — unquoted values with spaces break `source .env`
        # in bash, and values containing '#' get parsed as comments by dotenv
        # itself. Always quoting preserves credentials with #, $, ", spaces, etc.
        set_key(str(self.env_path), key, value, quote_mode="always")
        os.environ[key] = value
        self._invalidate_config_cache()

    def _strip_commented_env(self, key: str) -> bool:
        """Remove all `# KEY=...` (and `# export KEY=...`) lines from .env.
        Active lines are left untouched. Returns True if any lines were dropped."""
        if not self.env_path.exists():
            return False
        lines = self.env_path.read_text(encoding="utf-8").splitlines()
        pattern = self._env_line_pattern(key)
        new_lines = []
        changed = False
        for line in lines:
            stripped = line.lstrip()
            if stripped.startswith("#"):
                body = stripped.lstrip("#").lstrip()
                if pattern.match(body):
                    changed = True
                    continue  # drop this commented duplicate
            new_lines.append(line)
        if changed:
            self.env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        return changed

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
        """Activate a commented-out `# KEY=...` line in .env.

        Semantics:
          - If an active line for `key` already exists, drop every commented
            duplicate (they'd become stale doubles otherwise) and keep the
            active line's value.
          - Otherwise uncomment the FIRST commented match and drop the rest.
          - No-op if no matching lines exist at all.

        Returns True if the file was modified."""
        if not self.env_path.exists():
            return False
        lines = self.env_path.read_text(encoding="utf-8").splitlines()
        pattern = self._env_line_pattern(key)

        # First pass: is there already an active assignment for this key?
        has_active = any(
            pattern.match(line.lstrip())
            for line in lines
            if not line.lstrip().startswith("#")
        )

        changed = False
        new_lines: list[str] = []
        activated = False  # have we uncommented one yet?
        new_value_line: str | None = None

        for line in lines:
            stripped = line.lstrip()
            if not stripped.startswith("#"):
                new_lines.append(line)
                continue
            body = stripped.lstrip("#").lstrip()
            if not pattern.match(body):
                new_lines.append(line)
                continue
            # Matches our key, and is commented.
            if has_active or activated:
                # Drop — either an active line already wins, or we already
                # uncommented the first duplicate.
                changed = True
                continue
            # Uncomment this one. Preserve the original body verbatim so the
            # user's quoting style survives round-trips.
            new_lines.append(body)
            new_value_line = body
            activated = True
            changed = True

        if activated and new_value_line is not None:
            _, _, raw_val = new_value_line.partition("=")
            os.environ[key] = self._unquote_dotenv_value(raw_val)

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
