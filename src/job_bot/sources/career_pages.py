from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from datetime import datetime
from typing import Any

import httpx

from job_bot.domain.models import EmploymentFormat, Vacancy
from job_bot.domain.text_analysis import infer_required_english_level, plain_text
from job_bot.sources.base import VacancySource

_COUNTRY_MARKERS = {
    "азербайджан": "Азербайджан",
    "armenia": "Армения",
    "армения": "Армения",
    "azerbaijan": "Азербайджан",
    "belarus": "Беларусь",
    "беларус": "Беларусь",
    "georgia": "Грузия",
    "грузия": "Грузия",
    "kazakhstan": "Казахстан",
    "kyrgyzstan": "Кыргызстан",
    "moldova": "Молдова",
    "russia": "Россия",
    "ukraine": "Украина",
    "uzbekistan": "Узбекистан",
    "казахстан": "Казахстан",
    "кыргызстан": "Кыргызстан",
    "молдова": "Молдова",
    "россия": "Россия",
    "узбекистан": "Узбекистан",
    "украина": "Украина",
}
_BELARUS_ALLOWED_MARKERS = (
    "anywhere",
    "worldwide",
    "global remote",
    "remote globally",
    "belarus",
    "беларус",
)
_BELARUS_DISALLOWED_MARKERS = (
    "remote only from russia",
    "russia only",
    "only residents of russia",
    "только для граждан рф",
    "только для резидентов рф",
    "только россия",
)


class CompositeSource:
    name = "configured-sources"

    def __init__(self, sources: list[VacancySource]) -> None:
        self._sources = sources

    async def fetch(self) -> AsyncIterator[Vacancy]:
        for source in self._sources:
            async for vacancy in source.fetch():
                yield vacancy


class GreenhouseSource:
    def __init__(self, client: httpx.AsyncClient, board_token: str) -> None:
        self._client = client
        self._board_token = board_token
        self.name = f"Greenhouse/{board_token}"

    async def fetch(self) -> AsyncIterator[Vacancy]:
        response = await self._client.get(
            f"https://boards-api.greenhouse.io/v1/boards/{self._board_token}/jobs",
            params={"content": "true"},
        )
        response.raise_for_status()
        jobs = _mapping(response.json()).get("jobs")
        if not isinstance(jobs, list):
            raise RuntimeError(f"Invalid Greenhouse response for {self._board_token}")
        for job in jobs:
            if isinstance(job, Mapping):
                yield self._parse(job)

    def _parse(self, job: Mapping[str, Any]) -> Vacancy:
        location = str(_mapping(job.get("location")).get("name") or "")
        description = plain_text(str(job.get("content") or ""))
        context = f"{location} {description}"
        return Vacancy(
            source=self.name,
            external_id=str(job["id"]),
            title=str(job.get("title") or ""),
            url=str(job.get("absolute_url") or ""),
            description=description,
            country=_country(context),
            employment_format=_employment_format(context),
            remote_from_belarus=_remote_from_belarus(context),
            required_english_level=infer_required_english_level(description),
            published_at=_optional_datetime(job.get("updated_at")),
            raw=dict(job),
        )


class LeverSource:
    def __init__(self, client: httpx.AsyncClient, site: str) -> None:
        self._client = client
        self._site = site
        self.name = f"Lever/{site}"

    async def fetch(self) -> AsyncIterator[Vacancy]:
        response = await self._client.get(
            f"https://api.lever.co/v0/postings/{self._site}",
            params={"mode": "json"},
        )
        response.raise_for_status()
        jobs = response.json()
        if not isinstance(jobs, list):
            raise RuntimeError(f"Invalid Lever response for {self._site}")
        for job in jobs:
            if isinstance(job, Mapping):
                yield self._parse(job)

    def _parse(self, job: Mapping[str, Any]) -> Vacancy:
        categories = _mapping(job.get("categories"))
        location = str(categories.get("location") or "")
        description_parts = (
            job.get("descriptionPlain"),
            job.get("additionalPlain"),
            job.get("requirementsPlain"),
        )
        description = plain_text(" ".join(str(part) for part in description_parts if part))
        context = f"{location} {description}"
        return Vacancy(
            source=self.name,
            external_id=str(job["id"]),
            title=str(job.get("text") or ""),
            url=str(job.get("hostedUrl") or job.get("applyUrl") or ""),
            description=description,
            country=_country(context),
            employment_format=_employment_format(context),
            remote_from_belarus=_remote_from_belarus(context),
            required_english_level=infer_required_english_level(description),
            raw=dict(job),
        )


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _country(text: str) -> str | None:
    normalized = text.casefold()
    for marker, country in _COUNTRY_MARKERS.items():
        if marker in normalized:
            return country
    return None


def _employment_format(text: str) -> EmploymentFormat:
    normalized = text.casefold()
    if "hybrid" in normalized or "гибрид" in normalized:
        return EmploymentFormat.HYBRID
    if "remote" in normalized or "удален" in normalized or "удалён" in normalized:
        return EmploymentFormat.REMOTE
    return EmploymentFormat.OFFICE


def _remote_from_belarus(text: str) -> bool | None:
    normalized = text.casefold()
    if any(marker in normalized for marker in _BELARUS_DISALLOWED_MARKERS):
        return False
    if any(marker in normalized for marker in _BELARUS_ALLOWED_MARKERS):
        return True
    return None


def _optional_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
