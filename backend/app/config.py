"""Settings for the backend."""

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
    github_token: str = ""
    dedup_threshold: float = 0.92

    # ── Triage ──
    superset_fork_path: str = "/superset-fork"

    # ── AWS S3 ──
    aws_region: str = "us-east-1"
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    s3_endpoint_url: str | None = None
    s3_bucket_artifacts: str = ""
    s3_bucket_casefiles: str = ""
    s3_presign_ttl_seconds: int = 900


settings = Settings()
