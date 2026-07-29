"""stage 4: review_profiles.is_system

Revision ID: 0004_default_profile
Revises: 0003_template_path
Create Date: 2026-07-28

Adds ``is_system`` so a permanent "Default" review profile can be marked
as undeletable and used as the automatic fallback when a review is queued
without an explicit profile. Existing rows default to ``false``; the
Default row is flagged by ``ProfileService.ensure_default`` at startup.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_default_profile"
down_revision = "0003_template_path"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {c["name"] for c in inspector.get_columns("review_profiles")}
    if "is_system" not in existing:
        op.add_column(
            "review_profiles",
            sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.false()),
        )


def downgrade() -> None:
    op.drop_column("review_profiles", "is_system")
