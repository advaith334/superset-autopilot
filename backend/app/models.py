"""SQLAlchemy ORM + DB session manager + Pydantic response schemas."""

from collections.abc import Iterator
from datetime import datetime
from typing import Any, Optional

from pgvector.sqlalchemy import Vector
from pydantic import BaseModel, ConfigDict
from sqlalchemy import (
    JSON, BigInteger, DateTime, Float, ForeignKey, Integer, String, Text,
    create_engine, func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from .config import settings


# ──────────────────────── ORM ────────────────────────


class Base(DeclarativeBase):
    pass


class Issue(Base):
    __tablename__ = "issues"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    github_number: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    github_repo: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    labels: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    reporter: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    html_url: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="received")
    dedup_of_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("issues.id", ondelete="SET NULL"), nullable=True)
    embedding: Mapped[Optional[Any]] = mapped_column(Vector(384), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class TriageRun(Base):
    __tablename__ = "triage_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    issue_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("issues.id", ondelete="CASCADE"), nullable=False)
    classification: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    case_file_s3_key: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class DevinSession(Base):
    __tablename__ = "devin_sessions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    issue_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("issues.id", ondelete="CASCADE"), nullable=False)
    triage_run_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("triage_runs.id", ondelete="SET NULL"), nullable=True)
    devin_session_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="dispatched")
    acu_consumed: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    dispatched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class PullRequest(Base):
    __tablename__ = "pull_requests"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("devin_sessions.id", ondelete="CASCADE"), nullable=False)
    github_pr_number: Mapped[int] = mapped_column(Integer, nullable=False)
    github_repo: Mapped[str] = mapped_column(String(255), nullable=False)
    html_url: Mapped[str] = mapped_column(String(512), nullable=False)
    merge_state: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    merged_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    event: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


# ──────────────────────── DB session ────────────────────────


engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ──────────────────────── Pydantic response schemas ────────────────────────


class WebhookResponse(BaseModel):
    status: str
    issue_id: Optional[int] = None
    dedup_of_id: Optional[int] = None
    detail: Optional[str] = None


class IssueOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    github_number: int
    github_repo: str
    title: str
    body: str
    labels: list[str]
    reporter: Optional[str]
    html_url: str
    status: str
    dedup_of_id: Optional[int]
    created_at: datetime
    updated_at: datetime


class IssueListOut(BaseModel):
    items: list[IssueOut]
    total: int


class TriageRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    issue_id: int
    status: str
    classification: Optional[dict[str, Any]]
    confidence: Optional[float]
    case_file_s3_key: Optional[str]
    case_file_url: Optional[str] = None
    error: Optional[str]
    started_at: datetime
    completed_at: Optional[datetime]


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    issue_id: int
    devin_session_id: str
    state: str
    acu_consumed: float
    cost_usd: float
    dispatched_at: datetime
    completed_at: Optional[datetime]


class PullRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    session_id: int
    github_pr_number: int
    github_repo: str
    html_url: str
    merge_state: str
    created_at: datetime
