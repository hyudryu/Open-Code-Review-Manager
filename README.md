# OpenCodeReview Manager

A local-first web control plane for [Alibaba OpenCodeReview](https://github.com/alibaba/open-code-review) (`ocr`). It manages projects, review profiles, a durable review queue, live job progress, structured findings, usage analytics, and integrations (MCP server and signed webhooks) from one local app. Your code and credentials stay local except for requests to the LLM endpoint you configure.

- **Backend**: Python 3.12, FastAPI, SQLAlchemy 2 (async, SQLite WAL), Alembic
- **Frontend**: React 18, TypeScript strict, Vite, custom design system
- **Engine**: the `ocr` CLI runs reviews in isolated worktrees

## Features

- **Project management**: register git repositories, browse branches, and discover repositories by scanning folders
- **Review queue**: durable, priority-ordered, concurrency-limited jobs with drag-and-drop reordering
- **Live progress**: SSE-streamed logs, file progress, elapsed time, adaptive ETA, and input/output token consumption
- **Structured findings**: color-coded HIGH/MEDIUM/LOW findings with code snippets, reasoning, and triage states
- **Usage analytics**: token histograms, input/output/cache breakdowns, per-model usage bars, and time range filters
- **Provider management**: configure LLM endpoints, discover models, and test connections
- **Review profiles**: reusable provider, model, concurrency, and OCR presets
- **Repository scans**: review supported files at the current commit without choosing a range or pull request
- **Review recovery**: retry a review from scratch or resume an eligible OCR session
- **GitHub review requests**: switch between GitHub CLI keychain accounts and immediately refresh GitHub data
- **Field guidance**: Profile and Settings fields have brief explanations available by hover and keyboard focus
- **MCP server**: lets AI agents submit and monitor code reviews programmatically
- **Webhooks**: signed event delivery for CI/CD integration
- **Stale job recovery**: a watchdog reaper detects and cleans up stuck jobs

## Install

Prerequisites: **Python 3.12+**, **Node.js 20+**, **Git**, and the review engine:

```bash
npm i -g @alibaba-group/open-code-review
```

The app runs without `ocr` installed, but OCR-dependent actions show an "OCR not detected" state with install instructions until it is available.

## Quickstart (production - one command)

```bash
# Windows (PowerShell)
powershell -ExecutionPolicy Bypass -File scripts/start.ps1

# macOS / Linux (and Git Bash on Windows)
scripts/start.sh
```

The script creates the virtualenv and installs dependencies on first run, builds the frontend when needed, then starts the app. Database migrations, the queue worker, the webhook worker, and the MCP server all start with it.

Open **http://127.0.0.1:8372**. The same process serves the UI, REST API (`/api/v1`), and MCP endpoint (`/mcp`).

To use another port for a single launch:

```bash
powershell -ExecutionPolicy Bypass -File scripts/start.ps1 -Port 9000
scripts/start.sh --port 9000
```

### Root launchers

The repository root includes convenience launchers for the same startup commands:

| File | Platform | Purpose |
| --- | --- | --- |
| `start.bat` | Windows | Runs the production startup flow through PowerShell. Supports `--build` and `--port`. |
| `start.sh` | macOS, Linux, or Git Bash | Runs the production startup flow through the POSIX shell script. Supports `--build` and `--port`. |
| `start-network.bat` | Windows | Starts a separate LAN-accessible instance on port `8373` by default. See [LAN access](#lan-access-windows) below. |

Examples from the repository root:

```bat
start.bat --build --port 9000
```

```bash
./start.sh --build --port 9000
```

### MCP agent use cases

The MCP server lets an AI agent manage reviews asynchronously through the same
queue and results used by the web UI. After connecting the agent to
`http://127.0.0.1:8372/mcp`, you can ask it to:

- **Queue a pull request:** “Queue this pull request for a code review and
  check back after the ETA for the comments.” The agent registers or finds the
  project, submits the PR review, saves the returned `job_id`, and polls with
  `ocr_get_job` after the suggested `poll_interval_seconds` or uses
  `ocr_get_job_results` to wait for completion.
- **Review current work:** “Review my uncommitted changes and summarize the
  findings.” The agent submits a `workspace` review and retrieves the results
  with `ocr_get_findings` or `ocr_get_job_results`.
- **Plan the fixes:** “Turn the findings from this review into an ordered fix
  plan.” The agent can use the `turn_findings_into_fix_plan` MCP prompt after
  retrieving the job’s findings.

See [docs/MCP.md](docs/MCP.md) for the complete tool list, client setup, and
request details.

Configuration is optional; copy [.env.example](.env.example) to `.env` to override ports, paths, or executables. Provider credentials are entered in the UI and stored in the OS keyring, never in the database, logs, or exports.

### GitHub pull request access

For private GitHub repositories, install and sign in to the [GitHub CLI](https://cli.github.com/) before selecting a pull-request review:

```bash
gh auth login
```

The New Review pull-request picker shows the active `github.com` account and other accounts saved in the GitHub CLI keychain. Select another account to switch immediately; the app fetches branches and reloads open pull requests with that account. An explicitly configured `OCR_CC_GITHUB_TOKEN` takes precedence over the active GitHub CLI account. Tokens are used only in memory for GitHub API requests and are never shown, stored, or logged by the app.

### LAN access (Windows)

To let trusted devices on your local network reach the app, use the network launcher:

```bat
start-network.bat
start-network.bat --port 9000 --build
```

It binds to all interfaces on port `8373` by default and uses the separate `network-data/` directory so it can run beside the local instance. It also permits cross-origin requests; use it only on a trusted network.

## Development

```bash
# Windows (PowerShell)
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1

# macOS / Linux / Git Bash
scripts/dev.sh
```

Starts the backend with `uvicorn --reload` on :8372 and the Vite dev server on :5173 (proxying `/api` and `/mcp`). Tests:

```bash
# backend
backend/.venv/Scripts/python.exe -m pytest backend/tests -q   # .venv/bin/python on POSIX

# frontend
cd frontend && npm run build && npm test
```

## Project layout

```text
backend/    FastAPI app: core (config/secrets/security), db (models +
            Alembic), git service, OCR adapter, queue engine (with stale-job
            reaper), services, REST API + SSE, webhooks, MCP server
frontend/   React SPA: design system, app shell, all screens (Overview,
            Projects, Queue, Reviews, Usage, Providers, Profiles, Settings)
scripts/    dev.sh/.ps1 (dev servers) and start.sh/.ps1 (one-command production)
docs/       SPEC.md (authoritative spec), ARCHITECTURE.md, API.md, MCP.md,
            WEBHOOKS.md, VERIFICATION.md
```

## Documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): module map, data flow, isolation, and security model
- [docs/API.md](docs/API.md): REST routes with request/response sketches
- [docs/MCP.md](docs/MCP.md): MCP tools, resources, prompts, and client configs
- [docs/WEBHOOKS.md](docs/WEBHOOKS.md): payload reference, signing, and verification examples
- [docs/VERIFICATION.md](docs/VERIFICATION.md): acceptance criteria to test mapping

## License

MIT - see [LICENSE](LICENSE).
