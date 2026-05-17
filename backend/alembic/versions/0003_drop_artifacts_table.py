"""drop artifacts table

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-17

The Artifact model was scaffolded in Phase 2 for a "triage worker uploads
per-issue artifacts" flow that never shipped. Every artifact path now uses
TriageRun.case_file_s3_key directly. No rows have ever been inserted into
the table. Dropping it.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table("artifacts")


def downgrade() -> None:
    op.create_table(
        "artifacts",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("triage_run_id", sa.BigInteger, sa.ForeignKey("triage_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("s3_key", sa.String(512), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("bytes", sa.BigInteger, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_artifacts_triage_run", "artifacts", ["triage_run_id"])
