"""External-world adapters:
  - GitHub: HMAC verify, issue-event parse
  - S3: pre-signed URL minting + object PUT
  - Embedding: fastembed wrapper
  - Redis triage queue helpers

Later phases extend this with the Devin API client."""

import hashlib
import hmac
import json
import logging
from functools import lru_cache
from typing import Any

import boto3
import redis
from botocore.config import Config
from fastembed import TextEmbedding

from .config import settings

log = logging.getLogger("clients")


# ════════════════════════ GITHUB ════════════════════════


def verify_signature(secret: str, body: bytes, signature_header: str | None) -> bool:
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    provided = signature_header.removeprefix("sha256=")
    return hmac.compare_digest(expected, provided)


def parse_issue_event(payload: dict[str, Any]) -> dict[str, Any] | None:
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
