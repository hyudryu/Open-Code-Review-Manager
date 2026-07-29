# OpenCodeReview Manager

A local-first web control plane for [Alibaba OpenCodeReview](https://github.com/alibaba/open-code-review) (`ocr`).
It manages projects, review profiles, a durable review queue, live job progress,
structured findings, usage analytics, and integrations (MCP server, signed
webhooks) — all from one local app that never sends your code or credentials
anywhere except the LLM endpoint you configure.

- **Backend** — Python 3.12, FastAPI, SQLAlchemy 2 (async, SQLite WAL), Alembic
- **Frontend** — React 18, TypeScript strict, Vite, custom design system
- **Engine** — the `ocr` CLI runs your reviews in isolated worktrees

## Features

- **Project management** — register git repos, browse branches, start reviews
- **Review queue** — durable, priority-ordered, concurrency-limited, with drag-and-drop reordering
- **Live progress** — SSE-streamed logs and file-by-file progress for running reviews
- **Structured findings** — color-coded by severity (HIGH/MEDIUM/LOW), with code snippets, reasoning, and triage states
- **Usage analytics** — token consumption histograms, pie chart breakdowns (input/output/cache), per-model usage bars, with time range filters
- **Provider management** — configure LLM endpoints, discover models, test connections
- **Review profiles** — reusable presets for provider, model, concurrency, and OCR settings
- **MCP server** — lets AI agents submit and monitor code reviews programmatically
- **Webhooks** — signed event delivery for CI/CD integration
- **Stale job recovery** — runtime watchdog reaper detects and cleans up stuck jobs

## Install

Prerequisites: **Python 3.12+**, **Node.js 20+**, **Git**, and the review engine:

```bash
npm i -g @alibaba-group/open-code-review
```

The app runs fine without `ocr` installed — OCR-dependent actions show a clear
"OCR not detected" state with install instructions until it is.

## Quickstart (production — one command)

```bash
# Windows (PowerShell)
powershell -ExecutionPolicy Bypass -File scripts/start.ps1

# macOS / Linux (and Git Bash on Windows)
scripts/start.sh
```

The script creates the virtualenv and installs dependencies on first run,
builds the frontend when needed, then starts the app. Database migrations,
the queue worker, the webhook worker, and the MCP server all start with it.

Open **http://127.0.0.1:8372** — the same process serves the UI, the REST API
(`/api/v1`), and the MCP endpoint (`/mcp`).

To use another port for a single launch:

```bash
powershell -ExecutionPolicy Bypass -File scripts/start.ps1 -Port 9000
scripts/start.sh --port 9000
```

Configuration is optional; copy [.env.example](.env.example) to `.env` to
override ports, paths, or executables. Provider credentials are entered in the
UI and stored in the OS keyring — never in the database, logs, or exports.

## Development

```bash
# Windows (PowerShell)
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1

# macOS / Linux / Git Bash
scripts/dev.sh
```

Starts the backend with `uvicorn --reload` on :8372 and the Vite dev server on
:5173 (proxying `/api` and `/mcp`). Tests:

```bash
# backend (252 tests)
backend/.venv/Scripts/python.exe -m pytest backend/tests -q   # .venv/bin/python on POSIX

# frontend (typecheck + 52 vitest)
cd frontend && npm run build && npm test
```

## Project layout

```text
backend/    FastAPI app: core (config/secrets/security), db (models +
            Alembic), git service, OCR adapter, queue engine (with stale-job
            reaper), services, REST API + SSE, webhooks, MCP server
frontend/   React SPA: design system, app shell, all screens (Overview,
            Projects, Queue, Reviews, Usage, Providers, Profiles, Settings)
scripts/    dev.sh/.ps1 (dev servers) · start.sh/.ps1 (one-command production)
docs/       SPEC.md (authoritative spec), ARCHITECTURE.md, API.md, MCP.md,
            WEBHOOKS.md, VERIFICATION.md
```

## Documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — module map, data flow, isolation & security model
- [docs/API.md](docs/API.md) — every REST route with request/response sketches
- [docs/MCP.md](docs/MCP.md) — MCP tools/resources/prompts + client configs
- [docs/WEBHOOKS.md](docs/WEBHOOKS.md) — payload reference, signing, verification examples
- [docs/VERIFICATION.md](docs/VERIFICATION.md) — acceptance criteria → tests mapping

## License

MIT — see [LICENSE](LICENSE).
