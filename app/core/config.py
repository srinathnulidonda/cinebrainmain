# app/core/config.py

import json
from functools import lru_cache
from typing import Annotated, Any, Literal

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

INSECURE_SECRETS = {"", "changeme", "secret", "dev-secret-key-change-in-production-min-32-chars"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=True, extra="ignore")

    ENV: Literal["development", "staging", "production"] = "production"
    SERVICE_NAME: str = "cinebrain-api"
    API_PREFIX: str = "/api/v2"
    LOG_LEVEL: str = "INFO"

    DATABASE_URL: SecretStr
    REDIS_URL: SecretStr = SecretStr("redis://localhost:6379/0")
    SECRET_KEY: SecretStr
    TMDB_API_KEY: SecretStr
    METRICS_API_KEY: SecretStr = SecretStr("")

    CORS_ORIGINS: Annotated[list[str], NoDecode] = []
    CORS_ALLOW_HEADERS: Annotated[list[str], NoDecode] = [
        "Content-Type",
        "Accept",
        "Accept-Language",
        "X-Request-ID",
        "X-Preferred-Languages",
        "X-Timezone",
    ]
    ALLOWED_HOSTS: Annotated[list[str], NoDecode] = ["*"]
    COOKIE_SAMESITE: Literal["lax", "strict", "none"] = "lax"
    COOKIE_MAX_AGE: int = 30 * 24 * 3600
    ACCEPT_LEGACY_SESSIONS: bool = False

    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT: int = 10
    DB_POOL_RECYCLE: int = 1800
    DB_COMMAND_TIMEOUT: int = 15
    DB_ECHO: bool = False

    TMDB_BASE_URL: str = "https://api.themoviedb.org/3"
    GEO_API_URL: str = "http://ip-api.com/json"
    HTTP_CONNECT_TIMEOUT: float = 3.0
    HTTP_READ_TIMEOUT: float = 8.0
    HTTP_MAX_RETRIES: int = 2
    HTTP_BACKOFF_BASE: float = 0.3
    HTTP_BACKOFF_CAP: float = 4.0
    CB_FAILURE_THRESHOLD: int = 5
    CB_RECOVERY_SECONDS: float = 20.0

    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_GENERAL_PER_MINUTE: int = 120
    RATE_LIMIT_SEARCH_PER_MINUTE: int = 30
    TRUST_PROXY_HEADERS: bool = False

    OTEL_EXPORTER_OTLP_ENDPOINT: str = ""
    RUN_WORKERS_IN_PROCESS: bool = False
    AUTO_CREATE_SCHEMA: bool = False

    SYNC_PAGES_PER_QUERY: int = 2
    SYNC_CONCURRENCY: int = 4
    SYNC_INTERVAL_SECONDS: int = 3600
    MODEL_REFRESH_SECONDS: int = 3600
    TRENDING_REFRESH_SECONDS: int = 900
    MODEL_POLL_SECONDS: int = 60
    RECO_MAX_ITEMS: int = 30000
    RECO_NEIGHBORS: int = 40
    RECO_INTERACTION_DAYS: int = 90
    RECO_MAX_INTERACTIONS: int = 1_000_000
    RECO_CF_CONFIDENCE: float = 20.0
    RECO_CF_SHRINKAGE: float = 5.0

    @field_validator("CORS_ORIGINS", "CORS_ALLOW_HEADERS", "ALLOWED_HOSTS", mode="before")
    @classmethod
    def parse_list(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = value.strip()
            if value.startswith("["):
                return json.loads(value)
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @model_validator(mode="after")
    def enforce_production_safety(self) -> "Settings":
        secret = self.SECRET_KEY.get_secret_value()
        if self.ENV != "development":
            if len(secret) < 32 or secret in INSECURE_SECRETS:
                raise ValueError("SECRET_KEY must be a unique value of at least 32 characters")
            if "*" in self.CORS_ORIGINS:
                raise ValueError("CORS_ORIGINS must list explicit origins when credentials are allowed")
        if self.ENV == "production" and self.ALLOWED_HOSTS == ["*"]:
            raise ValueError("ALLOWED_HOSTS must be set explicitly in production")
        return self

    @property
    def is_production(self) -> bool:
        return self.ENV == "production"

    @property
    def cookie_secure(self) -> bool:
        return self.ENV != "development" or self.COOKIE_SAMESITE == "none"

    @property
    def docs_enabled(self) -> bool:
        return not self.is_production


@lru_cache
def get_settings() -> Settings:
    return Settings()
