from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from hmac import compare_digest
from typing import Protocol

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    inspect,
    select,
    text,
    update,
)
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from job_bot.domain.models import Decision, Vacancy


class VacancyStore(Protocol):
    async def claim(self, vacancy: Vacancy) -> bool:
        """Return true for a new or previously unfinished vacancy."""
        ...

    async def complete(self, vacancy: Vacancy, *, notified: bool) -> None:
        """Mark filtering as complete and optionally record successful delivery."""
        ...

    async def record_match(self, vacancy: Vacancy, decision: Decision) -> None:
        """Save an accepted vacancy for the per-source recent-vacancy view."""
        ...

    async def refresh_match(self, vacancy: Vacancy, decision: Decision) -> None:
        """Refresh an already accepted vacancy without sending it again."""
        ...


@dataclass(frozen=True, slots=True)
class MatchedVacancy:
    source: str
    external_id: str
    title: str
    url: str
    company: str | None
    location: str | None
    published_at: datetime | None
    score: int | None


class VacancyFeedbackStore(Protocol):
    async def record_feedback(
        self,
        source_token: str,
        external_id_token: str,
        value: str,
    ) -> bool:
        """Save feedback and return false when the referenced vacancy does not exist."""
        ...


class SourcePreferenceStore(Protocol):
    async def source_states(
        self,
        chat_id: int,
        sources: tuple[str, ...],
    ) -> dict[str, bool]:
        """Return enabled states; previously unseen sources default to enabled."""
        ...

    async def is_source_enabled(self, chat_id: int, source: str) -> bool:
        """Return whether new vacancies from a source should be sent."""
        ...

    async def toggle_source(self, chat_id: int, source: str) -> bool:
        """Toggle a source and return its new enabled state."""
        ...

    async def set_sources_enabled(
        self,
        chat_id: int,
        sources: tuple[str, ...],
        *,
        enabled: bool,
    ) -> None:
        """Set all supplied sources to the same state."""
        ...

    async def latest_matches(
        self,
        source: str,
        *,
        limit: int = 10,
    ) -> tuple[MatchedVacancy, ...]:
        """Return the newest accepted vacancies for one source."""
        ...


class Base(DeclarativeBase):
    pass


class StoredVacancy(Base):
    __tablename__ = "vacancies"
    __table_args__ = (UniqueConstraint("source", "external_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    url: Mapped[str] = mapped_column(String(2000), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class StoredVacancyFeedback(Base):
    __tablename__ = "vacancy_feedback"

    vacancy_id: Mapped[int] = mapped_column(
        ForeignKey("vacancies.id", ondelete="CASCADE"),
        primary_key=True,
    )
    value: Mapped[str] = mapped_column(String(30), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class StoredMatchedVacancy(Base):
    __tablename__ = "matched_vacancies"
    __table_args__ = (UniqueConstraint("source", "external_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    url: Mapped[str] = mapped_column(String(2000), nullable=False)
    company: Mapped[str | None] = mapped_column(String(500))
    location: Mapped[str | None] = mapped_column(String(500))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    matched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class StoredSourcePreference(Base):
    __tablename__ = "source_preferences"

    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source: Mapped[str] = mapped_column(String(100), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class SqlAlchemyVacancyStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def claim(self, vacancy: Vacancy) -> bool:
        async with self._session_factory() as session:
            existing = (
                await session.execute(
                    select(StoredVacancy).where(
                        StoredVacancy.source == vacancy.source,
                        StoredVacancy.external_id == vacancy.external_id,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                existing.title = vacancy.title
                existing.url = vacancy.url
                existing.payload = vacancy.raw
                if vacancy.published_at is not None:
                    existing.published_at = vacancy.published_at
                await session.commit()
                return existing.processed_at is None

            session.add(
                StoredVacancy(
                    source=vacancy.source,
                    external_id=vacancy.external_id,
                    title=vacancy.title,
                    url=vacancy.url,
                    payload=vacancy.raw,
                    published_at=vacancy.published_at,
                )
            )
            await session.commit()
            return True

    async def record_feedback(
        self,
        source_token: str,
        external_id_token: str,
        value: str,
    ) -> bool:
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            candidates = (
                await session.execute(
                    select(
                        StoredVacancy.id,
                        StoredVacancy.source,
                        StoredVacancy.external_id,
                    )
                )
            ).all()
            vacancy_id = next(
                (
                    candidate.id
                    for candidate in candidates
                    if (
                        compare_digest(
                            feedback_source_token(candidate.source),
                            source_token,
                        )
                        and compare_digest(
                            feedback_external_id_token(candidate.external_id),
                            external_id_token,
                        )
                    )
                ),
                None,
            )
            if vacancy_id is None:
                return False

            feedback = await session.get(StoredVacancyFeedback, vacancy_id)
            if feedback is None:
                session.add(
                    StoredVacancyFeedback(
                        vacancy_id=vacancy_id,
                        value=value,
                        updated_at=now,
                    )
                )
            else:
                feedback.value = value
                feedback.updated_at = now
            await session.commit()
            return True

    async def complete(self, vacancy: Vacancy, *, notified: bool) -> None:
        now = datetime.now(UTC)
        values: dict[str, datetime] = {"processed_at": now}
        if notified:
            values["notified_at"] = now

        async with self._session_factory() as session:
            await session.execute(
                update(StoredVacancy)
                .where(
                    StoredVacancy.source == vacancy.source,
                    StoredVacancy.external_id == vacancy.external_id,
                )
                .values(**values)
            )
            await session.commit()

    async def record_match(self, vacancy: Vacancy, decision: Decision) -> None:
        async with self._session_factory() as session:
            existing = (
                await session.execute(
                    select(StoredMatchedVacancy).where(
                        StoredMatchedVacancy.source == vacancy.source,
                        StoredMatchedVacancy.external_id == vacancy.external_id,
                    )
                )
            ).scalar_one_or_none()
            if existing is None:
                session.add(
                    StoredMatchedVacancy(
                        source=vacancy.source,
                        external_id=vacancy.external_id,
                        title=vacancy.title,
                        url=vacancy.url,
                        company=vacancy.company,
                        location=vacancy.location or vacancy.country,
                        published_at=vacancy.published_at,
                        score=decision.score,
                    )
                )
            else:
                _update_match(existing, vacancy, decision)
            await session.commit()

    async def refresh_match(self, vacancy: Vacancy, decision: Decision) -> None:
        if not decision.accepted:
            return
        async with self._session_factory() as session:
            stored = (
                await session.execute(
                    select(StoredVacancy).where(
                        StoredVacancy.source == vacancy.source,
                        StoredVacancy.external_id == vacancy.external_id,
                    )
                )
            ).scalar_one_or_none()
            if stored is None:
                return

            existing = (
                await session.execute(
                    select(StoredMatchedVacancy).where(
                        StoredMatchedVacancy.source == vacancy.source,
                        StoredMatchedVacancy.external_id == vacancy.external_id,
                    )
                )
            ).scalar_one_or_none()
            if existing is None and stored.notified_at is None:
                return
            if existing is None:
                session.add(
                    StoredMatchedVacancy(
                        source=vacancy.source,
                        external_id=vacancy.external_id,
                        title=vacancy.title,
                        url=vacancy.url,
                        company=vacancy.company,
                        location=vacancy.location or vacancy.country,
                        published_at=vacancy.published_at,
                        score=decision.score,
                        matched_at=stored.notified_at or stored.first_seen_at,
                    )
                )
            else:
                _update_match(existing, vacancy, decision)
            await session.commit()

    async def source_states(
        self,
        chat_id: int,
        sources: tuple[str, ...],
    ) -> dict[str, bool]:
        if not sources:
            return {}
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(StoredSourcePreference.source, StoredSourcePreference.enabled).where(
                        StoredSourcePreference.chat_id == chat_id,
                        StoredSourcePreference.source.in_(sources),
                    )
                )
            ).all()
        configured = {row.source: row.enabled for row in rows}
        return {source: configured.get(source, True) for source in sources}

    async def is_source_enabled(self, chat_id: int, source: str) -> bool:
        async with self._session_factory() as session:
            enabled = (
                await session.execute(
                    select(StoredSourcePreference.enabled).where(
                        StoredSourcePreference.chat_id == chat_id,
                        StoredSourcePreference.source == source,
                    )
                )
            ).scalar_one_or_none()
        return True if enabled is None else enabled

    async def toggle_source(self, chat_id: int, source: str) -> bool:
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            preference = await session.get(
                StoredSourcePreference,
                {"chat_id": chat_id, "source": source},
            )
            if preference is None:
                preference = StoredSourcePreference(
                    chat_id=chat_id,
                    source=source,
                    enabled=False,
                    updated_at=now,
                )
                session.add(preference)
            else:
                preference.enabled = not preference.enabled
                preference.updated_at = now
            await session.commit()
            return preference.enabled

    async def set_sources_enabled(
        self,
        chat_id: int,
        sources: tuple[str, ...],
        *,
        enabled: bool,
    ) -> None:
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            existing = {
                item.source: item
                for item in (
                    await session.execute(
                        select(StoredSourcePreference).where(
                            StoredSourcePreference.chat_id == chat_id,
                            StoredSourcePreference.source.in_(sources),
                        )
                    )
                ).scalars()
            }
            for source in sources:
                preference = existing.get(source)
                if preference is None:
                    session.add(
                        StoredSourcePreference(
                            chat_id=chat_id,
                            source=source,
                            enabled=enabled,
                            updated_at=now,
                        )
                    )
                else:
                    preference.enabled = enabled
                    preference.updated_at = now
            await session.commit()

    async def latest_matches(
        self,
        source: str,
        *,
        limit: int = 10,
    ) -> tuple[MatchedVacancy, ...]:
        async with self._session_factory() as session:
            rows = tuple(
                (
                    await session.execute(
                        select(StoredMatchedVacancy)
                        .where(StoredMatchedVacancy.source == source)
                        .order_by(
                            StoredMatchedVacancy.published_at.desc().nullslast(),
                            StoredMatchedVacancy.matched_at.desc(),
                        )
                        .limit(limit)
                    )
                ).scalars()
            )
            matches = [
                MatchedVacancy(
                    source=row.source,
                    external_id=row.external_id,
                    title=row.title,
                    url=row.url,
                    company=row.company,
                    location=row.location,
                    published_at=row.published_at,
                    score=row.score,
                )
                for row in rows
            ]
            if len(matches) >= limit:
                return tuple(matches)

            matched_ids = {row.external_id for row in rows}
            historical_rows = (
                await session.execute(
                    select(StoredVacancy)
                    .where(
                        StoredVacancy.source == source,
                        StoredVacancy.notified_at.is_not(None),
                    )
                    .order_by(StoredVacancy.notified_at.desc())
                    .limit(limit + len(matched_ids))
                )
            ).scalars()
            for row in historical_rows:
                if row.external_id in matched_ids:
                    continue
                matches.append(
                    MatchedVacancy(
                        source=row.source,
                        external_id=row.external_id,
                        title=row.title,
                        url=row.url,
                        company=None,
                        location=None,
                        published_at=row.published_at,
                        score=None,
                    )
                )
                if len(matches) == limit:
                    break
            return tuple(matches)


def _update_match(
    stored: StoredMatchedVacancy,
    vacancy: Vacancy,
    decision: Decision,
) -> None:
    stored.title = vacancy.title
    stored.url = vacancy.url
    stored.company = vacancy.company
    stored.location = vacancy.location or vacancy.country
    if vacancy.published_at is not None:
        stored.published_at = vacancy.published_at
    stored.score = decision.score


async def initialize_database(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(_create_or_upgrade_schema)


def _create_or_upgrade_schema(connection: Connection) -> None:
    Base.metadata.create_all(connection)
    vacancy_columns = {
        column["name"] for column in inspect(connection).get_columns("vacancies")
    }
    if "published_at" not in vacancy_columns:
        connection.execute(
            text(
                "ALTER TABLE vacancies "
                "ADD COLUMN published_at TIMESTAMP WITH TIME ZONE"
            )
        )


def feedback_source_token(source: str) -> str:
    return sha256(source.encode()).hexdigest()[:8]


def feedback_external_id_token(external_id: str) -> str:
    return sha256(external_id.encode()).hexdigest()[:16]
