from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Jira
    jira_url: str = "https://your-domain.atlassian.net"
    jira_email: str = ""
    jira_api_token: str = ""

    # LLM — pode ser OpenRouter ou LM Studio local
    openrouter_api_key: str = ""
    openrouter_model: str = "anthropic/claude-3-haiku"
    llm_base_url: str = ""          # ex: http://localhost:1234/v1 para LM Studio
    llm_api_key: str = "lm-studio"  # qualquer string funciona para LM Studio

    # Bot Framework (empty = unauthenticated, use for local emulator)
    microsoft_app_id: str = ""
    microsoft_app_password: str = ""

    # App
    log_level: str = "INFO"
    log_file: str = "logs/bot.log"
    port: int = 8000

    # Cache TTLs (seconds)
    identity_cache_ttl: int = 300
    conversation_cache_ttl: int = 300
    jira_cache_ttl: int = 60

    # Jira client
    jira_timeout: int = 10
    jira_max_retries: int = 3
    jira_circuit_breaker_threshold: int = 5
    jira_circuit_breaker_timeout: int = 60

    # Results
    ticket_list_limit: int = 10


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
