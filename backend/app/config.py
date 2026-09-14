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


@lru_cache
def get_settings() -> Settings:
    return Settings()
