#!/usr/bin/env bash
# Production startup — the ONE command (SPEC §2/§37):
#   scripts/start.sh
# Builds the frontend when needed, then runs `python -m app`, which serves the
# API + MCP + built UI on http://127.0.0.1:8787, applies DB migrations, and
# starts the queue and webhook workers.
#
# Options:
#   --build   force a frontend rebuild even if frontend/dist exists
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

FORCE_BUILD=0
for arg in "$@"; do
  case "$arg" in
    --build) FORCE_BUILD=1 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

VENV_PY="backend/.venv/bin/python"
if [[ ! -x "$VENV_PY" ]]; then VENV_PY="backend/.venv/Scripts/python.exe"; fi

if [[ ! -x "$VENV_PY" ]]; then
  echo "[start] creating backend virtualenv…"
  python -m venv backend/.venv
  if [[ -x "backend/.venv/bin/python" ]]; then VENV_PY="backend/.venv/bin/python"; else VENV_PY="backend/.venv/Scripts/python.exe"; fi
fi

# Install backend deps if the package is not importable.
if ! "$VENV_PY" -c "import app" 2>/dev/null; then
  echo "[start] installing backend dependencies…"
  "$VENV_PY" -m pip install -e "backend"
fi

# Build the frontend when dist is missing (or --build was passed).
if [[ ! -f frontend/dist/index.html || "$FORCE_BUILD" == "1" ]]; then
  echo "[start] building frontend…"
  if [[ ! -d frontend/node_modules ]]; then
    (cd frontend && npm install)
  fi
  (cd frontend && npm run build)
fi

# Load root .env (OCR_CC_* overrides) if present.
if [[ -f .env ]]; then
  set -a; # shellcheck disable=SC1091
  . ./.env; set +a
fi

echo "[start] OpenCodeReview Control Center → http://127.0.0.1:${OCR_CC_PORT:-8787}"
cd backend
exec "../$VENV_PY" -m app
