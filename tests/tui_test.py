"""Headless tests for the Textual TUI (autonoma/tui.py).

These drive the real widget tree through Textual's ``run_test`` pilot, so a
broken binding, a missing widget or a screen that won't mount fails loudly.
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import tempfile
import unittest
from pathlib import Path

from rich.console import Console

# WORKSPACE is resolved at import time from AUTONOMA_HOME, so it has to be set
# before autonoma.tui is imported — otherwise the tests would touch the real
# project's .env.
_HOME = tempfile.mkdtemp(prefix="autonoma-tui-")
os.environ["AUTONOMA_HOME"] = _HOME

# A pre-configured workspace: without it every screen test would sit under the
# forced first-run wizard. WizardTest blanks this file to exercise that path.
_ENV_PATH = Path(_HOME) / ".env"
_PLACEHOLDER_ENV = 'AUTONOMA_LLM_PROVIDER="anthropic"\nANTHROPIC_API_KEY="placeholder"\n'
_ENV_PATH.write_text(_PLACEHOLDER_ENV, encoding="utf-8")

from autonoma.splash import VARIANTS, pick_variant  # noqa: E402
from autonoma.tui import (  # noqa: E402
    CHANNEL_ORDER,
    AutonomaTUI,
    ChannelsScreen,
    Dialog,
    LogsScreen,
    MainScreen,
    SetupWizardScreen,
    StatusScreen,
    Workspace,
    _styled_log_line,
)


def _run(coro):
    return asyncio.run(coro)


def _render_text(renderable, width: int = 140) -> str:
    """Render a Rich renderable to plain text for assertions.

    Textual 8 wraps widget content in a ``RichVisual``; unwrap it so Rich sees
    the actual Table/Panel instead of the wrapper's repr.
    """
    inner = getattr(renderable, "_renderable", None)
    if inner is not None:
        renderable = inner
    buffer = io.StringIO()
    console = Console(file=buffer, width=width, force_terminal=False, color_system=None)
    console.print(renderable)
    return buffer.getvalue()


class MainScreenTest(unittest.TestCase):
    def test_menu_lists_every_action(self):
        async def scenario():
            async with AutonomaTUI().run_test(size=(100, 40)) as pilot:
                await pilot.pause()
                app = pilot.app
                self.assertIsInstance(app.screen, MainScreen)
                menu = app.screen.query_one("#menu")
                self.assertEqual(
                    [opt.id for opt in menu.options],
                    [key for key, _ in MainScreen.MENU],
                )
                self.assertIsNotNone(app.screen.query_one("#status"))

        _run(scenario())

    def test_menu_navigation_and_selection(self):
        async def scenario():
            async with AutonomaTUI().run_test(size=(100, 40)) as pilot:
                await pilot.pause()
                await pilot.press("down", "down", "enter")
                await pilot.pause()
                # Third entry is "Manage channels" — wrapped because the
                # agent isn't running, so we land on a ChannelsScreen.
                self.assertIsInstance(pilot.app.screen, ChannelsScreen)
                await pilot.press("escape")
                await pilot.pause()
                self.assertIsInstance(pilot.app.screen, MainScreen)

        _run(scenario())

    def test_escape_is_a_noop_on_the_main_screen(self):
        async def scenario():
            async with AutonomaTUI().run_test(size=(100, 40)) as pilot:
                await pilot.pause()
                await pilot.press("escape", "escape")
                await pilot.pause()
                self.assertIsInstance(pilot.app.screen, MainScreen)
                self.assertTrue(pilot.app.is_running)

        _run(scenario())


class LogsScreenTest(unittest.TestCase):
    def test_logs_screen_mounts_and_returns(self):
        async def scenario():
            async with AutonomaTUI().run_test(size=(100, 40)) as pilot:
                await pilot.pause()
                pilot.app.push_screen(LogsScreen())
                await pilot.pause()
                self.assertIsInstance(pilot.app.screen, LogsScreen)
                pilot.app.screen.query_one("#log")
                await pilot.press("escape")
                await pilot.pause()
                self.assertIsInstance(pilot.app.screen, MainScreen)

        _run(scenario())

    def test_log_ring_lines_are_styled_not_markup_parsed(self):
        # A message containing Rich markup must survive as literal text.
        line = "12:00:00 [ERROR] boom: bad [bold red]tag[/]"
        self.assertEqual(_styled_log_line(line).plain, line)

        # …while the level token still gets a colour of its own.
        styled = _styled_log_line("12:00:00 [ERROR] boom")
        self.assertEqual(styled.plain, "12:00:00 [ERROR] boom")
        self.assertTrue(
            any("red" in str(span.style) for span in styled.spans),
            "expected the ERROR token to be coloured red",
        )

        # Lines without a level prefix pass through untouched.
        self.assertEqual(_styled_log_line("no level here").plain, "no level here")

    def test_log_screen_pulls_ring_buffer_lines(self):
        async def scenario():
            async with AutonomaTUI().run_test(size=(100, 40)) as pilot:
                await pilot.pause()
                from autonoma.runtime import LogRingBuffer

                pilot.app.log_ring = LogRingBuffer(capacity=50)
                logger = logging.getLogger("autonoma.tui.test")
                logger.addHandler(pilot.app.log_ring)
                logger.setLevel(logging.DEBUG)
                logger.warning("hello from the test")
                pilot.app.push_screen(LogsScreen())
                await pilot.pause()
                screen = pilot.app.screen
                self.assertIsInstance(screen, LogsScreen)
                self.assertTrue(
                    any("hello from the test" in line for line in screen._previous)
                )

        _run(scenario())


class StatusScreenTest(unittest.TestCase):
    def test_status_collects_all_panels(self):
        async def scenario():
            async with AutonomaTUI().run_test(size=(110, 42)) as pilot:
                await pilot.pause()
                pilot.app.push_screen(StatusScreen())
                # push_screen() composes asynchronously — let it mount first.
                await pilot.pause()
                # The load runs in a thread worker; give it time to land.
                body = pilot.app.screen.query_one("#status-body")
                text = ""
                for _ in range(50):
                    await pilot.pause(0.1)
                    text = _render_text(body.render())
                    if "Proxy Health" in text:
                        break
                self.assertIn("Configuration", text)
                self.assertIn("Channels", text)
                self.assertIn("Memory", text)
                self.assertIn("Proxy Health", text)

        _run(scenario())


class ChannelsScreenTest(unittest.TestCase):
    def test_lists_every_channel(self):
        async def scenario():
            async with AutonomaTUI().run_test(size=(110, 42)) as pilot:
                await pilot.pause()
                pilot.app.push_screen(ChannelsScreen())
                await pilot.pause()
                table = pilot.app.screen.query_one("#ch-table")
                self.assertEqual(table.row_count, len(CHANNEL_ORDER))

        _run(scenario())

    def test_selecting_a_row_opens_the_action_menu(self):
        async def scenario():
            async with AutonomaTUI().run_test(size=(110, 42)) as pilot:
                await pilot.pause()
                pilot.app.push_screen(ChannelsScreen())
                await pilot.pause()
                await pilot.press("enter")
                await pilot.pause()
                self.assertEqual(type(pilot.app.screen).__name__, "ChoiceDialog")
                await pilot.press("escape")
                await pilot.pause()
                self.assertIsInstance(pilot.app.screen, ChannelsScreen)

        _run(scenario())


class WizardTest(unittest.TestCase):
    def setUp(self) -> None:
        # Blank the workspace so the app treats this as a first run.
        _ENV_PATH.write_text("", encoding="utf-8")
        for key in (
            "ANTHROPIC_API_KEY",
            "OPENROUTER_API_KEY",
            "AUTONOMA_LLM_API_KEY",
            "AUTONOMA_LLM_PROVIDER",
            "AUTONOMA_LLM_MODEL",
        ):
            os.environ.pop(key, None)

    def tearDown(self) -> None:
        # Restore the placeholder so later tests land straight on MainScreen.
        _ENV_PATH.write_text(_PLACEHOLDER_ENV, encoding="utf-8")
        os.environ.pop("OPENROUTER_API_KEY", None)
        os.environ.pop("AUTONOMA_LLM_MODEL", None)
        os.environ["AUTONOMA_LLM_PROVIDER"] = "anthropic"
        os.environ["ANTHROPIC_API_KEY"] = "placeholder"

    def test_first_run_is_detected_without_a_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(Workspace(Path(tmp)).is_first_run())
        # …and not once a provider key is present.
        _ENV_PATH.write_text(_PLACEHOLDER_ENV, encoding="utf-8")
        os.environ["AUTONOMA_LLM_PROVIDER"] = "anthropic"
        os.environ["ANTHROPIC_API_KEY"] = "placeholder"
        self.assertFalse(Workspace(Path(_HOME)).is_first_run())

    def test_forced_first_run_wizard_saves_everything(self):
        async def scenario():
            app = AutonomaTUI()
            # A test must never boot the real agent.
            app.ensure_agent = lambda: None  # type: ignore[method-assign]
            async with app.run_test(size=(100, 40)) as pilot:
                await pilot.pause()
                self.assertIsInstance(pilot.app.screen, SetupWizardScreen)

                # Step 1: provider (first entry = openrouter).
                await pilot.press("enter")
                await pilot.pause()

                # Step 2: API key.
                await pilot.press(*"sktestkey123", "enter")
                await pilot.pause()

                # Step 3: model — first suggestion.
                await pilot.press("enter")
                await pilot.pause(0.3)

                self.assertIsInstance(pilot.app.screen, Dialog)
                await pilot.press("enter")
                await pilot.pause(0.3)

                # Wizard popped, control tower revealed.
                self.assertIsInstance(pilot.app.screen, MainScreen)
                self.assertTrue(pilot.app.entered_main_loop)

                content = _ENV_PATH.read_text(encoding="utf-8")
                self.assertIn("AUTONOMA_LLM_PROVIDER=", content)
                self.assertIn("AUTONOMA_LLM_MODEL=", content)
                self.assertIn("OPENROUTER_API_KEY=", content)

        _run(scenario())


class SplashTest(unittest.TestCase):
    def test_largest_fitting_variant_is_chosen(self):
        self.assertEqual(pick_variant(200, 50).name, "xl")
        # Under 96 cols the double-width art no longer fits.
        self.assertEqual(pick_variant(80, 10).name, "lg")
        self.assertEqual(pick_variant(80, 3).name, "md")
        self.assertEqual(pick_variant(40, 5).name, "sm")
        self.assertEqual(pick_variant(15, 5).name, "xs")

    def test_nothing_fits_returns_none(self):
        self.assertIsNone(pick_variant(5, 0))

    def test_all_variants_are_rectangular_and_sized(self):
        by_name = {v.name: v for v in VARIANTS}
        for variant in VARIANTS:
            widths = {len(line) for line in variant.lines}
            self.assertEqual(len(widths), 1, f"{variant.name} is ragged")
            self.assertGreaterEqual(variant.width, variant.min_width)
            self.assertGreaterEqual(len(variant.lines), variant.min_height)
        # The plain-text variants spell the word literally.
        self.assertEqual("".join(by_name["sm"].lines).replace(" ", ""), "AUTONOMA")
        self.assertEqual("".join(by_name["xs"].lines), "AUTONOMA")
        # The block variants are double-width renderings of the same font.
        self.assertEqual(by_name["xl"].width, by_name["lg"].width * 2)

    def test_main_screen_hosts_the_splash(self):
        async def scenario():
            async with AutonomaTUI().run_test(size=(100, 40)) as pilot:
                await pilot.pause()
                splash = pilot.app.screen.query_one("#splash")
                text = _render_text(splash.render())
                # 100 cols / 40 rows leaves room for the full block-letter art.
                self.assertTrue(
                    "█" in text or "AUTONOMA" in text,
                    f"expected logo art, got: {text!r}",
                )

        _run(scenario())


class WorkspaceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Workspace(Path(self.tmp.name))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_disable_then_enable_round_trips(self):
        self.ws.set_env("TELEGRAM_BOT_TOKEN", "abc123")
        self.assertTrue(self.ws.channel_enabled("telegram"))
        self.assertTrue(self.ws.disable_env("TELEGRAM_BOT_TOKEN"))
        self.assertFalse(self.ws.channel_enabled("telegram"))
        self.assertTrue(self.ws.enable_env("TELEGRAM_BOT_TOKEN"))
        self.assertTrue(self.ws.channel_enabled("telegram"))
        with open(self.ws.env_path, encoding="utf-8") as handle:
            self.assertIn("TELEGRAM_BOT_TOKEN=", handle.read())

    def test_set_env_replaces_commented_duplicates(self):
        self.ws.env_path.write_text(
            "# TELEGRAM_BOT_TOKEN=old\nTELEGRAM_BOT_TOKEN=new\n", encoding="utf-8"
        )
        self.ws.set_env("TELEGRAM_BOT_TOKEN", "fresh")
        text = self.ws.env_path.read_text(encoding="utf-8")
        self.assertEqual(text.count("TELEGRAM_BOT_TOKEN="), 1)
        self.assertNotIn("# TELEGRAM_BOT_TOKEN", text)

    def test_credential_preview_masks_secrets(self):
        self.ws.set_env("TELEGRAM_BOT_TOKEN", "1234567890ABCDEFGHIJ")
        preview = self.ws.credential_preview("telegram")
        self.assertNotIn("1234567890ABCDEFGHIJ", preview)
        self.assertIn("1234…IJ", preview)


if __name__ == "__main__":
    unittest.main()
