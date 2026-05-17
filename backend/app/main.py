"""Backend HTTP surface (Phase 1):

  POST /webhook/github           — GitHub issue webhook (HMAC-verified, pgvector dedup)
  GET  /issues, /issues/{id}     — list / fetch ingested issues
  GET  /health, /metrics

Later phases add /triage, /dispatch, /sessions, /pull_requests."""

import json
import logging

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, generate_latest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .clients import (
    embed, enqueue_triage, parse_issue_event, triage_queue_depth, verify_signature,
)
from .config import settings
from .models import (
    Event, Issue, IssueListOut, IssueOut, WebhookResponse, get_db,
)

log = logging.getLogger("autopilot")
logging.basicConfig(level="INFO", format="%(asctime)s %(levelname)s %(name)s %(message)s")

app = FastAPI(title="autopilot", version="0.2.0")


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


# ════════════════════════ Health / metrics ════════════════════════


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/metrics")
def metrics() -> Response:
    triage_queue_depth_g.set(triage_queue_depth())
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


# ════════════════════════ pgvector dedup ════════════════════════


def find_duplicate(db: Session, embedding: list[float], threshold: float) -> Issue | None:
    """Cosine-distance nearest neighbour; returns the duplicate if similarity ≥ threshold."""
    distance = Issue.embedding.cosine_distance(embedding).label("distance")
    stmt = (
        select(Issue, distance)
        .where(Issue.embedding.is_not(None))
        .order_by(distance)
        .limit(1)
    )
    row = db.execute(stmt).first()
    if row is None:
        return None
    issue, dist = row
    return issue if (1.0 - float(dist)) >= threshold else None


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
    dup = find_duplicate(db, vec, settings.dedup_threshold)

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


# ════════════════════════ Issues read API ════════════════════════


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
