"""Runtime configuration, read from the environment (and a local .env in development)."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All knobs the agent needs. Names match the deployment secrets one-to-one."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: SecretStr = Field(description="Application role; never used to run model SQL.")
    database_url_ro: SecretStr = Field(
        description="Read-only role; the only role model SQL runs as."
    )

    sql_model: str = Field(
        default="ollama/qwen2.5-coder:7b", description="LiteLLM model id for SQL."
    )
    chat_model: str = Field(
        default="ollama/qwen2.5:7b-instruct", description="LiteLLM model id for prose."
    )
    ollama_base_url: str = "http://localhost:11434"
    azure_openai_api_key: SecretStr | None = None
    azure_openai_endpoint: str | None = None

    langfuse_public_key: SecretStr | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_base_url: str = "https://cloud.langfuse.com"

    sql_row_limit: int = Field(
        default=500, ge=1, le=10_000, description="LIMIT injected when absent."
    )
    sql_timeout_seconds: float = Field(
        default=10.0, gt=0, description="Client-side statement timeout."
    )
    sql_max_cost: float = Field(
        default=1_000_000.0, gt=0, description="EXPLAIN total-cost ceiling."
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
