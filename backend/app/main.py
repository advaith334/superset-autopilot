"""Unified FastAPI app — single entry point for the autopilot.

HTTP surface:
  POST /webhook/github           — receive real GitHub issue webhooks (HMAC-verified)
  POST /triage/{issue_id}        — manually re-enqueue triage
  POST /dispatch/{run_id}        — manually dispatch a Devin session (auto loop does this normally)
  GET  /issues, /issues/{id}     — list / fetch ingested issues
  GET  /triage_runs[/{id}]       — list / fetch triage runs (run's case file URL is pre-signed on GET)
  GET  /sessions[/{id}]          — list / fetch Devin sessions
  GET  /pull_requests            — list PRs linked from Devin sessions
  GET  /health, /metrics

Startup launches one bootstrap call (Devin knowledge / secret / repo index)
and six background daemon threads via dispatch.start_auto_dispatch() and
monitor.start_all() (plus triage.worker_loop)."""

import json
import logging
import threading

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, generate_latest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import dispatch, monitor, triage
from .clients import enqueue_triage, parse_issue_event, s3_presign_get, triage_queue_depth, verify_signature
from .clients import embed
from .config import settings
from .models import (
    DevinSession, Event, Issue, IssueListOut, IssueOut, PullRequest, PullRequestOut,
    SessionOut, TriageRun, TriageRunOut, WebhookResponse, get_db,
)

log = logging.getLogger("autopilot")
logging.basicConfig(level="INFO", format="%(asctime)s %(levelname)s %(name)s %(message)s")

app = FastAPI(title="autopilot", version="1.0.0")


# ════════════════════════ Prometheus metrics ════════════════════════

webhooks_received = Counter(
    "autopilot_webhooks_received_total",
    "GitHub webhooks received, by event and outcome.",
    ["event", "outcome"],
)
issues_ingested = Counter(
    "autopilot_issues_ingested_total",
    "Issues persisted to the database, by outcome.",
    ["outcome"],
)
triage_queue_depth_g = Gauge(
    "autopilot_triage_queue_depth",
    "Pending triage jobs in Redis.",
)
manual_triggers = Counter(
    "autopilot_triage_manual_triggers_total",
    "Manual /triage/{id} invocations.",
    ["outcome"],
)
sessions_dispatched = Counter(
    "autopilot_sessions_dispatched_total",
    "Devin sessions dispatched, by outcome and mode.",
    ["outcome", "mode"],
)


_mode = "real" if dispatch._client.enabled else "stub"  # noqa: SLF001


# ════════════════════════ Startup: bootstrap + daemons ════════════════════════


@app.on_event("startup")
def _startup() -> None:
    dispatch.bootstrap()
    threading.Thread(target=triage.worker_loop, name="triage-worker", daemon=True).start()
    dispatch.start_auto_dispatch()
    monitor.start_all()
    log.info("autopilot up — bootstrap + 6 daemons running")


# ════════════════════════ Health / metrics ════════════════════════


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "devin_mode": _mode}


@app.get("/metrics")
def metrics() -> Response:
    triage_queue_depth_g.set(triage_queue_depth())
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


# ════════════════════════ Webhook ════════════════════════


@app.post("/webhook/github", response_model=WebhookResponse)
async def github_webhook(request: Request, db: Session = Depends(get_db)) -> WebhookResponse:
    raw = await request.body()
    sig = request.headers.get("X-Hub-Signature-256")
    if not verify_signature(settings.github_webhook_secret, raw, sig):
        webhooks_received.labels(event="*", outcome="bad_signature").inc()
        raise HTTPException(status_code=401, detail="invalid signature")

    event = request.headers.get("X-GitHub-Event", "unknown")
    if event != "issues":
        webhooks_received.labels(event=event, outcome="ignored").inc()
        return WebhookResponse(status="ignored", detail=f"event '{event}' not handled")

    try:
        payload = json.loads(raw or b"{}")
    except json.JSONDecodeError as exc:
        log.warning("webhook body not JSON: %s; first bytes: %r", exc, raw[:60])
        raise HTTPException(status_code=400, detail="invalid JSON body") from exc

    parsed = parse_issue_event(payload)
    if parsed is None:
        webhooks_received.labels(event=event, outcome="ignored_action").inc()
        return WebhookResponse(status="ignored", detail=f"action '{payload.get('action')}' not handled")

    existing = db.execute(select(Issue).where(Issue.github_number == parsed["github_number"])).scalar_one_or_none()
    if existing is not None:
        webhooks_received.labels(event=event, outcome="duplicate_webhook").inc()
        return WebhookResponse(status="exists", issue_id=existing.id)

    vec = embed(f"{parsed['title']}\n\n{parsed['body']}")
    dup = triage.find_duplicate(db, vec, settings.dedup_threshold)

    issue = Issue(
        github_number=parsed["github_number"],
        github_repo=parsed["github_repo"],
        title=parsed["title"],
        body=parsed["body"],
        labels=parsed["labels"],
        reporter=parsed["reporter"],
        html_url=parsed["html_url"],
        embedding=vec,
        status="duplicate" if dup else "received",
        dedup_of_id=dup.id if dup else None,
    )
    db.add(issue); db.flush()
    db.add(Event(
        entity_type="issue", entity_id=issue.id, event="ingested",
        payload={"action": parsed["action"], "dedup_of": dup.id if dup else None},
    ))
    db.commit()

    if dup:
        issues_ingested.labels(outcome="duplicate").inc()
        webhooks_received.labels(event=event, outcome="duplicate").inc()
        return WebhookResponse(status="duplicate", issue_id=issue.id, dedup_of_id=dup.id)

    enqueue_triage(issue.id)
    issues_ingested.labels(outcome="queued").inc()
    webhooks_received.labels(event=event, outcome="queued").inc()
    return WebhookResponse(status="queued", issue_id=issue.id)


# ════════════════════════ Triage routes ════════════════════════


@app.post("/triage/{issue_id}")
def trigger_triage(issue_id: int) -> dict[str, str]:
    enqueue_triage(issue_id)
    manual_triggers.labels(outcome="queued").inc()
    return {"status": "queued", "issue_id": str(issue_id)}


@app.get("/triage_runs", response_model=list[TriageRunOut])
def list_triage_runs(
    issue_id: int | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[TriageRunOut]:
    stmt = select(TriageRun).order_by(TriageRun.id.desc()).limit(limit)
    if issue_id is not None:
        stmt = stmt.where(TriageRun.issue_id == issue_id)
    if status is not None:
        stmt = stmt.where(TriageRun.status == status)
    return [TriageRunOut.model_validate(r) for r in db.execute(stmt).scalars()]


@app.get("/triage_runs/{run_id}", response_model=TriageRunOut)
def get_triage_run(run_id: int, db: Session = Depends(get_db)) -> TriageRunOut:
    run = db.get(TriageRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="triage run not found")
    out = TriageRunOut.model_validate(run)
    if run.case_file_s3_key:
        out.case_file_url = s3_presign_get(settings.s3_bucket_casefiles, run.case_file_s3_key)
    return out


# ════════════════════════ Dispatch routes ════════════════════════


@app.post("/dispatch/{triage_run_id}")
def manual_dispatch(triage_run_id: int, db: Session = Depends(get_db)) -> dict[str, str]:
    try:
        session = dispatch.dispatch_triage_run(db, triage_run_id)
    except dispatch.DispatchError as exc:
        sessions_dispatched.labels(outcome="rejected", mode=_mode).inc()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    sessions_dispatched.labels(outcome="dispatched", mode=_mode).inc()
    return {"status": "dispatched", "devin_session_id": session.session_id, "mode": _mode}


# ════════════════════════ Issues / sessions / PRs read API ════════════════════════


@app.get("/issues", response_model=IssueListOut)
def list_issues(
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> IssueListOut:
    base = select(Issue)
    count_stmt = select(func.count()).select_from(Issue)
    if status:
        base = base.where(Issue.status == status)
        count_stmt = count_stmt.where(Issue.status == status)
    items = [IssueOut.model_validate(i) for i in db.execute(base.order_by(Issue.created_at.desc()).limit(limit).offset(offset)).scalars()]
    total = int(db.execute(count_stmt).scalar_one())
    return IssueListOut(items=items, total=total)


@app.get("/issues/{issue_id}", response_model=IssueOut)
def get_issue(issue_id: int, db: Session = Depends(get_db)) -> IssueOut:
    issue = db.get(Issue, issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail="issue not found")
    return IssueOut.model_validate(issue)


@app.get("/sessions", response_model=list[SessionOut])
def list_sessions(state: str | None = None, limit: int = 50, db: Session = Depends(get_db)) -> list[SessionOut]:
    stmt = select(DevinSession).order_by(DevinSession.id.desc()).limit(limit)
    if state:
        stmt = stmt.where(DevinSession.state == state)
    return [SessionOut.model_validate(s) for s in db.execute(stmt).scalars()]


@app.get("/sessions/{session_id}", response_model=SessionOut)
def get_session(session_id: int, db: Session = Depends(get_db)) -> SessionOut:
    s = db.get(DevinSession, session_id)
    if s is None:
        raise HTTPException(status_code=404, detail="session not found")
    return SessionOut.model_validate(s)


@app.get("/pull_requests", response_model=list[PullRequestOut])
def list_prs(limit: int = 50, db: Session = Depends(get_db)) -> list[PullRequestOut]:
    stmt = select(PullRequest).order_by(PullRequest.id.desc()).limit(limit)
    return [PullRequestOut.model_validate(p) for p in db.execute(stmt).scalars()]
