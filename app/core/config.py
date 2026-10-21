from typing import Literal

from arq.connections import RedisSettings
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    node_env: Literal["development", "test", "production"] = "development"
    port: int = Field(default=8000, ge=1, le=65535)
    database_url: str = "postgresql://postgres:postgres@localhost:55433/rag_fastapi"
    redis_host: str = "localhost"
    redis_port: int = Field(default=6380, ge=1, le=65535)
    redis_password: str = ""
    redis_tls: bool = False
    redis_database: int = Field(default=0, ge=0)
    queue_name: str = "rag-fastapi:documents"
    api_key: str = ""
    metrics_api_key: str = ""
    cors_origin: str = "*"
    upload_max_file_bytes: int = Field(default=10485760, gt=0)
    request_body_limit_bytes: int = Field(default=1048576, gt=0)
    throttle_ttl_seconds: int = Field(default=60, gt=0)
    throttle_limit: int = Field(default=60, gt=0)
    embedding_provider: Literal["fake", "openai-compatible"] = "fake"
    llm_provider: Literal["fake", "openai-compatible"] = "fake"
    openai_compatible_base_url: str = ""
    openai_compatible_api_key: str = ""
    openai_compatible_timeout_ms: int = Field(default=30000, gt=0)
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = Field(default=1536, ge=1, le=2000)
    llm_model: str = "gpt-4.1-mini"
    search_backend: Literal["postgres", "qdrant-elasticsearch"] = "postgres"
    qdrant_url: str = "http://localhost:6334"
    qdrant_api_key: str = ""
    qdrant_collection: str = Field(default="rag_fastapi_chunks", pattern=r"^[a-zA-Z0-9_-]+$")
    elasticsearch_url: str = "http://localhost:9201"
    elasticsearch_api_key: str = ""
    elasticsearch_index: str = Field(default="rag-fastapi-chunks", pattern=r"^[a-z0-9][a-z0-9_-]*$")
    otel_enabled: bool = False
    otel_service_name: str = "rag-from-zero-fastapi"
    otel_exporter_otlp_traces_endpoint: str = "http://localhost:4318/v1/traces"

    @model_validator(mode="after")
    def validate_providers(self):
        if "openai-compatible" in (self.embedding_provider, self.llm_provider):
            if (
                not self.openai_compatible_base_url.startswith(("http://", "https://"))
                or not self.openai_compatible_api_key
            ):
                raise ValueError(
                    "OpenAI-compatible providers require an HTTP(S) base URL and API key"
                )
        if self.node_env == "production":
            if "fake" in (self.embedding_provider, self.llm_provider):
                raise ValueError("Production cannot use fake providers")
            if min(len(self.api_key), len(self.metrics_api_key)) < 32:
                raise ValueError("Production API and metrics keys must have at least 32 characters")
            if "*" in self.cors_origin:
                raise ValueError("Production requires explicit CORS origins")
        return self

    def redis_settings(self) -> RedisSettings:
        return RedisSettings(
            host=self.redis_host,
            port=self.redis_port,
            password=self.redis_password or None,
            ssl=self.redis_tls,
            database=self.redis_database,
            conn_timeout=3,
            conn_retries=1,
        )
