from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "FlyRank AI Image Relevance Capstone"
    environment: str = "development"

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/flyrank"
    gemini_api_key: str | None = None

    ai_budget_usd: float = Field(
        default=0.0,
        ge=0.0,
        allow_inf_nan=False,
    )
    ai_max_calls: int = Field(default=200, ge=0)
    vision_confidence_threshold: float = Field(
        default=0.80,
        ge=0.0,
        le=1.0,
    )

    similarity_threshold: float = Field(
        default=0.70, ge=0.0, le=1.0, allow_inf_nan=False,
    )

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parent / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()