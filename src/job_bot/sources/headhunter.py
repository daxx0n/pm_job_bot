from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from datetime import datetime
from typing import Any

import httpx

from job_bot.domain.models import EmploymentFormat, Vacancy
from job_bot.domain.text_analysis import infer_required_english_level, plain_text

_SEARCH_TERMS = (
    "project manager",
    "менеджер проектов",
    "руководитель проектов",
    "project coordinator",
)
_REMOTE_WORK_FORMAT_ID = "REMOTE"
_HYBRID_WORK_FORMAT_ID = "HYBRID"
_TARGET_COUNTRIES = {
    "азербайджан",
    "армения",
    "беларусь",
    "грузия",
    "казахстан",
    "кыргызстан",
    "молдова",
    "россия",
    "узбекистан",
}

_EXPERIENCE_RANGES: dict[str, tuple[float | None, float | None]] = {
    "noExperience": (0, 0),
    "between1And3": (1, 3),
    "between3And6": (3, 6),
    "moreThan6": (6, None),
}


class HeadHunterSource:
    """Fetch recently published Belarus-compatible vacancies from HeadHunter."""

    name = "HeadHunter"

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        user_agent: str,
        page_size: int = 100,
    ) -> None:
        self._client = client
        self._user_agent = user_agent
        self._page_size = page_size
        self._country_by_area: dict[str, str] = {}
        self._target_area_ids: tuple[str, ...] = ()
        self._belarus_area_id: str | None = None

    async def fetch(self) -> AsyncIterator[Vacancy]:
        await self._load_areas()
        seen: set[str] = set()
        for term in _SEARCH_TERMS:
            async for item in self._search(
                term,
                _REMOTE_WORK_FORMAT_ID,
                self._target_area_ids,
            ):
                external_id = str(item["id"])
                if external_id in seen:
                    continue
                seen.add(external_id)
                yield self._parse(item)

            if self._belarus_area_id is not None:
                async for item in self._search(
                    term,
                    _HYBRID_WORK_FORMAT_ID,
                    (self._belarus_area_id,),
                ):
                    external_id = str(item["id"])
                    if external_id in seen:
                        continue
                    seen.add(external_id)
                    yield self._parse(item)

    async def _search(
        self,
        term: str,
        work_format: str,
        area_ids: tuple[str, ...],
    ) -> AsyncIterator[Mapping[str, Any]]:
        page = 0
        while True:
            params: list[tuple[str, str | int | float | bool | None]] = [
                ("text", term),
                ("work_format", work_format),
                ("period", "1"),
                ("order_by", "publication_time"),
                ("per_page", str(self._page_size)),
                ("page", str(page)),
                *(("area", area_id) for area_id in area_ids),
            ]
            response = await self._client.get(
                "https://api.hh.ru/vacancies",
                params=params,
                headers={"User-Agent": self._user_agent, "Accept-Language": "ru"},
            )
            response.raise_for_status()
            payload = response.json()
            for item in payload.get("items", []):
                yield item

            if page + 1 >= int(payload.get("pages", 1)):
                break
            page += 1

    async def _load_areas(self) -> None:
        if self._target_area_ids:
            return

        response = await self._client.get(
            "https://api.hh.ru/areas",
            headers={"User-Agent": self._user_agent, "Accept-Language": "ru"},
        )
        response.raise_for_status()
        countries = response.json()
        target_ids: list[str] = []
        for country in countries:
            if not isinstance(country, Mapping):
                continue
            country_name = str(country.get("name") or "")
            if country_name.casefold() not in _TARGET_COUNTRIES:
                continue
            country_id = str(country["id"])
            target_ids.append(country_id)
            if country_name.casefold() == "беларусь":
                self._belarus_area_id = country_id
            self._map_area_tree(country, country_name)

        if not target_ids or self._belarus_area_id is None:
            raise RuntimeError("HeadHunter areas response does not contain target countries")
        self._target_area_ids = tuple(target_ids)

    def _map_area_tree(self, area: Mapping[str, Any], country_name: str) -> None:
        self._country_by_area[str(area["id"])] = country_name
        children = area.get("areas")
        if not isinstance(children, list):
            return
        for child in children:
            if isinstance(child, Mapping):
                self._map_area_tree(child, country_name)

    def _parse(self, item: Mapping[str, Any]) -> Vacancy:
        employer = _mapping(item.get("employer"))
        experience = _mapping(item.get("experience"))
        salary = _mapping(item.get("salary"))
        work_formats = item.get("work_format")
        description = _snippet_text(item)
        experience_range = _EXPERIENCE_RANGES.get(str(experience.get("id", "")), (None, None))
        salary_min, salary_max = _salary_in_usd(salary)

        published_at: datetime | None = None
        if item.get("published_at"):
            published_at = datetime.fromisoformat(str(item["published_at"]))

        return Vacancy(
            source=self.name,
            external_id=str(item["id"]),
            title=str(item.get("name") or ""),
            url=str(item.get("alternate_url") or item.get("url") or ""),
            description=description,
            company=_optional_string(employer.get("name")),
            country=self._country_by_area.get(str(_mapping(item.get("area")).get("id"))),
            employment_format=_employment_format(work_formats),
            remote_from_belarus=_remote_from_belarus(item, self._country_by_area),
            experience_min_years=experience_range[0],
            experience_max_years=experience_range[1],
            required_english_level=infer_required_english_level(description),
            salary_min_usd=salary_min,
            salary_max_usd=salary_max,
            salary_min=_optional_int(salary.get("from")),
            salary_max=_optional_int(salary.get("to")),
            salary_currency=_optional_string(salary.get("currency")),
            published_at=published_at,
            raw=dict(item),
        )


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _optional_string(value: object) -> str | None:
    return str(value) if value is not None else None


def _optional_int(value: object) -> int | None:
    if isinstance(value, (int, float, str)):
        return int(value)
    return None


def _employment_format(value: object) -> EmploymentFormat:
    formats = value if isinstance(value, list) else []
    format_ids = {
        str(item.get("id"))
        for item in formats
        if isinstance(item, Mapping)
    }
    if _REMOTE_WORK_FORMAT_ID in format_ids:
        return EmploymentFormat.REMOTE
    if _HYBRID_WORK_FORMAT_ID in format_ids:
        return EmploymentFormat.HYBRID
    return EmploymentFormat.UNKNOWN


def _salary_in_usd(salary: Mapping[str, Any]) -> tuple[int | None, int | None]:
    """Normalize only USD values; unknown currencies remain unfiltered and visible in raw."""

    if salary.get("currency") != "USD":
        return None, None
    salary_from = salary.get("from")
    salary_to = salary.get("to")
    return (
        int(salary_from) if salary_from is not None else None,
        int(salary_to) if salary_to is not None else None,
    )


def _snippet_text(item: Mapping[str, Any]) -> str:
    snippet = _mapping(item.get("snippet"))
    parts = [
        str(value)
        for value in (snippet.get("requirement"), snippet.get("responsibility"))
        if value
    ]
    return plain_text(" ".join(parts))


def _remote_from_belarus(
    item: Mapping[str, Any],
    country_by_area: Mapping[str, str],
) -> bool | None:
    country = country_by_area.get(str(_mapping(item.get("area")).get("id")), "")
    if country.casefold() == "беларусь":
        return True

    description = _snippet_text(item).casefold()
    disallowed_markers = (
        "только для граждан рф",
        "только для резидентов рф",
        "только россия",
        "remote only from russia",
        "russia only",
    )
    if any(marker in description for marker in disallowed_markers):
        return False
    if "беларус" in description or "belarus" in description:
        return True
    return None
