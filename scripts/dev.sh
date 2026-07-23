#!/usr/bin/env bash
# Development startup: backend (uvicorn --reload :8787) + frontend (vite :5173).
# Usage: scripts/dev.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

VENV_PY="backend/.venv/bin/python"
if [[ ! -x "$VENV_PY" ]]; then VENV_PY="backend/.venv/Scripts/python.exe"; fi

if [[ ! -x "$VENV_PY" ]]; then
  echo "[dev] creating backend virtualenv…"
  python -m venv backend/.venv
  if [[ -x "backend/.venv/bin/python" ]]; then VENV_PY="backend/.venv/bin/python"; else VENV_PY="backend/.venv/Scripts/python.exe"; fi
  "$VENV_PY" -m pip install -e "backend[dev]"
fi

if [[ ! -d frontend/node_modules ]]; then
  echo "[dev] installing frontend dependencies…"
  (cd frontend && npm install)
fi

# Load root .env (OCR_CC_* overrides) if present.
if [[ -f .env ]]; then
  set -a; # shellcheck disable=SC1091
  . ./.env; set +a
fi

BACKEND_PID=""
cleanup() {
  [[ -n "$BACKEND_PID" ]] && kill "$BACKEND_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "[dev] backend  → http://127.0.0.1:8787 (uvicorn --reload)"
(cd backend && "../$VENV_PY" -m uvicorn app.main:app --host 127.0.0.1 --port 8787 --reload) &
BACKEND_PID=$!

echo "[dev] frontend → http://localhost:5173 (vite, proxies /api and /mcp)"
(cd frontend && npm run dev)

# npm exited (Ctrl+C) — trap cleans up the backend.
