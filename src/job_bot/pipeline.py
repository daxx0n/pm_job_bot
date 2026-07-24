from __future__ import annotations

import logging
from typing import Protocol

from job_bot.domain.filtering import EligibilityFilter
from job_bot.domain.models import Decision, Vacancy
from job_bot.sources.base import VacancySource
from job_bot.storage import VacancyStore

logger = logging.getLogger(__name__)


class VacancyNotifier(Protocol):
    async def send_vacancy(self, vacancy: Vacancy, decision: Decision) -> bool:
        """Send a vacancy and return false when its source is muted."""
        ...


class VacancyPipeline:
    def __init__(
        self,
        *,
        source: VacancySource,
        store: VacancyStore,
        notifier: VacancyNotifier,
        eligibility_filter: EligibilityFilter,
    ) -> None:
        self._source = source
        self._store = store
        self._notifier = notifier
        self._filter = eligibility_filter

    async def run_once(self) -> tuple[int, int]:
        checked = 0
        sent = 0
        async for vacancy in self._source.fetch():
            checked += 1
            if not await self._store.claim(vacancy):
                decision = self._filter.evaluate(vacancy)
                await self._store.refresh_match(vacancy, decision)
                continue

            decision = self._filter.evaluate(vacancy)
            if not decision.accepted:
                logger.info(
                    "Rejected vacancy %s/%s: %s",
                    vacancy.source,
                    vacancy.external_id,
                    ", ".join(decision.reasons),
                )
                await self._store.complete(vacancy, notified=False)
                continue

            await self._store.record_match(vacancy, decision)
            notified = await self._notifier.send_vacancy(vacancy, decision)
            await self._store.complete(vacancy, notified=notified)
            sent += int(notified)
        return checked, sent
