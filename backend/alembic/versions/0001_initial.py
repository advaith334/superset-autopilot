"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-05-16

Creates the full data model described in plan.md §2.6. Triage_runs, artifacts,
devin_sessions, and pull_requests are populated by later phases but are
defined here so foreign keys and indexes are stable from day one.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "issues",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("github_number", sa.Integer, nullable=False, unique=True),
        sa.Column("github_repo", sa.String(255), nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("body", sa.Text, nullable=False, server_default=""),
        sa.Column("labels", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("reporter", sa.String(255), nullable=True),
        sa.Column("html_url", sa.String(512), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="received"),
        sa.Column("dedup_of_id", sa.BigInteger, sa.ForeignKey("issues.id", ondelete="SET NULL"), nullable=True),
        sa.Column("embedding", Vector(384), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_issues_status", "issues", ["status"])
    op.create_index("ix_issues_dedup_of", "issues", ["dedup_of_id"])
    # IVFFlat index on the embedding column; lists=100 is fine until we have
    # >>10k issues. Re-tune when scale changes.
    op.execute(
        "CREATE INDEX ix_issues_embedding ON issues "
        "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )

    op.create_table(
        "triage_runs",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("issue_id", sa.BigInteger, sa.ForeignKey("issues.id", ondelete="CASCADE"), nullable=False),
        sa.Column("repro_verified", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("classification", sa.JSON, nullable=True),
        sa.Column("confidence", sa.Float, nullable=True),
        sa.Column("case_file_s3_key", sa.String(512), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_triage_runs_issue", "triage_runs", ["issue_id"])
    op.create_index("ix_triage_runs_status", "triage_runs", ["status"])

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

    op.create_table(
        "devin_sessions",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("issue_id", sa.BigInteger, sa.ForeignKey("issues.id", ondelete="CASCADE"), nullable=False),
        sa.Column("triage_run_id", sa.BigInteger, sa.ForeignKey("triage_runs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("devin_session_id", sa.String(128), nullable=False, unique=True),
        sa.Column("state", sa.String(32), nullable=False, server_default="dispatched"),
        sa.Column("acu_consumed", sa.Float, nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Float, nullable=False, server_default="0"),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_devin_sessions_issue", "devin_sessions", ["issue_id"])
    op.create_index("ix_devin_sessions_state", "devin_sessions", ["state"])

    op.create_table(
        "pull_requests",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.BigInteger, sa.ForeignKey("devin_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("github_pr_number", sa.Integer, nullable=False),
        sa.Column("github_repo", sa.String(255), nullable=False),
        sa.Column("html_url", sa.String(512), nullable=False),
        sa.Column("merge_state", sa.String(32), nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("merged_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_prs_session", "pull_requests", ["session_id"])

    op.create_table(
        "events",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("entity_id", sa.BigInteger, nullable=False),
        sa.Column("event", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON, nullable=True),
        sa.Column("ts", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_events_entity", "events", ["entity_type", "entity_id"])
    op.create_index("ix_events_ts", "events", ["ts"])


def downgrade() -> None:
    op.drop_table("events")
    op.drop_table("pull_requests")
    op.drop_table("devin_sessions")
    op.drop_table("artifacts")
    op.drop_table("triage_runs")
    op.execute("DROP INDEX IF EXISTS ix_issues_embedding")
    op.drop_table("issues")
