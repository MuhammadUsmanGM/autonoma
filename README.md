<p align="center">
  <h1 align="center">Autonoma</h1>
  <p align="center">
    <strong>A personal AI assistant that runs on your own machine.</strong>
  </p>
  <p align="center">
    <img src="https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python">
    <img src="https://img.shields.io/badge/License-MIT-22c55e?style=flat-square" alt="License">
    <img src="https://img.shields.io/badge/React-19-61DAFB?style=flat-square&logo=react&logoColor=black" alt="React">
    <img src="https://img.shields.io/badge/TypeScript-5.0-3178C6?style=flat-square&logo=typescript&logoColor=white" alt="TypeScript">
    <img src="https://img.shields.io/badge/SQLite-FTS5-003B57?style=flat-square&logo=sqlite&logoColor=white" alt="SQLite">
    <img src="https://img.shields.io/npm/v/autonoma-ai?style=flat-square&color=cb3837&logo=npm" alt="npm version">
    <img src="https://img.shields.io/npm/dm/autonoma-ai?style=flat-square&color=cb3837&logo=npm" alt="npm downloads">
    <img src="https://img.shields.io/badge/PRs-Welcome-brightgreen?style=flat-square" alt="PRs Welcome">
  </p>
</p>

---

Talk to it on **Telegram, Discord, WhatsApp or Gmail**. It remembers what you
told it before, searches the web, reads and writes files, and connects to your
calendar, OneDrive and GitHub. You can watch everything it does in a terminal
panel or a web dashboard.

It all runs as a single process on your own computer — no cloud account, no
subscription.

## Install

You need **Node.js 18+** and **Python 3.11+**.

```bash
npm install -g --allow-scripts=autonoma-ai autonoma-ai
autonoma
```

The first launch opens a short setup wizard: pick a provider, paste your API
key, choose a model. It saves all of that into a `.env` file for you.

Already know your key? Skip the wizard:

```bash
export OPENROUTER_API_KEY=sk-or-...
autonoma
```

<details>
<summary>Running from source instead</summary>

```bash
git clone https://github.com/MuhammadUsmanGM/autonoma.git
cd autonoma
cp .env.example .env    # then put your API key in it
pip install -e .
python -m autonoma
```
</details>

<details>
<summary>Python not found?</summary>

Install it from [python.org](https://www.python.org/downloads/), then:

```bash
npm rebuild -g --allow-scripts=autonoma-ai autonoma-ai
```

If npm skipped the setup scripts, just running `autonoma` will finish the
Python setup for you.
</details>

Supported providers: **OpenRouter, Anthropic, Google Gemini, OpenAI, Groq,
Mistral.**

## The terminal panel

`autonoma` opens a small control panel. Arrow keys to move, **Enter** to
select, **Esc** to go back.

| | |
|---|---|
| **Live logs** | What the agent is doing, right now |
| **Check status** | Provider, channels, memory stats, dashboard link |
| **Manage channels** | Turn channels on/off, enter credentials, reconnect |
| **Manage connectors** | Sign in and out of Google, Microsoft and GitHub |
| **Open web dashboard** | Opens the browser UI |
| **Restart** / **Quit** | Restart the agent, or exit |

## Connect a channel

Set these in `.env`, or do it from the terminal panel above.

| Channel | Variables | Notes |
|---------|-----------|-------|
| **Telegram** | `TELEGRAM_BOT_TOKEN` | Make a bot with [@BotFather](https://t.me/BotFather). |
| **Discord** | `DISCORD_BOT_TOKEN` | Enable the `MESSAGE_CONTENT` intent in the Discord developer portal. |
| **WhatsApp** | `WHATSAPP_BRIDGE_URL` | Scans a QR code on first launch. The sidecar starts for you. |
| **Gmail** | `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD` | Use an [App Password](https://support.google.com/accounts/answer/185833), not your normal password. |
| **REST API** | `AUTONOMA_REST_API_TOKEN` | Optional. `POST /api/chat` |
| **CLI** | — | Always on. |

## Settings

Settings are read in this order: **environment variables → `.env` →
`autonoma.yaml` → built-in defaults.**

```yaml
# autonoma.yaml
name: Autonoma
gateway:
  host: 127.0.0.1
  port: 8765        # WebSocket
  http_port: 8766   # REST API + dashboard
llm:
  provider: openrouter   # or anthropic, google, openai, groq, mistral
  model: nvidia/llama-3.1-nemotron-nano-8b-v1:free
```

| Variable | What it does |
|----------|--------------|
| `AUTONOMA_LLM_PROVIDER` | Which provider to use |
| `OPENROUTER_API_KEY` / `ANTHROPIC_API_KEY` | Your API key |
| `AUTONOMA_LLM_MODEL` | Override the model |
| `AUTONOMA_LOG_LEVEL` | `debug`, `info`, `warning`, `error` |

## Web dashboard

Pre-built and shipped with the package — it starts automatically at
<http://127.0.0.1:8766>. Nothing to set up.

Working on the dashboard itself?

```bash
cd dashboard
npm install
npm run dev    # http://localhost:5173
```

## How it's put together

```
   Telegram · Discord · WhatsApp · Gmail · REST · CLI
                         │
                    ┌────▼────┐
                    │ Gateway │  routes and authenticates
                    └────┬────┘
                         │
                    ┌────▼────┐          ┌──────────────┐
                    │ Cortex  │◄────────►│ Memory       │
                    │ thinks  │          │ SQLite, FTS5 │
                    └────┬────┘          └──────────────┘
                         │
                    ┌────▼─────┐
                    │ Executor │  runs tools in a sandbox
                    └──────────┘
```

```
autonoma/
├── cortex/           # the agent: reasoning loop, context, sessions
├── gateway/          # channel adapters, HTTP server, routing, auth
├── executor/         # sandboxed tool running
├── memory/           # SQLite + FTS5 storage and search
├── models/           # one interface for every LLM provider
├── connectors/       # Google, Microsoft, GitHub OAuth + tools
├── skills/           # tool registry
├── tui.py            # the terminal panel
├── splash.py         # the AUTONOMA logo
└── main.py           # start-up and wiring

dashboard/            # React web dashboard
whatsapp-bridge/      # Node sidecar that talks to WhatsApp Web
workspace/            # the agent's files: identity, memory, output
tests/                # test suite
```

## What it can do

| Tool | Does |
|------|------|
| `web_search` | Searches the web and summarises the results |
| `file_read` / `file_write` / `file_list` | Works with files in `workspace/` |
| `shell` | Runs commands — **off by default**, see below |

**Connectors** add more, and only work while you're signed in: Google
Calendar (list/create events, find a free slot), Google Contacts (search and
resolve people), Google Meet (links and transcripts), OneDrive (files), and
GitHub (search, read and comment on issues and PRs).
Sign in from the terminal panel or the dashboard's **Connectors** page.

## Safety

Tool calls go through one sandbox, and the defaults are deliberately
restrictive:

- **Shell is off until you switch it on** — nothing runs until you allowlist
  specific commands (e.g. `ls`, `git`).
- **Secrets never reach child processes** — API keys and tokens are stripped
  from the environment first.
- **Files can't escape `workspace/`** — path traversal is rejected outright.
- **No network access from spawned processes** by default.
- **Everything is logged** — each tool call is appended to
  `<session>/audit.log`.

To loosen any of this, set keys under `sandbox:` in `autonoma.yaml`; the full
list of options and what they mean is in
[`autonoma/executor/sandbox.py`](autonoma/executor/sandbox.py) (`SandboxConfig`).

Worth knowing: on Windows the memory/CPU limits are advisory only — for a
real deployment use WSL2 or a container.

## Monitoring

Always on, no setup:

| | |
|---|---|
| `GET /healthz` | 200 while the process is alive |
| `GET /readyz` | 200 once it's accepting traffic, 503 while starting |
| `GET /metrics` | Prometheus counters — agent runs, LLM tokens and cost, tool latency, channel status |

Set `AUTONOMA_LOG_FORMAT=json` for one JSON object per log line, and
`AUTONOMA_METRICS_ENABLED=false` to turn `/metrics` off. Tracing to
Jaeger/Honeycomb/etc. is available with `pip install autonoma[observability]`.

## Development

```bash
pip install -e .
pip install pytest
pytest tests/
```

Tests live in `tests/` as `*_test.py`.

| | |
|---|---|
| **Backend** | Python 3.11+, asyncio, SQLite + FTS5 |
| **Terminal UI** | Textual, Rich |
| **Dashboard** | React 19, TypeScript, Vite, Tailwind |
| **Channels** | python-telegram-bot, whatsapp-web.js, Discord, IMAP/SMTP |

## Contributing

Fork it, branch it (`git checkout -b feature/your-thing`), commit, push, open a
PR. Issues and PRs are welcome.

## License

MIT — see [LICENSE](LICENSE).

---

<p align="center">
  <sub>Built by <a href="https://github.com/MuhammadUsmanGM">Muhammad Usman</a></sub>
</p>
