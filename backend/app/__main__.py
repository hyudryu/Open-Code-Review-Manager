"""``python -m app`` — single-command startup (uvicorn).

Port precedence (highest to lowest):
  1. ``--port`` CLI flag
  2. ``OCR_CC_PORT`` environment variable
  3. ``server.port`` saved via the settings UI (requires restart to apply)
  4. built-in default (8372)
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

import uvicorn

from app.core.config import _DEFAULT_PORT, get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def _port(value: str) -> int:
    port = int(value)
    if port < 1 or port > 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the OpenCodeReview Manager.")
    parser.add_argument(
        "--host",
        help="Host to bind. Defaults to OCR_CC_HOST or 127.0.0.1.",
    )
    parser.add_argument(
        "--port",
        type=_port,
        help="Port to bind. Overrides OCR_CC_PORT and the saved setting for this startup.",
    )
    return parser.parse_args(argv)


def _read_saved_port() -> int | None:
    """Return the ``server.port`` saved via the settings UI, or None.

    Uses plain synchronous ``sqlite3`` against the DB file rather than the
    async engine, because (a) the async engine is not initialized yet at
    startup, and (b) this avoids event-loop concerns. On a first-ever start the
    DB/table may not exist — both are non-fatal and simply mean no saved
    override is applied.
    """

    import json
    import sqlite3
    from urllib.parse import urlparse, unquote

    settings = get_settings()
    # Derive the sqlite file path from the resolved DB URL (which may point at
    # a custom ``test.db`` rather than the default ``ocrcc.db``).
    url = settings.resolved_database_url
    if not url.startswith("sqlite"):
        return None
    parsed = urlparse(url)
    # For "sqlite+aiosqlite:///path" the path is in parsed.path; strip leading
    # slashes for absolute Windows paths and unquote percent-encoded chars.
    db_path_str = unquote(parsed.path).lstrip("/")
    db_path_str = db_path_str or parsed.netloc
    if not db_path_str:
        return None
    from pathlib import Path

    db_path = Path(db_path_str)
    if not db_path.exists():
        return None
    try:
        with sqlite3.connect(str(db_path)) as conn:
            cur = conn.execute(
                "SELECT value_json FROM app_settings WHERE key = ?",
                ("server.port",),
            )
            row = cur.fetchone()
    except sqlite3.DatabaseError as exc:
        logger.warning("could not read saved server.port: %s", exc)
        return None
    if row is None:
        return None
    raw = row[0]
    # The JSON column may surface as a native Python int (SQLite returns the
    # stored token as-is) or as a JSON string; normalize both.
    if isinstance(raw, (int, float)):
        value = raw
    elif isinstance(raw, str):
        try:
            value = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
    else:
        return None
    if isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 65535:
        return value
    return None


def _resolve_port(cli_port: int | None) -> int:
    """Apply the documented port precedence and return the chosen port."""

    import os

    settings = get_settings()
    # 1. CLI flag (already validated by argparse).
    if cli_port is not None:
        return cli_port
    # 2. OCR_CC_PORT env var — Pydantic populated ``settings.port`` from it.
    if os.environ.get("OCR_CC_PORT"):
        return settings.port
    # 3. Saved UI setting (requires restart to apply).
    saved = _read_saved_port()
    if saved is not None:
        return saved
    # 4. Built-in default (settings.port already == default here).
    return settings.port


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    settings = get_settings()
    if args.host:
        settings.host = args.host
    settings.port = _resolve_port(args.port)
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
        reload=False,
    )


if __name__ == "__main__":
    main()
