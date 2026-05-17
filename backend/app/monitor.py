"""Four background monitors:
  - reconciler:          poll Devin session state → update our DB row
  - pr_watcher:          poll GitHub for Devin-opened PRs → link + send wrap-up
  - ci_watcher:          poll PR check-runs → send Devin CI-fail follow-up
  - consumption_poller:  poll Devin /consumption/daily → Prometheus gauges

All four are launched as daemon threads from main.py on app startup.
"""

import logging
import re
import threading
import time
from datetime import datetime, timezone
from typing import Optional

from prometheus_client import Counter, Gauge
from sqlalchemy import select

from .clients import (
    devin_get_session, devin_send_message,
    get_check_runs, get_pr_head_sha, list_recent_prs_by_author,
)
from .clients import DevinClient
from .config import settings
from .models import DevinSession, Event, Issue, PullRequest, SessionLocal

log = logging.getLogger("monitor")


# ════════════════════ Reconciler ════════════════════

reconciler_ticks = Counter(
    "autopilot_reconciler_ticks_total",
    "Reconciler iterations, by outcome.",
    ["outcome"],
)
sessions_in_flight = Gauge(
    "autopilot_sessions_in_flight",
    "Devin sessions currently in non-terminal state.",
)
session_outcomes = Counter(
    "autopilot_session_outcomes_total",
    "Devin session terminal outcomes.",
    ["state"],
)


def _reconcile_once() -> None:
    db = SessionLocal()
    try:
        in_flight = db.execute(
            select(DevinSession).where(DevinSession.state.in_(("dispatched", "running")))
        ).scalars().all()
        sessions_in_flight.set(len(in_flight))

        for s in in_flight:
            try:
                state = devin_get_session(s.devin_session_id, s.dispatched_at)
            except Exception as exc:  # noqa: BLE001
                log.exception("reconcile %s failed: %s", s.devin_session_id, exc)
                reconciler_ticks.labels(outcome="error").inc()
                continue

            old_state = s.state
            s.state = state.state
            s.acu_consumed = state.acu_consumed
            s.cost_usd = state.cost_usd
            if state.state in ("completed", "failed"):
                s.completed_at = datetime.now(timezone.utc)
                session_outcomes.labels(state=state.state).inc()
            if old_state != state.state:
                db.add(Event(
                    entity_type="devin_session", entity_id=s.id,
                    event=f"state:{state.state}",
                    payload={"acu": state.acu_consumed, "cost_usd": state.cost_usd},
                ))
                log.info("session %s: %s -> %s", s.devin_session_id, old_state, state.state)

        db.commit()
        reconciler_ticks.labels(outcome="ok").inc()
    finally:
        db.close()


def reconciler_loop() -> None:
    log.info("reconciler started (interval=%ss)", settings.reconcile_interval_seconds)
    while True:
        try:
            _reconcile_once()
        except Exception as exc:  # noqa: BLE001
            log.exception("reconciler loop error: %s", exc)
            reconciler_ticks.labels(outcome="loop_error").inc()
        time.sleep(settings.reconcile_interval_seconds)


# ════════════════════ PR watcher ════════════════════

pr_links_total = Counter(
    "autopilot_pr_links_total",
    "PRs linked to sessions by the GitHub watcher, by outcome.",
    ["outcome"],
)

_FIXES_RE = re.compile(r"(?:fixes|closes|resolves)\s+#(\d+)", re.IGNORECASE)
_PR_URL_RE = re.compile(r"https://github\.com/([^/]+/[^/]+)/pull/(\d+)")


def _wrap_up_message(pr_url: str, pr_number: int) -> str:
    return (
        f"The autopilot has detected and linked your PR (#{pr_number}: {pr_url}). "
        f"Post a one-line summary here and stop — no need to iterate further. "
        f"This session stays open so I can ping you if CI fails."
    )


def _extract_issue_number(body: str | None) -> Optional[int]:
    if not body:
        return None
    m = _FIXES_RE.search(body)
    return int(m.group(1)) if m else None


def _link_pr(db, session: DevinSession, pr: dict) -> bool:
    url = pr.get("html_url") or pr.get("url") or ""
    m = _PR_URL_RE.match(url)
    if not m:
        return False
    repo, num = m.group(1), int(m.group(2))

    exists = db.execute(
        select(PullRequest).where(
            PullRequest.github_repo == repo, PullRequest.github_pr_number == num
        )
    ).scalar_one_or_none()
    if exists is not None:
        return False

    db.add(PullRequest(
        session_id=session.id, github_pr_number=num, github_repo=repo,
        html_url=url, merge_state="open",
    ))
    db.add(Event(
        entity_type="devin_session", entity_id=session.id,
        event="pr_linked_via_github", payload={"pr": num, "repo": repo},
    ))

    # PR linked = the session delivered its primary output. Flip our state
    # to 'completed' so the dashboard reflects reality even if Devin's own
    # session.status is still 'running' or transitions to 'suspended'.
    if session.state not in ("completed", "failed"):
        session.state = "completed"
        session.completed_at = datetime.now(timezone.utc)
        db.add(Event(
            entity_type="devin_session", entity_id=session.id,
            event="state:completed", payload={"reason": "pr_linked", "pr": num},
        ))

    already_wrapped = db.execute(
        select(Event).where(
            Event.entity_type == "devin_session",
            Event.entity_id == session.id,
            Event.event == "wrap_up_message_sent",
        ).limit(1)
    ).scalar_one_or_none()

    if already_wrapped is None:
        delivered = devin_send_message(session.devin_session_id, _wrap_up_message(url, num))
        db.add(Event(
            entity_type="devin_session", entity_id=session.id,
            event="wrap_up_message_sent", payload={"pr": num, "delivered": delivered},
        ))
        db.flush()
        log.info("wrap-up %s for session %s (PR #%s)", "sent" if delivered else "stubbed", session.devin_session_id, num)

    return True


def _backfill_completed_for_linked_prs(db) -> int:
    stale = db.execute(
        select(DevinSession)
        .join(PullRequest, PullRequest.session_id == DevinSession.id)
        .where(DevinSession.state.in_(("dispatched", "running")))
        .distinct()
    ).scalars().all()
    if not stale:
        return 0
    now = datetime.now(timezone.utc)
    for s in stale:
        s.state = "completed"
        s.completed_at = now
        db.add(Event(
            entity_type="devin_session", entity_id=s.id,
            event="state:completed", payload={"reason": "backfill_pr_already_linked"},
        ))
        log.info("backfilled session %s → completed", s.devin_session_id)
    return len(stale)


def _pr_watcher_tick() -> None:
    if not settings.github_token:
        return

    db = SessionLocal()
    try:
        if _backfill_completed_for_linked_prs(db):
            db.commit()

        in_flight = db.execute(
            select(DevinSession)
            .where(DevinSession.state.in_(("dispatched", "running")))
            .order_by(DevinSession.dispatched_at.desc())
        ).scalars().all()
        if not in_flight:
            return

        repos: set[str] = set()
        for s in in_flight:
            issue = db.get(Issue, s.issue_id)
            if issue is not None:
                repos.add(issue.github_repo)

        for repo in repos:
            prs = list_recent_prs_by_author(repo, settings.devin_github_actor, limit=30)
            for pr in prs:
                # Only consider PRs created after at least one in-flight session
                # was dispatched. Without this, a stale GitHub PR from an earlier
                # demo run can be misattributed to a brand-new session after a
                # state wipe.
                pr_created_at_raw = pr.get("created_at")
                if not pr_created_at_raw:
                    continue
                try:
                    pr_created_at = datetime.fromisoformat(pr_created_at_raw.replace("Z", "+00:00"))
                except (TypeError, ValueError):
                    continue

                issue_num = _extract_issue_number(pr.get("body"))
                target: Optional[DevinSession] = None

                if issue_num is not None:
                    issue = db.execute(
                        select(Issue).where(Issue.github_repo == repo, Issue.github_number == issue_num)
                    ).scalar_one_or_none()
                    if issue is not None:
                        candidate = next((s for s in in_flight if s.issue_id == issue.id), None)
                        if candidate is not None and pr_created_at >= candidate.dispatched_at:
                            target = candidate

                if target is None:
                    for s in in_flight:
                        if pr_created_at < s.dispatched_at:
                            continue
                        issue = db.get(Issue, s.issue_id)
                        if issue is None or issue.github_repo != repo:
                            continue
                        if db.execute(select(PullRequest).where(PullRequest.session_id == s.id).limit(1)).scalar_one_or_none() is None:
                            target = s
                            break

                if target is None:
                    continue

                if _link_pr(db, target, pr):
                    pr_links_total.labels(outcome="linked").inc()

        db.commit()
    finally:
        db.close()


def pr_watcher_loop() -> None:
    log.info("pr_watcher started (interval=%ss, actor=%s)",
             settings.pr_watch_interval_seconds, settings.devin_github_actor)
    while True:
        try:
            _pr_watcher_tick()
        except Exception as exc:  # noqa: BLE001
            log.exception("pr_watcher tick failed: %s", exc)
            pr_links_total.labels(outcome="error").inc()
        time.sleep(settings.pr_watch_interval_seconds)


# ════════════════════ CI watcher ════════════════════

ci_followups_sent = Counter(
    "autopilot_ci_followups_sent_total",
    "Devin follow-up messages sent on CI failure, by outcome.",
    ["outcome"],
)

# In-memory dedup: (session_id, check_run_id) → conclusion we already messaged about.
_followed_up: dict[tuple[str, int], str] = {}


def _failing_runs(check_runs: list[dict]) -> list[dict]:
    return [
        c for c in check_runs
        if c.get("status") == "completed" and c.get("conclusion") in ("failure", "timed_out")
    ]


def _format_ci_message(repo: str, pr_number: int, runs: list[dict]) -> str:
    lines = [
        f"CI is failing on your PR https://github.com/{repo}/pull/{pr_number}.",
        "", "Failed check runs:",
    ]
    for r in runs[:5]:
        name = r.get("name", "?")
        url = r.get("html_url") or r.get("details_url") or ""
        summary = (r.get("output") or {}).get("summary") or ""
        lines.append(f"- **{name}** — {r.get('conclusion')}  {url}")
        if summary:
            lines.append(f"  ```\n  {summary[: settings.ci_log_snippet_chars]}\n  ```")
    lines += ["", "Please investigate, push another commit to the same branch, and continue."]
    return "\n".join(lines)


def _check_one_pr(pr: PullRequest, session: DevinSession) -> Optional[str]:
    sha = get_pr_head_sha(pr.github_repo, pr.github_pr_number)
    if sha is None:
        return None
    runs = get_check_runs(pr.github_repo, sha)
    failing = _failing_runs(runs)
    if not failing:
        return None
    new_failures = [
        r for r in failing
        if _followed_up.get((session.devin_session_id, int(r["id"]))) != r.get("conclusion")
    ]
    if not new_failures:
        return None
    msg = _format_ci_message(pr.github_repo, pr.github_pr_number, new_failures)
    ok = devin_send_message(session.devin_session_id, msg)
    for r in new_failures:
        _followed_up[(session.devin_session_id, int(r["id"]))] = r.get("conclusion", "")
    return "sent" if ok else "stub"


def _ci_watcher_tick() -> None:
    db = SessionLocal()
    try:
        rows = db.execute(
            select(PullRequest, DevinSession)
            .join(DevinSession, DevinSession.id == PullRequest.session_id)
            .where(PullRequest.merge_state == "open")
            .where(DevinSession.state != "failed")
        ).all()
        for pr, session in rows:
            try:
                outcome = _check_one_pr(pr, session)
                if outcome:
                    ci_followups_sent.labels(outcome=outcome).inc()
                    db.add(Event(
                        entity_type="devin_session", entity_id=session.id,
                        event="ci_followup", payload={"pr": pr.github_pr_number, "delivered": outcome == "sent"},
                    ))
                    db.commit()
                    log.info("CI follow-up %s for session %s (PR #%s)", outcome, session.devin_session_id, pr.github_pr_number)
            except Exception as exc:  # noqa: BLE001
                log.exception("ci_watcher _check_one_pr failed: %s", exc)
    finally:
        db.close()


def ci_watcher_loop() -> None:
    log.info("ci_watcher started (interval=%ss)", settings.ci_watch_interval_seconds)
    while True:
        try:
            _ci_watcher_tick()
        except Exception as exc:  # noqa: BLE001
            log.exception("ci_watcher tick failed: %s", exc)
        time.sleep(settings.ci_watch_interval_seconds)


# ════════════════════ Consumption poller ════════════════════

devin_acu_today = Gauge(
    "autopilot_devin_acu_today",
    "Devin ACU consumed in the current day (from Devin's consumption API).",
)
devin_sessions_today = Gauge(
    "autopilot_devin_sessions_today",
    "Devin sessions started in the current day (from Devin's consumption API).",
)
devin_consumption_last_fetch_seconds = Gauge(
    "autopilot_devin_consumption_last_fetch_seconds",
    "Unix timestamp of the last successful consumption fetch.",
)

_consumption_client = DevinClient()


def _consumption_tick() -> None:
    days = _consumption_client.get_daily_consumption()
    if not days:
        return
    today_iso = datetime.now(timezone.utc).date().isoformat()
    today = next((d for d in days if d.date.startswith(today_iso)), days[-1])
    devin_acu_today.set(today.acu_consumed)
    devin_sessions_today.set(today.sessions)
    devin_consumption_last_fetch_seconds.set(time.time())


def consumption_loop() -> None:
    if not _consumption_client.enabled:
        log.info("Devin disabled; consumption poller emits zero gauges")
    log.info("consumption poller started (interval=%ss)", settings.devin_consumption_poll_seconds)
    while True:
        try:
            _consumption_tick()
        except Exception as exc:  # noqa: BLE001
            log.exception("consumption tick failed: %s", exc)
        time.sleep(settings.devin_consumption_poll_seconds)


# ════════════════════ Public starters ════════════════════


def start_all() -> None:
    """Launch all four monitor daemons. Called once from main on startup."""
    threading.Thread(target=reconciler_loop, name="reconciler", daemon=True).start()
    threading.Thread(target=pr_watcher_loop, name="pr-watcher", daemon=True).start()
    threading.Thread(target=ci_watcher_loop, name="ci-watcher", daemon=True).start()
    threading.Thread(target=consumption_loop, name="consumption-poller", daemon=True).start()
