# OpenCodeReview Control Center — Implementation Plan

Source of truth: `docs/SPEC.md` (verbatim copy of the owner's spec).
Upstream engine: Alibaba OpenCodeReview CLI (`ocr`), repo `alibaba/open-code-review`,
npm package `@alibaba-group/open-code-review`. The backend must never guess OCR flags;
`OCRAdapter` detects capabilities from the installed binary (`ocr version`, `ocr review --help`)
and degrades gracefully when OCR is absent.

## Architecture

```
frontend/   React 18 + TS strict + Vite + React Router + TanStack Query + Zustand (UI state only)
            + React Hook Form + Zod + Radix primitives + CSS Modules (custom design system)
backend/    Python 3.12 + FastAPI + Pydantic v2 + SQLAlchemy 2 (async) + Alembic + SQLite WAL
            asyncio subprocesses (argv arrays only), SSE for live events, httpx for webhooks
            + model discovery, keyring-backed SecretStore, MCP (Streamable HTTP at /mcp)
patches/    open-code-review planning-control patch set (--plan-mode/--plan-threshold/--max-tokens/--template)
scripts/    dev + one-command production startup (Windows/macOS/Linux)
```

### Backend module map (one responsibility each)

| Module | Responsibility |
|---|---|
| `core/config.py` | App settings, data dir, env overrides |
| `core/secrets.py` | `SecretStore` abstraction: keyring (WinCred/Keychain/SecretService) + env-var refs; DB stores references only |
| `core/security.py` | Path normalization/allowlist, ref validation, redaction, CSRF token, localhost binding |
| `db/` | SQLAlchemy models per SPEC §4, Alembic migrations, WAL mode, short transactions |
| `git/service.py` | `GitService`: repo detection/validation, folder scan (depth-limited, symlink-safe, exclusion list), `for-each-ref` branch cache, fetch/prune, worktree add/remove/prune, ref→SHA resolution. argv arrays only, `--end-of-options` for refs |
| `ocr/adapter.py` | `OCRAdapter`: binary detect/custom path, version + capability probe, command generation, per-job HOME + config.json isolation, env construction (OCR_LLM_*), process start/cancel (process-tree kill, POSIX+Windows), JSON result parse, JSONL session tail → normalized events, `ocr llm test` wrapper, preview (`--preview`) |
| `queue/` | `QueueService`: durable queue, state machine (SPEC §13, rejected invalid transitions), priority + manual_position ordering, per-project/provider/global concurrency, workspace-job lock, pause/resume/reorder/cancel/retry/duplicate/resume-session, startup recovery (interrupted + orphan worktrees) |
| `services/` | Business logic shared by REST + MCP + workers (folders, projects, providers, profiles, jobs, exports, settings, diagnostics) |
| `webhooks/` | `WebhookService`: HMAC-SHA256 signing (ts + "." + raw body), SSRF guards, retry/backoff schedule per SPEC §18, delivery log + replay |
| `mcp/` | MCP Streamable HTTP server at `/mcp`: tools/resources/prompts per SPEC §17, thin wrappers over services |
| `api/v1/` | All REST routes per SPEC §19 + SSE endpoint `GET /api/v1/jobs/{id}/events` with event-ID resume |
| `main.py` | Lifespan: migrations, queue worker, webhook worker, MCP mount, static frontend serving, startup cleanup |

### Frontend pages (SPEC §33 — all 22 screens)

Sidebar app shell (Overview, Projects, Queue, Reviews, Providers, Profiles, Integrations, Settings)
+ first-run setup wizard, project detail, new review (range/commit/workspace) with command preview,
file preview, queue operator view (drag reorder), live job detail (SSE), review history,
result detail (findings grouped by file, warnings, copy/export), session inspector (virtualized JSONL),
provider editor (test connection + model discovery), profile editor (master-detail + live command preview),
MCP/webhook integration pages, settings sections, diagnostics, 404/error states.

### Design system

Tokens exactly per SPEC §22 (light/dark via `data-theme`), Inter/system stack, 4px grid,
radius 6–14px, custom CSS Modules components (Button/Input/Table/StatusDot/Modal/etc.), no component-library styling, motion 120–220ms, WCAG 2.2 AA.

## Key decisions

1. **Every control maps to a real mechanism** — each UI setting → OCR flag, per-job config value, env var, or documented control-plane behavior. Unsupported-by-binary controls are disabled with explanation (plan-mode until patched OCR detected).
2. **No secrets in DB/logs/exports** — keyring references only; redaction helper applied to logs, command previews, metadata.json, exports.
3. **Immutable job snapshots** — resolved provider/model/settings/refs/SHAs/command/OCR version persisted at queue time.
4. **Isolation** — range/commit jobs in detached worktrees under `<data_dir>/worktrees/<project>/<job>`; workspace jobs on real path with per-project exclusive lock; per-job HOME at `<data_dir>/jobs/<job>/home`.
5. **OCR absent ≠ broken** — app installs and runs fully; OCR-dependent actions surface a clear "OCR not detected" state with install instructions. Tests mock the adapter.

## Execution stages

- [x] Stage 0 — Spec ingestion, toolchain check, grounding research, plan
- [ ] Stage 1 — Backend: scaffold, db models + migrations, secrets, git service, OCR adapter
- [ ] Stage 2 — Backend: queue engine + runner + worktrees, webhooks, services, REST API + SSE, MCP, main.py, startup recovery
- [ ] Stage 3 — Frontend: design system + app shell + all 22 screens
- [ ] Stage 4 — Tests (backend unit/integration, frontend vitest), OCR planning patch, scripts, docs (README/ARCHITECTURE/API/MCP/WEBHOOKS), .env.example, verification report

## Verification

Backend: `pytest backend/tests`. Frontend: `npm run build` (tsc strict) + vitest.
Acceptance mapping in `docs/VERIFICATION.md` (SPEC §37 criteria → test/manual check).
