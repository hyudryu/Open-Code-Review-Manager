"""Add error_code column to review_jobs for structured error tracking.

Allows the runner to set machine-readable error codes (e.g. "ocr_exit",
"preparation_failed", "provider_unavailable") alongside the human-readable
status_message. The UI displays these codes on hover in the queue table.
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_job_error_code"
down_revision: str | None = "0004_default_profile"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {c["name"] for c in inspector.get_columns("review_jobs")}
    if "error_code" not in existing:
        op.add_column(
            "review_jobs",
            sa.Column("error_code", sa.String(64), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "error_code" in {c["name"] for c in inspector.get_columns("review_jobs")}:
        op.drop_column("review_jobs", "error_code")
