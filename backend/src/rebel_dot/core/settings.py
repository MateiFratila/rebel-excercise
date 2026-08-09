from enum import StrEnum
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit

from argon2 import Type, extract_parameters
from argon2.exceptions import InvalidHashError
from pydantic import AnyUrl, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Environment(StrEnum):
    LOCAL = "local"
    TEST = "test"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    environment: Environment = Environment.LOCAL
    database_url: AnyUrl = AnyUrl("postgresql+asyncpg://faq:faq@localhost:5432/faq")
    openai_api_key: SecretStr
    shared_password_hash: SecretStr

    embedding_model: Literal["text-embedding-3-small", "text-embedding-3-large"] = (
        "text-embedding-3-small"
    )
    embedding_dimensions: int = Field(default=1536, ge=1, le=3072)
    chat_model: Literal[
        "gpt-5.4-mini",
        "gpt-5.4",
        "gpt-5.4-nano",
        "gpt-5.3-chat-latest",
    ] = "gpt-5.4-mini"
    collection_name: str = Field(default="support", min_length=1, max_length=200)

    session_cookie_name: str = Field(default="faq_session", min_length=1, max_length=100)
    session_cookie_secure: bool = True
    session_lifetime_seconds: int = Field(default=604800, ge=604800, le=604800)
    allowed_origins: Annotated[tuple[str, ...], NoDecode] = (
        "http://localhost:5173",
        "http://localhost:8000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:8000",
    )

    local_similarity_threshold: float = Field(default=0.84, ge=0, le=1)
    local_similarity_margin: float = Field(default=0.08, ge=0, le=1)
    scope_confidence_threshold: float = Field(default=0.75, ge=0, le=1)
    openai_timeout_seconds: float = Field(default=20, gt=0, le=120)
    openai_max_retries: int = Field(default=2, ge=0, le=5)
    embedding_batch_size: int = Field(default=64, ge=1, le=1000)
    job_poll_interval_seconds: float = Field(default=5, gt=0, le=300)
    job_stale_after_seconds: int = Field(default=300, ge=30, le=86400)
    max_question_chars: int = Field(default=2000, ge=1, le=16000)
    login_rate_limit: int = Field(default=5, ge=1, le=100)
    login_rate_window_seconds: int = Field(default=60, ge=1, le=3600)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def parse_allowed_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return tuple(origin.strip() for origin in value.split(",") if origin.strip())
        return value

    @field_validator("allowed_origins")
    @classmethod
    def validate_allowed_origins(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("at least one allowed origin is required")
        parsed_origins = tuple(urlsplit(origin) for origin in value)
        if any(
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.path
            or parsed.query
            or parsed.fragment
            or parsed.username is not None
            or parsed.password is not None
            for parsed in parsed_origins
        ):
            raise ValueError("allowed origins must be absolute HTTP(S) origins")
        return value

    @field_validator("shared_password_hash")
    @classmethod
    def validate_shared_password_hash(cls, value: SecretStr) -> SecretStr:
        try:
            parameters = extract_parameters(value.get_secret_value())
        except InvalidHashError as error:
            raise ValueError("shared password must be a valid Argon2id hash") from error
        if parameters.type is not Type.ID:
            raise ValueError("shared password must be provisioned as an Argon2id hash")
        return value

    @model_validator(mode="after")
    def validate_deployment_security(self) -> Self:
        if self.environment is not Environment.LOCAL and not self.session_cookie_secure:
            raise ValueError("non-local sessions require secure cookies")
        if self.environment is Environment.PRODUCTION and any(
            not origin.startswith("https://") for origin in self.allowed_origins
        ):
            raise ValueError("production origins must use HTTPS")
        return self
