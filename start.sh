#!/usr/bin/env bash
# OpenCodeReview Control Center - launcher (macOS/Linux/Git Bash)
# Usage: ./start.sh [--build]
# Builds the frontend when needed, then serves API + MCP + UI on
# http://127.0.0.1:8787 with migrations, queue, and webhook workers.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$ROOT/scripts/start.sh" "$@"
