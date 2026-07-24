from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from hmac import compare_digest
from typing import Protocol

from sqlalchemy import JSON, DateTime, ForeignKey, String, UniqueConstraint, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from job_bot.domain.models import Vacancy


class VacancyStore(Protocol):
    async def claim(self, vacancy: Vacancy) -> bool:
        """Return true for a new or previously unfinished vacancy."""
        ...

    async def complete(self, vacancy: Vacancy, *, notified: bool) -> None:
        """Mark filtering as complete and optionally record successful delivery."""
        ...


class VacancyFeedbackStore(Protocol):
    async def record_feedback(
        self,
        source_token: str,
        external_id_token: str,
        value: str,
    ) -> bool:
        """Save feedback and return false when the referenced vacancy does not exist."""
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


class SqlAlchemyVacancyStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def claim(self, vacancy: Vacancy) -> bool:
        async with self._session_factory() as session:
            existing = (
                await session.execute(
                    select(StoredVacancy.id, StoredVacancy.processed_at).where(
                        StoredVacancy.source == vacancy.source,
                        StoredVacancy.external_id == vacancy.external_id,
                    )
                )
            ).one_or_none()
            if existing is not None:
                return existing.processed_at is None

            session.add(
                StoredVacancy(
                    source=vacancy.source,
                    external_id=vacancy.external_id,
                    title=vacancy.title,
                    url=vacancy.url,
                    payload=vacancy.raw,
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


def feedback_source_token(source: str) -> str:
    return sha256(source.encode()).hexdigest()[:8]


def feedback_external_id_token(external_id: str) -> str:
    return sha256(external_id.encode()).hexdigest()[:16]
