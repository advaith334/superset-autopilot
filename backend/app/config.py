"""Unified settings for the single-container backend.

Union of what the previous four services (ingest, triage, dispatcher, monitor)
each had. Same env-var names; the .env file works unchanged."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ── Shared ──
    database_url: str = "postgresql+psycopg://autopilot:autopilot@postgres:5432/autopilot"
    redis_url: str = "redis://redis:6379/0"
    triage_queue: str = "triage"

    # ── Ingest ──
    github_webhook_secret: str = "changeme"
    github_target_repo: str = "advaith334/superset"
    dedup_threshold: float = 0.92

    # ── Triage ──
    superset_fork_path: str = "/superset-fork"

    # ── Devin ──
    devin_api_key: str = ""
    devin_org_id: str = ""
    devin_api_base: str = "https://api.devin.ai"
    devin_max_concurrent: int = 3
    devin_max_acu_per_day: int = 500
    devin_target_repo: str = "advaith334/superset"
    devin_github_secret_name: str = "AUTOPILOT_GITHUB_TOKEN"
    devin_knowledge_folder: str = "Superset Autopilot"
    devin_consumption_poll_seconds: int = 60
    devin_github_actor: str = "devin-ai-integration[bot]"

    # ── Dispatcher loop ──
    auto_dispatch_threshold: float = 0.0
    auto_dispatch_interval_seconds: int = 10

    # ── Monitor loops ──
    reconcile_interval_seconds: int = 30
    stub_session_lifetime_seconds: int = 60
    ci_watch_interval_seconds: int = 45
    ci_log_snippet_chars: int = 1500
    pr_watch_interval_seconds: int = 15

    # ── GitHub (monitor side) ──
    github_token: str = ""

    # ── AWS S3 ──
    aws_region: str = "us-east-1"
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    s3_endpoint_url: str | None = None
    s3_bucket_artifacts: str = ""
    s3_bucket_casefiles: str = ""
    s3_presign_ttl_seconds: int = 900


settings = Settings()
