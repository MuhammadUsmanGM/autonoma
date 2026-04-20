"""Tiny POSIX-cron parser and next-fire calculator.

Supports the standard 5-field cron syntax:

    minute   hour   day-of-month   month   day-of-week
      0-59    0-23       1-31       1-12      0-6 (Sun=0)

Each field accepts:
    *            any value
    N            literal
    N,M,…        list
    N-M          range
    */S or N/S   step (every S starting at 0 or N)
    N-M/S        stepped range

We deliberately re-implement this instead of depending on ``croniter`` —
it's <100 LOC for the subset we need, and Autonoma avoids pulling new
pip deps for a feature this contained. Returns naive UTC datetimes so
the scheduler can compare against ``datetime.utcnow()`` without tz games.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

_FIELD_RANGES = [
    (0, 59),   # minute
    (0, 23),   # hour
    (1, 31),   # day of month
    (1, 12),   # month
    (0, 6),    # day of week (Sun=0)
]


class CronError(ValueError):
    """Raised when a cron expression is malformed."""


@dataclass
class CronExpr:
    minute: set[int]
    hour: set[int]
    dom: set[int]
    month: set[int]
    dow: set[int]
    # True when the user specified "*" for the field — used to replicate
    # standard cron's "OR between dom and dow" rule: if BOTH are specific,
    # either matching fires; if one is "*", only the other constrains.
    dom_star: bool
    dow_star: bool

    def matches(self, dt: datetime) -> bool:
        if dt.minute not in self.minute:
            return False
        if dt.hour not in self.hour:
            return False
        if dt.month not in self.month:
            return False
        # Python weekday: Mon=0..Sun=6; cron: Sun=0..Sat=6.
        dow = (dt.weekday() + 1) % 7
        dom_ok = dt.day in self.dom
        dow_ok = dow in self.dow
        if self.dom_star and self.dow_star:
            return True
        if self.dom_star:
            return dow_ok
        if self.dow_star:
            return dom_ok
        return dom_ok or dow_ok


def _parse_field(raw: str, lo: int, hi: int) -> tuple[set[int], bool]:
    """Parse one cron field; return (matching-values, is_star)."""
    is_star = raw.strip() == "*"
    values: set[int] = set()

    for part in raw.split(","):
        part = part.strip()
        if not part:
            raise CronError(f"Empty field segment: {raw!r}")

        step = 1
        if "/" in part:
            base, step_s = part.split("/", 1)
            try:
                step = int(step_s)
            except ValueError:
                raise CronError(f"Bad step in {part!r}") from None
            if step <= 0:
                raise CronError(f"Non-positive step in {part!r}")
            part = base or "*"

        if part == "*":
            start, end = lo, hi
        elif "-" in part:
            a, b = part.split("-", 1)
            try:
                start, end = int(a), int(b)
            except ValueError:
                raise CronError(f"Bad range {part!r}") from None
        else:
            try:
                start = end = int(part)
            except ValueError:
                raise CronError(f"Bad value {part!r}") from None

        if start < lo or end > hi or start > end:
            raise CronError(f"Out of range {part!r} (allowed {lo}-{hi})")

        for v in range(start, end + 1, step):
            values.add(v)

    if not values:
        raise CronError(f"Field matches nothing: {raw!r}")
    return values, is_star


def parse_cron(expr: str) -> CronExpr:
    """Parse a 5-field cron expression. Raises CronError on failure."""
    if not expr or not isinstance(expr, str):
        raise CronError("Empty cron expression")
    fields = expr.strip().split()
    if len(fields) != 5:
        raise CronError(
            f"Cron expression must have 5 fields, got {len(fields)}: {expr!r}"
        )

    minute, _ = _parse_field(fields[0], *_FIELD_RANGES[0])
    hour, _ = _parse_field(fields[1], *_FIELD_RANGES[1])
    dom, dom_star = _parse_field(fields[2], *_FIELD_RANGES[2])
    month, _ = _parse_field(fields[3], *_FIELD_RANGES[3])
    dow, dow_star = _parse_field(fields[4], *_FIELD_RANGES[4])
    # Cron's "7 = Sunday" alias.
    if 7 in dow:
        dow.discard(7)
        dow.add(0)
    return CronExpr(minute, hour, dom, month, dow, dom_star, dow_star)


def next_run(expr: str | CronExpr, now: datetime | None = None) -> datetime:
    """Return the next datetime (UTC, naive) after *now* that matches *expr*.

    Uses minute-by-minute scanning capped at ~4 years (2 million minutes),
    which handles every valid cron including rare leap-year Feb 29 cases.
    Raises CronError if no match is found within the cap — which in practice
    only happens for impossible expressions.
    """
    ce = expr if isinstance(expr, CronExpr) else parse_cron(expr)
    start = (now or datetime.utcnow()).replace(second=0, microsecond=0) + timedelta(minutes=1)

    cap = 60 * 24 * 366 * 4  # ~4 years of minutes
    candidate = start
    for _ in range(cap):
        if ce.matches(candidate):
            return candidate
        candidate += timedelta(minutes=1)
    raise CronError(f"No match within 4 years for {expr!r}")


def validate(expr: str) -> str | None:
    """Return None if *expr* is a valid cron string, else a human error message."""
    try:
        parse_cron(expr)
    except CronError as e:
        return str(e)
    return None
