"""Autonoma TUI — Textual control tower.

One ``AutonomaTUI`` app with a screen stack instead of the old hand-rolled
raw-mode input loop and Rich ``Live`` frames:

    MainScreen ──► LogsScreen / StatusScreen / ChannelsScreen /
                   ConnectorsScreen / SetupWizardScreen

Every modal is an awaited result, so multi-step actions read top to bottom::

    @work(exclusive=True, group="chan")
    async def _reconnect(self, name: str) -> None:
        if not await self.ask("Reconnect", "Rotate credentials?"):
            return
        values = await self.credentials(name)
        ...

Blocking work (agent stop/start, HTTP calls, DB reads) runs behind a
``RunDialog`` in a thread; long async waits (OAuth callback, WhatsApp QR)
are awaited behind the same dialog. The UI never freezes.

``AutonomaTUI().run()`` is still the public entry point used by
``autonoma.main.cli_entry``.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any, Callable, Coroutine, Sequence, cast

from dotenv import load_dotenv, set_key
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    HelpPanel,
    Input,
    Label,
    OptionList,
    RichLog,
    Static,
)
from textual.widgets.option_list import Option

from autonoma.config import LLMConfig, load_config, save_yaml_config
from autonoma.models.catalog import PROVIDER_SPECS, ProviderSpec
from autonoma.models import verify_model
from autonoma.runtime import AgentRunner, LogRingBuffer, install_logging
from autonoma.splash import AutonomaSplash

BANNER = "AUTONOMA"


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

CHANNEL_ENV: dict[str, list[str]] = {
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

CHANNEL_ORDER = list(CHANNEL_ENV)

_SECRET_HINTS = ("TOKEN", "PASSWORD", "KEY", "SECRET")

_STATUS_COLOURS = {
    "running": "green",
    "starting": "yellow",
    "stopping": "yellow",
    "stopped": "dim",
    "error": "red",
}

_LOG_LEVEL_COLOURS = {
    "DEBUG": "dim",
    "INFO": "cyan",
    "WARNING": "yellow",
    "ERROR": "red",
    "CRITICAL": "bold red",
}


# --------------------------------------------------------------------------
# Small pure helpers
# --------------------------------------------------------------------------


def _mask(val: str) -> str:
    if len(val) <= 8:
        return "***"
    return val[:4] + "…" + val[-2:]


def _fmt_uptime(sec: int) -> str:
    if sec <= 0:
        return "—"
    h, rem = divmod(int(sec), 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _env_line_pattern(key: str) -> re.Pattern[str]:
    """Match a dotenv assignment for `key` with optional `export ` prefix and
    optional whitespace around `=`."""
    return re.compile(rf"^(?:export\s+)?{re.escape(key)}\s*=")


def _unquote_dotenv_value(raw: str) -> str:
    """Decode a dotenv-style RHS into its literal string value."""
    s = raw.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ('"', "'"):
        inner = s[1:-1]
        if s[0] == '"':
            return (
                inner.replace("\\\\", "\x00")
                .replace('\\"', '"')
                .replace("\\n", "\n")
                .replace("\\r", "\r")
                .replace("\\t", "\t")
                .replace("\x00", "\\")
            )
        return inner  # single-quoted: literal
    hash_idx = s.find(" #")
    if hash_idx >= 0:
        s = s[:hash_idx].rstrip()
    return s


def _styled_log_line(line: str) -> Text:
    """Colour the ``HH:MM:SS [LEVEL]`` prefix of a formatted log line.

    Built with ``Text.append`` rather than markup so message bodies that
    contain ``[`` render literally.
    """
    match = re.match(r"^(\S+\s+)\[([A-Za-z]+)\]", line)
    if not match:
        return Text(line)
    colour = _LOG_LEVEL_COLOURS.get(match.group(2).upper())
    if not colour:
        return Text(line)
    text = Text(match.group(1), style="dim")
    text.append(f"[{match.group(2)}]", style=colour)
    text.append(line[match.end() :])
    return text


def _probe_tcp(url: str, timeout: float = 1.0) -> bool:
    """True if the host:port behind `url` accepts a TCP connection."""
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname or "localhost"
    port = parsed.port or (443 if parsed.scheme == "https" else 3001)
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _http(url: str, method: str = "GET") -> tuple[bool, Any]:
    req = urllib.request.Request(url, method=method)
    try:
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            return True, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            return False, json.loads(exc.read().decode("utf-8")).get("error", str(exc))
        except Exception:
            return False, str(exc)
    except Exception as exc:
        return False, str(exc)


# --------------------------------------------------------------------------
# Workspace — every .env / autonoma.yaml touch, and nothing else
# --------------------------------------------------------------------------


class Workspace:
    """Disk state for one run of the TUI (`.env`, `autonoma.yaml`, logs).

    Kept free of UI concerns so the screens can share a single instance and
    so this logic stays easy to test on its own.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self.env_path = root / ".env"
        self.yaml_path = root / "autonoma.yaml"
        self.log_file = root / ".session" / "autonoma.log"
        self.env_path.parent.mkdir(parents=True, exist_ok=True)
        self.env_path.touch(exist_ok=True)
        load_dotenv(self.env_path, override=True)
        # Config cache keyed by (env_mtime, yaml_mtime); invalidated explicitly
        # after we mutate either file.
        self._config_key: tuple[float, float] | None = None
        self._config_value: Any = None
        self._env_mtime: float | None = None

    # ----- config -----

    def load(self):
        """Cached `load_config`; returns None when config can't be read."""
        try:
            env_m = self.env_path.stat().st_mtime if self.env_path.exists() else 0.0
            yaml_m = self.yaml_path.stat().st_mtime if self.yaml_path.exists() else 0.0
        except OSError:
            env_m = yaml_m = 0.0
        key = (env_m, yaml_m)
        if key == self._config_key:
            return self._config_value
        try:
            load_dotenv(self.env_path, override=True)
            cfg = load_config(str(self.yaml_path) if self.yaml_path.exists() else None)
        except Exception:
            cfg = None
        self._config_key = key
        self._config_value = cfg
        return cfg

    def invalidate(self) -> None:
        """Force config + .env re-reads on the next call."""
        self._config_key = None
        self._config_value = None
        self._env_mtime = None

    def is_first_run(self) -> bool:
        """True when no provider API key is configured yet."""
        load_dotenv(self.env_path, override=True)
        cfg = self.load()
        provider = os.getenv("AUTONOMA_LLM_PROVIDER", "") or (
            cfg.llm.provider if cfg else ""
        )
        spec = next((s for s in PROVIDER_SPECS if s.key == provider), None)
        if os.getenv("AUTONOMA_LLM_API_KEY") or (spec and os.getenv(spec.env_key)):
            return False
        # An inline api_key in autonoma.yaml counts too — don't re-wizard those.
        if cfg and getattr(cfg.llm, "api_key", None):
            return False
        return True

    # ----- .env reads -----

    def ensure_env(self) -> None:
        """Reload .env into os.environ only if the file changed on disk."""
        try:
            mtime = self.env_path.stat().st_mtime if self.env_path.exists() else 0.0
        except OSError:
            mtime = 0.0
        if mtime != self._env_mtime:
            load_dotenv(self.env_path, override=True)
            self._env_mtime = mtime

    def channel_enabled(self, name: str) -> bool:
        self.ensure_env()
        return all(os.getenv(var) for var in CHANNEL_ENV[name])

    def credential_preview(self, name: str) -> str:
        """Rich-markup summary of a channel's credentials, secrets masked."""
        self.ensure_env()
        parts = []
        for var in CHANNEL_ENV[name]:
            val = os.getenv(var, "")
            if not val:
                parts.append(f"[dim]{var}=?[/]")
            else:
                parts.append(f"{var}=[green]{_mask(val)}[/]")
        return " ".join(parts)

    @staticmethod
    def enabled_channels(cfg) -> list[str]:
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

    # ----- .env writes -----

    def set_env(self, key: str, value: str) -> None:
        self.env_path.parent.mkdir(parents=True, exist_ok=True)
        self.env_path.touch(exist_ok=True)
        # Drop commented-out copies first so set_key writes exactly one active
        # assignment and no stale uncommented value ever lands in os.environ.
        self.strip_commented_env(key)
        # quote_mode="always" keeps #, $, " and spaces safe for `source .env`
        # and for dotenv's own comment parsing.
        set_key(str(self.env_path), key, value, quote_mode="always")
        os.environ[key] = value
        self.invalidate()

    def strip_commented_env(self, key: str) -> bool:
        """Remove all `# KEY=...` lines. Active lines are left untouched."""
        if not self.env_path.exists():
            return False
        lines = self.env_path.read_text(encoding="utf-8").splitlines()
        pattern = _env_line_pattern(key)
        new_lines = []
        changed = False
        for line in lines:
            stripped = line.lstrip()
            if stripped.startswith("#"):
                body = stripped.lstrip("#").lstrip()
                if pattern.match(body):
                    changed = True
                    continue
            new_lines.append(line)
        if changed:
            self.env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        return changed

    def disable_env(self, key: str) -> bool:
        """Comment out `KEY=...` and drop it from os.environ."""
        if not self.env_path.exists():
            return False
        lines = self.env_path.read_text(encoding="utf-8").splitlines()
        pattern = _env_line_pattern(key)
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
            self.invalidate()
        return changed

    def enable_env(self, key: str) -> bool:
        """Activate a commented-out `# KEY=...` line.

        An already-active assignment wins; otherwise the first commented match
        is uncommented and later duplicates are dropped. No-op if there is
        nothing to flip. Returns True if the file changed.
        """
        if not self.env_path.exists():
            return False
        lines = self.env_path.read_text(encoding="utf-8").splitlines()
        pattern = _env_line_pattern(key)

        has_active = any(
            pattern.match(line.lstrip())
            for line in lines
            if not line.lstrip().startswith("#")
        )

        changed = False
        new_lines: list[str] = []
        activated = False
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
            if has_active or activated:
                changed = True
                continue
            # Preserve the user's original quoting style verbatim.
            new_lines.append(body)
            new_value_line = body
            activated = True
            changed = True

        if activated and new_value_line is not None:
            _, _, raw_val = new_value_line.partition("=")
            os.environ[key] = _unquote_dotenv_value(raw_val)

        if changed:
            self.env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
            self.invalidate()
        return changed

    def set_channel_enabled(self, name: str, enabled: bool) -> None:
        """Persist cfg.channels.<name>.enabled so the runtime honours the
        toggle on its next start. The env-var flip alone is not enough."""
        save_yaml_config(
            self.yaml_path, {"channels": {name: {"enabled": bool(enabled)}}}
        )
        self.invalidate()


# --------------------------------------------------------------------------
# Modal dialogs
# --------------------------------------------------------------------------


class Dialog(ModalScreen[bool]):
    """Message box. Dismisses True on confirm, False on cancel / Escape."""

    BINDINGS = [Binding("escape", "cancel", show=False)]

    def __init__(
        self,
        title: str,
        body: str,
        *,
        confirm: str = "OK",
        cancel: str | None = None,
    ) -> None:
        super().__init__(classes="dialog")
        self._title = title
        self._body = body
        self._confirm = confirm
        self._cancel = cancel

    def compose(self) -> ComposeResult:
        buttons = [Button(self._confirm, id="confirm", variant="primary")]
        if self._cancel:
            buttons.append(Button(self._cancel, id="cancel"))
        yield Vertical(
            Static(self._title, id="dlg-title"),
            Static(self._body, id="dlg-body"),
            Horizontal(*buttons, id="dlg-buttons"),
            classes="dbox",
        )

    def on_mount(self) -> None:
        self.query_one("#confirm", Button).focus()

    @on(Button.Pressed)
    def _pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm")

    def action_cancel(self) -> None:
        self.dismiss(False)


class ChoiceDialog(ModalScreen[str | None]):
    """Arrow-key picker. Dismisses the chosen option's id, or None on Escape."""

    BINDINGS = [Binding("escape", "cancel", show=False)]

    def __init__(
        self,
        title: str,
        options: Sequence[tuple[str | None, str]],
        *,
        note: str = "",
    ) -> None:
        super().__init__(classes="dialog")
        self._title = title
        self._options = list(options)
        self._note = note

    def compose(self) -> ComposeResult:
        children: list[Any] = [Static(self._title, id="dlg-title")]
        if self._note:
            children.append(Static(self._note, id="dlg-note"))
        children.append(
            OptionList(
                *(Option(label, id=str(i)) for i, (_, label) in enumerate(self._options)),
                id="choice-list",
            )
        )
        children.append(Static("[dim]↑/↓ navigate · enter select · esc back[/]"))
        yield Vertical(*children, classes="dbox")

    def on_mount(self) -> None:
        self.query_one("#choice-list", OptionList).focus()

    @on(OptionList.OptionSelected)
    def _selected(self, event: OptionList.OptionSelected) -> None:
        try:
            index = int(event.option.id or "0")
        except ValueError:
            index = 0
        self.dismiss(self._options[index][0])

    def action_cancel(self) -> None:
        self.dismiss(None)


class RunDialog(ModalScreen[Any]):
    """Run work to completion, then dismiss with its result.

    A plain callable runs in a thread (Escape does nothing); a coroutine is
    awaited and Escape cancels it, dismissing None.
    """

    BINDINGS = [Binding("escape", "cancel", show=False)]

    def __init__(
        self, message: str, work: Callable[[], Any] | Coroutine[Any, Any, Any]
    ) -> None:
        super().__init__(classes="dialog")
        self._message = message
        self._work = work
        self._cancellable = asyncio.iscoroutine(work)

    def compose(self) -> ComposeResult:
        hint = "escape to cancel" if self._cancellable else "working…"
        yield Vertical(
            Static(self._message, id="run-message"),
            Static(f"[dim]{hint}[/]"),
            classes="dbox",
        )

    def on_mount(self) -> None:
        self._run()

    @work(exclusive=True, group="dialog")
    async def _run(self) -> None:
        try:
            if self._cancellable:
                result = await cast(Coroutine[Any, Any, Any], self._work)
            else:
                result = await asyncio.to_thread(cast(Callable[[], Any], self._work))
        except Exception as exc:  # noqa: BLE001 - surfaced to the caller
            result = exc
        if not self.is_mounted:
            return
        self.dismiss(result)

    def action_cancel(self) -> None:
        if self._cancellable:
            self.dismiss(None)


class CredentialDialog(ModalScreen[dict[str, str] | None]):
    """One masked input per environment variable. Dismisses the values the
    user actually typed (empty fields are omitted), or None on Cancel."""

    BINDINGS = [Binding("escape", "cancel", show=False)]

    def __init__(self, name: str, variables: Sequence[str] | None = None) -> None:
        super().__init__(classes="dialog")
        self._name = name
        self._variables = list(variables or CHANNEL_ENV[name])

    def compose(self) -> ComposeResult:
        rows: list[Any] = [
            Static(f"Configure {self._name}", id="dlg-title"),
            Static(
                f"[dim]{CHANNEL_DESCRIPTIONS.get(self._name, '')}[/]", id="dlg-note"
            ),
        ]
        for var in self._variables:
            current = os.getenv(var, "")
            label = f"{var}"
            if current:
                label += f"  [dim](current: {_mask(current)})[/]"
            secret = any(hint in var for hint in _SECRET_HINTS)
            rows.append(Label(label, classes="cred-label"))
            rows.append(
                Input(
                    placeholder=(
                        "hidden — enter to keep current"
                        if secret
                        else "enter to keep current"
                    ),
                    password=secret,
                    id=f"field::{var}",
                )
            )
        rows.append(
            Static(
                "[dim]leave a field empty to keep its current value[/]", id="dlg-note"
            )
        )
        rows.append(
            Horizontal(
                Button("Save", id="save", variant="primary"),
                Button("Cancel", id="cancel"),
                id="dlg-buttons",
            )
        )
        yield Vertical(*rows, classes="dbox")

    def on_mount(self) -> None:
        self.query_one("#save", Button).focus()

    @on(Button.Pressed)
    def _pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
            return
        values: dict[str, str] = {}
        for var in self._variables:
            value = self.query_one(f"#field::{var}", Input).value.strip()
            if value:
                values[var] = value
        self.dismiss(values)

    def action_cancel(self) -> None:
        self.dismiss(None)


class QrDialog(ModalScreen[None]):
    """Scannable WhatsApp QR rendered in the terminal."""

    BINDINGS = [Binding("escape", "cancel", show=False)]

    def __init__(self, art: str, note: str = "") -> None:
        super().__init__(classes="dialog")
        self._art = art
        self._note = note

    def compose(self) -> ComposeResult:
        children: list[Any] = [
            Static("Scan this with WhatsApp", id="dlg-title"),
            Static(Text(self._art), id="qr-art"),
        ]
        if self._note:
            children.append(Static(f"[dim]{self._note}[/]"))
        children.append(
            Static(
                "[dim]WhatsApp → Settings → Linked devices → Link a device[/]"
            )
        )
        children.append(
            Horizontal(Button("Close", id="close", variant="primary"), id="dlg-buttons")
        )
        yield Vertical(*children, classes="dbox")

    def on_mount(self) -> None:
        self.query_one("#close", Button).focus()

    @on(Button.Pressed)
    def _close(self, _event: Button.Pressed) -> None:
        self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class BaseScreen(Screen):
    """Shared await-a-modal helpers. Only ever called from ``@work`` flows —
    Textual requires ``wait_for_dismiss`` to be awaited inside a worker."""

    @property
    def tui(self) -> "AutonomaTUI":
        return cast("AutonomaTUI", self.app)

    async def ask(
        self,
        title: str,
        body: str,
        *,
        confirm: str = "OK",
        cancel: str | None = None,
    ) -> bool:
        return await cast(App, self.app).push_screen(
            Dialog(title, body, confirm=confirm, cancel=cancel),
            wait_for_dismiss=True,
        )

    async def choose(
        self,
        title: str,
        options: Sequence[tuple[str | None, str]],
        *,
        note: str = "",
    ) -> str | None:
        return await cast(App, self.app).push_screen(
            ChoiceDialog(title, options, note=note),
            wait_for_dismiss=True,
        )

    async def task(
        self,
        message: str,
        work: Callable[[], Any] | Coroutine[Any, Any, Any],
    ) -> Any:
        return await cast(App, self.app).push_screen(
            RunDialog(message, work), wait_for_dismiss=True
        )

    async def credentials(
        self, name: str, variables: Sequence[str] | None = None
    ) -> dict[str, str] | None:
        return await cast(App, self.app).push_screen(
            CredentialDialog(name, variables), wait_for_dismiss=True
        )

class BackScreen(BaseScreen):
    """A screen that leaves on Escape."""

    BINDINGS = [Binding("escape", "back", "Back")]

    def action_back(self) -> None:
        self.app.pop_screen()


class MenuOptionList(OptionList):
    """OptionList that advertises its arrow keys in the screen footer.

    Textual ships those bindings with ``show=False``, and the focused
    widget's binding shadows the screen's for the same key — so the hint
    has to live on the widget itself to reach the footer.
    """

    BINDINGS = [
        Binding("up", "cursor_up", "Up"),
        Binding("down", "cursor_down", "Down"),
        Binding("enter", "select", "Select"),
        Binding("home", "first", "First", show=False),
        Binding("end", "last", "Last", show=False),
        Binding("pageup", "page_up", "Page Up", show=False),
        Binding("pagedown", "page_down", "Page Down", show=False),
    ]


class MenuDataTable(DataTable):
    """DataTable whose row navigation shows up in the footer."""

    BINDINGS = [
        Binding("enter", "select_cursor", "Select"),
        Binding("up", "cursor_up", "Up"),
        Binding("down", "cursor_down", "Down"),
        Binding("right", "cursor_right", "Right", show=False),
        Binding("left", "cursor_left", "Left", show=False),
        Binding("pageup", "page_up", "Page up", show=False),
        Binding("pagedown", "page_down", "Page down", show=False),
        Binding("ctrl+home", "scroll_top", "Top", show=False),
        Binding("ctrl+end", "scroll_bottom", "Bottom", show=False),
        Binding("home", "scroll_home", "Home", show=False),
        Binding("end", "scroll_end", "End", show=False),
    ]


class ScrollRichLog(RichLog):
    """RichLog that advertises its arrow keys in the screen footer.

    ``ScrollView`` ships those bindings with ``show=False``, and the focused
    widget shadows the screen's binding for the same key.
    """

    BINDINGS = [
        Binding("up", "scroll_up", "Up"),
        Binding("down", "scroll_down", "Down"),
        Binding("left", "scroll_left", "Scroll Left", show=False),
        Binding("right", "scroll_right", "Scroll Right", show=False),
        Binding("home", "scroll_home", "Home", show=False),
        Binding("end", "scroll_end", "End", show=False),
        Binding("pageup", "page_up", "Page Up", show=False),
        Binding("pagedown", "page_down", "Page Down", show=False),
        Binding("ctrl+pageup", "page_left", show=False),
        Binding("ctrl+pagedown", "page_right", show=False),
    ]


class KeysPanel(HelpPanel):
    """Textual's keys panel with an explicit Close button.

    The palette's "Keys" command only toggles the panel open, which makes
    it look like a one-way door.
    """

    DEFAULT_CSS = """
    KeysPanel #keys-close {
        width: 100%;
        margin: 1 0;
    }
    """

    def compose(self) -> ComposeResult:
        yield from super().compose()
        yield Button("Close", id="keys-close")


# --------------------------------------------------------------------------
# Screens
# --------------------------------------------------------------------------


class MainScreen(BaseScreen):
    """The control tower: live status header over an arrow-key menu."""

    MENU: list[tuple[str, str]] = [
        ("logs", "Live logs"),
        ("config", "Change AI provider or model"),
        ("channels", "Connect messaging apps"),
        ("connectors", "Connect accounts"),
        ("dashboard", "Open web dashboard"),
        ("status", "Check status"),
        ("restart", "Restart Autonoma"),
        ("quit", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield AutonomaSplash(reserved_rows=26, id="splash")
        yield Static(id="status")
        yield MenuOptionList(
            *(Option(label, id=key) for key, label in self.MENU), id="menu"
        )
        yield Static("[dim]↑/↓ navigate · enter select · ctrl+c quit[/]", id="hint")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#menu", OptionList).focus()
        self._refresh_status()
        self.set_interval(1.0, self._refresh_status)

    def _refresh_status(self) -> None:
        self.query_one("#status", Static).update(
            _status_panel(self.tui.ws, self.tui.runner)
        )

    @on(OptionList.OptionSelected, "#menu")
    def _select(self, event: OptionList.OptionSelected) -> None:
        key = event.option.id or ""
        if key == "logs":
            self.app.push_screen(LogsScreen())
        elif key == "status":
            self.app.push_screen(StatusScreen())
        elif key == "channels":
            self.tui.open_with_agent_stopped(ChannelsScreen)
        elif key == "connectors":
            self.app.push_screen(ConnectorsScreen())
        elif key == "config":
            self.tui.open_with_agent_stopped(lambda: SetupWizardScreen())
        elif key == "dashboard":
            self._open_dashboard_flow()
        elif key == "restart":
            self._restart_flow()
        elif key == "quit":
            self.app.exit()

    @work(exclusive=True, group="main")
    async def _open_dashboard_flow(self) -> None:
        url = self.tui.base_url()
        result = await self.task(f"Opening {url}…", lambda: _open_browser(url))
        if isinstance(result, Exception):
            await self.ask("Dashboard", f"[red]Could not open the browser:[/] {result}")
            return
        reachable, opened = result
        if not opened:
            await self.ask("Dashboard", "[red]Could not launch the browser.[/]")
        elif not reachable:
            await self.ask(
                "Dashboard",
                f"[yellow]⚠ {url} is not reachable yet — the agent may still "
                "be starting.[/]\n\nOpened the browser anyway.",
            )

    @work(exclusive=True, group="main")
    async def _restart_flow(self) -> None:
        result = await self.task("Restarting agent…", self.tui.restart_agent)
        if isinstance(result, Exception):
            await self.ask("Restart failed", f"[red]{result}[/]")
            return
        await self.ask("Restarted", "[green]✓ Agent restarted.[/]")
        self._refresh_status()


class LogsScreen(BaseScreen):
    """Fullscreen live-tailing log view."""

    BINDINGS = [
        Binding("escape", "back", "Back"),
        Binding("q", "back", show=False),
        Binding("c", "clear", "Clear"),
        Binding("f", "toggle_follow", "Follow"),
        Binding("up", "line_up", "Up"),
        Binding("down", "line_down", "Down"),
        Binding("pageup", "page_up", show=False),
        Binding("pagedown", "page_down", show=False),
        Binding("home", "to_top", show=False),
        Binding("end", "to_bottom", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.follow = True
        self._previous: list[str] = []

    def compose(self) -> ComposeResult:
        yield Header()
        yield ScrollRichLog(
            id="log",
            max_lines=5000,
            wrap=False,
            markup=False,
            highlight=False,
            auto_scroll=True,
        )
        yield Static(id="log-hint")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#log", RichLog).focus()
        self._set_hint()
        self._pull()
        self.set_interval(0.4, self._pull)

    def _set_hint(self) -> None:
        state = "[green]following[/]" if self.follow else "[yellow]paused[/]"
        self.query_one("#log-hint", Static).update(
            f"{state} [dim]· ↑/↓ scroll · pgup/pgdn page · home/end · "
            "f follow · c clear · esc back[/]"
        )

    def _pull(self) -> None:
        """Append whatever is new in the ring buffer since the last tick."""
        ring = self.tui.log_ring
        if ring is None:
            return
        current = ring.all()
        if current == self._previous:
            return
        log = self.query_one("#log", RichLog)
        log.auto_scroll = self.follow
        if (
            len(current) >= len(self._previous)
            and current[: len(self._previous)] == self._previous
        ):
            new_lines = current[len(self._previous) :]
        else:
            # Cleared, or the ring wrapped — repaint from scratch.
            log.clear()
            new_lines = current
        for line in new_lines:
            log.write(_styled_log_line(line))
        self._previous = current

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_clear(self) -> None:
        if self.tui.log_ring is not None:
            self.tui.log_ring.clear()
        self.query_one("#log", RichLog).clear()
        self._previous = []
        self.follow = True
        self._set_hint()

    def action_toggle_follow(self) -> None:
        self.follow = not self.follow
        log = self.query_one("#log", RichLog)
        log.auto_scroll = self.follow
        if self.follow:
            log.scroll_end(animate=False)
        self._set_hint()

    def action_line_up(self) -> None:
        self._stop_follow()
        self.query_one("#log", RichLog).scroll_up(animate=False)

    def action_line_down(self) -> None:
        log = self.query_one("#log", RichLog)
        log.scroll_down(animate=False)
        if log.scroll_offset.y >= log.max_scroll_y:
            self.follow = True
            log.auto_scroll = True
            self._set_hint()

    def action_page_up(self) -> None:
        self._stop_follow()
        self.query_one("#log", RichLog).scroll_page_up(animate=False)

    def action_page_down(self) -> None:
        self.query_one("#log", RichLog).scroll_page_down(animate=False)

    def action_to_top(self) -> None:
        self._stop_follow()
        self.query_one("#log", RichLog).scroll_home(animate=False)

    def action_to_bottom(self) -> None:
        log = self.query_one("#log", RichLog)
        log.scroll_end(animate=False)
        self.follow = True
        log.auto_scroll = True
        self._set_hint()

    def _stop_follow(self) -> None:
        if self.follow:
            self.follow = False
            self.query_one("#log", RichLog).auto_scroll = False
            self._set_hint()


class StatusScreen(BackScreen):
    """Configuration / channels / memory / proxy health, gathered off-thread."""

    def compose(self) -> ComposeResult:
        yield Header()
        yield VerticalScroll(Static(id="status-body"), id="status-scroll")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#status-body", Static).update("[dim]Collecting status…[/]")
        self._load_flow()

    @work(exclusive=True, group="status")
    async def _load_flow(self) -> None:
        panels = await asyncio.to_thread(self._collect)
        if not self.is_mounted:
            return
        body = Table.grid(padding=(0, 0))
        body.add_column()
        for panel in panels:
            body.add_row(panel)
        self.query_one("#status-body", Static).update(body)

    def _collect(self) -> list[Panel]:
        ws = self.tui.ws
        cfg = ws.load()
        if cfg is None:
            return [Panel("[red]Could not load config.[/]", title="Configuration")]

        rows = Table(show_header=False, box=None, padding=(0, 2))
        rows.add_column(style="dim", min_width=11)
        rows.add_column()
        rows.add_row("Name", cfg.name)
        rows.add_row("Provider", cfg.llm.provider_name or cfg.llm.provider)
        rows.add_row("Model", cfg.llm.model)
        rows.add_row(
            "API key",
            "[green]✓ configured[/]" if cfg.llm.api_key else "[red]✗ missing[/]",
        )
        rows.add_row("Gateway", f"{cfg.gateway.host}:{cfg.gateway.port}")
        rows.add_row("Dashboard", self.tui.base_url())
        rows.add_row("Workspace", cfg.workspace_dir)
        rows.add_row("Memory DB", cfg.memory.db_path)
        rows.add_row("Log file", str(ws.log_file))
        panels = [Panel(rows, title="Configuration", border_style="cyan")]

        channels = Table(show_header=True, header_style="bold cyan", box=None)
        channels.add_column("Channel")
        channels.add_column("Enabled")
        for name in CHANNEL_ORDER:
            channels.add_row(
                name,
                "[green]✓[/]" if ws.channel_enabled(name) else "[dim]—[/]",
            )
        panels.append(Panel(channels, title="Channels", border_style="cyan"))

        panels.append(self._memory_panel(cfg))
        panels.append(self._proxy_panel(cfg))
        return panels

    @staticmethod
    def _memory_panel(cfg) -> Panel:
        try:
            from autonoma.memory.database import MemoryDatabase

            Path(cfg.memory.db_path).parent.mkdir(parents=True, exist_ok=True)
            db = MemoryDatabase(cfg.memory.db_path)
            try:
                active = db.count(active_only=True)
                total = db.count(active_only=False)
                expiry = db.get_expiry_stats()
            finally:
                db.close()
        except Exception as exc:  # noqa: BLE001 - stats are best-effort
            return Panel(f"[dim]Memory stats unavailable: {exc}[/]", title="Memory")

        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column(style="dim", min_width=18)
        table.add_column()
        table.add_row("Active memories", str(active))
        table.add_row("Archived", str(total - active))
        table.add_row("Stale (needs review)", str(expiry.get("stale", 0)))
        table.add_row("Expired", str(expiry.get("expired", 0)))
        return Panel(table, title="Memory", border_style="cyan")

    @staticmethod
    def _proxy_panel(cfg) -> Panel:
        """Probe each configured channel proxy. Never raises."""
        try:
            from autonoma.gateway.proxy_health import check_proxy, mask_proxy_url
        except Exception as exc:  # noqa: BLE001
            return Panel(
                f"[dim]Proxy health module unavailable: {exc}[/]", title="Proxy Health"
            )

        # Telegram is currently the only channel with a configurable proxy.
        configured: list[tuple[str, str]] = []
        if cfg.channels.telegram.proxy_url:
            configured.append(("telegram", cfg.channels.telegram.proxy_url))

        if not configured:
            return Panel(
                "[dim]No proxies configured. Set TELEGRAM_PROXY_URL in .env to "
                "route Telegram through SOCKS/HTTP.[/]",
                title="Proxy Health",
                border_style="cyan",
            )

        try:
            results = asyncio.run(
                asyncio.gather(
                    *(
                        check_proxy(url, channel=ch, timeout=6.0)
                        for ch, url in configured
                    ),
                    return_exceptions=True,
                )
            )
        except Exception as exc:  # noqa: BLE001
            return Panel(
                f"[dim]Proxy probe failed: {exc}[/]", title="Proxy Health"
            )

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
                table.add_row(
                    channel, masked, "[red]●[/] DOWN", "-", f"probe error: {res}"
                )
                any_down = True
            elif res.ok:
                table.add_row(
                    channel,
                    masked,
                    "[green]●[/] OK",
                    f"{res.latency_ms} ms",
                    f"→ {res.target}",
                )
            else:
                table.add_row(
                    channel, masked, "[red]●[/] DOWN", "-", res.error or "unknown error"
                )
                any_down = True

        body: Any = table
        if any_down:
            body = Table.grid(padding=(1, 0))
            body.add_column()
            body.add_row(table)
            body.add_row(
                "[dim]Hint: if a proxy keeps dying, consider a permanent "
                "replacement — an SSH dynamic tunnel "
                "[cyan]ssh -D 1080 user@vps[/] or Cloudflare WARP in proxy mode.[/]"
            )
        return Panel(body, title="Proxy Health", border_style="cyan")


class ChannelsScreen(BackScreen):
    """Enable/disable, configure and reconnect channels."""

    def __init__(self) -> None:
        super().__init__()
        self._names: list[str] = list(CHANNEL_ORDER)

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("", id="ch-intro")
        yield MenuDataTable(id="ch-table")
        yield Static(
            "[dim]enter on a row for actions · esc back[/]", id="hint"
        )
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#ch-table", DataTable)
        table.add_columns("Channel", "Status", "Credentials")
        # Whole-row selection: the actions apply to the channel, not a cell.
        # (The default "cell" cursor posts CellSelected, not RowSelected.)
        table.cursor_type = "row"
        table.focus()
        self._refresh()

    def _refresh(self) -> None:
        ws = self.tui.ws
        table = self.query_one("#ch-table", DataTable)
        table.clear()
        for name in self._names:
            enabled = ws.channel_enabled(name)
            table.add_row(
                name,
                "[green]● enabled[/]" if enabled else "[dim]○ disabled[/]",
                ws.credential_preview(name),
                key=name,
            )

    def _note(self, message: str) -> None:
        self.query_one("#ch-intro", Static).update(message)

    @on(DataTable.RowSelected, "#ch-table")
    def _row_selected(self, event: DataTable.RowSelected) -> None:
        name = str(event.row_key.value)
        self._actions_flow(name)

    @work(exclusive=True, group="chan")
    async def _actions_flow(self, name: str) -> None:
        choice = await self.choose(
            name,
            [
                ("toggle", "Toggle enable / disable"),
                ("configure", "Configure credentials"),
                ("reconnect", "Reconnect (clear session & re-auth)"),
                (None, "Back"),
            ],
            note=CHANNEL_DESCRIPTIONS.get(name, ""),
        )
        if choice == "toggle":
            await self._toggle(name)
        elif choice == "configure":
            await self._configure(name)
        elif choice == "reconnect":
            await self._reconnect(name)
        self._refresh()

    async def _toggle(self, name: str) -> None:
        ws = self.tui.ws
        if ws.channel_enabled(name):
            for var in CHANNEL_ENV[name]:
                ws.disable_env(var)
            ws.set_channel_enabled(name, False)
            self._note(f"[yellow]○ {name} disabled.[/]")
            return
        reenabled = False
        for var in CHANNEL_ENV[name]:
            if ws.enable_env(var):
                reenabled = True
        if reenabled:
            ws.set_channel_enabled(name, True)
            self._note(f"[green]● {name} re-enabled.[/]")
            return
        # No saved credentials — send the user through configuration first.
        self._note(f"[dim]No saved credentials for {name} — configuring…[/]")
        values = await self.credentials(name)
        if values:
            for key, value in values.items():
                ws.set_env(key, value)
            if ws.channel_enabled(name):
                ws.set_channel_enabled(name, True)
                self._note(f"[green]● {name} enabled.[/]")

    async def _configure(self, name: str) -> None:
        values = await self.credentials(name)
        if values is None:
            return
        for key, value in values.items():
            self.tui.ws.set_env(key, value)
        self._note(f"[green]✓ {name} configured.[/]")

    async def _reconnect(self, name: str) -> None:
        if name == "whatsapp":
            await self._reconnect_whatsapp()
            return
        proceed = await self.ask(
            f"Reconnect {name}",
            "Reconnecting means re-entering this channel's credentials — "
            "the old values will be overwritten.",
            confirm="Continue",
            cancel="Cancel",
        )
        if not proceed:
            return
        values = await self.credentials(name)
        if values is None:
            return
        for key, value in values.items():
            self.tui.ws.set_env(key, value)

        # Mirror the enable flag so the runtime honours it, then ask the live
        # gateway to rebuild the channel — no restart needed when it's up.
        ws = self.tui.ws
        for var in CHANNEL_ENV[name]:
            ws.enable_env(var)
        ws.set_channel_enabled(name, True)

        rebuilt = await self.task(
            f"Rebuilding {name}…", lambda: self.tui.rebuild_channel(name)
        )
        if rebuilt is True:
            self._note(
                f"[green]✓ {name} credentials rotated and channel rebuilt "
                "live — no restart needed.[/]"
            )
        else:
            self._note(
                f"[green]✓ {name} credentials rotated.[/] "
                "[dim]Restart Autonoma to apply.[/]"
            )

    # ----- WhatsApp -----

    async def _reconnect_whatsapp(self) -> None:
        ws = self.tui.ws
        cleared = await asyncio.to_thread(self._wipe_wa_session)
        if cleared:
            self._note("[green]✓ Cleared the local WhatsApp session.[/]")
        else:
            self._note("[dim]No cached WhatsApp session found — nothing to wipe.[/]")

        if not os.getenv("WHATSAPP_BRIDGE_URL"):
            values = await self.credentials("whatsapp", ["WHATSAPP_BRIDGE_URL"])
            if values:
                for key, value in values.items():
                    ws.set_env(key, value)

        bridge_url = (
            os.getenv("WHATSAPP_BRIDGE_URL") or "http://localhost:3001"
        ).rstrip("/")

        up = await asyncio.to_thread(_probe_tcp, bridge_url)
        if not up:
            if not await self.ask(
                "WhatsApp bridge",
                f"The bridge at [cyan]{bridge_url}[/] is not running.\n\n"
                "It is a separate Node sidecar that speaks to WhatsApp Web via "
                "puppeteer, and it must be running to scan a QR code.",
                confirm="Start it now",
                cancel="Not now",
            ):
                return
            spawned = await self.task(
                "Starting the WhatsApp bridge…",
                lambda: _spawn_bridge(self.tui.ws.root / "whatsapp-bridge"),
            )
            if isinstance(spawned, Exception):
                await self.ask(
                    "WhatsApp bridge",
                    f"[red]Could not start the bridge:[/] {spawned}",
                )
                return
            up = await asyncio.to_thread(self._wait_for_bridge, bridge_url, 15.0)
            if not up:
                await self.ask(
                    "WhatsApp bridge",
                    f"[yellow]The bridge did not come online within 15s.[/]\n\n"
                    f"[dim]Log: {self.tui.ws.root / 'whatsapp-bridge' / 'bridge.log'}[/]",
                )
                return

        result = await self.task(
            "Waiting for a fresh QR code (puppeteer takes a few seconds)…",
            _poll_qr(bridge_url),
        )
        await self._show_qr_result(result)

    async def _show_qr_result(self, result: Any) -> None:
        if isinstance(result, Exception):
            await self.ask("WhatsApp QR", f"[red]{result}[/]")
            return
        if isinstance(result, dict) and result.get("qr"):
            art = _qr_ascii(result["qr"])
            age = result.get("age")
            note = (
                f"QR age: {age}s — rotates every ~20s, re-run Reconnect to refresh."
                if age is not None
                else ""
            )
            await self._push_qr(art, note)
            return
        if isinstance(result, dict) and result.get("ready"):
            await self.ask(
                "WhatsApp",
                "[green]WhatsApp session is already authenticated — no QR "
                "needed.[/]\n[dim]Use Reconnect to wipe the session first if you "
                "wanted a fresh login.[/]",
            )
            return
        detail = result.get("error") if isinstance(result, dict) else str(result)
        await self.ask(
            "WhatsApp QR",
            f"[yellow]No QR arrived within 30s.[/]\n\n[dim]{detail}[/]\n\n"
            "This usually means puppeteer is still booting or the bridge is "
            "stuck. Check the bridge log, then run Reconnect again.",
        )

    async def _push_qr(self, art: str, note: str) -> None:
        await cast(App, self.app).push_screen(
            QrDialog(art, note), wait_for_dismiss=True
        )

    def _wipe_wa_session(self) -> list[Path]:
        """Drop whatsapp-web.js LocalAuth state so the bridge shows a new QR."""
        return _wipe_wa_session(self.tui.ws.root)

    @staticmethod
    def _wait_for_bridge(url: str, budget: float) -> bool:
        deadline = time.time() + budget
        while time.time() < deadline:
            if _probe_tcp(url, timeout=0.5):
                return True
            time.sleep(0.5)
        return False


class ConnectorsScreen(BackScreen):
    """OAuth connectors: connect, sign out, and wait for the callback."""

    def __init__(self) -> None:
        super().__init__()
        self._entries: list[dict] = []

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("", id="conn-intro")
        yield MenuOptionList(id="connectors")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#connectors", OptionList).focus()
        self._load_flow()

    @work(exclusive=True, group="conn")
    async def _load_flow(self) -> None:
        base = self.tui.base_url()
        ok, entries = await self.task(
            "Loading connectors…", lambda: _http(f"{base}/api/connectors")
        )
        if not self.is_mounted:
            return
        options = self.query_one("#connectors", OptionList)
        options.clear_options()
        if not ok or not isinstance(entries, list):
            self._note(
                "[red]Could not reach the gateway HTTP API. Is the agent "
                "running?[/]"
            )
            return
        if not entries:
            self._note(
                "[yellow]No account connections are set up yet. Add the "
                "service client ID and secret to .env (see README: Connect "
                "accounts), then try again.[/]"
            )
            return
        self._entries = entries
        self._note("")
        items = []
        for index, entry in enumerate(entries):
            manifest = entry["manifest"]
            status = entry["status"]
            state = status.get("state", "?")
            account = status.get("account_label") or status.get("account_id") or ""
            tail = f" — {account}" if state == "connected" and account else ""
            items.append(Option(f"{manifest['display_name']}  [{state}]{tail}", id=str(index)))
        items.append(Option("Back", id="back"))
        options.add_options(items)
        options.highlighted = 0

    def _note(self, message: str) -> None:
        self.query_one("#conn-intro", Static).update(message)

    @on(OptionList.OptionSelected, "#connectors")
    def _selected(self, event: OptionList.OptionSelected) -> None:
        raw = event.option.id or "back"
        if raw == "back":
            self.app.pop_screen()
            return
        self._action_flow(int(raw))

    @work(exclusive=True, group="conn")
    async def _action_flow(self, index: int) -> None:
        entry = self._entries[index]
        name = entry["manifest"]["name"]
        display = entry["manifest"]["display_name"]
        connected = entry["status"].get("state") == "connected"
        base = self.tui.base_url()

        if connected:
            if not await self.ask(
                display, f"Sign out of {display}?", confirm="Sign out", cancel="Cancel"
            ):
                return
            ok, payload = await self.task(
                f"Signing out of {display}…",
                lambda: _http(f"{base}/api/connectors/{name}/disconnect", "POST"),
            )
            if ok:
                self._note(f"[green]Signed out of {display}.[/]")
            else:
                self._note(f"[red]Disconnect failed:[/] {payload}")
            await self._load_flow()
            return

        ok, payload = await self.task(
            f"Connecting to {display}…",
            lambda: _http(f"{base}/api/connectors/{name}/connect", "POST"),
        )
        if not ok:
            self._note(f"[red]Connect failed:[/] {payload}")
            return
        auth_url = (payload or {}).get("auth_url", "")
        if not auth_url:
            self._note("[red]No auth URL returned.[/]")
            return
        await self.ask(
            display,
            f"Authorize {display} in your browser.\n\n[cyan]{auth_url}[/]",
        )
        try:
            webbrowser.open(auth_url)
        except Exception:  # noqa: BLE001 - browser is best-effort
            pass
        result = await self.task(
            "Waiting for the OAuth callback (up to 3 minutes)…",
            _wait_for_connection(base, name, timeout=180.0),
        )
        if result is None:
            self._note("[dim]Cancelled while waiting for the callback.[/]")
        elif isinstance(result, Exception):
            self._note(f"[red]{result}[/]")
        elif isinstance(result, dict) and result.get("state") == "connected":
            label = result.get("label") or "authorized account"
            self._note(f"[green]✓ Connected as {label}.[/]")
        elif isinstance(result, dict) and result.get("state") == "error":
            self._note(f"[red]Connection failed:[/] {result.get('error', 'unknown')}")
        else:
            self._note("[yellow]Timed out waiting for the OAuth callback.[/]")
        await self._load_flow()


class SetupWizardScreen(BaseScreen):
    """Guided setup for built-in and OpenAI-compatible custom providers.

    All three steps are composed up front and toggled with ``display`` — no
    mount/unmount mid-navigation, so focus and layout stay predictable.
    """

    BINDINGS = [Binding("escape", "cancel", "Back")]

    def __init__(self, *, forced: bool = False) -> None:
        super().__init__()
        self.forced = forced
        self.step = 1
        self.spec: ProviderSpec | None = None
        self.provider = ""
        self.api_key = ""
        self.model = ""
        self.provider_name = ""
        self.base_url = ""

    def compose(self) -> ComposeResult:
        yield Header()
        yield AutonomaSplash(reserved_rows=14, id="splash")
        yield Static(id="wiz-head")
        yield Vertical(
            MenuOptionList(
                *(Option(f"{s.label}  —  {s.description}", id=s.key) for s in PROVIDER_SPECS),
                id="providers",
                classes="step",
            ),
            Vertical(
                Label("Name shown in Autonoma"),
                Input(placeholder="e.g. My company AI", id="provider-name"),
                Label("API key"),
                Input(placeholder="API key (hidden)", password=True, id="custom-api-key"),
                Label("OpenAI-compatible API base URL"),
                Input(placeholder="https://ai.example.com/v1", id="base-url"),
                Label("Model ID"),
                Input(placeholder="e.g. provider/model-name", id="custom-model-id"),
                Button("Check and save", id="custom-provider-submit", variant="primary"),
                id="custom-provider",
                classes="step",
            ),
            Vertical(
                Label("Will be saved to .env", id="key-label"),
                Input(placeholder="API key (hidden)", password=True, id="api-key"),
                id="step-key",
                classes="step",
            ),
            Vertical(
                MenuOptionList(id="models"),
                Static(id="model-note"),
                Vertical(
                    Label("Or enter a model ID:"),
                    Input(
                        placeholder="e.g. claude-sonnet-4-6 or provider/model-name",
                        id="model-id",
                    ),
                    id="custom-wrap",
                ),
                id="step-model",
                classes="step",
            ),
            id="wiz-body",
        )
        yield Static(id="wiz-hint")
        yield Footer()

    def on_mount(self) -> None:
        self._show_step(1)

    # ----- navigation -----

    def action_cancel(self) -> None:
        custom = self.query_one("#custom-wrap", Vertical)
        if self.step == 3 and custom.display:
            custom.display = False
            self.query_one("#models", OptionList).focus()
            return
        if self.step > 1:
            self._show_step(self.step - 1)
            return
        if self.forced:
            self.app.exit()
        else:
            self.app.pop_screen()

    def _show_step(self, step: int) -> None:
        self.step = step
        custom = self.provider == "custom"
        key_step = 3 if custom else 2
        model_step = 4 if custom else 3
        step_count = 2 if custom else 3
        titles = {
            1: "AI provider",
            2: "Custom provider" if custom else "API key",
            key_step: "API key",
            model_step: "Model",
        }
        self.query_one("#wiz-head", Static).update(
            f"[bold]Setup — step {step} of {step_count} · {titles[step]}[/]"
        )
        self.query_one("#providers", OptionList).display = step == 1
        self.query_one("#custom-provider", Vertical).display = custom and step == 2
        self.query_one("#step-key", Vertical).display = step == key_step
        self.query_one("#step-model", Vertical).display = step == model_step
        self.query_one("#custom-wrap", Vertical).display = False

        if step == 1:
            self.query_one("#wiz-hint", Static).update(
                "[dim]Choose an AI service, or add a custom compatible service. "
                "↑/↓ select · enter continue · esc "
                + ("quit" if self.forced else "cancel")
                + "[/]"
            )
            self.query_one("#providers", OptionList).focus()
        elif custom and step == 2:
            self.query_one("#provider-name", Input).value = self.provider_name
            self.query_one("#custom-api-key", Input).value = self.api_key
            self.query_one("#base-url", Input).value = self.base_url
            self.query_one("#custom-model-id", Input).value = self.model
            self.query_one("#wiz-hint", Static).update(
                "[dim]Fill in all four fields. Use an OpenAI-compatible API "
                "base URL. Tab between fields, then press Enter to check and save.[/]"
            )
            self.query_one("#provider-name", Input).focus()
        elif step == key_step:
            assert self.spec is not None
            self.query_one("#key-label", Label).update(
                f"Will be saved to .env as [bold]{self.spec.env_key}[/]"
            )
            key_input = self.query_one("#api-key", Input)
            key_input.value = self.api_key
            self.query_one("#wiz-hint", Static).update(
                "[dim]Enter your provider API key. A short request will later "
                "check that the key and model work; your provider may charge "
                "a small amount. Enter to continue"
                + ("" if self.forced else " · enter empty to skip")
                + " · esc back[/]"
            )
            key_input.focus()
        elif step == model_step:
            models = self.query_one("#models", OptionList)
            models.clear_options()
            labels = list(self.spec.models if self.spec else []) + [
                "Enter a different model ID"
            ]
            models.add_options(
                Option(label, id=str(i)) for i, label in enumerate(labels)
            )
            # clear_options() resets `highlighted` to None, which would make
            # Enter a no-op until the user moved the cursor.
            models.highlighted = 0
            self.query_one("#wiz-hint", Static).update(
                "[dim]Choose a suggested model or enter its ID below. "
                "Autonoma will check that it works before saving. "
                "↑/↓ select · enter choose · esc back[/]"
            )
            self.query_one("#model-note", Static).update(
                "Suggestions are common models; availability depends on your account."
            )
            models.focus()

    def _error(self, message: str) -> None:
        self.query_one("#wiz-hint", Static).update(f"[red]{message}[/]")

    # ----- steps -----

    @on(OptionList.OptionSelected, "#providers")
    def _pick_provider(self, event: OptionList.OptionSelected) -> None:
        key = event.option.id or ""
        spec = next((s for s in PROVIDER_SPECS if s.key == key), None)
        if spec is None:
            return
        self.spec = spec
        self.provider = spec.key
        self.api_key = os.getenv(spec.env_key, "")
        if self.provider == "custom":
            cfg = self.tui.ws.load()
            if cfg and cfg.llm.provider == "custom":
                self.provider_name = cfg.llm.provider_name
                self.base_url = cfg.llm.base_url
                self.model = cfg.llm.model
                self.api_key = cfg.llm.api_key or self.api_key
            self._show_step(2)
        else:
            self.provider_name = ""
            self.base_url = ""
            self._show_step(2)

    @on(Button.Pressed, "#custom-provider-submit")
    def _submit_custom_provider(self) -> None:
        self.provider_name = self.query_one("#provider-name", Input).value.strip()
        self.api_key = self.query_one("#custom-api-key", Input).value.strip()
        self.base_url = self.query_one("#base-url", Input).value.strip().rstrip("/")
        self.model = self.query_one("#custom-model-id", Input).value.strip()
        parts = urllib.parse.urlsplit(self.base_url)
        if not self.provider_name:
            self._error("Enter a name for this provider.")
            self.query_one("#provider-name", Input).focus()
            return
        if (
            parts.scheme not in {"http", "https"}
            or not parts.netloc
            or parts.username is not None
            or parts.password is not None
        ):
            self._error("Enter a valid http:// or https:// API base URL.")
            self.query_one("#base-url", Input).focus()
            return
        if not self.api_key:
            self._error("Enter an API key for this provider.")
            self.query_one("#custom-api-key", Input).focus()
            return
        if not self.model:
            self._error("Enter a model ID for this provider.")
            self.query_one("#custom-model-id", Input).focus()
            return
        self._save_flow()

    @on(Input.Submitted, "#api-key")
    def _submit_key(self, event: Input.Submitted) -> None:
        value = event.value.strip()
        if not value and self.forced:
            self._error("An API key is required to continue.")
            self.query_one("#api-key", Input).focus()
            return
        self.api_key = value
        self._show_step(4 if self.provider == "custom" else 3)

    @on(OptionList.OptionSelected, "#models")
    def _pick_model(self, event: OptionList.OptionSelected) -> None:
        try:
            index = int(event.option.id or "0")
        except ValueError:
            index = 0
        count = len(self.spec.models) if self.spec else 0
        if index >= count:
            wrap = self.query_one("#custom-wrap", Vertical)
            wrap.display = True
            self.query_one("#wiz-hint", Static).update(
                "[dim]enter to confirm · esc back to the list[/]"
            )
            self.query_one("#model-id", Input).focus()
            return
        self.model = list(self.spec.models)[index]
        self._save_flow()

    @on(Input.Submitted, "#model-id")
    def _submit_custom_model(self, event: Input.Submitted) -> None:
        value = event.value.strip()
        if not value:
            if self.forced:
                self._error("A model identifier is required.")
                self.query_one("#model-id", Input).focus()
                return
            self.action_cancel()
            return
        self.model = value
        self._save_flow()

    @work(exclusive=True, group="wizard")
    async def _save_flow(self) -> None:
        ws = self.tui.ws
        self.query_one("#wiz-hint", Static).update(
            "[yellow]Checking the API key and selected model…[/]"
        )
        try:
            await verify_model(LLMConfig(
                provider=self.provider,
                api_key=self.api_key,
                model=self.model,
                provider_name=self.provider_name,
                base_url=self.base_url,
            ))
        except Exception as exc:
            self._show_step(2 if self.provider == "custom" else 3)
            self._error(
                f"Could not use this model. Check the API key, model ID, or "
                f"base URL, then try again. ({str(exc)[:180]})"
            )
            return

        ws.set_env("AUTONOMA_LLM_PROVIDER", self.provider)
        ws.set_env("AUTONOMA_LLM_MODEL", self.model)
        if self.api_key and self.spec is not None:
            ws.set_env(self.spec.env_key, self.api_key)
        if self.provider == "custom":
            ws.set_env("AUTONOMA_LLM_PROVIDER_NAME", self.provider_name)
            ws.set_env("AUTONOMA_LLM_BASE_URL", self.base_url)
        else:
            ws.disable_env("AUTONOMA_LLM_API_KEY")
            ws.disable_env("AUTONOMA_LLM_PROVIDER_NAME")
            ws.disable_env("AUTONOMA_LLM_BASE_URL")
        save_yaml_config(
            ws.yaml_path,
            {"llm": {
                "provider": self.provider,
                "model": self.model,
                "provider_name": self.provider_name,
                "base_url": self.base_url,
            }},
        )
        ws.invalidate()

        await self.ask(
            "Setup complete",
            f"Provider: [bold]{self.provider_name or self.provider}[/]\n"
            f"Model: [bold]{self.model}[/]\n\n"
            "Next: choose Connect messaging apps or Connect accounts from the menu.",
        )
        if self.forced:
            self.tui.enter_main()
        else:
            # Deferred one tick: popping this screen cancels its workers.
            self.app.call_later(self.app.pop_screen)


# --------------------------------------------------------------------------
# WhatsApp bridge helpers
# --------------------------------------------------------------------------


def _wipe_wa_session(root: Path) -> list[Path]:
    """Delete whatsapp-web.js LocalAuth state under whatsapp-bridge/."""
    bridge_dir = root / "whatsapp-bridge"
    cleared: list[Path] = []
    for sub in (".wwebjs_auth", ".wwebjs_cache"):
        target = bridge_dir / sub
        if target.exists():
            try:
                shutil.rmtree(target)
                cleared.append(target)
            except OSError:
                pass
    return cleared


def _spawn_bridge(bridge_dir: Path) -> bool:
    """Start the Node sidecar detached, logging to whatsapp-bridge/bridge.log.

    Raises RuntimeError with an actionable message when the sidecar can't be
    started; returns True once it has been spawned.
    """
    if not (bridge_dir / "package.json").exists():
        raise RuntimeError(
            f"No bridge found at {bridge_dir}. Reinstall Autonoma with the "
            "whatsapp-bridge/ folder in place."
        )
    if not (bridge_dir / "node_modules").exists():
        raise RuntimeError(
            f"node_modules/ is missing — run `npm install` in {bridge_dir} first."
        )
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    if not npm:
        raise RuntimeError("Could not find `npm` on PATH. Install Node.js first.")

    log_path = bridge_dir / "bridge.log"
    handle = open(log_path, "a", buffering=1, encoding="utf-8")
    handle.write(f"\n=== Bridge spawned by TUI at {time.strftime('%F %T')} ===\n")
    handle.flush()
    kwargs: dict = {
        "cwd": str(bridge_dir),
        "stdout": handle,
        "stderr": subprocess.STDOUT,
        "stdin": subprocess.DEVNULL,
    }
    if os.name == "nt":
        # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP — outlive the TUI.
        kwargs["creationflags"] = 0x00000008 | 0x00000200  # type: ignore[assignment]
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen([npm, "start"], **kwargs)  # noqa: S603
    return True


async def _poll_qr(bridge_url: str) -> dict:
    """Poll the bridge for a fresh QR. 15 × 2s = 30s, longer than puppeteer's
    usual cold start."""
    qr_url = f"{bridge_url}/qr"
    last_error: str | None = None
    for _ in range(15):
        try:
            with urllib.request.urlopen(qr_url, timeout=3.0) as resp:
                payload = json.loads(resp.read().decode("utf-8", errors="replace"))
                status_code = resp.getcode()
            if status_code == 200 and payload.get("qr"):
                return {"qr": payload["qr"], "age": payload.get("age_seconds")}
            if payload.get("status") == "ready":
                return {"ready": True}
            last_error = payload.get("message") or f"bridge responded {status_code}"
        except urllib.error.HTTPError as exc:
            # 404 during warmup is normal — puppeteer hasn't emitted a QR yet.
            last_error = (
                "bridge has not emitted a QR yet" if exc.code == 404 else f"HTTP {exc.code}"
            )
        except urllib.error.URLError as exc:
            last_error = f"bridge unreachable: {exc.reason}"
        except (json.JSONDecodeError, ValueError) as exc:
            last_error = f"bad bridge response: {exc}"
        await asyncio.sleep(2.0)
    return {"error": last_error or "timeout"}


def _qr_ascii(qr_string: str) -> str:
    """Render a scannable QR as terminal ASCII. Falls back to the raw payload."""
    try:
        import qrcode
    except ImportError:
        return f"(install the `qrcode` package for inline rendering)\n\n{qr_string}"
    qr = qrcode.QRCode(border=1)
    qr.add_data(qr_string)
    qr.make(fit=True)
    import io

    buf = io.StringIO()
    qr.print_ascii(out=buf, invert=True)
    return buf.getvalue().rstrip("\n")


async def _wait_for_connection(base: str, name: str, timeout: float) -> dict | None:
    """Poll the connectors API until the OAuth callback lands."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        ok, data = await asyncio.to_thread(_http, f"{base}/api/connectors")
        if ok and isinstance(data, list):
            for entry in data:
                if entry["manifest"]["name"] != name:
                    continue
                status = entry["status"]
                state = status.get("state")
                if state == "connected":
                    return {"state": "connected", "label": status.get("account_label", "")}
                if state == "error":
                    return {"state": "error", "error": status.get("last_error", "unknown")}
        await asyncio.sleep(1.0)
    return None


def _open_browser(url: str) -> tuple[bool, bool]:
    """Returns (reachable, opened)."""
    reachable = _probe_tcp(url, timeout=0.5)
    try:
        webbrowser.open(url)
        opened = True
    except Exception:  # noqa: BLE001
        opened = False
    return reachable, opened


# --------------------------------------------------------------------------
# The app
# --------------------------------------------------------------------------


def _status_panel(ws: Workspace, runner: AgentRunner | None) -> Panel:
    """Header panel: status, uptime, provider, channels, dashboard URL."""
    cfg = ws.load()
    status = runner.status() if runner else "stopped"
    err = runner.error() if runner else None
    colour = _STATUS_COLOURS.get(status, "white")

    status_text = Text()
    status_text.append("● ", style=colour)
    status_text.append(status.upper(), style=f"bold {colour}")
    if err:
        status_text.append(f"  {err}", style="red")

    grid = Table.grid(padding=(0, 3))
    grid.add_column(style="dim", min_width=11)
    grid.add_column()
    grid.add_row("Status", status_text)
    grid.add_row("Uptime", _fmt_uptime(runner.uptime() if runner else 0))
    if cfg:
        grid.add_row("Provider", f"{cfg.llm.provider} · {cfg.llm.model}")
        enabled = ws.enabled_channels(cfg)
        grid.add_row("Channels", ", ".join(enabled) if enabled else "none (CLI only)")
        grid.add_row("Dashboard", _base_url(cfg))

    return Panel(grid, title="Agent", border_style=colour, padding=(1, 2))


def _base_url(cfg) -> str:
    host = cfg.gateway.host or "127.0.0.1"
    # 127.0.0.1 is more reliable than 0.0.0.0 for client connects.
    if host in ("0.0.0.0", "::"):
        host = "127.0.0.1"
    return f"http://{host}:{cfg.gateway.http_port}"


class AutonomaTUI(App[None]):
    """The Autonoma control tower."""

    TITLE = "Autonoma"
    SUB_TITLE = "AI agent control tower"

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", priority=True),
    ]

    # Human-friendly key labels. Textual's own defaults render `ctrl+c` as
    # `^c` (and `caps_lock` as `caps_lock`), which reads like shorthand.
    _KEY_LABELS: dict[str, str] = {
        "escape": "Esc",
        "enter": "Enter",
        "tab": "Tab",
        "space": "Space",
        "backspace": "⌫",
        "delete": "Del",
        "up": "↑",
        "down": "↓",
        "left": "←",
        "right": "→",
        "pageup": "PgUp",
        "pagedown": "PgDn",
        "home": "Home",
        "end": "End",
        "ctrl": "Ctrl",
        "shift": "Shift",
        "alt": "Alt",
        "meta": "Meta",
        "super": "Super",
    }

    def get_key_display(self, binding: Binding) -> str:
        """Render bound keys as ``Ctrl+C`` / ``Esc`` / ``↑`` (footer + keys panel)."""
        if binding.key_display:
            return binding.key_display
        modifiers, key = binding.parse_key()
        if not key:
            label = "+"
        elif key in self._KEY_LABELS:
            label = self._KEY_LABELS[key]
        elif len(key) > 1:
            label = key.replace("_", " ").replace("-", " ").title()
        else:
            label = key
        parts = [self._KEY_LABELS.get(mod, mod.title()) for mod in modifiers if mod]
        if parts and len(label) == 1 and label.isalpha():
            label = label.upper()
        return "+".join(parts + [label])

    def action_show_help_panel(self) -> None:
        """Show the keys panel — ours, which carries a Close button."""
        if not self.screen.query(HelpPanel):
            self.screen.mount(KeysPanel())

    @on(Button.Pressed, "#keys-close")
    def _close_keys_panel(self, event: Button.Pressed) -> None:
        event.stop()
        self.action_hide_help_panel()

    CSS = """
    Screen {
        background: $surface;
    }

    /* Textual's maximize backdrop draws a hatch pattern; keep it plain. */
    Screen.-maximized-view {
        hatch: none;
        background: $surface;
    }

    /* The keys panel: louder than Textual's default so it reads as a panel. */
    HelpPanel {
        background: $panel;
        border-left: tall $accent;
    }
    HelpPanel Markdown, HelpPanel KeyPanel {
        background: $panel;
    }
    HelpPanel .bindings-table--key {
        color: $accent;
        text-style: bold;
    }
    HelpPanel .bindings-table--header {
        color: $text;
        text-style: bold;
    }

    #status {
        height: auto;
        margin: 1 2 0 2;
    }

    #splash {
        height: auto;
    }

    #menu {
        height: 1fr;
        margin: 1 2;
        padding: 1 2;
        background: $panel;
        border: round $primary;
    }
    #menu > .option-list--option {
        padding: 0 2;
    }
    #menu > .option-list--option-highlighted {
        background: $primary;
        color: $text;
        text-style: bold;
    }

    #hint, #log-hint, #ch-intro, #conn-intro, #wiz-hint {
        height: auto;
        margin: 0 2 1 2;
        color: $text-muted;
    }

    #log {
        height: 1fr;
        margin: 1 2;
        border: round $primary;
    }

    #status-scroll {
        height: 1fr;
        margin: 1 2;
    }
    #status-body {
        height: auto;
    }

    #ch-table {
        height: 1fr;
        margin: 0 2;
        border: round $primary;
    }

    #connectors {
        height: 1fr;
        margin: 0 2;
        padding: 1 2;
        background: $panel;
        border: round $primary;
    }
    #connectors > .option-list--option-highlighted {
        background: $primary;
        color: $text;
        text-style: bold;
    }

    #wiz-head {
        height: auto;
        margin: 1 2;
    }
    #wiz-body {
        height: auto;
        margin: 0 2 1 2;
        padding: 1 2;
        background: $panel;
        border: round $primary;
    }
    #wiz-body .step {
        height: auto;
    }
    #wiz-body Label {
        height: auto;
        color: $text-muted;
        margin-bottom: 1;
    }
    #wiz-body Input {
        width: 100%;
        margin-bottom: 1;
    }
    #wiz-body OptionList {
        height: auto;
        background: transparent;
        border: none;
    }
    #custom-wrap {
        height: auto;
        margin-top: 1;
        padding-left: 1;
        border-left: thick $accent;
    }
    #wiz-body OptionList > .option-list--option-highlighted {
        background: $primary;
        color: $text;
        text-style: bold;
    }

    .dialog {
        align: center middle;
        background: $background 60%;
    }
    .dbox {
        width: auto;
        max-width: 92%;
        height: auto;
        padding: 1 2;
        background: $panel;
        border: round $primary;
    }
    #dlg-title {
        height: auto;
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }
    #dlg-body, #dlg-note {
        height: auto;
        margin-bottom: 1;
        color: $text;
    }
    #dlg-buttons {
        height: auto;
        align: center middle;
        margin-top: 1;
    }
    #dlg-buttons Button {
        margin: 0 1;
    }
    #qr-art {
        height: auto;
        text-style: none;
        margin-bottom: 1;
    }
    .cred-label {
        height: auto;
        margin-top: 1;
        color: $text-muted;
    }
    .dbox Input {
        width: 100%;
        margin-bottom: 1;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self.ws = Workspace(WORKSPACE)
        self.runner: AgentRunner | None = None
        self.log_ring: LogRingBuffer | None = None
        # True once the user has reached the control tower; gates the goodbye.
        self.entered_main_loop = False

    # ----- public entry point -----

    def run(self, **kwargs: Any) -> None:
        first_run = self.ws.is_first_run()
        self.log_ring = install_logging(log_file=str(self.ws.log_file), level="INFO")
        if not first_run:
            self.ensure_agent()
        try:
            super().run(**kwargs)
        finally:
            self._teardown()

    def on_mount(self) -> None:
        # Always mount the control tower first and, on a fresh install, lay the
        # forced wizard on top of it — finishing the wizard just pops back to
        # the tower. `switch_screen` can't be used here: Textual's built-in
        # `_default` screen has no result callback to pop.
        self.push_screen(MainScreen())
        if self.ws.is_first_run():
            self.push_screen(SetupWizardScreen(forced=True))
        else:
            self.entered_main_loop = True

    def _teardown(self) -> None:
        if self.runner and self.runner.status() != "stopped":
            print("Stopping agent…")
            self.runner.stop()
        if self.entered_main_loop:
            print("\nGoodbye.")

    # ----- navigation -----

    def enter_main(self) -> None:
        """Called by the forced first-run wizard once setup is done.

        Deferred one tick so the wizard's own worker can finish before its
        screen is popped (popping a screen cancels its workers).
        """
        self.entered_main_loop = True
        self.ensure_agent()
        self.call_later(self.pop_screen)

    def open_with_agent_stopped(self, factory: Callable[[], Screen]) -> None:
        """Push `factory()`'s screen with the agent stopped, restart after.

        Config edits write .env / autonoma.yaml, so the channels must not be
        mid-flight while we do it.
        """
        self._open_with_agent_stopped_flow(factory)

    @work(exclusive=True, group="nav")
    async def _open_with_agent_stopped_flow(self, factory: Callable[[], Screen]) -> None:
        was_running = self.runner is not None and self.runner.is_running()
        if was_running:
            await cast(App, self).push_screen(
                RunDialog("Stopping agent to safely change configuration…", self.stop_agent),
                wait_for_dismiss=True,
            )
        await cast(App, self).push_screen(factory(), wait_for_dismiss=True)
        if was_running:
            await cast(App, self).push_screen(
                RunDialog("Restarting agent with new config…", self.restart_agent),
                wait_for_dismiss=True,
            )

    # ----- agent lifecycle -----

    def ensure_agent(self) -> None:
        if self.runner is None:
            self.runner = AgentRunner()
            self.runner.start()

    def stop_agent(self) -> None:
        if self.runner is not None:
            self.runner.stop()

    def restart_agent(self) -> None:
        if self.runner is not None:
            self.runner.stop()
        self.runner = AgentRunner()
        self.runner.start()
        # Give the new thread a beat to report 'running' before we re-render.
        time.sleep(0.5)

    def rebuild_channel(self, name: str) -> bool:
        """Ask a running gateway to rebuild `name` with the current .env."""
        cfg = self.ws.load()
        if cfg is None:
            return False
        req = urllib.request.Request(
            f"{_base_url(cfg)}/api/channels/{name}/reconnect",
            data=b"{}",
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                return 200 <= resp.getcode() < 300
        except Exception:  # noqa: BLE001 - gateway down / channel unregistered
            return False

    def base_url(self) -> str:
        cfg = self.ws.load()
        if cfg is None:
            return "http://127.0.0.1:8766"
        return _base_url(cfg)
