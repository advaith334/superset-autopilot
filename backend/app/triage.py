"""Triage pipeline: classifier + code locator + case-file builder + pgvector
dedup + queue worker. The full path from an ingested issue to a ready-for-
dispatch triage_run row + a case file in S3."""

import json
import logging
import re
import subprocess
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import redis
from prometheus_client import Counter as PromCounter, Histogram
from sqlalchemy import select
from sqlalchemy.orm import Session

from .clients import embed, s3_put_json
from .config import settings
from .models import Event, Issue, SessionLocal, TriageRun

log = logging.getLogger("triage")


# ──────────────────────── Classifier (heuristic) ────────────────────────


@dataclass
class Classification:
    bug_type: str
    severity: str
    devinable_confidence: float
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "bug_type": self.bug_type,
            "severity": self.severity,
            "devinable_confidence": self.devinable_confidence,
            "rationale": self.rationale,
        }


_SEVERITY_KEYWORDS = {
    "critical": ("crash", "data loss", "data corruption", "security", "cve"),
    "high":     ("error", "exception", "broken", "regression", "fails"),
    "medium":   ("incorrect", "wrong", "unexpected", "slow"),
    "low":      ("typo", "alignment", "label", "tooltip"),
}


def classify(title: str, body: str, labels: list[str], code_hits: int) -> Classification:
    text = f"{title}\n{body}".lower()
    label_set = {l.lower() for l in labels}

    if "feature" in label_set or "enhancement" in label_set or "feature request" in label_set:
        bug_type = "feature"
    elif "docs" in label_set or "documentation" in label_set:
        bug_type = "docs"
    elif "question" in label_set or text.startswith("how do i") or "?" in title:
        bug_type = "question"
    elif "performance" in label_set or "perf" in label_set or "slow" in text:
        bug_type = "perf"
    else:
        bug_type = "bug"

    severity = "low"
    for level, words in _SEVERITY_KEYWORDS.items():
        if any(w in text for w in words):
            severity = level
            break

    confidence = 0.3
    if bug_type == "bug":        confidence += 0.2
    if code_hits >= 1:           confidence += 0.2
    if code_hits >= 5:           confidence += 0.1
    if severity in ("high", "critical"):
        confidence += 0.1
    if bug_type == "question":
        confidence = min(confidence, 0.2)
    confidence = max(0.0, min(1.0, confidence))

    return Classification(
        bug_type=bug_type,
        severity=severity,
        devinable_confidence=round(confidence, 2),
        rationale=f"bug_type from labels/text, severity from keyword scan, confidence boosted by {code_hits} code pointers",
    )


# ──────────────────────── Code locator (ripgrep) ────────────────────────


_IDENT_RE = re.compile(r"\b([A-Z][a-zA-Z0-9_]{3,}|[a-z_][a-z0-9_]{4,})\b")
_PATHLIKE_RE = re.compile(
    r"(?:^|[\s\"'(])((?:[\w\-./]+)?(?:superset|src|tests?)/[\w\-./]+\.(?:py|ts|tsx|js|jsx))",
    re.MULTILINE,
)


def _candidate_symbols(text: str, limit: int = 20) -> list[str]:
    stop = {
        "the", "this", "that", "with", "when", "from", "issue", "bug", "error",
        "expected", "actual", "should", "would", "could", "value", "result",
        "True", "False", "None", "self",
    }
    tokens = [t for t in _IDENT_RE.findall(text) if t not in stop]
    return [tok for tok, _ in Counter(tokens).most_common(limit)]


def _path_hints(text: str, limit: int = 10) -> list[str]:
    return [p for p, _ in Counter(_PATHLIKE_RE.findall(text)).most_common(limit)]


def locate(issue_text: str, max_files: int = 25) -> dict[str, list[str]]:
    fork = Path(settings.superset_fork_path)
    if not fork.exists():
        return {"symbol_matches": [], "stack_trace_files": []}

    stack_trace_files = [p for p in _path_hints(issue_text) if (fork / p).exists()][:max_files]
    symbols = _candidate_symbols(issue_text)
    if not symbols:
        return {"symbol_matches": [], "stack_trace_files": stack_trace_files}

    pattern = "|".join(re.escape(s) for s in symbols)
    try:
        proc = subprocess.run(
            ["rg", "-l", "-S", "-e", pattern, "--max-count", "1", str(fork)],
            capture_output=True, text=True, timeout=20,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return {"symbol_matches": [], "stack_trace_files": stack_trace_files}

    files = [line.removeprefix(str(fork) + "/") for line in proc.stdout.splitlines() if line]
    return {"symbol_matches": files[:max_files], "stack_trace_files": stack_trace_files}


# ──────────────────────── Case-file builder ────────────────────────


def build_case_file(issue: Issue, classification: Classification, code_pointers: dict) -> dict[str, Any]:
    """The JSON bundle Devin fetches via pre-signed GET. Shape per plan.md §2.3."""
    return {
        "issue": {
            "id": issue.id,
            "github_number": issue.github_number,
            "github_repo": issue.github_repo,
            "title": issue.title,
            "body": issue.body,
            "labels": issue.labels,
            "reporter": issue.reporter,
            "html_url": issue.html_url,
        },
        "reporter_narrative": issue.body,
        "code_pointers": {
            "stack_trace_files": code_pointers.get("stack_trace_files", []),
            "symbol_matches": code_pointers.get("symbol_matches", []),
        },
        "classification": classification.to_dict(),
        "acceptance_criteria": [
            "Reproduce the bug end-to-end before changing production code (see the autopilot-fix-recipe knowledge note).",
            "Open a pull request that fixes the bug and includes a regression test that fails without the fix.",
            "CI must be green before requesting review.",
        ],
        "budget": {"max_acu": 50, "max_wall_clock_min": 30},
    }


# ──────────────────────── pgvector dedup ────────────────────────


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


# ──────────────────────── Triage pipeline ────────────────────────


triage_runs_total = PromCounter(
    "autopilot_triage_runs_total",
    "Triage runs, by outcome.",
    ["outcome"],
)
triage_duration_seconds = Histogram(
    "autopilot_triage_duration_seconds",
    "Wall-clock duration of a triage run, by outcome.",
    ["outcome"],
)


def run_pipeline(issue_id: int) -> int:
    """Run the full triage pipeline for one issue. Returns the new triage_run id."""
    start = datetime.now(timezone.utc)
    db = SessionLocal()
    try:
        issue = db.get(Issue, issue_id)
        if issue is None:
            triage_runs_total.labels(outcome="missing_issue").inc()
            raise ValueError(f"issue {issue_id} not found")

        tr = TriageRun(issue_id=issue.id, status="running")
        db.add(tr); db.flush()

        try:
            text = f"{issue.title}\n\n{issue.body}"
            code_pointers = locate(text)
            classification = classify(issue.title, issue.body, issue.labels, len(code_pointers["symbol_matches"]))

            case = build_case_file(issue, classification, code_pointers)
            key = f"casefiles/issue-{issue.id}/triage-run-{tr.id}.json"
            s3_put_json(settings.s3_bucket_casefiles, key, case)

            tr.classification = classification.to_dict()
            tr.confidence = classification.devinable_confidence
            tr.case_file_s3_key = key
            tr.status = "ready_for_dispatch"
            tr.completed_at = datetime.now(timezone.utc)
            issue.status = "triaged"
            db.add(Event(
                entity_type="triage_run", entity_id=tr.id, event="completed",
                payload={"confidence": classification.devinable_confidence, "case_file_s3_key": key},
            ))
            db.commit()
            triage_runs_total.labels(outcome="ready_for_dispatch").inc()
            log.info("triage run %s done for issue %s (confidence=%.2f)", tr.id, issue.id, classification.devinable_confidence)
            return tr.id
        except Exception as exc:
            tr.status = "failed"
            tr.error = repr(exc)[:1000]
            tr.completed_at = datetime.now(timezone.utc)
            db.add(Event(entity_type="triage_run", entity_id=tr.id, event="failed", payload={"error": str(exc)}))
            db.commit()
            triage_runs_total.labels(outcome="failed").inc()
            raise
    finally:
        elapsed = (datetime.now(timezone.utc) - start).total_seconds()
        triage_duration_seconds.labels(outcome="any").observe(elapsed)
        db.close()


# ──────────────────────── Worker daemon ────────────────────────


def worker_loop() -> None:
    """Daemon thread: blocking-pop the Redis queue and run the pipeline for each item."""
    client = redis.from_url(settings.redis_url)
    log.info("triage worker listening on queue=%s", settings.triage_queue)
    while True:
        item = client.brpop([settings.triage_queue], timeout=5)
        if item is None:
            continue
        _, raw = item
        try:
            job = json.loads(raw)
            issue_id = int(job["issue_id"])
        except (ValueError, KeyError, TypeError) as exc:
            log.error("malformed job %r: %s", raw, exc)
            continue
        log.info("picked up issue_id=%s", issue_id)
        try:
            run_pipeline(issue_id)
        except Exception as exc:  # noqa: BLE001 — keep the worker alive
            log.exception("triage failed for issue %s: %s", issue_id, exc)
