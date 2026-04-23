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
Secure execution environment with built-in tools for web search, file operations, and shell command chaining in isolated workspaces.

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

## Built-in Tools

| Tool | Description |
|------|-------------|
| `web_search` | Search the web and return summarized results |
| `file_read` | Read file contents from the workspace |
| `file_write` | Write or create files in the workspace |
| `file_list` | List files and directories in the workspace |
| `shell` | Execute shell commands in a sandboxed environment |

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
