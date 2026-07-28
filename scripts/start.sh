#!/usr/bin/env bash
# Production startup — the ONE command (SPEC §2/§37):
#   scripts/start.sh
# Builds the frontend when needed, then runs `python -m app`, which serves the
# API + MCP + built UI on http://127.0.0.1:8372, applies DB migrations, and
# starts the queue and webhook workers.
#
# Options:
#   --build   force a frontend rebuild even if frontend/dist exists
#   --port N  override OCR_CC_PORT for this startup
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

FORCE_BUILD=0
PORT_OVERRIDE=""
while [[ $# -gt 0 ]]; do
  arg="$1"
  case "$arg" in
    --build)
      FORCE_BUILD=1
      shift
      ;;
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

if [[ -n "$PORT_OVERRIDE" ]]; then
  export OCR_CC_PORT="$PORT_OVERRIDE"
fi

echo "[start] OpenCodeReview Manager → http://127.0.0.1:${OCR_CC_PORT:-8372}"
cd backend
exec "../$VENV_PY" -m app --port "${OCR_CC_PORT:-8372}"
