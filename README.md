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
    <img src="https://img.shields.io/badge/PRs-Welcome-brightgreen?style=flat-square" alt="PRs Welcome">
  </p>
</p>

---

Autonoma is a modular AI agent that operates as a **digital full-time employee (FTE)**. It connects to your communication channels, remembers context across conversations, executes tasks with built-in tools, and exposes a real-time dashboard for monitoring — all from a single Python process.

## Features

### Multi-Channel Communication
Connect once, reach everywhere. Autonoma natively supports **Telegram**, **Discord**, **WhatsApp** (QR scan via whatsapp-web.js), **Gmail**, a **REST API**, and an interactive **CLI**. Channels auto-enable when you set their credentials in `.env`.

### Intelligent Memory
SQLite + FTS5 powered memory with **BM25 ranked retrieval**. Memories are scored by relevance, importance, and recency. Automatic deduplication, importance decay, and consolidation keep the context window clean. The LLM stores and forgets memories via inline tags (`[REMEMBER:]`, `[FACT:]`, `[PREFERENCE:]`, `[FORGET:]`).

### Web Dashboard
A React + Tailwind dashboard with an **amber glow dark theme**. Includes an overview with live stats, a chat interface to talk to the agent, a memory explorer with search/filter/delete, and a session browser to replay past conversations.

### Tool Execution
Sandboxed execution environment with built-in tools for file operations, shell commands, and web search. The agent autonomously decides when to use tools and chains them for multi-step workflows.

### Flexible LLM Backend
Swap between **Anthropic Claude** and **OpenRouter** (access to 100+ models) by changing a single environment variable. No code changes needed.

### Personality System
Agent behavior is defined in `SOUL.md` — a human-readable personality file that controls communication style, proactivity level, and domain expertise. Edit it to make the agent yours.

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

```bash
# Clone the repository
git clone https://github.com/MuhammadUsmanGM/digital-fte.git
cd digital-fte

# Configure environment
cp .env.example .env
# Edit .env — add your API key (OPENROUTER_API_KEY or ANTHROPIC_API_KEY)

# Install Python dependencies
pip install -e .

# Run the agent
python -m autonoma
```

### Dashboard

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
