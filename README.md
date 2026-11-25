<p align="center"><picture><source media="(prefers-color-scheme: dark)" srcset="assets/ancilla_icon_dark.svg" /><img src="assets/ancilla_icon.svg" alt="" height="80" align="absmiddle" /></picture><picture><source media="(prefers-color-scheme: dark)" srcset="assets/ancilla_logo_dark.svg" /><img src="assets/ancilla_logo.svg" alt="Ancilla" height="88" align="absmiddle" /></picture></p>

# Ancilla

A resident personal AI agent runtime and homelab operations assistant powered by local or OpenAI-compatible LLMs ([Ollama](https://ollama.com/), `llama.cpp`, etc.).

Ancilla runs as a persistent background Core daemon with CLI, Discord, Slack, WebUI, HTTP, WebSocket, and MCP interfaces—combining scoped persistent memory, autonomous heartbeats, policy-gated tool execution, and homelab monitoring & self-healing.

## Features

- **Flexible LLM Backends**: Supports [Ollama](https://ollama.com/) (default) and OpenAI-compatible APIs (`LLM_PROVIDER=openai`), with independent chat/embedding provider configuration and both JSON-schema constrained (`gbnf`) and native (`native`) tool-calling modes.
- **Multi-Channel Interfaces**:
  - Interactive CLI (`ancilla`) attached to the background Core daemon
  - Owner-restricted Discord and Slack (Socket Mode) bots
  - Built-in React/Vite WebUI (`/ui/`), PWA Companion Mode (`/companion/`), and REST/SSE Client API (`/api/v1`)
  - Edge WebSocket server (`ws://127.0.0.1:8766`) and Companion Voice APIs (`/api/v1/voice/stt`, `/api/v1/voice/tts`) using optional `faster-whisper-server` (STT) and `Coeiroink` (TTS)
  - Second-precision timers (`ancilla timer` / `/api/v1/timers`) with real-time SSE alerts and notification event broadcast
  - MCP support as both client (`mcp.json`, including bundled `prometheus` and `wazuh` plugins) and server (`ancilla mcp` stdio & `/mcp` Streamable HTTP)
- **Persistent Memory & Customization**: SQLite-backed tasks, reminders, scoped memories, procedures, and artifacts; rolling history compression and daily conversation summarization; optional ChromaDB vector RAG; customizable prompts (`CHARACTER.md`, `AGENT.md`, `USER.md`), runtime personas (`general`, `researcher`, `developer`, `operator`), and `skills/`.
- **Autonomous Loops & Policy Gate**: Scheduled task/reminder execution (Fast Heartbeat), daily summarization (Slow Heartbeat), Idle Reflection, proactive rules, fail-closed capability policies, approval workflows (via CLI, WebUI, Discord, or Slack), and optional Docker `bash` sandboxing.
- **HomeLab Monitoring & Self-Healing**: Inventory-driven (`data/homelab.yaml`) monitoring via `ancilla node` agents (Linux `systemd` / Windows Task Scheduler) and Core health checks, confirmed state-change events, incident deduplication with automated LLM diagnosis, and conditional self-healing with a global `autoheal` kill switch.

## Requirements

- Python 3.11+
- `git`
- LLM backend: [Ollama](https://ollama.com/) or an OpenAI-compatible API
- Optional: Node.js 22+ and `npm` (to build the WebUI and Companion UI), Docker (for containerized Core or `ANCILLA_SANDBOX=docker`)

## Installation

### Quick Install

```bash
# Linux / macOS
curl -fsSL https://raw.githubusercontent.com/K16858/ancilla-bot/main/scripts/install.sh | bash
```

```powershell
# Windows (PowerShell)
irm https://raw.githubusercontent.com/K16858/ancilla-bot/main/scripts/install.ps1 | iex
```

Initialize and start Ancilla:

```bash
ancilla install core
ancilla setup
ancilla start
ancilla
```

### From Source (Development)

```bash
git clone https://github.com/K16858/ancilla-bot.git
cd ancilla-bot
pip install -e ".[dev]"

ancilla install core
ancilla setup
ancilla start
ancilla
```

## Usage

### Core & Chat Lifecycle

```bash
ancilla start                 # Start Core daemon in the background
ancilla                       # Open the interactive CLI client (exit / quit / :q to quit)
ancilla start --cli           # Ensure Core is running and open CLI (Core keeps running on exit)
ancilla start all             # Start Core plus configured adapters (Discord / Slack)
ancilla start --foreground    # Run Core in the foreground (Docker / debugging)
ancilla status                # Check status of Core and adapters
ancilla logs core --follow    # Tail logs (core / discord / slack)
ancilla restart               # Restart managed processes
ancilla stop                  # Stop managed processes
ancilla setup                 # Interactive configuration wizard (provider, keys, notify, api, etc.)
ancilla doctor                # Run environment and connectivity diagnostics
ancilla update --check        # Check for updates
ancilla update                # Pull updates and reinstall (run `ancilla stop` first)
```

### WebUI, Companion & Client API

Build the WebUI and Companion PWA bundles, and issue API tokens:

```bash
cd webui && npm ci && npm run build
cd companion && npm ci && npm run build
ancilla api token create webui --role read         # WebUI monitoring (use --role operate for approvals)
ancilla api token create companion --role operate  # Voice Companion Mode & timer control
```

Open `http://127.0.0.1:8765/ui/` (WebUI) or `http://127.0.0.1:8765/companion/` (Companion Mode) in your browser and sign in with the generated token. For tablet microphone access (`getUserMedia`) over LAN, serve behind an HTTPS reverse proxy (e.g. Caddy / Nginx / Tailscale Serve).

### HomeLab Monitoring & Self-Healing

Copy `homelab.yaml.example` to `data/homelab.yaml`, edit your hosts/services, and verify with `ancilla homelab check`. Host agents can be registered on Linux (`systemd`) or Windows (Task Scheduler) via `ancilla install node`.

See [`docs/homelab.md`](docs/homelab.md) for the full setup, node installation, approval, and self-healing guide.

### MCP Integration

- **As an MCP Client**: Copy `.mcp.json.example` to `mcp.json` (or set `ANCILLA_MCP_CONFIG`) to attach external stdio or Streamable HTTP MCP servers, or the bundled read-only plugins:
  - `ancilla plugin prometheus`
  - `ancilla plugin wazuh`
- **As an MCP Server**: Ancilla exposes `ask_ancilla` over stdio (`ancilla mcp`) and Streamable HTTP (`http://127.0.0.1:8767/mcp`) while Core is running.

### Additional CLI Commands

```bash
ancilla persona list                  # List personas (* marks active)
ancilla persona use <name>            # Switch active persona (general / researcher / developer / operator)
ancilla runs                          # List recent agent runs
ancilla trace <run_id>                # Inspect step-by-step execution trace
ancilla resume <run_id>               # Resume an agent run
ancilla approve <run_id>              # Approve a pending tool call
ancilla reject <run_id>               # Reject a pending tool call
ancilla timer list                    # List active/firing second-precision timers
ancilla timer set 180 --label "Tea"   # Start a 3-minute countdown timer
ancilla timer stop [timer_id]         # Stop firing timer alarm(s)
ancilla timer cancel <timer_id>       # Cancel a running timer
ancilla batch summarize               # Summarize overflow conversation history into long-term memory
```

## Docker Compose (Optional)

```bash
cp .env.docker.example .env
# Edit .env and set OLLAMA_MODEL (required)
docker compose up -d --build
```

The container builds both the WebUI and Companion bundles into the image, runs Core via `ancilla run --no-repl`, mounts `./workspace` and `./data`, and connects to Ollama on the host via `http://host.docker.internal:11434`. Ports `8765`, `8766`, and `8767` are bound to `127.0.0.1` by default.

## Configuration & Ports

- Full environment reference: [`.env.example`](.env.example) (or run `ancilla setup show --all`).
- Prompts & workspace files: `ancilla install core` initializes `.env`, `data/prompts/CHARACTER.md` (from `data/prompts/CHARACTER.md.example`), and the runtime workspace (`data/home/workspace/`, seeded from `workspace/` with `AGENT.md`, `AGENT.native.md`, `USER.md`, and `NOTE.md`). Note that the default prompt templates instruct Ancilla to respond in Japanese—edit `CHARACTER.md` and `AGENT.md` / `AGENT.native.md` to change the language or style.
- Default ports (all bound to `127.0.0.1` unless overridden):
  - `8765` — HTTP API (`/health`, `/chat`, `/cancel`, `/api/v1/...`), WebUI (`/ui/`), and Companion (`/companion/`)
  - `8766` — Edge WebSocket server
  - `8767` — MCP Streamable HTTP server (`/mcp`)
  - `8768` — HomeLab Node WebSocket server (supports `wss://` via `ANCILLA_NODE_TLS_CERT` / `ANCILLA_NODE_TLS_KEY`)
- Binding unauthenticated or plaintext endpoints (`WS`, `MCP HTTP`, or non-TLS `NODE`) to non-loopback interfaces requires `ANCILLA_INSECURE_BIND=1`. (`/api/v1/...` and non-loopback HTTP API requests are token-gated via `ancilla api token`).

## Development & Tests

```bash
# Run Python test suite
pip install -e ".[dev]"
pytest

# Build WebUI & Companion
cd webui && npm ci && npm run build
cd ../companion && npm ci && npm run build
```

## Documentation

- [`.env.example`](.env.example) — Environment variable reference
- [`homelab.yaml.example`](homelab.yaml.example) — Sample HomeLab inventory
- [`.mcp.json.example`](.mcp.json.example) — Sample MCP server & plugin configuration
- [`docs/homelab.md`](docs/homelab.md) — HomeLab monitoring, nodes, and self-healing guide _(Japanese)_
- [`docs/client_api.md`](docs/client_api.md) — Client HTTP/SSE API (`/api/v1`) and WebUI reference _(Japanese)_
- [`docs/ws_client_api.md`](docs/ws_client_api.md) — Edge WebSocket protocol specification _(Japanese)_
