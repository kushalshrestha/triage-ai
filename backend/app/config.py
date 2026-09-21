from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://platform:platform@db:5432/support_platform"  # pragma: allowlist secret
    anthropic_api_key: str = ""
    ollama_base_url: str = "http://ollama:11434"
    jwt_secret_key: str = "change-me-in-real-deployments"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    cors_allowed_origins: list[str] = ["http://localhost:5173"]
    embedding_model_name: str = "all-MiniLM-L6-v2"
    reranker_model_name: str = "cross-encoder/ms-marco-MiniLM-L6-v2"
    ollama_model_name: str = "llama3.2:1b"
    claude_model_name: str = "claude-haiku-4-5-20251001"
    draft_confidence_threshold: float = 0.5
    auto_respond_confidence_threshold: float = 0.8
    # Rate limits on AI-facing endpoints, see ADR-0018. Triage is
    # tightest since it can spend real Claude money; search is loosest
    # since it's read-only and the cheapest model call (local
    # embedding only).
    triage_rate_limit_per_minute: int = 5
    knowledge_ingest_rate_limit_per_minute: int = 20
    knowledge_search_rate_limit_per_minute: int = 30


@lru_cache
def get_settings() -> Settings:
    return Settings()
