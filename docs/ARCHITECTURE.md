# Architecture

OpenCodeReview Manager is a local-first, single-process application:
one Python process serves the REST API, the SSE event streams, the MCP
endpoint, the built React frontend, and runs the queue + webhook workers
in-process. SQLite (WAL) is the only datastore.

```text
┌────────────────────────────────────────────────────────────────────┐
│ Browser (React SPA, served from FastAPI static mount)              │
│   REST /api/v1 · SSE /api/v1/jobs/{id}/events                      │
└──────────────┬─────────────────────────────────────────────────────┘
               │
┌──────────────▼─────────────────────────────────────────────────────┐
│ FastAPI app (app/main.py)                                          │
│  api/v1/ ── thin routes                                            │
│  mcp/    ── MCP Streamable HTTP at /mcp (thin wrappers)            │
│  services/ ── business logic (shared by REST, MCP, workers)        │
│  queue/  ── QueueService (state machine) + QueueWorker + Runner    │
│  webhooks/ ── WebhookService + delivery worker                     │
│  git/ · ocr/ ── GitService · OCRAdapter (the only integration pts) │
│  db/ ── SQLAlchemy 2 async models + Alembic migrations (SQLite WAL)│
└──────────────┬─────────────────────────────────────────────────────┘
               │ argv arrays only (never a shell)
┌──────────────▼─────────────────────────────────────────────────────┐
│ git (worktrees, refs) · ocr CLI (reviews, sessions) · OS keyring   │
└────────────────────────────────────────────────────────────────────┘
```

## Module map (`backend/app/`)

| Module | Responsibility |
|---|---|
| `core/config.py` | `Settings` (pydantic-settings, `OCR_CC_*` env prefix), data-dir layout, defaults |
| `core/secrets.py` | `SecretStore` abstraction: keyring (WinCred/Keychain/SecretService), `env:` references, in-memory for tests. The DB only ever stores references |
| `core/security.py` | Path normalization/allowlist, ref validation, additional-args parsing, env redaction, CSRF token |
| `core/logging.py` | structlog JSON logging + `redact_text` credential scrubber |
| `db/` | SQLAlchemy 2 async models (SPEC §4 entities), session factory, Alembic runner |
| `git/service.py` | `GitService`: repo validation, folder scan (depth-limited, symlink-safe), `for-each-ref` branch cache, fetch/prune, worktree add/remove/prune, ref→SHA resolution. argv arrays only, `--end-of-options` for refs |
| `ocr/adapter.py` | `OCRAdapter`: binary detection, version + capability probe from `--help`, command generation, per-job HOME/config isolation, env construction (`OCR_LLM_*`), process start/cancel (process-tree kill), JSON result parse, JSONL session tail, `ocr llm test`, preview |
| `queue/` | `QueueService` (durable queue + state machine, SPEC §13), `QueueWorker` (polling loop, concurrency limits, workspace locks), `runner` (job lifecycle: worktree → OCR process → parse → findings), `recovery` (interrupted jobs + orphan worktrees at startup), `bus` (in-process SSE fan-out) |
| `services/` | Business logic shared by REST, MCP, and workers: folders, projects, providers (incl. model discovery + connection test), profiles, jobs (incl. exports), findings, settings, diagnostics |
| `webhooks/` | `WebhookService`: HMAC-SHA256 signing, SSRF guards, retry/backoff, delivery log, replay; delivery worker polls `next_attempt_at` |
| `mcp/` | MCP Streamable HTTP server: tools/resources/prompts (SPEC §17), thin wrappers over `services/` |
| `api/v1/` | All REST routes (SPEC §19) + SSE endpoint with `Last-Event-ID` resume |
| `main.py` | Lifespan: migrations → engine → workers → recovery; MCP mount; SPA static serving |

The frontend (`frontend/src/`) is a React 18 + strict-TS SPA: `api/` (typed
fetch client + TanStack Query hooks), `types/` (API contracts), `layouts/`
(app shell), `pages/` (all SPEC §33 screens), `features/` (complex widgets
like `FindingCard`), `components/ui/` (custom design system), `styles/`
(design tokens, light/dark via `data-theme`).

## Data flow (a review job)

1. **Submit** (REST `POST /jobs` or MCP `ocr_submit_review`) → `JobService`
   resolves the profile/provider/model, resolves refs to SHAs via
   `GitService`, builds the OCR command via `OCRAdapter`, and persists an
   **immutable configuration snapshot** + generated command on the job row.
2. **Queue** — `QueueService` enqueues with priority + manual position;
   per-project/provider/global concurrency and per-project workspace locks
   gate dispatch. Invalid state transitions are rejected.
3. **Run** — the runner creates a detached worktree (range/commit jobs) or
   takes the workspace lock (workspace jobs), writes a per-job HOME with an
   OCR `config.json` (no secrets), spawns `ocr review --format json
   --audience agent` as an argv array, and tails the session JSONL for
   progress events.
4. **Events** — persisted to `job_events` and fanned out on the in-process
   bus; the SSE endpoint replays persisted events from `Last-Event-ID` then
   streams live ones, closing on terminal states.
5. **Result** — stdout JSON is parsed into `Finding` rows (severity/category
   passed through, never invented; `thinking` stored but never returned by
   default), warnings derive `completed_with_warnings`, and terminal-state
   webhooks are dispatched.
6. **Consume** — findings/warnings/logs/session/exports via REST or MCP
   resources; exports and previews pass through the same redactor as logs.

## Isolation model

- **Git** — range/commit jobs run in detached worktrees under
  `<data_dir>/worktrees/<project>/<job>`; the user's repo is never mutated
  (no destructive git commands anywhere). Workspace jobs run on the real
  path under a per-project exclusive lock so uncommitted changes are
  preserved and never raced. Orphan worktrees are pruned at startup.
- **OCR config** — every job gets its own HOME at
  `<data_dir>/jobs/<job>/home` with a job-specific `config.json`; jobs never
  share or mutate a global OCR config, so concurrent jobs can use different
  providers/models without races. LLM settings flow via `OCR_LLM_*`
  environment variables, not config edits.
- **Processes** — OCR runs as a subprocess tree; cancellation kills the
  whole tree (POSIX process groups / Windows job objects), with a grace
  period before SIGKILL.
- **Credentials** — stored only in the OS keyring (or as `env:` references);
  the DB holds opaque references. Redaction is applied to logs, command
  previews, metadata, exports, webhook payloads, and the diagnostics bundle.

## Security model

- **Binding** — defaults to `127.0.0.1`; CORS origins are restricted to the
  app origin.
- **CSRF** — double-submit cookie (`ocrcc_csrf` + `X-OCR-CSRF` header) on
  every state-changing request.
- **Paths** — project/folder paths are normalized, symlink-resolved, and can
  be locked to allowlisted roots (`OCR_CC_PATH_RESTRICTIONS_ENABLED`).
- **Refs/args** — git refs validated and passed after `--end-of-options`;
  expert additional-arguments are parsed into an argv array, shell
  metacharacters are rejected, and control-plane-owned flags are refused.
- **Webhooks** — HTTPS required by default, private-network targets blocked
  unless explicitly allowed, HMAC-SHA256 signatures, bounded response reads.
- **Reasoning** — raw model reasoning (`thinking`) is stored for opt-in
  inspection but excluded from every API response and export unless
  explicitly requested (SPEC §38.15).
- **Errors** — a consistent `{error: {code, message, detail, next_action}}`
  envelope; internal details are redacted before leaving the process.
