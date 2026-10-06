# Changelog

All notable changes to Autonoma will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **DeepSeek provider.** A seventh built-in provider in the setup wizard,
  `.env.example` / `autonoma.yaml` docs and the dashboard Settings page,
  wired through `create_provider` (`https://api.deepseek.com`, OpenAI
  format) and `DEEPSEEK_API_KEY`.
- `textual>=8.0,<9.0` as a runtime dependency, and `tests/tui_test.py`
  driving the real widget tree through Textual's headless pilot (menu
  navigation, logs, status, channels, wizard save, splash variants).

### Changed
- **Model lists refreshed (Oct 2026), newest/best first.** GPT‑6 Astra /
  6.1 Sol / 5.6, Claude Opus 5.5, Sonnet 5.5 and Fable 5.1, Gemini 3.8/3.5,
  Groq's GPT‑OSS and Qwen3.6 lineup, Mistral's current aliases and
  OpenRouter's flagships. Retired suggestions (Gemini 2.0/1.5, GPT‑4o, o3,
  `deepseek-chat`) are gone; users can still type any custom model ID.
  DeepSeek lists the four names its API actually serves — it publishes only
  four — so `test_builtin_providers_offer_more_model_choices` keeps its
  six-model floor for every other provider and expects four there.
- **Key labels read as `Ctrl+C`, not `^c`.** `AutonomaTUI.get_key_display`
  renders modifiers and named keys as words/arrows (`Esc`, `↑`, `Shift+Tab`),
  so the footer and the keys panel drop Textual's caret shorthand.
- **The bottom bar carries real buttons.** Footers show `↑ Up`, `↓ Down` and
  `Enter Select` on every list screen, and `Esc Back` on the wizard, logs,
  channels, connectors and status screens, next to `Ctrl+C Quit` and the
  palette key. (Escape stays a deliberate no-op on the main screen — it is
  the root of the stack.)
- **The keys panel is prominent.** Panel background, accent border and
  brighter key/header colours make it read as a real panel instead of a
  transparent strip.
- **TUI rebuilt on Textual.** The interactive TUI was a hand-rolled loop:
  raw-mode `termios`/`msvcrt` key reading, `atexit` guards to restore the
  terminal, a `_drain_stdin()` that had to swallow orphaned bytes after every
  screen, and Rich `Live(screen=True)` frames repainted on each keypress. It
  flickered, frames stacked in scrollback, and keys often needed pressing
  twice. `autonoma/tui.py` is now a Textual `App` with a real screen stack —
  Textual owns the alt-screen and input decoding, so the raw-mode plumbing,
  the stdin drain, and the manual scroll maths are all gone.
- **Feature parity kept**: live log viewer, status (config / channels /
  memory / proxy health), channel toggle-configure-reconnect with inline
  WhatsApp QR, OAuth connectors, and the three-step setup wizard. Blocking
  work (agent stop/start, HTTP, DB reads) runs behind a modal in a thread, so
  the UI no longer freezes for up to 15s while the agent restarts; long waits
  (OAuth callback, QR poll) are cancellable with Escape.
- **New `autonoma/splash.py`.** Responsive amber block-letter `AUTONOMA` logo,
  built once from a bitmap font with five width/height variants so it steps
  down cleanly on smaller terminals.
- **Fixed `json` NameError in TUI HTTP helpers.** The `_http` request
  helper called `json.loads` but the module never imported `json` at module
  scope, so connector status lookups failed with a swallowed `name 'json' is
  not defined`.
- **One command: `autonoma`.** The console script now always opens the TUI;
  `--start`, `-c/--config` and `--log-level` are gone. Start/stop the agent,
  edit config, watch logs and open the dashboard from inside the TUI.
  `autonoma.main.run()` remains importable for embedders that host the
  agent without a terminal.
- **No more log spam on the terminal.** When the TUI runs the agent the
  root logger gets no stderr stream handler — logs go to the TUI log
  viewer, the workspace log file and the dashboard's Logs page only.

### Fixed
- **`verify_model` now closes a provider that owns its lifecycle.** It only
  ever looked at `provider._client`, so a provider exposing its own
  `aclose`/`close` was left open after the key check. The provider's own
  method is used first, falling back to the underlying HTTP client.
- **`AgentLoop._observe` no longer assumes the trace already has `stages`.**
  A missing key raised `KeyError` instead of recording the stage; it now
  seeds `trace["stages"]` on first use (production always passes a
  pre-built one, so behaviour there is unchanged).
- **The keys panel can be closed from inside it.** The palette's "Keys"
  command only toggled it open; the panel now mounts a Close button that
  calls `action_hide_help_panel`, and the palette still flips to "hide".
- **Maximize no longer leaves a hatched backdrop.** Textual's
  `Screen.-maximized-view` draws `hatch: right $panel` behind the maximized
  widget; the app CSS now keeps the normal flat background.
- **Workspace log file keeps recording after the agent starts.**
  `configure_root_logger` mistook the TUI's `FileHandler` for a console
  handler (it subclasses `StreamHandler`) and stripped it on every agent
  start, so the log file went silent while the agent ran.

## [1.0.4] - 2026-09-26

### Fixed
- **Launcher self-heals without npm install scripts.** npm's install-scripts
  policy can silently block the package `postinstall`, leaving the Python
  `.venv` missing. The old auto-recovery in `bin/autonoma.js` called
  `npm rebuild`, which is subject to the same policy — it exited 0 while
  skipping the setup script, so `autonoma` kept telling users to install
  Python even when Python 3.11+ was present. The launcher now detects the
  missing venv and bootstraps it directly (`python -m venv .venv` +
  `pip install -e .`), independent of npm's allowScripts configuration. The
  recovery help text and `scripts/install.js` bail messages now point to
  `npm rebuild -g --allow-scripts=autonoma-ai autonoma-ai` instead of a
  rebuild that could silently no-op.
- **WhatsApp bridge self-install.** When auto-spawn found
  `whatsapp-bridge/` without `node_modules`, the adapter only logged "run
  `npm install` yourself" and gave up. It now runs the install itself
  (60→300s timeout, output captured), and if `node_modules` is still missing
  afterwards it explains that npm's install-scripts policy likely blocked
  puppeteer's Chromium download, with the exact allow-scripts command to
  fix it.
- **README install instructions** now pass `--allow-scripts=autonoma-ai`
  so the postinstall actually runs on policy-restricted npm setups, and
  mention the launcher's first-run self-setup as a fallback.
- **prepublish secret-file check actually runs.** The banned-path scan in
  `scripts/prepublish-check.js` parsed `npm pack --json` output as an array
  (`data[0].files`), but npm >= 7 returns an object keyed by package name —
  so the scan always inspected zero files and reported "tarball clean"
  unconditionally. It now handles both shapes and fails loudly if the file
  list can't be read, instead of passing a check that never ran.

## [1.0.2] - 2026-05-05

### Added
- **Three new connectors:** GitHub, Google Contacts, Google Meet — all share
  the same OAuth client subsystem as the existing Google Calendar / OneDrive
  connectors, with tokens encrypted at rest in the connector token store.
  - `github_*` tools (search/get issues + PRs, list notifications, comment,
    create issue) for triaging issues and PRs without leaving Autonoma.
  - `contacts_*` tools (search, get, resolve) on top of Google People API.
  - `meet_*` tools (list conferences, get transcript, create link via
    Calendar) — Meet has no standalone create-event endpoint, so Meet link
    creation requires the Google Calendar connector to also be connected.
- **Contact enrichment.** When Google Contacts is connected, inbound senders
  matched in the user's saved contacts are auto-bumped from `stranger` to
  `acquaintance` and their saved name + organisation are copied onto the
  contact row. Higher tiers (colleague / VIP) are never downgraded; manually
  flagged VIPs are never overwritten. Per-contact 24h rate limit on lookups.
- **Meeting action items.** The `meet_get_transcript` tool scans transcripts
  for "action item:", "@user will …", and "Name will …" patterns and writes
  each unique item into the conversation state machine with a 48h follow-up,
  so the proactive followup_scheduler picks them up. Disable with
  `connectors.google_meet.extract_action_items: false`.
- **GitHub identifier kind.** New `github` cross-channel kind on the contact
  identity registry — `@login` mentions in github-context messages are
  extracted into the identity graph (rejected on the GitHub-username grammar)
  and `[LINK_IDENTITY: github=login]` tags are honoured everywhere.

### Configuration
- New `connectors.github`, `connectors.google_contacts`, `connectors.google_meet`
  blocks in `autonoma.yaml`. Google connectors fall back to a shared
  `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` if a per-connector pair isn't
  set. New env-var toggles: `AUTONOMA_GITHUB_ENABLED`,
  `AUTONOMA_GCONTACTS_ENABLED`, `AUTONOMA_GMEET_ENABLED`.

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
