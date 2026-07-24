"""stage 2 extensions: queue/runtime job fields + provider discovery state

Revision ID: 0002_stage2_extensions
Revises: 0001_initial
Create Date: 2026-07-24

Adds the columns the Stage 2 control plane needs on top of the Stage 1
schema:

- review_jobs.paused                — individually paused queued job
- review_jobs.result_summary_json   — parsed result.json summary/token counts
- review_jobs.warnings_json         — normalized OCR warnings
- review_jobs.dirty_fingerprint     — workspace dirty-state fingerprint
- provider_profiles.last_discovery_at / last_discovery_error — SPEC §9
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_stage2_extensions"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def _add_column_if_missing(table: str, column: sa.Column) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {c["name"] for c in inspector.get_columns(table)}
    if column.name not in existing:
        op.add_column(table, column)


def upgrade() -> None:
    # Plain ADD COLUMN works on SQLite and Postgres alike; batch mode is
    # avoided because review_jobs has a self-referencing FK (retry_of_job_id)
    # which makes table recreation hit a circular dependency. Column-existence
    # checks keep this migration idempotent when 0001's create_all already ran
    # against the current metadata (fresh databases).
    _add_column_if_missing(
        "review_jobs",
        sa.Column("paused", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    _add_column_if_missing(
        "review_jobs", sa.Column("result_summary_json", sa.JSON(), nullable=True)
    )
    _add_column_if_missing(
        "review_jobs", sa.Column("warnings_json", sa.JSON(), nullable=True)
    )
    _add_column_if_missing(
        "review_jobs", sa.Column("dirty_fingerprint", sa.Text(), nullable=True)
    )
    _add_column_if_missing(
        "provider_profiles",
        sa.Column("last_discovery_at", sa.DateTime(timezone=True), nullable=True),
    )
    _add_column_if_missing(
        "provider_profiles", sa.Column("last_discovery_error", sa.Text(), nullable=True)
    )


def downgrade() -> None:
    with op.batch_alter_table("provider_profiles") as batch:
        batch.drop_column("last_discovery_error")
        batch.drop_column("last_discovery_at")
    with op.batch_alter_table("review_jobs") as batch:
        batch.drop_column("dirty_fingerprint")
        batch.drop_column("warnings_json")
        batch.drop_column("result_summary_json")
        batch.drop_column("paused")
