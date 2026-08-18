"""Конфигурация приложения через Pydantic Settings."""
from functools import lru_cache
from typing import List

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Глобальные настройки приложения.

    Загружаются из переменных окружения или файла .env.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Приложение
    app_env: str = "development"
    app_name: str = "Task Manager API"
    app_debug: bool = True
    app_host: str = "0.0.0.0"
    app_port: int = 8000

    # База данных
    database_url: str = "sqlite+aiosqlite:///./taskmanager.db"

    # JWT
    jwt_secret_key: str = "change-me-in-production-please-use-openssl-rand-hex-32"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # CORS
    cors_origins: str = "http://localhost:3000,http://localhost:8080"

    # Rate Limiting
    rate_limit_enabled: bool = False
    rate_limit_per_minute: int = 100
    redis_url: str = "redis://localhost:6379/0"

    # Файлы
    upload_dir: str = "./uploads"
    max_upload_size_mb: int = 10
    allowed_mime_types: str = (
        "image/png,image/jpeg,image/gif,application/pdf,text/plain,application/zip"
    )

    # SMTP
    smtp_enabled: bool = False
    smtp_host: str = "smtp.example.com"
    smtp_port: int = 587
    smtp_user: str = "no-reply@example.com"
    smtp_password: str = ""
    email_from: str = "no-reply@example.com"

    @property
    def cors_origins_list(self) -> List[str]:
        """Список разрешённых CORS-доменов."""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def allowed_mime_types_list(self) -> List[str]:
        """Список разрешённых MIME-типов файлов."""
        return [t.strip() for t in self.allowed_mime_types.split(",") if t.strip()]

    @field_validator("database_url")
    @classmethod
    def normalize_sqlite_url(cls, v: str) -> str:
        """Нормализуем URL SQLite для асинхронного драйвера."""
        if v.startswith("sqlite://") and not v.startswith("sqlite+aiosqlite://"):
            v = v.replace("sqlite://", "sqlite+aiosqlite://", 1)
        return v


@lru_cache
def get_settings() -> Settings:
    """Возвращает синглтон настроек."""
    return Settings()


settings = get_settings()
