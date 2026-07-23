from __future__ import annotations

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables or a local .env file."""

    telegram_bot_token: SecretStr
    telegram_recipient_chat_id: int | None = None
    telegram_bot_username: str = "project_manager_job_bot"
    database_url: str = "postgresql+asyncpg://job_bot:job_bot@postgres:5432/job_bot"
    hh_enabled: bool = True
    hh_poll_interval_seconds: int = 300
    hh_request_timeout_seconds: float = 20
    hh_user_agent: str = "project-manager-job-bot/0.1"
    greenhouse_boards: str = ""
    lever_sites: str = ""
    log_level: str = "INFO"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    def greenhouse_board_tokens(self) -> tuple[str, ...]:
        return _csv_values(self.greenhouse_boards)

    def lever_site_names(self) -> tuple[str, ...]:
        return _csv_values(self.lever_sites)


def _csv_values(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())
