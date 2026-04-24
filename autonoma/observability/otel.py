"""Optional OpenTelemetry bridge.

Activates only when BOTH conditions hold:
  1. ``opentelemetry-sdk`` (and the OTLP HTTP exporter) is installed — install
     the optional extra with ``pip install autonoma[observability]``.
  2. An OTLP endpoint is configured via ``AUTONOMA_OTEL_ENDPOINT`` / YAML.

When inactive, every public entry point is a cheap no-op so core behavior is
unaffected. This lets us keep OTel out of the required dependency set while
still offering first-class tracing for production deployments.

Design:
  - One module-level ``TracerProvider`` is configured once on ``init()``.
  - ``start_trace_span`` is called by the agent loop when a new ``Trace`` is
    created, and returns an opaque handle.
  - ``end_trace_span`` closes the span with the final status (ok / error) and
    folds in token counts + cost as span attributes so backends like
    Jaeger / Honeycomb / Tempo can slice by model.
  - ``add_trace_event`` turns each pipeline stage (``validate``, ``infer``,
    etc.) into an OTel span event — giving you the existing 9-stage pipeline
    view for free inside any OTel UI.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_tracer = None  # opentelemetry.trace.Tracer | None
_enabled = False
_init_attempted = False  # guard so a failed install is reported once, not per-trace


def init(
    endpoint: str,
    service_name: str = "autonoma",
    headers: str = "",
) -> bool:
    """Configure the OTel tracer provider.

    Returns True when successfully initialized. Safe to call multiple times;
    only the first successful call wires up the exporter.
    """
    global _tracer, _enabled, _init_attempted
    if _enabled:
        return True
    if _init_attempted:
        return False
    _init_attempted = True

    if not endpoint:
        return False

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError as e:
        logger.warning(
            "AUTONOMA_OTEL_ENDPOINT is set but OpenTelemetry is not installed. "
            "Run `pip install autonoma[observability]` to enable tracing. (%s)",
            e,
        )
        return False

    parsed_headers: dict[str, str] = {}
    if headers:
        for pair in headers.split(","):
            if "=" in pair:
                k, v = pair.split("=", 1)
                parsed_headers[k.strip()] = v.strip()

    try:
        resource = Resource.create({"service.name": service_name})
        provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(
            endpoint=endpoint,
            headers=parsed_headers or None,
        )
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer("autonoma")
        _enabled = True
        logger.info("OpenTelemetry tracing enabled (endpoint=%s)", endpoint)
        return True
    except Exception as e:  # pragma: no cover — advisory
        logger.warning("Failed to initialize OpenTelemetry: %s", e)
        return False


def is_enabled() -> bool:
    return _enabled


def start_trace_span(
    name: str,
    attributes: dict[str, Any] | None = None,
):
    """Start a new OTel span for an agent trace. Returns an opaque handle (or None)."""
    if not _enabled or _tracer is None:
        return None
    try:
        span = _tracer.start_span(name)
        if attributes:
            for k, v in attributes.items():
                if v is None:
                    continue
                try:
                    span.set_attribute(k, v)
                except Exception:
                    span.set_attribute(k, str(v))
        return span
    except Exception as e:  # pragma: no cover — advisory
        logger.debug("start_trace_span failed: %s", e)
        return None


def add_trace_event(span, event_name: str, attributes: dict[str, Any] | None = None) -> None:
    if span is None:
        return
    try:
        flat: dict[str, Any] = {}
        if attributes:
            for k, v in attributes.items():
                if isinstance(v, (str, int, float, bool)) or v is None:
                    flat[k] = v
                else:
                    flat[k] = str(v)
        span.add_event(event_name, attributes=flat)
    except Exception as e:  # pragma: no cover — advisory
        logger.debug("add_trace_event failed: %s", e)


def end_trace_span(
    span,
    *,
    status: str = "ok",
    error: str | None = None,
    attributes: dict[str, Any] | None = None,
) -> None:
    """End the span with a final status and any final attributes."""
    if span is None:
        return
    try:
        from opentelemetry.trace import Status, StatusCode

        if attributes:
            for k, v in attributes.items():
                if v is None:
                    continue
                try:
                    span.set_attribute(k, v)
                except Exception:
                    span.set_attribute(k, str(v))

        if status == "error":
            span.set_status(Status(StatusCode.ERROR, description=error or "error"))
            if error:
                span.set_attribute("autonoma.error", error)
        else:
            span.set_status(Status(StatusCode.OK))
        span.end()
    except Exception as e:  # pragma: no cover — advisory
        logger.debug("end_trace_span failed: %s", e)
