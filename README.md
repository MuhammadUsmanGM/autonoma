<p align="center">
  <h1 align="center">Autonoma</h1>
  <p align="center">
    <strong>Open-source AI agent platform. Build, deploy, and run digital employees.</strong>
  </p>
  <p align="center">
    <img src="https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python">
    <img src="https://img.shields.io/badge/License-MIT-22c55e?style=flat-square" alt="License">
    <img src="https://img.shields.io/badge/React-19-61DAFB?style=flat-square&logo=react&logoColor=black" alt="React">
    <img src="https://img.shields.io/badge/TypeScript-5.0-3178C6?style=flat-square&logo=typescript&logoColor=white" alt="TypeScript">
    <img src="https://img.shields.io/badge/SQLite-FTS5-003B57?style=flat-square&logo=sqlite&logoColor=white" alt="SQLite">
    <img src="https://img.shields.io/npm/v/autonoma-ai?style=flat-square&color=cb3837&logo=npm" alt="npm version">
    <img src="https://img.shields.io/npm/dm/autonoma-ai?style=flat-square&color=cb3837&logo=npm" alt="npm downloads">
    <img src="https://img.shields.io/bundlephobia/min/autonoma-ai?style=flat-square&color=8b5cf6" alt="install size">
    <img src="https://img.shields.io/badge/PRs-Welcome-brightgreen?style=flat-square" alt="PRs Welcome">
  </p>
</p>

---

Autonoma is a modular AI agent that operates as a **digital full-time employee (FTE)**. It connects to your communication channels, remembers context across conversations, executes tasks with built-in tools, and exposes a high-fidelity HUD for real-time monitoring — all from a single Python process.

## Features

### Multi-Channel Communication
Connect once, reach everywhere. Autonoma natively supports **Telegram**, **Discord**, **WhatsApp**, **Gmail**, and a **REST API**. Features intelligent routing and multi-session persistence.

### Proactive Monitoring & Alerts
The platform is no longer purely reactive. A background polling service continuously monitors system health, memory thresholds, and channel connectivity, triggering **HUD Alerts** through a slide-over triage panel.

### High-Fidelity Dashboard
A premium React + TypeScript HUD with context-aware **Dual-Theme support** (Light/Dark).
- **Execution Telemetry**: Live Gantt-style visualizations tracking pipeline latency.
- **Neural Registry**: Memory explorer with bulk-pruning and stale node maintenance.
- **Soul Evolution**: Identity editor with integrated **diff view** to track personality shifts.
- **Session Audit Log**: Advanced search and filtering to replay historical interactions.

### Intelligent Memory
SQLite + FTS5 powered memory with **BM25 ranked retrieval**. Memories are scored by relevance, importance, and recency. Features automatic deduplication and importance decay.

### Tool execution & Sandbox
Secure execution environment with built-in tools for web search, file operations, and shell command chaining in isolated workspaces. **Hardened by default**: shell is off until binaries are allowlisted, path traversal is rejected via `Path.relative_to()` containment, secrets and shell-hook env vars never reach child processes, and every tool call is appended to a per-session JSONL audit log.

### Production Observability
Structured JSON logs, a Prometheus `/metrics` endpoint (agent loops, LLM tokens + cost per model, tool latency, channel status, HTTP latency), always-on `/healthz` and `/readyz` probes, and optional **OpenTelemetry** tracing — each agent loop becomes one span with the 9 pipeline stages as events.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                     Channels                         │
│  Telegram · Discord · WhatsApp · Gmail · REST · CLI  │
└──────────────────────┬──────────────────────────────┘
                       │
              ┌────────▼────────┐
              │     Gateway     │
              │  Route · Auth   │
              └────────┬────────┘
                       │
              ┌────────▼────────┐
              │     Cortex      │
              │  Agent · LLM    │◄────► Memory (SQLite + FTS5)
              │  Context · Loop │      BM25 · Decay · Dedup
              └────────┬────────┘
                       │
              ┌────────▼────────┐
              │    Executor     │
              │  Sandbox · Tools│
              └─────────────────┘
```

## Quick Start

### Install via npm (recommended)

```bash
npm install -g autonoma-ai
```

The postinstall step creates a Python virtual environment and installs the
Python runtime. If Python 3.11+ is not on your `PATH`, install it from
[python.org](https://www.python.org/downloads/) and run
`npm rebuild autonoma-ai`. The npm install itself will succeed either way —
only the Python runtime step is deferred.

Configure your API key via environment variable (exported in your shell, or in
a `.env` file in the directory you run `autonoma` from):

```bash
export OPENROUTER_API_KEY=sk-or-...    # or ANTHROPIC_API_KEY
autonoma
```

> **Requires:** Node.js 18+ and Python 3.11+
> CI users can set `AUTONOMA_SKIP_POSTINSTALL=1` to skip the Python step
> during `npm install`.

### Install from source

```bash
git clone https://github.com/MuhammadUsmanGM/autonoma.git
cd autonoma

cp .env.example .env
# Edit .env — add your API key

pip install -e .
python -m autonoma
```

### Dashboard

The npm package ships the pre-built dashboard (`dashboard/dist/`) — it is
served automatically by the Autonoma gateway on `http://127.0.0.1:8766`
when you run `autonoma`. No separate dev server is needed for end users.

Dashboard contributors working from a source clone can run it standalone:

```bash
cd dashboard
npm install
npm run dev
# Opens at http://localhost:5173
```

## Project Structure

```
autonoma/
├── cortex/           # Agent core — reasoning loop, context assembly, sessions
├── gateway/          # Channel adapters, HTTP server, routing, auth
├── executor/         # Sandboxed tool execution engine
├── memory/           # SQLite + FTS5 store, retrieval, consolidation
├── models/           # LLM provider abstraction (Anthropic, OpenRouter)
├── skills/           # Tool registry and loader
├── config.py         # Dataclass-based configuration
├── schema.py         # Core data models (Message, AgentResponse, etc.)
└── main.py           # Bootstrap and wiring

dashboard/            # React + TypeScript + Vite + Tailwind frontend
whatsapp-bridge/      # Node.js sidecar for WhatsApp Web (QR scan)
workspace/            # Agent workspace — SOUL.md, memory, task outputs
```

## Channel Setup

| Channel | Environment Variables | Notes |
|---------|----------------------|-------|
| **Telegram** | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_PROXY_URL` | Create bot via [@BotFather](https://t.me/BotFather). Proxy optional (SOCKS5 supported). |
| **Discord** | `DISCORD_BOT_TOKEN` | Requires `MESSAGE_CONTENT` privileged intent enabled in Discord Developer Portal. |
| **WhatsApp** | `WHATSAPP_BRIDGE_URL` | Runs via `whatsapp-bridge/` sidecar. Scan QR code on first launch. |
| **Gmail** | `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD` | Use an [App Password](https://support.google.com/accounts/answer/185833), not your account password. |
| **REST API** | `AUTONOMA_REST_API_TOKEN` | Token is optional. Endpoint: `POST /api/chat` |
| **CLI** | Always enabled | Interactive terminal with rich formatting. |

## Configuration

Autonoma loads config with this precedence: **env vars > .env > autonoma.yaml > defaults**.

```yaml
# autonoma.yaml
name: Autonoma
gateway:
  host: 127.0.0.1
  port: 8765          # WebSocket
  http_port: 8766     # REST API + Dashboard API
llm:
  provider: openrouter # or "anthropic"
  model: nvidia/llama-3.1-nemotron-nano-8b-v1:free
```

Key environment variables:

| Variable | Description |
|----------|-------------|
| `AUTONOMA_LLM_PROVIDER` | `openrouter` or `anthropic` |
| `OPENROUTER_API_KEY` | OpenRouter API key |
| `ANTHROPIC_API_KEY` | Anthropic API key |
| `AUTONOMA_LLM_MODEL` | Model name override |
| `AUTONOMA_LOG_LEVEL` | `debug`, `info`, `warning`, `error` |

## Observability

Autonoma ships production-grade observability out of the box — structured
logs, Prometheus metrics, health probes, and optional OpenTelemetry tracing.

### Health probes

Always-on, no configuration required:

| Endpoint | Purpose |
|----------|---------|
| `GET /healthz` | Liveness — returns 200 while the process is running. |
| `GET /readyz` | Readiness — returns 200 once the HTTP server is accepting traffic, 503 during startup/shutdown. |

### Structured JSON logs

Set `AUTONOMA_LOG_FORMAT=json` (or `observability.log_format: json` in
`autonoma.yaml`) to emit one JSON object per log line. Designed to be piped
into Loki, Elasticsearch, CloudWatch, or any log aggregator that understands
JSON.

```json
{"timestamp":"2026-04-24T12:34:56.789Z","level":"INFO","logger":"autonoma","message":"Processed message in 1.23s","asctime":"12:34:56"}
```

### Prometheus metrics

A `/metrics` endpoint exposes the full metric set in Prometheus text format.
Scrape it with any standard config:

```yaml
# prometheus.yml
scrape_configs:
  - job_name: autonoma
    static_configs:
      - targets: ["localhost:8766"]
```

Exposed series:

| Metric | Type | Description |
|--------|------|-------------|
| `autonoma_agent_loop_total{status,channel}` | counter | Total agent loops by outcome. |
| `autonoma_agent_loop_duration_seconds` | histogram | End-to-end loop latency. |
| `autonoma_llm_tokens_total{direction,model}` | counter | Input / output tokens per model. |
| `autonoma_llm_cost_usd_total{model}` | counter | Estimated LLM spend. |
| `autonoma_tool_calls_total{tool,status}` | counter | Tool invocations (ok / timeout / error / denied). |
| `autonoma_tool_duration_seconds{tool}` | histogram | Tool execution latency. |
| `autonoma_channel_status{channel}` | gauge | 1=running, 0=stopped, -1=error. |
| `autonoma_http_requests_total{method,path,status}` | counter | HTTP requests served. |
| `autonoma_http_request_duration_seconds{method,path}` | histogram | Request latency. |
| `autonoma_build_info{version,python}` | gauge | Build metadata. |

Disable with `AUTONOMA_METRICS_ENABLED=false` if you want `/metrics` off.

### OpenTelemetry (optional)

Ship traces to any OTLP-compatible backend (Jaeger, Tempo, Honeycomb,
Datadog, etc.). The core install stays lean — OTel only activates when both
the optional dependency is installed and an endpoint is configured.

```bash
pip install autonoma[observability]
export AUTONOMA_OTEL_ENDPOINT=http://localhost:4318/v1/traces
export AUTONOMA_OTEL_SERVICE_NAME=autonoma-prod
# Optional: authenticated collectors
export AUTONOMA_OTEL_HEADERS="x-api-key=...,x-tenant=acme"
autonoma
```

Each agent loop becomes one span (`autonoma.agent.loop`) with the 9 pipeline
stages as span events, plus attributes for model, tokens, cost, and elapsed
time — so you can slice latency by channel or cost by model directly in your
tracing UI.

## Built-in Tools

| Tool | Description |
|------|-------------|
| `web_search` | Search the web and return summarized results |
| `file_read` | Read file contents from the workspace |
| `file_write` | Write or create files in the workspace |
| `file_list` | List files and directories in the workspace |
| `shell` | Execute shell commands in a sandboxed environment |

## Security & Sandbox

Tool execution goes through a single sandbox boundary (`autonoma/executor/sandbox.py`)
that enforces path containment, env scrubbing, POSIX rlimits, output caps, and
per-session rate limits. Every tool call — success, denial, timeout, or error —
is appended as a JSON line to `<session_dir>/audit.log`.

### Defaults

* **Shell is disabled out of the box.** `shell_allowed_binaries` is an empty
  list, which means the `shell` tool returns a "disabled" error until an
  operator explicitly allowlists binaries.
* **Argv mode only.** Tools pass `args: [binary, ...]`; shell-string mode with
  metacharacter parsing is opt-in via `shell_allow_strings: true`.
* **No network egress from subprocess tools.** `allow_network: false` strips
  proxy env vars and blocks known network binaries (`curl`, `wget`, `nc`, ...)
  from the shell allowlist at call time.
* **Secrets never reach children.** API keys, bot tokens, and shell-hook vars
  (`BASH_ENV`, `LD_PRELOAD`, ...) are stripped from subprocess env regardless
  of `env_allowlist`.
* **Path traversal is rejected.** All file paths resolve through
  `path_safety.resolve_within`, which uses `Path.relative_to()` rather than a
  prefix match — `../workspace_evil/secret` can't escape a `workspace/` base.
* **Write extensions are gated.** Binaries, shared libraries, and shell
  scripts land on a denylist (`.exe`, `.so`, `.dll`, `.sh`, ...).

### YAML surface

```yaml
# autonoma.yaml
sandbox:
  timeout: 15.0                 # wall-clock seconds per tool call
  max_output_bytes: 10485760    # combined stdout+stderr cap (bytes)
  max_memory_mb: 256            # RLIMIT_AS (POSIX only)
  max_cpu_seconds: 30           # RLIMIT_CPU (POSIX only)
  max_processes: 64             # RLIMIT_NPROC (POSIX only)
  max_file_size_mb: 50          # per-file write ceiling
  allow_network: false          # subprocess network egress
  env_allowlist: [PATH, HOME, LANG, LC_ALL, TZ, TMPDIR]
  shell_allowed_binaries: []    # e.g. [ls, cat, grep, git] to enable shell
  shell_allow_strings: false    # enables `command:` string mode + metachar check
  write_denied_extensions:      # file_write refuses these suffixes
    [.exe, .bat, .cmd, .ps1, .sh, .bash, .so, .dylib, .dll, .com, .scr, .msi]
  backend: direct               # 'direct' (default) | 'docker' (scaffold — not yet implemented)
  rate_limit_calls: 60          # per-session sliding-window cap
  rate_limit_window: 60.0       # window in seconds
```

### Recommended profiles

* **Read-only research agent** — leave `shell_allowed_binaries` empty. The
  agent keeps `web_search`, `file_read`, `file_list`, and a `file_write` that
  refuses binaries and respects `max_file_size_mb`.
* **Developer agent** — `shell_allowed_binaries: [ls, cat, grep, git, npm]`,
  still `shell_allow_strings: false`. Tool calls look like
  `args: ["git", "status"]`; metacharacters in arguments are literal strings.
* **Power-user shell** — add `shell_allow_strings: true` and include `sh` or
  `bash` in the allowlist. This is the only path to pipes/redirects and is
  only appropriate for fully trusted deployments.

### Platform notes

* **Linux/macOS**: memory, CPU, and process caps are enforced via
  `resource.setrlimit` in a subprocess `preexec_fn`.
* **Windows**: the `resource` module is absent — rlimits become advisory.
  Wall-clock timeout and output caps still apply; the sandbox logs a
  one-time warning on startup. For production on Windows, run Autonoma
  inside WSL2 or a Linux container.
* **Docker backend**: scaffolded but not implemented. Selecting
  `backend: docker` raises a clear startup error. For container isolation
  today, run the Autonoma process itself inside a container.

### Audit log

Every tool call appends a JSONL record:

```json
{"ts": "2026-04-24T10:12:03.412+00:00", "session_id": "s_abc", "tool": "shell",
 "tool_use_id": "toolu_01...", "input_hash": "9f2a...", "status": "ok",
 "elapsed_ms": 42, "error": null}
```

`input_hash` is a sha256-16 of the canonicalized input — enough to
correlate replays without storing argument content.

## Tech Stack

| Category | Technology |
|----------|-----------|
| **Backend** | Python 3.11+, asyncio, SQLite + FTS5, WebSockets |
| **Frontend** | React 19, TypeScript, Vite, Tailwind CSS |
| **LLM Providers** | Anthropic Claude, OpenRouter (100+ models) |
| **Channels** | python-telegram-bot, whatsapp-web.js, Discord raw gateway, IMAP/SMTP |
| **Memory** | BM25 ranked retrieval, importance decay, Jaccard dedup |

## Contributing

Contributions are welcome! Here's how:

1. **Fork** the repository
2. **Create** a feature branch (`git checkout -b feature/your-feature`)
3. **Commit** your changes (`git commit -m "Add your feature"`)
4. **Push** to the branch (`git push origin feature/your-feature`)
5. **Open** a Pull Request

## License

This project is licensed under the **MIT License** — see the [LICENSE](LICENSE) file for details.

---

<p align="center">
  <sub>Built by <a href="https://github.com/MuhammadUsmanGM">Muhammad Usman</a></sub>
</p>
