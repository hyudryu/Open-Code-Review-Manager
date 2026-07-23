"""initial schema (SPEC §4 entities)

Revision ID: 0001_initial
Revises:
Create Date: 2026-07-23

Creates every table from the declarative metadata so the ORM models remain
the single source of truth. Subsequent migrations are hand-written diffs.
"""

from __future__ import annotations

import sys
from pathlib import Path

from alembic import op

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from app.db.base import Base  # noqa: E402
from app.db import models  # noqa: E402,F401  (register all tables)

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
