from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from job_bot.domain.models import Decision, EmploymentFormat, Vacancy
from job_bot.storage import SqlAlchemyVacancyStore, initialize_database


def _vacancy(*, published_at: datetime | None) -> Vacancy:
    return Vacancy(
        source="Telegram/@example",
        external_id="example/42",
        title="Junior Project Manager",
        url="https://t.me/example/42",
        company="Example",
        country="Беларусь",
        location="Минск",
        employment_format=EmploymentFormat.REMOTE,
        remote_from_belarus=True,
        experience_min_years=1,
        required_english_level="B1",
        published_at=published_at,
        raw={"published_at": published_at.isoformat() if published_at else None},
    )


@pytest.mark.asyncio
async def test_reparse_refreshes_source_date_without_duplicate_processing() -> None:
    engine = create_async_engine("sqlite+aiosqlite://")
    await initialize_database(engine)
    store = SqlAlchemyVacancyStore(async_sessionmaker(engine, expire_on_commit=False))

    original = _vacancy(published_at=None)
    assert await store.claim(original) is True
    await store.record_match(original, Decision(accepted=True, score=95))
    await store.complete(original, notified=True)

    source_date = datetime(2026, 7, 20, 10, 30, tzinfo=UTC)
    reparsed = _vacancy(published_at=source_date)
    assert await store.claim(reparsed) is False
    await store.refresh_match(reparsed, Decision(accepted=True, score=97))

    latest = await store.latest_matches(reparsed.source)
    assert len(latest) == 1
    assert latest[0].published_at is not None
    assert latest[0].published_at.replace(tzinfo=UTC) == source_date
    assert latest[0].score == 97
    await engine.dispose()


@pytest.mark.asyncio
async def test_historical_fallback_does_not_use_notification_time_as_publication() -> None:
    engine = create_async_engine("sqlite+aiosqlite://")
    await initialize_database(engine)
    store = SqlAlchemyVacancyStore(async_sessionmaker(engine, expire_on_commit=False))

    vacancy = _vacancy(published_at=None)
    assert await store.claim(vacancy) is True
    await store.complete(vacancy, notified=True)

    latest = await store.latest_matches(vacancy.source)
    assert len(latest) == 1
    assert latest[0].published_at is None
    await engine.dispose()


@pytest.mark.asyncio
async def test_schema_upgrade_adds_publication_date_to_existing_database() -> None:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "CREATE TABLE vacancies ("
                "id INTEGER PRIMARY KEY, source VARCHAR(100), external_id VARCHAR(255), "
                "title VARCHAR(500), url VARCHAR(2000), payload JSON, "
                "first_seen_at DATETIME, processed_at DATETIME, notified_at DATETIME)"
            )
        )

    await initialize_database(engine)

    async with engine.connect() as connection:
        columns = await connection.execute(text("PRAGMA table_info(vacancies)"))
        assert "published_at" in {row[1] for row in columns}
    await engine.dispose()
