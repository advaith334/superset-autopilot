"""External-world adapters (Phase 1):
  - GitHub: HMAC verify, issue-event parse
  - Embedding: fastembed wrapper
  - Redis triage queue helpers

Later phases extend this module with S3 and the Devin API client."""

import hashlib
import hmac
import json
import logging
from functools import lru_cache
from typing import Any

import redis
from fastembed import TextEmbedding

from .config import settings

log = logging.getLogger("clients")


# ════════════════════════ GITHUB ════════════════════════


def verify_signature(secret: str, body: bytes, signature_header: str | None) -> bool:
    """Constant-time HMAC-SHA256 check against X-Hub-Signature-256."""
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


# ════════════════════════ EMBEDDING ════════════════════════


EMBEDDING_DIM = 384
_EMBED_MODEL_NAME = "BAAI/bge-small-en-v1.5"


@lru_cache(maxsize=1)
def _embed_model() -> TextEmbedding:
    return TextEmbedding(model_name=_EMBED_MODEL_NAME)


def embed(text: str) -> list[float]:
    """384-dim fastembed embedding. Truncates long inputs to bound latency."""
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
