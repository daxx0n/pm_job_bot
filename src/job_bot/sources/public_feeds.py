from __future__ import annotations

import re
import time
from collections.abc import AsyncIterator, Mapping
from datetime import datetime
from email.utils import parsedate_to_datetime
from hashlib import sha256
from typing import Any
from xml.etree import ElementTree

import httpx

from job_bot.domain.models import EmploymentFormat, Vacancy
from job_bot.domain.text_analysis import (
    infer_experience_min_years,
    infer_required_english_level,
    plain_text,
)

_COUNTRY_MARKERS = {
    "belarus": "Беларусь",
    "беларус": "Беларусь",
    "russia": "Россия",
    "россия": "Россия",
    "kazakhstan": "Казахстан",
    "казахстан": "Казахстан",
    "armenia": "Армения",
    "армения": "Армения",
    "georgia": "Грузия",
    "грузия": "Грузия",
    "moldova": "Молдова",
    "молдова": "Молдова",
    "kyrgyzstan": "Кыргызстан",
    "кыргызстан": "Кыргызстан",
    "uzbekistan": "Узбекистан",
    "узбекистан": "Узбекистан",
    "azerbaijan": "Азербайджан",
    "азербайджан": "Азербайджан",
    "ukraine": "Украина",
    "украина": "Украина",
}
_WORLDWIDE_MARKERS = (
    "anywhere",
    "worldwide",
    "global",
    "work from anywhere",
    "all countries",
)
_POSSIBLY_ALLOWED_REGIONS = ("europe", "emea", "european time", "utc")
_NON_LOCATION_VALUES = ("remote", "remote work", "distributed")


class _RefreshLimitedSource:
    def __init__(self, refresh_seconds: int) -> None:
        self._refresh_seconds = refresh_seconds
        self._last_fetch_at: float | None = None

    def _fetch_is_due(self) -> bool:
        if self._last_fetch_at is None:
            return True
        return time.monotonic() - self._last_fetch_at >= self._refresh_seconds

    def _mark_fetched(self) -> None:
        self._last_fetch_at = time.monotonic()


class RemotiveSource(_RefreshLimitedSource):
    name = "Remotive"

    def __init__(self, client: httpx.AsyncClient, refresh_seconds: int = 21_600) -> None:
        super().__init__(refresh_seconds)
        self._client = client

    async def fetch(self) -> AsyncIterator[Vacancy]:
        if not self._fetch_is_due():
            return
        response = await self._client.get(
            "https://remotive.com/api/remote-jobs",
            params={"category": "project-management"},
        )
        response.raise_for_status()
        payload = _mapping(response.json())
        jobs = payload.get("jobs")
        if not isinstance(jobs, list):
            raise RuntimeError("Invalid Remotive response")
        self._mark_fetched()
        for job in jobs:
            if isinstance(job, Mapping):
                yield self._parse(job)

    def _parse(self, job: Mapping[str, Any]) -> Vacancy:
        description = plain_text(str(job.get("description") or ""))
        location = str(job.get("candidate_required_location") or "")
        salary_min, salary_max = _monthly_salary(str(job.get("salary") or ""))
        return Vacancy(
            source=self.name,
            external_id=str(job["id"]),
            title=str(job.get("title") or ""),
            url=str(job.get("url") or ""),
            description=description,
            company=str(job.get("company_name") or "") or None,
            country=_country(location),
            employment_format=EmploymentFormat.REMOTE,
            remote_from_belarus=_remote_from_belarus(location),
            experience_min_years=infer_experience_min_years(description),
            required_english_level=infer_required_english_level(description),
            salary_min_usd=salary_min,
            salary_max_usd=salary_max,
            published_at=_optional_datetime(job.get("publication_date")),
            raw=dict(job),
        )


class PublicRssSource(_RefreshLimitedSource):
    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        name: str,
        url: str,
        refresh_seconds: int = 1_800,
    ) -> None:
        super().__init__(refresh_seconds)
        self._client = client
        self.name = name
        self._url = url

    async def fetch(self) -> AsyncIterator[Vacancy]:
        if not self._fetch_is_due():
            return
        response = await self._client.get(self._url)
        response.raise_for_status()
        try:
            root = _parse_rss(response.content)
        except ElementTree.ParseError as error:
            raise RuntimeError(f"Invalid RSS response from {self.name}") from error
        self._mark_fetched()
        for item in root.findall(".//item"):
            yield self._parse(item)

    def _parse(self, item: ElementTree.Element) -> Vacancy:
        fields = _rss_fields(item)
        raw_title = fields.get("title", "")
        company = fields.get("companyname") or None
        title = raw_title
        if company is None and ": " in raw_title:
            possible_company, possible_title = raw_title.split(": ", 1)
            if possible_company and possible_title:
                company = possible_company
                title = possible_title

        description_html = fields.get("encoded") or fields.get("description", "")
        description = plain_text(description_html)
        locations = [
            value
            for key, value in fields.items()
            if key in {"region", "locationrestriction", "location"}
        ]
        location = " ".join(locations)
        link = fields.get("link", "")
        external_id = _rss_external_id(fields.get("guid"), link)
        return Vacancy(
            source=self.name,
            external_id=external_id,
            title=title,
            url=link,
            description=description,
            company=company,
            country=_country(location),
            employment_format=EmploymentFormat.REMOTE,
            remote_from_belarus=_remote_from_belarus(location),
            experience_min_years=infer_experience_min_years(description),
            required_english_level=infer_required_english_level(description),
            published_at=_rss_datetime(fields.get("pubdate")),
            raw=fields,
        )


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _parse_rss(content: bytes) -> ElementTree.Element:
    try:
        return ElementTree.fromstring(content)
    except ElementTree.ParseError as error:
        if "unbound prefix" not in str(error):
            raise
        without_unbound_prefixes = re.sub(
            rb"<(/?)[A-Za-z_][\w.-]*:([A-Za-z_][\w.-]*)(?=[\s>/])",
            rb"<\1\2",
            content,
        )
        return ElementTree.fromstring(without_unbound_prefixes)


def _rss_external_id(guid: str | None, link: str) -> str:
    value = (guid or link).strip()
    if link and link in value:
        value = link
    if len(value) <= 255:
        return value
    return f"sha256:{sha256(value.encode()).hexdigest()}"


def _country(text: str) -> str | None:
    normalized = text.casefold()
    for marker, country in _COUNTRY_MARKERS.items():
        if marker in normalized:
            return country
    return None


def _remote_from_belarus(location: str) -> bool | None:
    normalized = plain_text(location).casefold().strip(" ,;")
    if not normalized or normalized in _NON_LOCATION_VALUES:
        return None
    if "belarus" in normalized or "беларус" in normalized:
        return True
    if any(marker in normalized for marker in _WORLDWIDE_MARKERS):
        return True
    if any(marker in normalized for marker in _POSSIBLY_ALLOWED_REGIONS):
        return None
    return False


def _monthly_salary(value: str) -> tuple[int | None, int | None]:
    normalized = value.casefold().replace(",", "")
    matches = re.findall(r"(?:usd|\$)?\s*(\d+(?:\.\d+)?)\s*([kк]?)", normalized)
    amounts = [float(number) * (1000 if suffix else 1) for number, suffix in matches]
    amounts = [amount for amount in amounts if amount >= 100]
    if not amounts:
        return None, None

    if any(marker in normalized for marker in ("hour", "час")):
        amounts = [amount * 160 for amount in amounts]
    elif (
        any(marker in normalized for marker in ("year", "annual", "год"))
        or max(amounts) >= 12_000
    ):
        amounts = [amount / 12 for amount in amounts]

    rounded = [round(amount) for amount in amounts[:2]]
    return rounded[0], rounded[1] if len(rounded) > 1 else None


def _optional_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _rss_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return _optional_datetime(value)


def _rss_fields(item: ElementTree.Element) -> dict[str, str]:
    fields: dict[str, str] = {}
    for child in item:
        key = child.tag.rsplit("}", 1)[-1].casefold()
        value = "".join(child.itertext()).strip()
        if value:
            if key not in fields:
                fields[key] = value
            elif fields[key] != value:
                fields[key] = f"{fields[key]} {value}"
    return fields
