# Changelog

All notable changes to Autonoma will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.1] - 2026-04-28

### Added
- **Observability stack.** Optional OpenTelemetry tracing — each agent loop
  becomes one `autonoma.agent.loop` span with the 9 pipeline stages as span
  events, plus attributes for model, tokens, cost, and elapsed time. Configure
  via `AUTONOMA_OTEL_ENDPOINT` / `AUTONOMA_OTEL_SERVICE_NAME` /
  `AUTONOMA_OTEL_HEADERS`. Install with `pip install autonoma[observability]`.
- **Prometheus `/metrics` endpoint** exposing agent loop counters and
  histograms, LLM token + cost totals per model, tool call status counters
  and latency histograms, channel status gauges, HTTP request counters and
  latency, and `autonoma_build_info`. Toggle with
  `AUTONOMA_METRICS_ENABLED`.
- **Health probes.** Always-on `GET /healthz` (liveness) and `GET /readyz`
  (readiness — 503 during startup/shutdown, 200 once the HTTP server is
  serving traffic).
- **Structured JSON logging.** Set `AUTONOMA_LOG_FORMAT=json` (or
  `observability.log_format: json` in `autonoma.yaml`) to emit one JSON
  object per log line for Loki / Elasticsearch / CloudWatch ingestion.
- **Sandbox configuration surface.** New `sandbox:` block in `autonoma.yaml`
  exposing wall-clock timeout, output cap, POSIX rlimits (memory / CPU /
  process count), per-file write ceiling, env allowlist, shell binary
  allowlist, write extension denylist, and per-session rate limits.
- **Pluggable executor backends.** New `executor/backends/` package with a
  `direct` backend (default) and a `docker` scaffold (raises a clear startup
  error until implemented).
- **Tool audit log.** Every tool invocation — ok / denied / timeout / error —
  is appended as a JSONL record to `<session_dir>/audit.log` with session id,
  tool name, sha256-16 `input_hash`, elapsed ms, and error.

### Changed
- **Sandbox hardened by default.** Shell is now disabled out of the box
  (`shell_allowed_binaries: []`); operators must explicitly allowlist
  binaries. Argv mode is the only mode by default — string mode with
  metacharacter parsing is opt-in via `shell_allow_strings: true`.
  Subprocess network egress is off (`allow_network: false`), which strips
  proxy env vars and blocks `curl` / `wget` / `nc` from the shell allowlist
  at call time. API keys, bot tokens, and shell-hook env vars (`BASH_ENV`,
  `LD_PRELOAD`, ...) are stripped from subprocess env regardless of
  `env_allowlist`.
- **Path containment via `Path.relative_to()`** in
  `autonoma/executor/path_safety.py` instead of a prefix match — closes a
  `../workspace_evil/secret` traversal that could escape a `workspace/` base.
- **`file_write` write-extension denylist.** Binaries, shared libraries, and
  shell scripts (`.exe`, `.bat`, `.cmd`, `.ps1`, `.sh`, `.bash`, `.so`,
  `.dylib`, `.dll`, `.com`, `.scr`, `.msi`) are refused by default.

### Notes
- **Windows**: POSIX rlimits become advisory (the `resource` module is
  absent). Wall-clock timeout and output caps still apply, and the sandbox
  logs a one-time warning on startup. Run inside WSL2 or a Linux container
  for production on Windows.

[1.0.1]: https://github.com/MuhammadUsmanGM/autonoma/releases/tag/v1.0.1

## [1.0.0] - 2026-04-23

### Added
- Initial public release on npm as `autonoma-ai`.
- Core agent loop with 9-stage pipeline, hybrid memory, and tool execution.
- Multi-channel gateway: Telegram, Discord, WhatsApp, Gmail, REST API.
- Real-time React + TypeScript dashboard with dual-theme support.
- Proactive monitoring: HUD alerts, proxy health polling, channel connectivity.
- Priority task queue with **cron scheduling** — submit tasks with a 5-field
  POSIX cron string (`0 8 * * *`) and the scheduler fires them on a 30s tick.
- LLM cost + token dashboard: per-trace `tokens_in`, `tokens_out`, `cost_usd`;
  Settings page shows today / week / month spend per model.
- Inline proxy URL editor in the dashboard (Telegram), persisting to both
  `.env` and `autonoma.yaml`.
- `POST /api/tasks` accepts `prompt` + `cron` and routes through the default
  `agent_prompt` handler.
- OpenRouter provider with pluggable model routing.

[1.0.0]: https://github.com/MuhammadUsmanGM/autonoma/releases/tag/v1.0.0
