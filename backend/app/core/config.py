"""
Application configuration loaded from environment variables or .env file.

All settings use pydantic-settings for type-safe validation.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppMode(StrEnum):
    """Deployment mode determines available features and UI simplifications."""

    PERSONAL = "personal"
    ENTERPRISE = "enterprise"


class AIMode(StrEnum):
    """AI provider routing strategy."""

    DISABLED = "disabled"  # No AI features
    BYOK = "byok"  # User provides their own API key (Community)
    TURNKEY = "turnkey"  # ApexLedger Cloud Gateway (Enterprise)
    LOCAL = "local"  # Local LLM (Ollama / vLLM)


class Settings(BaseSettings):
    """Global application settings.

    Values are read from environment variables or a `.env` file located
    next to the running process.  Every setting has a sensible default
    so the app can start with zero configuration for development.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="APEX_",
        case_sensitive=False,
    )

    # --- App ---
    app_name: str = "ApexLedger"
    app_version: str = "0.1.0"
    app_mode: AppMode = AppMode.PERSONAL
    debug: bool = False

    # --- Database ---
    database_url: PostgresDsn = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/apexledger",
        description="Async SQLAlchemy connection string.",
    )

    # --- JWT Auth ---
    jwt_secret: str = Field(
        default="CHANGE-ME-IN-PRODUCTION",
        description="Secret key for signing JWT tokens.",
    )
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60 * 24  # 24 hours

    # --- AI ---
    ai_mode: AIMode = AIMode.DISABLED
    ai_openai_api_key: str | None = None
    ai_openai_base_url: str | None = None
    ai_ollama_base_url: str = "http://localhost:11434"
    ai_ollama_model: str = "llama3.1"

    # --- Update Checker (Opt-In) ---
    update_check_enabled: bool = True
    update_check_url: str = "https://api.apexledger.com/v1/releases/latest"
    update_check_interval_hours: int = 24

    # --- License (Enterprise) ---
    license_key: str | None = None
    license_server_url: str = "https://api.apexledger.com/v1/license/validate"


settings = Settings()
