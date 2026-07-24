from typing import cast

from pydantic import SecretStr

from job_bot.settings import Settings


def test_empty_recipient_chat_id_is_treated_as_unset() -> None:
    settings = Settings(
        telegram_bot_token=SecretStr("test-token"),
        telegram_recipient_chat_id=cast(int | None, ""),
    )

    assert settings.telegram_recipient_chat_id is None


def test_recipient_chat_id_is_parsed_as_integer() -> None:
    settings = Settings(
        telegram_bot_token=SecretStr("test-token"),
        telegram_recipient_chat_id=cast(int | None, "123456789"),
    )

    assert settings.telegram_recipient_chat_id == 123456789


def test_default_public_channels_include_additional_sources() -> None:
    settings = Settings(telegram_bot_token=SecretStr("test-token"))

    assert settings.telegram_public_channel_names() == (
        "product_project_job",
        "pmclub",
        "geekjobs",
        "budujobs",
        "it_vakansii_jobs",
        "forproducts",
        "jobforjunior",
        "young_june",
        "igaming_work",
        "betting_job",
    )


def test_international_sources_are_opt_in() -> None:
    settings = Settings(telegram_bot_token=SecretStr("test-token"))

    assert settings.international_sources_enabled is False


def test_public_channels_are_deduplicated() -> None:
    settings = Settings(
        telegram_bot_token=SecretStr("test-token"),
        telegram_public_channels="pmclub,budujobs",
        telegram_public_russian_channels="",
        telegram_public_additional_channels="budujobs,remotejobss",
    )

    assert settings.telegram_public_channel_names() == (
        "pmclub",
        "budujobs",
        "remotejobss",
    )


def test_existing_additional_channels_do_not_replace_russian_defaults() -> None:
    settings = Settings(
        telegram_bot_token=SecretStr("test-token"),
        telegram_public_additional_channels="budujobs,remotejobss",
    )

    channels = settings.telegram_public_channel_names()

    assert "it_vakansii_jobs" in channels
    assert "igaming_work" in channels
    assert "betting_job" in channels
    assert channels.count("budujobs") == 1
    assert "remotejobss" in channels
