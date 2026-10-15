from typing import Literal
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    app_env: str = "development"
    fact_extraction_mode: Literal["deterministic", "structured_llm"] = "deterministic"
    entailment_judge_enabled: bool = True
    max_request_bytes: int = 5_000_000
    document_retention_days: int = Field(default=7, ge=0)
    ocr_max_pages: int = Field(default=25, ge=1)
    database_url: str = "sqlite:///./discharge_explainer.db"
    api_access_token: str = ""

    llm_base_url: str = "http://localhost:11434/v1"
    model_id: str = "qwen3:1.7b"
    translation_judge_model_id: str = "qwen3:1.7b"
    llm_provider: Literal["ollama", "openai_compatible"] = "ollama"
    llm_api_key: str = ""

    cors_origins: str = "http://localhost:3000"

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / ".env",
        extra="ignore",
    )


settings = Settings()
