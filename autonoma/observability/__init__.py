"""Observability: metrics, traces, structured logs.

Public surface:

- ``metrics``           — Prometheus exposition + a small set of counters,
                          gauges, and histograms instrumented across the
                          agent loop, tool runner, and HTTP server.
- ``otel``              — Optional OpenTelemetry bridge; only activates when
                          both ``opentelemetry-sdk`` and an OTLP endpoint
                          are configured.
"""

from autonoma.observability.metrics import (
    metrics_registry,
    render_prometheus,
)

__all__ = ["metrics_registry", "render_prometheus"]
