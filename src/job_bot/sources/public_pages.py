from __future__ import annotations

import re
import time
from collections.abc import AsyncIterator
from datetime import datetime
from hashlib import sha256
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

import httpx

from job_bot.domain.models import EmploymentFormat, Vacancy
from job_bot.domain.text_analysis import (
    infer_experience_min_years,
    infer_required_english_level,
    plain_text,
)

HABR_PROJECT_MANAGER_URL = (
    "https://career.habr.com/vacancies/project_manager/remote/full_time"
)
TELEGRAM_PREVIEW_URL = "https://t.me/s/{channel}"
_REQUEST_HEADERS = {
    "User-Agent": "project-manager-job-bot/0.1 (+https://github.com/daxx0n/pm_job_bot)"
}
_VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta"}

_PROJECT_TITLE = re.compile(
    r"(?:\b(?:junior|middle|technical|it|digital)?\s*project manager\b|"
    r"\bproject coordinator\b|\bdelivery coordinator\b|"
    r"\bменеджер(?:а|ом)? проектов\b|\bруководитель(?:я|ем)? проектов\b)",
    re.IGNORECASE,
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
    "global remote",
    "remote globally",
    "из любой страны",
    "по всему миру",
)
_BELARUS_DISALLOWED_MARKERS = (
    "remote only from russia",
    "russia only",
    "only residents of russia",
    "только для граждан рф",
    "только для резидентов рф",
    "только россия",
    "только по рф",
)
_FIELD_PATTERNS = {
    "company": re.compile(
        r"^\s*(?:компания|company|работодатель|employer)\s*[:—–-]\s*(.+?)\s*$",
        re.IGNORECASE,
    ),
    "location": re.compile(
        r"^\s*(?:локация|location|город|география)\s*[:—–-]\s*(.+?)\s*$",
        re.IGNORECASE,
    ),
}


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


class HabrCareerSource(_RefreshLimitedSource):
    name = "Habr Career"

    def __init__(self, client: httpx.AsyncClient, refresh_seconds: int = 1_800) -> None:
        super().__init__(refresh_seconds)
        self._client = client

    async def fetch(self) -> AsyncIterator[Vacancy]:
        if not self._fetch_is_due():
            return
        response = await self._client.get(HABR_PROJECT_MANAGER_URL, headers=_REQUEST_HEADERS)
        response.raise_for_status()
        parser = _HabrCareerParser()
        parser.feed(response.text)
        parser.close()
        self._mark_fetched()
        for item in parser.items:
            yield _habr_vacancy(item)


class TelegramPublicChannelSource(_RefreshLimitedSource):
    def __init__(
        self,
        client: httpx.AsyncClient,
        channel: str,
        refresh_seconds: int = 1_800,
    ) -> None:
        super().__init__(refresh_seconds)
        self._client = client
        self._channel = channel.strip().lstrip("@")
        self.name = f"Telegram/@{self._channel}"

    async def fetch(self) -> AsyncIterator[Vacancy]:
        if not self._fetch_is_due():
            return
        response = await self._client.get(
            TELEGRAM_PREVIEW_URL.format(channel=self._channel),
            headers=_REQUEST_HEADERS,
        )
        response.raise_for_status()
        parser = _TelegramPreviewParser()
        parser.feed(response.text)
        parser.close()
        self._mark_fetched()
        for post in parser.posts:
            yield _telegram_vacancy(self.name, post)


class _HabrCareerParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.items: list[dict[str, str]] = []
        self._capture: str | None = None
        self._parts: list[str] = []
        self._item: dict[str, str] | None = None

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        values = dict(attrs)
        classes = set((values.get("class") or "").split())
        if "vacancy-card" in classes:
            self._finish_item()
            self._item = {}

        if self._item is None:
            return
        if tag == "a" and "vacancy-card__title-link" in classes:
            self._capture = "title"
            self._parts = []
            self._item["url"] = urljoin(HABR_PROJECT_MANAGER_URL, values.get("href", ""))
        elif "vacancy-card__company-title" in classes:
            self._capture = "company"
            self._parts = []
        elif "vacancy-card__date" in classes:
            self._capture = "published_at"
            self._parts = []
        elif "vacancy-card__meta" in classes:
            self._capture = "meta"
            self._parts = []
        elif "vacancy-card__skills" in classes or "vacancy-card__salary" in classes:
            self._capture = "context"
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._capture is not None:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._capture is not None and tag in {"a", "div", "span"}:
            value = " ".join("".join(self._parts).split())
            if value and self._item is not None:
                if self._capture == "context":
                    self._item["context"] = " ".join(
                        filter(None, (self._item.get("context"), value))
                    )
                else:
                    self._item[self._capture] = value
            self._capture = None
            self._parts = []

    def close(self) -> None:
        super().close()
        self._finish_item()

    def _finish_item(self) -> None:
        if self._item is not None and self._item.get("title") and self._item.get("url"):
            self.items.append(self._item)
        self._item = None


class _TelegramPreviewParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.posts: list[dict[str, object]] = []
        self._message_depth = 0
        self._text_depth = 0
        self._post: dict[str, object] | None = None

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        values = dict(attrs)
        classes = set((values.get("class") or "").split())
        if tag == "br" and self._post is not None and self._text_depth:
            parts = self._post["parts"]
            assert isinstance(parts, list)
            parts.append("\n")
            return
        if tag in _VOID_TAGS:
            return
        if self._message_depth:
            self._message_depth += 1
        elif "js-widget_message" in classes and values.get("data-post"):
            self._message_depth = 1
            self._post = {
                "post": values["data-post"],
                "parts": [],
                "links": [],
            }

        if self._post is None:
            return
        if "js-message_text" in classes:
            self._text_depth = 1
        elif self._text_depth:
            self._text_depth += 1
        if tag == "a" and self._text_depth and values.get("href"):
            links = self._post["links"]
            assert isinstance(links, list)
            links.append(values["href"])
        if tag == "time" and values.get("datetime"):
            self._post["datetime"] = values["datetime"]

    def handle_data(self, data: str) -> None:
        if self._post is None or not self._text_depth:
            return
        parts = self._post["parts"]
        assert isinstance(parts, list)
        parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._text_depth:
            self._text_depth -= 1
        if not self._message_depth:
            return
        self._message_depth -= 1
        if self._message_depth == 0 and self._post is not None:
            parts = self._post["parts"]
            assert isinstance(parts, list)
            text = _clean_multiline("".join(parts))
            if text:
                self._post["text"] = text
                self.posts.append(self._post)
            self._post = None


def _habr_vacancy(item: dict[str, str]) -> Vacancy:
    meta = plain_text(item.get("meta", ""))
    context = plain_text(" ".join((meta, item.get("context", ""))))
    url = item["url"]
    return Vacancy(
        source=HabrCareerSource.name,
        external_id=_stable_external_id(url),
        title=item["title"],
        url=url,
        description=context,
        company=item.get("company"),
        country=_country(context),
        location=_habr_location(meta) or _country(context),
        employment_format=EmploymentFormat.REMOTE,
        remote_from_belarus=_remote_from_belarus(context),
        experience_min_years=infer_experience_min_years(context),
        required_english_level=infer_required_english_level(context),
        published_at=_habr_datetime(item.get("published_at")),
        publication_time_known=False,
        raw=dict(item),
    )


def _telegram_vacancy(source: str, post: dict[str, object]) -> Vacancy:
    text = str(post["text"])
    post_id = str(post["post"])
    post_url = f"https://t.me/{post_id}"
    links = post["links"]
    assert isinstance(links, list)
    external_link = next(
        (
            str(link)
            for link in links
            if urlparse(str(link)).scheme in {"http", "https"}
            and (urlparse(str(link)).hostname or "") not in {"t.me", "telegram.me"}
        ),
        post_url,
    )
    return Vacancy(
        source=source,
        external_id=post_id,
        title=_vacancy_title(text),
        url=external_link,
        description=text,
        company=_field_value(text, "company"),
        country=_country(text),
        location=_field_value(text, "location") or _country(text),
        employment_format=_employment_format(text),
        remote_from_belarus=_remote_from_belarus(text),
        experience_min_years=infer_experience_min_years(text),
        required_english_level=infer_required_english_level(text),
        published_at=_optional_datetime(post.get("datetime")),
        raw={"post_url": post_url, "links": links},
    )


def _vacancy_title(text: str) -> str:
    for line in text.splitlines():
        value = line.strip(" #•—–-:|")
        match = _PROJECT_TITLE.search(value)
        if match:
            return value[:200]
    return text.splitlines()[0].strip()[:200]


def _clean_multiline(value: str) -> str:
    lines = (" ".join(line.split()) for line in value.splitlines())
    return "\n".join(line for line in lines if line)


def _stable_external_id(value: str) -> str:
    path = urlparse(value).path.rstrip("/").rsplit("/", 1)[-1]
    if path and len(path) <= 255:
        return path
    return f"sha256:{sha256(value.encode()).hexdigest()}"


def _country(text: str) -> str | None:
    normalized = text.casefold()
    for marker, country in _COUNTRY_MARKERS.items():
        if marker in normalized:
            return country
    return None


def _employment_format(text: str) -> EmploymentFormat:
    normalized = text.casefold()
    if "гибрид" in normalized or "hybrid" in normalized:
        return EmploymentFormat.HYBRID
    if "удален" in normalized or "удалён" in normalized or "remote" in normalized:
        return EmploymentFormat.REMOTE
    if "office" in normalized or "офис" in normalized:
        return EmploymentFormat.OFFICE
    return EmploymentFormat.UNKNOWN


def _remote_from_belarus(text: str) -> bool | None:
    normalized = plain_text(text).casefold()
    if any(marker in normalized for marker in _BELARUS_DISALLOWED_MARKERS):
        return False
    if "belarus" in normalized or "беларус" in normalized:
        return True
    if any(marker in normalized for marker in _WORLDWIDE_MARKERS):
        return True
    return None


def _optional_datetime(value: object) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _field_value(text: str, field: str) -> str | None:
    pattern = _FIELD_PATTERNS[field]
    for line in text.splitlines():
        match = pattern.match(line)
        if match:
            return match.group(1).strip(" .")
    return None


def _habr_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.casefold().strip()
    months = {
        "января": 1,
        "февраля": 2,
        "марта": 3,
        "апреля": 4,
        "мая": 5,
        "июня": 6,
        "июля": 7,
        "августа": 8,
        "сентября": 9,
        "октября": 10,
        "ноября": 11,
        "декабря": 12,
    }
    match = re.fullmatch(r"(\d{1,2})\s+([а-яё]+)(?:\s+(\d{4}))?", normalized)
    if not match or match.group(2) not in months:
        return _optional_datetime(value)
    now = datetime.now(ZoneInfo("Europe/Minsk"))
    year = int(match.group(3)) if match.group(3) else now.year
    return datetime(year, months[match.group(2)], int(match.group(1)), tzinfo=now.tzinfo)


def _habr_location(meta: str) -> str | None:
    value = re.sub(
        r"\b(?:intern|junior|middle\+?|senior|lead)\b",
        " ",
        meta,
        flags=re.IGNORECASE,
    )
    value = re.sub(
        r"(?:можно\s+удал[её]нно|удал[её]нно|remote|гибрид|hybrid|офис|office)",
        " ",
        value,
        flags=re.IGNORECASE,
    )
    value = " ".join(value.strip(" ,;—–-").split())
    return value or None
