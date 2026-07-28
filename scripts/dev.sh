#!/usr/bin/env bash
# Development startup: backend (uvicorn --reload :8372) + frontend (vite :5173).
# Usage: scripts/dev.sh [--port 8372]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PORT_OVERRIDE=""
while [[ $# -gt 0 ]]; do
  arg="$1"
  case "$arg" in
    --port)
      if [[ $# -lt 2 ]]; then echo "--port requires a value" >&2; exit 2; fi
      PORT_OVERRIDE="$2"
      shift 2
      ;;
    --port=*)
      PORT_OVERRIDE="${arg#--port=}"
      shift
      ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

if [[ -n "$PORT_OVERRIDE" && ! "$PORT_OVERRIDE" =~ ^[0-9]+$ ]]; then
  echo "--port must be a number" >&2
  exit 2
fi
if [[ -n "$PORT_OVERRIDE" && ( "$PORT_OVERRIDE" -lt 1 || "$PORT_OVERRIDE" -gt 65535 ) ]]; then
  echo "--port must be between 1 and 65535" >&2
  exit 2
fi

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

if [[ -n "$PORT_OVERRIDE" ]]; then
  export OCR_CC_PORT="$PORT_OVERRIDE"
fi
BACKEND_PORT="${OCR_CC_PORT:-8372}"

BACKEND_PID=""
cleanup() {
  [[ -n "$BACKEND_PID" ]] && kill "$BACKEND_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "[dev] backend  → http://127.0.0.1:${BACKEND_PORT} (uvicorn --reload)"
(cd backend && "../$VENV_PY" -m uvicorn app.main:app --host 127.0.0.1 --port "$BACKEND_PORT" --reload) &
BACKEND_PID=$!

echo "[dev] frontend → http://localhost:5173 (vite, proxies /api and /mcp)"
(cd frontend && npm run dev)

# npm exited (Ctrl+C) — trap cleans up the backend.
