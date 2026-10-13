from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "Insurance Intelligence Hub"
    api_v1_prefix: str = "/api/v1"
    frontend_origin: str = "http://localhost:8002"
    pgvector_database_url: str = "sqlite:///./data/insurance.db"
    customer_database_url: str = ""
    openai_api_key: str = ""
    openai_chat_model: str = "gpt-4o-mini"
    openai_embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = Field(default=1536, ge=1)
    chunk_size: int = Field(default=1400, ge=300, le=5000)
    chunk_overlap: int = Field(default=180, ge=0, le=1000)
    upload_directory: Path = PROJECT_ROOT / "data" / "uploads"
    max_upload_bytes: int = Field(default=20 * 1024 * 1024, ge=1024)
    minimum_answer_similarity: float = Field(default=0.22, ge=-1, le=1)
    default_top_k: int = Field(default=5, ge=1, le=10)


@lru_cache
def get_settings() -> Settings:
    return Settings()
