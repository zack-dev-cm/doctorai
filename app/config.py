from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    openai_api_key: str | None = None
    openai_model: str = "gpt-4.1-mini"
    openai_verifier_model: str = "gpt-4.1-mini"
    reasoning_effort: str | None = None
    google_api_key: str | None = None
    environment: str = "local"
    app_name: str = "DoctorAI"
    default_agent: str = "dermatologist"

    model_config = SettingsConfigDict(env_prefix="", env_file=".env", extra="ignore")


settings = Settings()
