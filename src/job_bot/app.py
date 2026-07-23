from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

import httpx
from aiogram import Bot
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from job_bot.domain.filtering import EligibilityFilter
from job_bot.pipeline import VacancyPipeline
from job_bot.settings import Settings
from job_bot.sources.headhunter import HeadHunterSource
from job_bot.storage import Base, SqlAlchemyVacancyStore
from job_bot.telegram.bot import TelegramNotifier, create_dispatcher

logger = logging.getLogger(__name__)


async def _poll(pipeline: VacancyPipeline, interval_seconds: int) -> None:
    while True:
        try:
            checked, sent = await pipeline.run_once()
            logger.info("Vacancy poll completed: checked=%d sent=%d", checked, sent)
        except Exception:
            logger.exception("Vacancy poll failed")
        await asyncio.sleep(interval_seconds)


async def main() -> None:
    settings = Settings()  # type: ignore[call-arg]
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    bot = Bot(token=settings.telegram_bot_token.get_secret_value())
    engine = create_async_engine(settings.database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    store = SqlAlchemyVacancyStore(async_sessionmaker(engine, expire_on_commit=False))
    dispatcher = create_dispatcher(settings, store)

    poll_task: asyncio.Task[None] | None = None
    client: httpx.AsyncClient | None = None
    if settings.hh_enabled and settings.telegram_recipient_chat_id is not None:
        client = httpx.AsyncClient(timeout=settings.hh_request_timeout_seconds)
        pipeline = VacancyPipeline(
            source=HeadHunterSource(client, user_agent=settings.hh_user_agent),
            store=store,
            notifier=TelegramNotifier(bot, settings.telegram_recipient_chat_id),
            eligibility_filter=EligibilityFilter(),
        )
        poll_task = asyncio.create_task(
            _poll(pipeline, settings.hh_poll_interval_seconds),
            name="headhunter-poller",
        )
    elif settings.hh_enabled:
        logger.warning("HeadHunter polling is disabled until TELEGRAM_RECIPIENT_CHAT_ID is set")

    try:
        await dispatcher.start_polling(bot)
    finally:
        if poll_task is not None:
            poll_task.cancel()
            with suppress(asyncio.CancelledError):
                await poll_task
        if client is not None:
            await client.aclose()
        await engine.dispose()
        await bot.session.close()


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
