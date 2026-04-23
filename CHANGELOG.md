# Changelog

All notable changes to Autonoma will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
