# Backend — OCR Control Center

Local-first FastAPI control plane for Alibaba OpenCodeReview (`ocr`).
Stage 1 contains the foundation: settings, structured logging with secret
redaction, the `SecretStore` abstraction, path/ref security helpers, the
SQLAlchemy 2 async data layer with Alembic migrations, `GitService`, and the
`OCRAdapter` compatibility layer. Queue/REST/MCP/webhooks land in Stage 2.

## Dev setup

```bash
# from the repo root (Git Bash on Windows works)
python -m venv backend/.venv
backend/.venv/Scripts/pip.exe install -e "backend[dev]"   # or pip install -r deps manually

# run tests
backend/.venv/Scripts/python.exe -m pytest backend/tests -q
```

On macOS/Linux use `backend/.venv/bin/pip` and `backend/.venv/bin/python`.

## Layout

```
app/
  core/      config (pydantic-settings), logging (structlog JSON + redaction),
             secrets (keyring/env/in-memory SecretStore), security (paths, refs, redaction, CSRF)
  db/        models (SPEC §4 entities), async session factory, Alembic runner
  git/       GitService: validate_repo, scan_folder, refresh_branches,
             resolve_ref, worktree add/remove/prune/list (argv arrays only)
  ocr/       OCRAdapter: binary+capability detection, command generation,
             per-job env/config isolation, result JSON + session JSONL parsing
alembic/     initial migration builds all tables from ORM metadata
tests/       pytest + pytest-asyncio; real temp git repos; OCR-binary tests skipped when absent
```

## Conventions

- No shell execution anywhere — argv arrays via `asyncio.create_subprocess_exec`.
- Secrets live behind `SecretStore` references (`keyring:<name>` / `env:VAR`);
  never in the DB, logs, or on-disk job configs.
- User refs are validated and passed after `--end-of-options`.
- When `ocr` is not installed, adapter entry points return structured
  `ocr_not_found` statuses instead of raising.

## Configuration

Copy `.env.example` to `.env`; every setting maps to `OCR_CC_*` env vars
(see `app/core/config.py`).
