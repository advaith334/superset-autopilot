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


settings = Settings()
