"""Settings for the backend (scaffold phase)."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://autopilot:autopilot@postgres:5432/autopilot"
    redis_url: str = "redis://redis:6379/0"


settings = Settings()
