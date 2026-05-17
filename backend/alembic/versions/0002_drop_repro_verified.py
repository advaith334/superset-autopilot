"""drop triage_runs.repro_verified

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-17

We removed pre-verified reproduction from the pipeline — Devin owns
reproduction inside its own session now (see autopilot-fix-recipe knowledge
note). The column was always populated as False; dropping cleanly.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("triage_runs", "repro_verified")


def downgrade() -> None:
    op.add_column(
        "triage_runs",
        sa.Column("repro_verified", sa.Boolean, nullable=False, server_default=sa.text("false")),
    )
