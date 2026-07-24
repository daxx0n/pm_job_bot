from __future__ import annotations

from pydantic import SecretStr, field_validator, model_validator
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
    remotive_enabled: bool = True
    remotive_refresh_seconds: int = 21_600
    we_work_remotely_enabled: bool = True
    himalayas_enabled: bool = True
    jobicy_enabled: bool = True
    jobicy_refresh_seconds: int = 21_600
    rss_refresh_seconds: int = 1_800
    habr_career_enabled: bool = True
    telegram_public_enabled: bool = True
    telegram_public_channels: str = (
        "product_project_job,pmclub,geekjobs"
    )
    telegram_public_additional_channels: str = "budujobs,remotejobss"
    public_pages_refresh_seconds: int = 1_800
    email_alerts_enabled: bool = False
    email_imap_host: str = "imap.gmail.com"
    email_imap_port: int = 993
    email_imap_username: str = ""
    email_imap_app_password: SecretStr | None = None
    email_imap_folder: str = "INBOX"
    email_lookback_days: int = 2
    email_max_messages: int = 50
    log_level: str = "INFO"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("telegram_recipient_chat_id", mode="before")
    @classmethod
    def empty_recipient_chat_id_is_unset(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    def greenhouse_board_tokens(self) -> tuple[str, ...]:
        return _csv_values(self.greenhouse_boards)

    def lever_site_names(self) -> tuple[str, ...]:
        return _csv_values(self.lever_sites)

    def telegram_public_channel_names(self) -> tuple[str, ...]:
        configured = _csv_values(self.telegram_public_channels)
        additional = _csv_values(self.telegram_public_additional_channels)
        return tuple(dict.fromkeys((*configured, *additional)))

    @model_validator(mode="after")
    def validate_email_alert_settings(self) -> Settings:
        if self.email_alerts_enabled:
            if not self.email_imap_username.strip():
                raise ValueError(
                    "EMAIL_IMAP_USERNAME is required when EMAIL_ALERTS_ENABLED=true"
                )
            if (
                self.email_imap_app_password is None
                or not self.email_imap_app_password.get_secret_value().strip()
            ):
                raise ValueError(
                    "EMAIL_IMAP_APP_PASSWORD is required when EMAIL_ALERTS_ENABLED=true"
                )
        return self


def _csv_values(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())
