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
