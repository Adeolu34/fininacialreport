from __future__ import annotations

from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/financial_reports"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Portal 1
    portal_1_url: str = ""
    portal_1_user: str = ""
    portal_1_pass: str = ""

    # Portal 2
    portal_2_url: str = ""
    portal_2_user: str = ""
    portal_2_pass: str = ""

    # SMTP
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_pass: str = ""

    # Recipients — stored as comma-separated string
    report_recipients: str = ""

    # Directories
    downloads_dir: str = "/app/downloads"
    reports_output_dir: str = "/app/reports"
    screenshots_dir: str = "/app/screenshots"

    # Logging
    log_level: str = "INFO"

    # Scheduler
    report_schedule_hour: int = 8
    report_schedule_minute: int = 0

    @property
    def recipients_list(self) -> List[str]:
        """Return REPORT_RECIPIENTS as a list of email strings."""
        if not self.report_recipients:
            return []
        return [r.strip() for r in self.report_recipients.split(",") if r.strip()]

    @property
    def celery_broker_url(self) -> str:
        return self.redis_url

    @property
    def celery_result_backend(self) -> str:
        return self.redis_url


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
