from functools import lru_cache

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, read from environment variables (or a .env file)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Callers must send this value in the X-API-Key header to upload files or create links.
    api_key: SecretStr = Field(min_length=16)

    # HMAC key used to sign download tokens. Rotating it invalidates every outstanding link.
    link_default_ttl_seconds: int = Field(default=900, ge=60)
    link_max_ttl_seconds: int = Field(default=86400, ge=60)
    link_signing_key: SecretStr = Field(min_length=32)

    # Externally reachable base URL; used to build the links handed to users.
    public_base_url: str = "http://localhost:8000"

    # S3-compatible object storage (RustFS by default). Endpoint is host:port, without a scheme.
    s3_endpoint: str = "localhost:9000"
    s3_region: str = "us-east-1"
    s3_access_key: str = "rustfsadmin"
    s3_secret_key: SecretStr = SecretStr("rustfsadmin")
    s3_secure: bool = False
    s3_bucket: str = "downloads"

    @field_validator("public_base_url")
    @classmethod
    def _strip_trailing_slash(cls, value: str) -> str:
        """Remove trailing slashes so links can be built as f"{base}/path"."""
        return value.rstrip("/")

    @model_validator(mode="after")
    def _check_ttl_seconds(self) -> "Settings":
        """Ensure that the default TTL does not exceed the maximum TTL"""
        if self.link_default_ttl_seconds > self.link_max_ttl_seconds:
            raise ValueError("LINK_DEFAULT_TTL_SECONDS must not exceed LINK_MAX_TTL_SECONDS")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # values come from the environment
