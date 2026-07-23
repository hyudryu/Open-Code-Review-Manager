"""stage 4: review_profiles.template_path

Revision ID: 0003_template_path
Revises: 0002_stage2_extensions
Create Date: 2026-07-24

Adds the profile-owned ``--template`` planning control (SPEC §8). The
OCRAdapter and the control-plane-owned flag list already supported
``--template``; the profile schema/DB simply had no column for it.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_template_path"
down_revision = "0002_stage2_extensions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {c["name"] for c in inspector.get_columns("review_profiles")}
    if "template_path" not in existing:
        op.add_column("review_profiles", sa.Column("template_path", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("review_profiles", "template_path")
