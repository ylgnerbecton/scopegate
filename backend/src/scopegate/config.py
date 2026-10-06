"""Validated runtime inputs. Local fixtures are never production identity."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SCOPEGATE_", env_file=ROOT / ".env", extra="ignore", hide_input_in_errors=True
    )

    environment: Literal["local", "test", "production"] = "local"
    component: Literal["api", "worker", "bootstrap", "operations"] = "api"
    database_url: str = Field(
        default="postgresql+psycopg://scopegate_app:development@localhost:5547/scopegate", repr=False
    )
    migration_database_url: str = Field(default="", repr=False)
    public_origin: str = "http://localhost:5187"
    oidc_issuer: str = "http://localhost:8901"
    oidc_internal_url: str = "http://localhost:8901"
    oidc_client_id: str = "scopegate-local"
    oidc_redirect_uri: str = "http://localhost:5187/auth/callback"
    session_cookie: str = "scopegate_session"
    secure_cookies: bool = False
    session_secret: str = Field(default="", repr=False)
    cursor_secret: str = Field(default="", repr=False)
    outbox_key: str = Field(default="", repr=False)
    platform_key: str = Field(default="", repr=False)
    catalog_key: str = Field(default="", repr=False)
    migration_ops_key: str = Field(default="", repr=False)
    journal_directory: Path = ROOT / "var/journal"
    mailbox_directory: Path = ROOT / "var/mailbox"
    local_delivery_enabled: bool = True
    pool_size: int = 4
    max_overflow: int = 1
    log_level: str = "INFO"
    otel_export_enabled: bool = True

    @model_validator(mode="after")
    def validate_trust(self):
        self._validate_credentials()
        self._validate_connections()
        self._validate_deployment()
        return self

    def _validate_credentials(self) -> None:
        required = {
            "api": ("session_secret", "cursor_secret", "platform_key", "catalog_key"),
            "worker": (),
            "bootstrap": (),
            "operations": ("migration_ops_key",),
        }
        for name in required[self.component]:
            if len(getattr(self, name)) < 32:
                raise ValueError(f"{name} must contain at least 32 characters; run make setup")
        from cryptography.fernet import Fernet

        Fernet(self.outbox_key.encode())
        if self.component == "api" and self.platform_key == self.catalog_key:
            raise ValueError("Publisher and platform credentials must differ")

    def _validate_connections(self) -> None:
        if self.pool_size < 1 or self.max_overflow < 0 or self.pool_size + self.max_overflow > 5:
            raise ValueError("Per-process connection allocation exceeds five")
        if self.component == "bootstrap" and not self.migration_database_url:
            raise ValueError("Bootstrap requires a separately supplied migration database URL")

    def _validate_deployment(self) -> None:
        if self.environment == "production":
            if not self.oidc_issuer.startswith("https://") or "localhost" in self.oidc_issuer:
                raise ValueError("Production requires an external HTTPS identity provider")
            if self.local_delivery_enabled or not self.secure_cookies:
                raise ValueError("Local delivery and insecure cookies cannot reach production")
            raise ValueError(
                "Live journal, delivery and host adapters require separate operational integration"
            )


@lru_cache
def get_settings() -> Settings:
    return Settings()
