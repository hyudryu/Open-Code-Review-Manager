"""Programmatic migration runner invoked at application startup."""

from __future__ import annotations

import asyncio
from pathlib import Path

from alembic import command
from alembic.config import Config

_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent


def _make_config(database_url: str) -> Config:
    cfg = Config(str(_BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


def run_migrations(database_url: str) -> None:
    """Upgrade the database at ``database_url`` to head (synchronous)."""

    command.upgrade(_make_config(database_url), "head")


async def run_migrations_async(database_url: str) -> None:
    """Async wrapper: alembic's env manages its own event loop, so this must
    run in a worker thread when called from a running loop."""

    await asyncio.to_thread(run_migrations, database_url)
