"""Zero-dependency Prometheus metrics.

We deliberately avoid the `prometheus_client` package so that the core
install stays lean — Autonoma already ships with only a handful of runtime
dependencies and metrics shouldn't change that.

The implementation is small on purpose:

* ``Counter``   — monotonically increasing value per label-set.
* ``Gauge``     — arbitrary value per label-set (can go up or down).
* ``Histogram`` — bucketed distribution with sum + count, matching the
                  Prometheus exposition shape exactly so Grafana / PromQL
                  work without any custom mapping.

Thread-safety: all operations take a module-level ``threading.Lock``. The
agent loop is async-single-threaded today, but the HTTP server and task
queue run work on the default executor; a coarse lock is simpler and
cheaper than per-metric locking at the volumes we expect (< 10k samples/s).
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Tuple

_LOCK = threading.Lock()

# Default histogram buckets (seconds) — covers sub-millisecond tool calls up
# to multi-minute LLM/ReAct loops. Matches the range of `elapsed_seconds`
# we already see in trace_store.
DEFAULT_BUCKETS: Tuple[float, ...] = (
    0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0,
)

LabelKey = Tuple[Tuple[str, str], ...]


def _label_key(labels: Dict[str, str] | None) -> LabelKey:
    """Convert a label dict into a hashable, order-stable key."""
    if not labels:
        return ()
    return tuple(sorted((k, str(v)) for k, v in labels.items()))


def _escape_label_value(value: str) -> str:
    """Escape per Prometheus exposition format: backslash, double quote, newline."""
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _format_labels(key: LabelKey) -> str:
    if not key:
        return ""
    inner = ",".join(f'{k}="{_escape_label_value(v)}"' for k, v in key)
    return "{" + inner + "}"


@dataclass
class _Metric:
    name: str
    help_text: str
    type_name: str  # "counter" | "gauge" | "histogram"

    def render(self) -> Iterable[str]:  # pragma: no cover — overridden
        raise NotImplementedError


@dataclass
class Counter(_Metric):
    type_name: str = "counter"
    values: Dict[LabelKey, float] = field(default_factory=dict)

    def inc(self, amount: float = 1.0, labels: Dict[str, str] | None = None) -> None:
        if amount < 0:
            return  # counters only go up; silently ignore negative increments
        key = _label_key(labels)
        with _LOCK:
            self.values[key] = self.values.get(key, 0.0) + amount

    def render(self) -> Iterable[str]:
        yield f"# HELP {self.name} {self.help_text}"
        yield f"# TYPE {self.name} counter"
        with _LOCK:
            items = list(self.values.items())
        if not items:
            # Emit a zero sample with no labels so scrapers see the series exists.
            yield f"{self.name} 0"
            return
        for key, val in items:
            yield f"{self.name}{_format_labels(key)} {val}"


@dataclass
class Gauge(_Metric):
    type_name: str = "gauge"
    values: Dict[LabelKey, float] = field(default_factory=dict)

    def set(self, value: float, labels: Dict[str, str] | None = None) -> None:
        key = _label_key(labels)
        with _LOCK:
            self.values[key] = float(value)

    def inc(self, amount: float = 1.0, labels: Dict[str, str] | None = None) -> None:
        key = _label_key(labels)
        with _LOCK:
            self.values[key] = self.values.get(key, 0.0) + amount

    def dec(self, amount: float = 1.0, labels: Dict[str, str] | None = None) -> None:
        self.inc(-amount, labels=labels)

    def render(self) -> Iterable[str]:
        yield f"# HELP {self.name} {self.help_text}"
        yield f"# TYPE {self.name} gauge"
        with _LOCK:
            items = list(self.values.items())
        if not items:
            yield f"{self.name} 0"
            return
        for key, val in items:
            yield f"{self.name}{_format_labels(key)} {val}"


@dataclass
class _HistogramState:
    # Upper-bound → cumulative count (Prometheus histogram semantics).
    # We store per-bucket counts and convert to cumulative at render time.
    bucket_counts: List[int] = field(default_factory=list)
    sum: float = 0.0
    count: int = 0


@dataclass
class Histogram(_Metric):
    type_name: str = "histogram"
    buckets: Tuple[float, ...] = DEFAULT_BUCKETS
    values: Dict[LabelKey, _HistogramState] = field(default_factory=dict)

    def observe(self, value: float, labels: Dict[str, str] | None = None) -> None:
        key = _label_key(labels)
        with _LOCK:
            state = self.values.get(key)
            if state is None:
                state = _HistogramState(bucket_counts=[0] * (len(self.buckets) + 1))
                self.values[key] = state
            state.sum += value
            state.count += 1
            for i, upper in enumerate(self.buckets):
                if value <= upper:
                    state.bucket_counts[i] += 1
                    return
            # Overflow bucket (+Inf)
            state.bucket_counts[-1] += 1

    def render(self) -> Iterable[str]:
        yield f"# HELP {self.name} {self.help_text}"
        yield f"# TYPE {self.name} histogram"
        with _LOCK:
            items = list(self.values.items())
        if not items:
            return
        for key, state in items:
            cumulative = 0
            for i, upper in enumerate(self.buckets):
                cumulative += state.bucket_counts[i]
                bucket_labels = dict(key) if key else {}
                bucket_labels["le"] = _format_float(upper)
                yield f"{self.name}_bucket{_format_labels(_label_key(bucket_labels))} {cumulative}"
            # +Inf bucket
            cumulative += state.bucket_counts[-1]
            bucket_labels = dict(key) if key else {}
            bucket_labels["le"] = "+Inf"
            yield f"{self.name}_bucket{_format_labels(_label_key(bucket_labels))} {cumulative}"
            yield f"{self.name}_sum{_format_labels(key)} {state.sum}"
            yield f"{self.name}_count{_format_labels(key)} {state.count}"


def _format_float(value: float) -> str:
    """Match Prometheus' own bucket labeling — 0.5 not 0.500000."""
    if value == int(value):
        return f"{int(value)}.0"
    return repr(value)


class Registry:
    """Holds every metric series we expose on /metrics."""

    def __init__(self) -> None:
        self._metrics: Dict[str, _Metric] = {}

    def counter(self, name: str, help_text: str) -> Counter:
        return self._register(Counter(name=name, help_text=help_text))

    def gauge(self, name: str, help_text: str) -> Gauge:
        return self._register(Gauge(name=name, help_text=help_text))

    def histogram(
        self,
        name: str,
        help_text: str,
        buckets: Tuple[float, ...] = DEFAULT_BUCKETS,
    ) -> Histogram:
        return self._register(Histogram(name=name, help_text=help_text, buckets=buckets))

    def _register(self, metric):
        if metric.name in self._metrics:
            existing = self._metrics[metric.name]
            if type(existing) is not type(metric):
                raise ValueError(
                    f"Metric {metric.name} already registered with a different type "
                    f"({existing.type_name})"
                )
            return existing  # idempotent — useful across test reloads
        self._metrics[metric.name] = metric
        return metric

    def render(self) -> str:
        lines: List[str] = []
        for metric in self._metrics.values():
            lines.extend(metric.render())
        lines.append("")  # trailing newline required by the exposition format
        return "\n".join(lines)


# -----------------------------------------------------------------------------
# Module-level registry + the canonical Autonoma metric set.
# -----------------------------------------------------------------------------

metrics_registry = Registry()

agent_loop_total = metrics_registry.counter(
    "autonoma_agent_loop_total",
    "Total agent loop invocations, by outcome.",
)
agent_loop_duration_seconds = metrics_registry.histogram(
    "autonoma_agent_loop_duration_seconds",
    "Wall-clock duration of a complete agent loop invocation.",
)
llm_tokens_total = metrics_registry.counter(
    "autonoma_llm_tokens_total",
    "Total LLM tokens, split by direction (input/output) and model.",
)
llm_cost_usd_total = metrics_registry.counter(
    "autonoma_llm_cost_usd_total",
    "Estimated LLM spend in USD, per model.",
)
tool_calls_total = metrics_registry.counter(
    "autonoma_tool_calls_total",
    "Tool call invocations from the ReAct loop.",
)
tool_duration_seconds = metrics_registry.histogram(
    "autonoma_tool_duration_seconds",
    "Wall-clock duration of a single tool execution.",
)
channel_status = metrics_registry.gauge(
    "autonoma_channel_status",
    "Channel state: 1=running, 0=stopped, -1=error.",
)
http_requests_total = metrics_registry.counter(
    "autonoma_http_requests_total",
    "HTTP requests served by the gateway.",
)
http_request_duration_seconds = metrics_registry.histogram(
    "autonoma_http_request_duration_seconds",
    "Wall-clock duration of an HTTP request handler.",
)
build_info = metrics_registry.gauge(
    "autonoma_build_info",
    "Constant 1, labeled with build metadata (version, python).",
)


def render_prometheus() -> str:
    """Return the current metrics snapshot in Prometheus text format."""
    return metrics_registry.render()


_STATUS_TO_GAUGE = {"running": 1.0, "stopped": 0.0, "starting": 0.0, "error": -1.0}


def set_channel_status(name: str, status: str) -> None:
    """Translate a channel status string to the gauge sample."""
    value = _STATUS_TO_GAUGE.get(status, 0.0)
    channel_status.set(value, labels={"channel": name})


class Timer:
    """Context manager that observes wall-clock duration into a histogram.

    Usage::

        with Timer(tool_duration_seconds, labels={"tool": "shell"}):
            ...
    """

    __slots__ = ("_hist", "_labels", "_start")

    def __init__(self, hist: Histogram, labels: Dict[str, str] | None = None):
        self._hist = hist
        self._labels = labels
        self._start = 0.0

    def __enter__(self) -> "Timer":
        self._start = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._hist.observe(time.perf_counter() - self._start, labels=self._labels)
