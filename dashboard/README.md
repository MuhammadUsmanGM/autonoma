# Autonoma Control Tower

The high-fidelity management suite for the Autonoma AI platform. Built for performance, observability, and deep system audit.

## Architecture & Tech Stack

- **Core**: React 19 + TypeScript 5
- **Styling**: Tailwind CSS 4 + Headless UI
- **Animations**: Framer Motion (HUD-grade transitions)
- **Icons**: Lucide React
- **Theme**: Context-aware CSS Variable architecture with **Amber-Dark** and **Slate-Light** modes.

## Primary Modules

### 1. Operations Overview
Real-time telemetry pulses and system-wide stats (uptime, channel count, memory metrics).

### 2. Neural Registry (Memory)
Deep inspection of the agent's long-term memory. Supports semantic search, type-filtering, and **bulk maintenance** for stale/decaying nodes.

### 3. Execution Telemetry (Traces)
A Gantt-style timeline visualization of every agent reasoning loop. Track performance bottlenecks across tool-calls and multi-step pipeline stages.

### 4. Session Audit Log 
Historical interaction replay with advanced filtering (by channel, outcome, or keyword). Features fully responsive conversation logs.

### 5. SOUL Evolution Editor
Live identity management. Modify the agent's primary personality file (`SOUL.md`) with a built-in **diff view** to compare draft changes against the live configuration.

### 6. Command Center (Settings)
Centralized configuration for LLM providers, active pathways, and cognitive parameters. Features bespoke theme-matched dropdowns and interaction surfaces.

## Getting Started

```bash
# Install dependencies
npm install

# Launch development local server
npm run dev

# Build production bundle
npm run build
```

## Theme Stabilization
The dashboard utilizes a semantic variable system (`--bg`, `--text`, `--accent-dim`, etc.) defined in `index.css`. To ensure visual consistency, avoid hardcoding `white` or `black` in new components; instead, use the `var()` tokens to enable automatic inversion in light mode.
