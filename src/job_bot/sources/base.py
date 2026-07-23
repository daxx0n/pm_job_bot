from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from job_bot.domain.models import Vacancy


class VacancySource(Protocol):
    name: str

    def fetch(self) -> AsyncIterator[Vacancy]:
        """Yield the latest vacancies. Persistent storage decides which ones are new."""
        ...
