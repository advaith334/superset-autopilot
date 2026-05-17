"""Devin session dispatch: orchestrator, auto-dispatch loop, one-shot bootstrap.

  - dispatch_triage_run: budget-gated single dispatch (called from /dispatch and auto loop)
  - auto_dispatch_loop:  background thread polling ready triage runs
  - bootstrap:           startup-time Devin setup (knowledge notes, GH-PAT secret, repo index)
"""

import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from prometheus_client import Counter
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .clients import DevinClient, DevinSession as _DevinSession, s3_presign_get
from .config import settings
from .models import DevinSession, Event, Issue, SessionLocal, TriageRun

log = logging.getLogger("dispatch")

_client = DevinClient()

auto_dispatch_attempts = Counter(
    "autopilot_auto_dispatch_attempts_total",
    "Auto-dispatch attempts by outcome.",
    ["outcome"],
)


# ────────────────────── Dispatch orchestrator ──────────────────────


class DispatchError(Exception):
    pass


def _prompt(issue: Issue, case_file_url: str) -> str:
    return (
        f"You are remediating GitHub issue #{issue.github_number} in {issue.github_repo}.\n\n"
        f"Title: {issue.title}\n\n"
        f"A case file (issue text, reporter narrative, code pointers, classification, "
        f"acceptance criteria, budget) is at this URL. Fetch it before doing anything else:\n\n"
        f"  {case_file_url}\n\n"
        f"You own reproduction and fixing as a single session. The `autopilot-fix-recipe` "
        f"knowledge note describes the expected workflow. Stay within the budget.\n\n"
        f"IMPORTANT — completion: open **exactly one** pull request that fixes the issue, "
        f"including `Fixes #{issue.github_number}` in the PR body so the autopilot can link it. "
        f"As soon as the PR is up and CI is queued, post a one-line summary in this session and stop. "
        f"Do not iterate further or open additional PRs unless I send you a follow-up message. "
        f"If CI breaks, I'll send the failure back to this session — keep it open for that."
    )


def _tags_for(issue: Issue, tr: TriageRun) -> list[str]:
    cls = tr.classification or {}
    tags = [
        "source:autopilot",
        f"issue:{issue.github_number}",
        f"repo:{issue.github_repo}",
    ]
    if cls.get("bug_type"):
        tags.append(f"type:{cls['bug_type']}")
    if cls.get("severity"):
        tags.append(f"severity:{cls['severity']}")
    if tr.confidence is not None:
        tags.append(f"confidence:{tr.confidence:.2f}")
    return tags


def _check_budget(db: Session) -> None:
    in_flight = db.execute(
        select(func.count()).select_from(DevinSession).where(DevinSession.state.in_(("dispatched", "running")))
    ).scalar_one()
    if in_flight >= settings.devin_max_concurrent:
        raise DispatchError(f"concurrency cap reached: {in_flight}/{settings.devin_max_concurrent} sessions in flight")

    since = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    used = db.execute(
        select(func.coalesce(func.sum(DevinSession.acu_consumed), 0.0))
        .where(DevinSession.dispatched_at >= since)
    ).scalar_one()
    if used >= settings.devin_max_acu_per_day:
        raise DispatchError(f"daily ACU budget exhausted: {used}/{settings.devin_max_acu_per_day}")


def dispatch_triage_run(db: Session, triage_run_id: int) -> _DevinSession:
    tr = db.get(TriageRun, triage_run_id)
    if tr is None:
        raise DispatchError(f"triage run {triage_run_id} not found")
    if tr.status != "ready_for_dispatch":
        raise DispatchError(f"triage run {triage_run_id} not ready (status={tr.status})")
    if not tr.case_file_s3_key:
        raise DispatchError(f"triage run {triage_run_id} has no case file")

    issue = db.get(Issue, tr.issue_id)
    if issue is None:
        raise DispatchError(f"issue {tr.issue_id} not found")

    _check_budget(db)

    url = s3_presign_get(settings.s3_bucket_casefiles, tr.case_file_s3_key)
    session = _client.create_session(
        prompt=_prompt(issue, url),
        tags=_tags_for(issue, tr),
        metadata={
            "case_file_url": url,
            "source": "superset-devin-autopilot",
            "triage_run_id": tr.id,
            "issue_id": issue.id,
        },
    )

    db.add(DevinSession(
        issue_id=issue.id,
        triage_run_id=tr.id,
        devin_session_id=session.session_id,
        state=session.state or "dispatched",
    ))
    tr.status = "dispatched"
    issue.status = "in_progress"
    db.add(Event(
        entity_type="devin_session", entity_id=0,
        event="dispatched",
        payload={"issue_id": issue.id, "devin_session_id": session.session_id, "mode": "real" if _client.enabled else "stub"},
    ))
    db.commit()
    log.info("dispatched session %s for issue %s (mode=%s)",
             session.session_id, issue.id, "real" if _client.enabled else "stub")
    return session


# ────────────────────── Auto-dispatch loop ──────────────────────


def _auto_tick() -> None:
    db = SessionLocal()
    try:
        candidates = db.execute(
            select(TriageRun)
            .where(TriageRun.status == "ready_for_dispatch")
            .where((TriageRun.confidence == None) | (TriageRun.confidence >= settings.auto_dispatch_threshold))  # noqa: E711
            .order_by(TriageRun.id.asc())
        ).scalars().all()
        for run in candidates:
            try:
                dispatch_triage_run(db, run.id)
                auto_dispatch_attempts.labels(outcome="dispatched").inc()
                log.info("auto-dispatched triage run %s", run.id)
            except DispatchError as exc:
                auto_dispatch_attempts.labels(outcome="rejected").inc()
                if "concurrency" in str(exc).lower() or "budget" in str(exc).lower():
                    break
    finally:
        db.close()


def auto_dispatch_loop() -> None:
    log.info(
        "auto-dispatch loop started (threshold=%.2f, interval=%ss)",
        settings.auto_dispatch_threshold, settings.auto_dispatch_interval_seconds,
    )
    while True:
        try:
            _auto_tick()
        except Exception as exc:  # noqa: BLE001
            log.exception("auto-dispatch tick failed: %s", exc)
            auto_dispatch_attempts.labels(outcome="loop_error").inc()
        time.sleep(settings.auto_dispatch_interval_seconds)


# ────────────────────── Bootstrap ──────────────────────


_SEED_DIR = Path(__file__).resolve().parent / "seeds" / "knowledge"


def bootstrap() -> None:
    """One-shot startup setup: repo index, GH-PAT secret push, knowledge upload."""
    if not _client.enabled:
        log.info("Devin in STUB mode — bootstrap logs intent only")

    # Repo
    try:
        _client.index_repository(settings.devin_target_repo)
        log.info("repository index requested: repo=%s", settings.devin_target_repo)
    except Exception as exc:  # noqa: BLE001
        log.warning("repository index failed: %s", exc)

    # Secret
    if settings.github_token:
        try:
            existing = {s.get("name") for s in _client.list_secrets()}
            if settings.devin_github_secret_name not in existing:
                _client.create_secret(settings.devin_github_secret_name, settings.github_token)
                log.info("pushed Devin secret %s", settings.devin_github_secret_name)
        except Exception as exc:  # noqa: BLE001
            log.warning("Devin secret push failed: %s", exc)
    else:
        log.info("no GITHUB_TOKEN; skipping Devin secret push")

    # Knowledge
    if _SEED_DIR.exists():
        try:
            existing_names = {n.get("name") for n in _client.list_knowledge_notes()}
        except Exception:  # noqa: BLE001
            existing_names = set()
        for md in sorted(_SEED_DIR.glob("*.md")):
            name = md.stem
            if name in existing_names:
                continue
            try:
                _client.create_knowledge_note(name=name, body=md.read_text(), folder=settings.devin_knowledge_folder)
                log.info("uploaded knowledge note %r", name)
            except Exception as exc:  # noqa: BLE001
                log.warning("knowledge upload %r failed: %s", name, exc)
    else:
        log.warning("knowledge seed dir missing: %s", _SEED_DIR)

    log.info("bootstrap complete")


def start_auto_dispatch() -> None:
    threading.Thread(target=auto_dispatch_loop, name="auto-dispatch", daemon=True).start()
