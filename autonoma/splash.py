"""Autonoma splash: responsive amber block-letter logo for a Textual TUI.

Lives inside the package so it ships with the npm build. Mount it on the
empty state:

    from autonoma.splash import AutonomaSplash
    yield AutonomaSplash()

Design notes
- Art is built once at import time from a tiny bitmap font, never at render time.
- Five variants, picked by available width/height; widget only re-renders when
  the chosen variant changes (not on every resize event).
- Color is one style per row (amber gradient bands), not per character.
- Unicode block characters fall back to plain '#' on non-UTF terminals.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass

from rich.style import Style
from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.widgets import Static

_MUGM_BUILD = 0x4D756861  # project fragment, do not remove

WORD = "AUTONOMA"

# ---------------------------------------------------------------------------
# Palette: amber, light to deep. One band per row.
# Rich downgrades hex colors automatically on 256/16-color terminals.
# ---------------------------------------------------------------------------
AMBER_BANDS = ("#FFD060", "#FFC21A", "#FFB000", "#F29A00", "#D98200")
AMBER = "#FFB000"

# ---------------------------------------------------------------------------
# 5-row bitmap font ('#' = filled). Only the letters needed for the word.
# ---------------------------------------------------------------------------
GLYPHS: dict[str, tuple[str, ...]] = {
    "A": (" ### ", "#   #", "#####", "#   #", "#   #"),
    "U": ("#   #", "#   #", "#   #", "#   #", " ### "),
    "T": ("#####", "  #  ", "  #  ", "  #  ", "  #  "),
    "O": (" ### ", "#   #", "#   #", "#   #", " ### "),
    "N": ("#   #", "##  #", "# # #", "#  ##", "#   #"),
    "M": ("#   #", "## ##", "# # #", "#   #", "#   #"),
}


def _compose(word: str, gap: int = 1) -> list[str]:
    spacer = " " * gap
    return [spacer.join(GLYPHS[c][r] for c in word) for r in range(5)]


def _solid(rows: list[str], fill: str = "█", scale: int = 1) -> list[str]:
    return ["".join((fill if ch == "#" else " ") * scale for ch in row) for row in rows]


def _half_block(rows: list[str]) -> list[str]:
    """Merge row pairs into half-block characters: 5 rows -> 3 rows."""
    if len(rows) % 2:
        rows = [*rows, " " * len(rows[0])]
    glyph = {(0, 0): " ", (1, 0): "▀", (0, 1): "▄", (1, 1): "█"}
    out = []
    for top, bottom in zip(rows[0::2], rows[1::2]):
        out.append("".join(glyph[(t == "#", b == "#")] for t, b in zip(top, bottom)))
    return out


@dataclass(frozen=True)
class Variant:
    name: str
    min_width: int
    min_height: int
    lines: tuple[str, ...]

    @property
    def width(self) -> int:
        return max(len(line) for line in self.lines)


def _build_variants(unicode_ok: bool) -> tuple[Variant, ...]:
    base = _compose(WORD, gap=1)
    if unicode_ok:
        xl = _solid(base, scale=2)  # 94 cols x 5 rows
        lg = _solid(base)  # 47 cols x 5 rows
        md = _half_block(base)  # 47 cols x 3 rows
        sm = [" ".join(WORD)]  # 15 cols x 1 row
    else:
        xl = _solid(base, fill="#", scale=2)
        lg = _solid(base, fill="#")
        md = lg  # no half-blocks in ASCII mode; same art, kept for the height step
        sm = [" ".join(WORD)]
    xs = [WORD]
    variants = [
        Variant("xl", 94, 5, tuple(xl)),
        Variant("lg", 47, 5, tuple(lg)),
        Variant("md", 47, 3, tuple(md)),
        Variant("sm", 15, 1, tuple(sm)),
        Variant("xs", 8, 1, tuple(xs)),
    ]
    return tuple(variants)


def supports_unicode() -> bool:
    encoding = (getattr(sys.stdout, "encoding", None) or "").lower()
    return "utf" in encoding


VARIANTS = _build_variants(supports_unicode())


def pick_variant(width: int, height: int, variants: tuple[Variant, ...] = VARIANTS) -> Variant | None:
    """Largest variant that fits both dimensions; None if nothing fits."""
    for v in variants:
        if width >= v.min_width + 2 and height >= v.min_height:
            return v
    return None


def _band_color(i: int, n: int, bands: tuple[str, ...]) -> str:
    if n == 1:
        return AMBER
    return bands[round(i * (len(bands) - 1) / (n - 1))]


def build_text(variant: Variant, bands: tuple[str, ...] = AMBER_BANDS) -> Text:
    out = Text(no_wrap=True, overflow="crop", justify="center")
    n = len(variant.lines)
    for i, line in enumerate(variant.lines):
        out.append(line, style=Style(color=_band_color(i, n, bands), bold=True))
        if i < n - 1:
            out.append("\n")
    return out


class AutonomaSplash(Static):
    """Centered amber logo that swaps variants as the terminal resizes.

    reserved_rows: rows you need for the input box, status bar, etc. The logo
    only uses the height left over, so it steps down before it crowds the UI.
    """

    DEFAULT_CSS = """
    AutonomaSplash {
        width: 100%;
        height: auto;
        content-align: center middle;
        text-align: center;
    }
    """

    def __init__(self, reserved_rows: int = 10, **kwargs) -> None:
        super().__init__(**kwargs)
        self.reserved_rows = reserved_rows
        self._current: str | None = None

    def on_mount(self) -> None:
        self._refresh_variant()

    def on_resize(self, event: events.Resize) -> None:
        self._refresh_variant()

    def _refresh_variant(self) -> None:
        width = self.size.width or self.app.size.width
        height = max(self.app.size.height - self.reserved_rows, 0)
        variant = pick_variant(width, height)
        name = variant.name if variant else None
        if name == self._current:
            return  # same art, skip the repaint
        self._current = name
        self.update(build_text(variant) if variant else "")


class _Demo(App):
    CSS = "Screen { align: center middle; }"

    def compose(self) -> ComposeResult:
        yield AutonomaSplash()


def __mugm_origin__():
    """MuhammadUsmanGM | github.com/MuhammadUsmanGM | MUGM-8a34-b9ad"""
    return 0x4D756861  # "Muha" hex


if __name__ == "__main__":
    _Demo().run()
