"""All external-world adapters in one module:
  - DevinClient + module-level wrappers
  - GitHub: HMAC verify, issue-event parse, outbound API
  - S3: pre-signed URL minting + object PUT
  - Embedding: fastembed wrapper
  - Redis triage queue helpers
"""

import hashlib
import hmac
import json
import logging
import uuid
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

import boto3
import httpx
import redis
from botocore.config import Config
from fastembed import TextEmbedding
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from .config import settings

log = logging.getLogger("clients")


# ════════════════════════ DEVIN API ════════════════════════


_TERMINAL_STATES = {"completed", "finished", "succeeded", "done"}
_FAILED_STATES = {"failed", "errored", "expired", "cancelled", "canceled"}


def _normalize_state(raw: str) -> str:
    s = (raw or "").lower()
    if s in _TERMINAL_STATES:
        return "completed"
    if s in _FAILED_STATES:
        return "failed"
    return "running"


def _extract_pr_url(data: dict) -> str | None:
    pr = data.get("pull_request")
    if isinstance(pr, str) and pr.startswith("http"):
        return pr
    if isinstance(pr, dict):
        return pr.get("url") or pr.get("html_url")
    for output in (data.get("structured_output") or []):
        if isinstance(output, dict) and output.get("type") == "pull_request":
            return output.get("url") or output.get("html_url")
    return None


@dataclass
class DevinSession:
    session_id: str
    state: str
    pr_url: str | None = None
    acu_consumed: float = 0.0
    cost_usd: float = 0.0
    tags: list[str] = field(default_factory=list)


@dataclass
class DailyConsumption:
    date: str
    acu_consumed: float
    sessions: int


class DevinClient:
    def __init__(self) -> None:
        self.api_key = settings.devin_api_key
        self.org_id = settings.devin_org_id
        self.base = settings.devin_api_base.rstrip("/")
        self._enabled = bool(self.api_key and self.org_id)

    @property
    def enabled(self) -> bool:
        return self._enabled

    def _url(self, path: str) -> str:
        return f"{self.base}/v3/organizations/{self.org_id}{path}"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    @retry(
        retry=retry_if_exception_type(httpx.HTTPError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    def _req(self, method: str, path: str, **kwargs) -> httpx.Response:
        r = httpx.request(method, self._url(path), headers=self._headers(), timeout=30.0, **kwargs)
        r.raise_for_status()
        return r

    # ── Sessions ──
    def create_session(self, prompt: str, tags: list[str] | None = None, playbook_id: str | None = None, metadata: dict | None = None) -> DevinSession:
        if not self._enabled:
            sid = f"stub-{uuid.uuid4().hex[:12]}"
            log.info("STUB: create_session sid=%s tags=%s", sid, tags)
            return DevinSession(session_id=sid, state="dispatched", tags=tags or [])
        body: dict = {"prompt": prompt}
        if tags: body["tags"] = tags
        if playbook_id: body["playbook_id"] = playbook_id
        if metadata: body["metadata"] = metadata
        data = self._req("POST", "/sessions", json=body).json()
        return DevinSession(
            session_id=str(data.get("session_id") or data.get("id") or ""),
            state=_normalize_state(data.get("status", "dispatched")),
            tags=list(data.get("tags") or tags or []),
        )

    def get_session(self, session_id: str) -> DevinSession:
        if not self._enabled or session_id.startswith("stub-"):
            return DevinSession(session_id=session_id, state="running")
        data = self._req("GET", f"/sessions/{session_id}").json()
        return DevinSession(
            session_id=session_id,
            state=_normalize_state(data.get("status", "running")),
            pr_url=_extract_pr_url(data),
            acu_consumed=float(data.get("acu_consumed", 0.0)),
            cost_usd=float(data.get("cost_usd", 0.0)),
            tags=list(data.get("tags") or []),
        )

    def tag_session(self, session_id: str, tags: list[str]) -> None:
        if not self._enabled or session_id.startswith("stub-"):
            return
        self._req("POST", f"/sessions/{session_id}/tags", json={"tags": tags})

    def send_message(self, session_id: str, message: str) -> None:
        if not self._enabled or session_id.startswith("stub-"):
            log.info("STUB: send_message %s: %s", session_id, message[:120])
            return
        self._req("POST", f"/sessions/{session_id}/messages", json={"message": message})

    # ── Knowledge ──
    def list_knowledge_notes(self) -> list[dict]:
        if not self._enabled: return []
        data = self._req("GET", "/knowledge/notes").json()
        if isinstance(data, list): return data
        return data.get("notes") or data.get("data") or []

    def create_knowledge_note(self, name: str, body: str, folder: str | None = None, trigger: str = "always") -> dict | None:
        if not self._enabled:
            log.info("STUB: create_knowledge_note name=%r", name); return None
        payload: dict = {"name": name, "body": body, "trigger": trigger}
        if folder: payload["folder"] = folder
        return self._req("POST", "/knowledge/notes", json=payload).json()

    # ── Secrets ──
    def list_secrets(self) -> list[dict]:
        if not self._enabled: return []
        return self._req("GET", "/secrets").json().get("secrets", [])

    def create_secret(self, name: str, value: str) -> dict | None:
        if not self._enabled:
            log.info("STUB: create_secret name=%s", name); return None
        return self._req("POST", "/secrets", json={"name": name, "value": value}).json()

    # ── Repository indexing ──
    def index_repository(self, repo_id: str) -> dict | None:
        if not self._enabled:
            log.info("STUB: index_repository %s", repo_id); return None
        try:
            return self._req("PUT", f"/repositories/{repo_id}").json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                log.info("repository-indexing endpoint not available on this org; skipping")
                return None
            raise

    # ── Consumption ──
    def get_daily_consumption(self) -> list[DailyConsumption]:
        if not self._enabled: return []
        try:
            data = self._req("GET", "/consumption/daily").json()
        except httpx.HTTPError as exc:
            log.warning("consumption fetch failed: %s", exc); return []
        out: list[DailyConsumption] = []
        for row in data.get("days", []) or data.get("data", []) or []:
            out.append(DailyConsumption(
                date=str(row.get("date", "")),
                acu_consumed=float(row.get("acu_consumed", row.get("acu", 0.0))),
                sessions=int(row.get("sessions", row.get("session_count", 0))),
            ))
        return out


# Module-level convenience used by the monitor loops.
_default_devin = DevinClient()


def devin_is_stub(session_id: str) -> bool:
    return session_id.startswith("stub-")


def devin_get_session(session_id: str, _dispatched_at=None) -> DevinSession:
    return _default_devin.get_session(session_id)


def devin_send_message(session_id: str, message: str) -> bool:
    try:
        _default_devin.send_message(session_id, message)
        return True
    except Exception:  # noqa: BLE001
        return False


# ════════════════════════ GITHUB ════════════════════════


def verify_signature(secret: str, body: bytes, signature_header: str | None) -> bool:
    """Constant-time HMAC-SHA256 check against the X-Hub-Signature-256 header."""
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    provided = signature_header.removeprefix("sha256=")
    return hmac.compare_digest(expected, provided)


def parse_issue_event(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Extract fields from an `issues` webhook payload; return None for actions we don't ingest."""
    action = payload.get("action")
    if action not in ("opened", "reopened"):
        return None
    issue = payload.get("issue") or {}
    repo = payload.get("repository") or {}
    return {
        "action": action,
        "github_number": issue.get("number"),
        "github_repo": repo.get("full_name", ""),
        "title": issue.get("title", ""),
        "body": issue.get("body") or "",
        "labels": [lbl.get("name", "") for lbl in issue.get("labels", [])],
        "reporter": (issue.get("user") or {}).get("login"),
        "html_url": issue.get("html_url", ""),
    }


def _gh_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def post_issue_comment(repo: str, issue_number: int, body: str) -> bool:
    if not settings.github_token:
        log.info("STUB GitHub: would comment on %s#%s: %s", repo, issue_number, body[:120])
        return False
    r = httpx.post(
        f"https://api.github.com/repos/{repo}/issues/{issue_number}/comments",
        headers=_gh_headers(), json={"body": body}, timeout=15.0,
    )
    return r.status_code < 300


def get_pr_head_sha(repo: str, pr_number: int) -> str | None:
    if not settings.github_token: return None
    try:
        r = httpx.get(f"https://api.github.com/repos/{repo}/pulls/{pr_number}", headers=_gh_headers(), timeout=15.0)
        r.raise_for_status()
        return r.json().get("head", {}).get("sha")
    except httpx.HTTPError as exc:
        log.warning("get_pr_head_sha failed for %s#%s: %s", repo, pr_number, exc)
        return None


def get_check_runs(repo: str, sha: str) -> list[dict]:
    if not settings.github_token: return []
    try:
        r = httpx.get(
            f"https://api.github.com/repos/{repo}/commits/{sha}/check-runs",
            headers=_gh_headers(), timeout=15.0,
        )
        r.raise_for_status()
        return r.json().get("check_runs", []) or []
    except httpx.HTTPError as exc:
        log.warning("get_check_runs failed for %s@%s: %s", repo, sha[:8], exc)
        return []


def list_recent_prs_by_author(repo: str, author: str, limit: int = 20) -> list[dict]:
    if not settings.github_token: return []
    try:
        r = httpx.get(
            "https://api.github.com/search/issues",
            headers=_gh_headers(),
            params={"q": f"repo:{repo} is:pr author:{author}", "per_page": limit, "sort": "created", "order": "desc"},
            timeout=15.0,
        )
        r.raise_for_status()
        return r.json().get("items", []) or []
    except httpx.HTTPError as exc:
        log.warning("list_recent_prs_by_author failed for %s author=%s: %s", repo, author, exc)
        return []


# ════════════════════════ S3 ════════════════════════


_s3 = boto3.client(
    "s3",
    region_name=settings.aws_region,
    aws_access_key_id=settings.aws_access_key_id,
    aws_secret_access_key=settings.aws_secret_access_key,
    endpoint_url=settings.s3_endpoint_url or None,
    config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
)


def s3_put_object(bucket: str, key: str, body: bytes, content_type: str = "application/octet-stream") -> tuple[str, int]:
    _s3.put_object(Bucket=bucket, Key=key, Body=body, ContentType=content_type)
    return hashlib.sha256(body).hexdigest(), len(body)


def s3_put_json(bucket: str, key: str, payload: dict) -> tuple[str, int]:
    body = json.dumps(payload, default=str).encode("utf-8")
    return s3_put_object(bucket, key, body, "application/json")


def s3_presign_get(bucket: str, key: str, ttl_seconds: int | None = None) -> str:
    return _s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=ttl_seconds or settings.s3_presign_ttl_seconds,
    )


# ════════════════════════ EMBEDDING ════════════════════════


EMBEDDING_DIM = 384
_EMBED_MODEL_NAME = "BAAI/bge-small-en-v1.5"


@lru_cache(maxsize=1)
def _embed_model() -> TextEmbedding:
    return TextEmbedding(model_name=_EMBED_MODEL_NAME)


def embed(text: str) -> list[float]:
    """384-dim fastembed embedding. Truncates very long inputs to bound latency."""
    if not text.strip():
        text = "(empty)"
    vectors = list(_embed_model().embed([text[:4000]]))
    return vectors[0].tolist()


# ════════════════════════ REDIS QUEUE ════════════════════════


_redis = redis.from_url(settings.redis_url)


def enqueue_triage(issue_id: int) -> None:
    _redis.lpush(settings.triage_queue, json.dumps({"issue_id": issue_id}))


def triage_queue_depth() -> int:
    return int(_redis.llen(settings.triage_queue))
