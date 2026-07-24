from __future__ import annotations

import asyncio
import html
import imaplib
import re
from collections.abc import AsyncIterator
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email import message_from_bytes, policy
from email.header import decode_header
from email.message import Message
from email.utils import parseaddr, parsedate_to_datetime
from hashlib import sha256
from html.parser import HTMLParser
from urllib.parse import parse_qs, unquote, urlparse

from job_bot.domain.models import EmploymentFormat, Vacancy

_VACANCY_PATH = re.compile(r"/vacanc(?:y|ies)/(\d+)(?:/|$)", re.IGNORECASE)
_PUBLIC_VACANCY_PATHS = {
    "career.habr.com": re.compile(r"/vacancies/([^/?#]+)", re.IGNORECASE),
    "geekjob.ru": re.compile(r"/vacancy/([^/?#]+)", re.IGNORECASE),
    "getmatch.ru": re.compile(r"/vacancies/([^/?#]+)", re.IGNORECASE),
    "jobs.dev.by": re.compile(r"/vacancies/([^/?#]+)", re.IGNORECASE),
    "jobs.devby.io": re.compile(r"/vacancies/([^/?#]+)", re.IGNORECASE),
}
_URL_PATTERN = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_ALLOWED_SENDER_SUFFIXES = (
    "rabota.by",
    "hh.ru",
    "habr.com",
    "geekjob.ru",
    "getmatch.ru",
    "dev.by",
    "devby.io",
)
_TITLE_MARKERS = (
    "project manager",
    "project coordinator",
    "delivery coordinator",
    "менеджер проектов",
    "руководитель проектов",
)
_NEXT_FIELD = (
    r"(?=\s+(?:компания|company|работодатель|employer|локация|location|"
    r"город|география|формат|format|зарплата|salary|опыт|experience)"
    r"\s*[:—–-]|\s*\n|$)"
)
_FIELD_PATTERNS = {
    "company": re.compile(
        r"(?:^|\s)(?:компания|company|работодатель|employer)\s*[:—–-]\s*"
        rf"(.{{2,100}}?){_NEXT_FIELD}",
        re.IGNORECASE,
    ),
    "location": re.compile(
        r"(?:^|\s)(?:локация|location|город|география)\s*[:—–-]\s*"
        rf"(.{{2,100}}?){_NEXT_FIELD}",
        re.IGNORECASE,
    ),
}


@dataclass(frozen=True, slots=True)
class _Link:
    url: str
    text: str


class _HtmlContentParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[_Link] = []
        self.text_parts: list[str] = []
        self._href: str | None = None
        self._anchor_parts: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag.casefold() == "br":
            self.text_parts.append("\n")
            return
        if tag.casefold() != "a":
            return
        self._href = next((value for key, value in attrs if key == "href"), None)
        self._anchor_parts = []

    def handle_data(self, data: str) -> None:
        value = " ".join(data.split())
        if not value:
            return
        self.text_parts.append(value)
        if self._href is not None:
            self._anchor_parts.append(value)

    def handle_endtag(self, tag: str) -> None:
        normalized_tag = tag.casefold()
        if normalized_tag in {"p", "div", "li", "tr"}:
            self.text_parts.append("\n")
        if normalized_tag != "a" or self._href is None:
            return
        self.links.append(_Link(self._href, " ".join(self._anchor_parts).strip()))
        self._href = None
        self._anchor_parts = []


class EmailAlertSource:
    """Read official vacancy-alert emails without scraping the job site."""

    name = "Rabota.by email"

    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str,
        app_password: str,
        folder: str = "INBOX",
        lookback_days: int = 2,
        max_messages: int = 50,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._app_password = app_password
        self._folder = folder
        self._lookback_days = lookback_days
        self._max_messages = max_messages

    async def fetch(self) -> AsyncIterator[Vacancy]:
        vacancies = await asyncio.to_thread(self._fetch_sync)
        for vacancy in vacancies:
            yield vacancy

    def _fetch_sync(self) -> list[Vacancy]:
        client = imaplib.IMAP4_SSL(self._host, self._port)
        try:
            client.login(self._username, self._app_password)
            status, _ = client.select(self._folder, readonly=True)
            if status != "OK":
                raise RuntimeError(f"Cannot select IMAP folder {self._folder!r}")

            since = (datetime.now(UTC) - timedelta(days=self._lookback_days)).strftime(
                "%d-%b-%Y"
            )
            status, search_data = client.uid("search", None, "SINCE", since)  # type: ignore[arg-type]
            if status != "OK":
                raise RuntimeError("IMAP message search failed")

            uids = search_data[0].split()[-self._max_messages :] if search_data else []
            vacancies: dict[str, Vacancy] = {}
            for uid in uids:
                status, message_data = client.uid("fetch", uid, "(BODY.PEEK[])")
                if status != "OK":
                    continue
                raw_message = _message_bytes(message_data)
                if raw_message is None:
                    continue
                for vacancy in parse_alert_message(raw_message):
                    vacancies.setdefault(vacancy.external_id, vacancy)
            return list(vacancies.values())
        finally:
            with suppress(imaplib.IMAP4.error):
                client.logout()


def parse_alert_message(raw_message: bytes) -> list[Vacancy]:
    message = message_from_bytes(raw_message, policy=policy.default)
    if not _is_official_sender(_decoded_header(message.get("From"))):
        return []
    subject = _decoded_header(message.get("Subject"))
    links: list[_Link] = []
    plain_parts: list[str] = []

    for part in message.walk():
        if part.get_content_disposition() == "attachment":
            continue
        content_type = part.get_content_type()
        if content_type not in {"text/plain", "text/html"}:
            continue
        payload = part.get_payload(decode=True)
        if not isinstance(payload, bytes):
            continue
        charset = part.get_content_charset() or "utf-8"
        body = payload.decode(charset, errors="replace")
        if content_type == "text/html":
            parser = _HtmlContentParser()
            parser.feed(body)
            links.extend(parser.links)
            plain_parts.append(" ".join(parser.text_parts))
        else:
            plain_parts.append(body)
            links.extend(_Link(url, "") for url in _URL_PATTERN.findall(body))

    candidates: dict[str, tuple[str, str]] = {}
    for link in links:
        vacancy_url = _vacancy_url(link.url)
        if vacancy_url is None:
            continue
        external_id, canonical_url = vacancy_url
        title = " ".join(link.text.split())
        current = candidates.get(external_id)
        if current is None or _title_quality(title) > _title_quality(current[1]):
            candidates[external_id] = (canonical_url, title)

    published_at = _message_datetime(message)
    message_id = _decoded_header(message.get("Message-ID"))
    context = " ".join((subject, *plain_parts))
    single_vacancy = len(candidates) == 1
    vacancies: list[Vacancy] = []
    for external_id, (url, title) in candidates.items():
        if not title or _title_quality(title) == 0:
            continue
        hostname = (urlparse(url).hostname or "").casefold()
        country = (
            "Беларусь"
            if hostname == "rabota.by" or hostname.endswith(".rabota.by")
            else None
        )
        vacancies.append(
            Vacancy(
                source=_email_source(hostname),
                external_id=external_id,
                title=title,
                url=url,
                description="",
                company=_field_value(context, "company") if single_vacancy else None,
                country=country,
                location=(
                    _field_value(context, "location") if single_vacancy else country
                ),
                employment_format=_employment_format(context),
                remote_from_belarus=True if country == "Беларусь" else None,
                published_at=published_at,
                raw={
                    "email_subject": subject,
                    "message_id": message_id,
                    "published_at": published_at.isoformat() if published_at else None,
                },
            )
        )
    return vacancies


def _message_bytes(message_data: list[object]) -> bytes | None:
    for item in message_data:
        if isinstance(item, tuple) and len(item) > 1 and isinstance(item[1], bytes):
            return item[1]
    return None


def _decoded_header(value: object) -> str:
    if value is None:
        return ""
    parts: list[str] = []
    for item, charset in decode_header(str(value)):
        if isinstance(item, bytes):
            parts.append(item.decode(charset or "utf-8", errors="replace"))
        else:
            parts.append(item)
    return "".join(parts)


def _is_official_sender(value: str) -> bool:
    address = parseaddr(value)[1].casefold()
    domain = address.rpartition("@")[2]
    return any(
        domain == suffix or domain.endswith(f".{suffix}")
        for suffix in _ALLOWED_SENDER_SUFFIXES
    )


def _message_datetime(message: Message) -> datetime | None:
    value = message.get("Date")
    if not value:
        return None
    try:
        return parsedate_to_datetime(str(value))
    except (TypeError, ValueError):
        return None


def _vacancy_url(raw_url: str, *, depth: int = 0) -> tuple[str, str] | None:
    if depth > 2:
        return None
    value = html.unescape(unquote(raw_url.strip().rstrip(".,);]")))
    parsed = urlparse(value)
    hostname = (parsed.hostname or "").casefold()
    match = _VACANCY_PATH.search(parsed.path)
    if match and any(
        hostname == suffix or hostname.endswith(f".{suffix}")
        for suffix in ("rabota.by", "hh.ru", "hh.kz")
    ):
        external_id = match.group(1)
        return external_id, f"{parsed.scheme}://{hostname}/vacancy/{external_id}"

    site_pattern = _PUBLIC_VACANCY_PATHS.get(hostname)
    if site_pattern is not None:
        site_match = site_pattern.search(parsed.path)
        if site_match:
            canonical_path = site_match.group(0).rstrip("/")
            raw_external_id = f"{hostname}:{site_match.group(1)}"
            external_id = (
                raw_external_id
                if len(raw_external_id) <= 255
                else f"sha256:{sha256(raw_external_id.encode()).hexdigest()}"
            )
            return external_id, f"{parsed.scheme}://{hostname}{canonical_path}"

    for values in parse_qs(parsed.query).values():
        for nested in values:
            candidate = _vacancy_url(nested, depth=depth + 1)
            if candidate is not None:
                return candidate
    return None


def _email_source(hostname: str) -> str:
    if hostname == "rabota.by" or hostname.endswith(".rabota.by"):
        return EmailAlertSource.name
    if hostname in {"hh.ru", "hh.kz"} or hostname.endswith((".hh.ru", ".hh.kz")):
        return EmailAlertSource.name
    return f"Email/{hostname}"


def _title_quality(value: str) -> int:
    normalized = value.casefold()
    if any(marker in normalized for marker in _TITLE_MARKERS):
        return 2
    if 3 <= len(value.split()) <= 12 and len(value) <= 120:
        return 1
    return 0


def _employment_format(value: str) -> EmploymentFormat:
    normalized = value.casefold()
    if "гибрид" in normalized or "hybrid" in normalized:
        return EmploymentFormat.HYBRID
    if "удален" in normalized or "удалён" in normalized or "remote" in normalized:
        return EmploymentFormat.REMOTE
    return EmploymentFormat.UNKNOWN


def _field_value(text: str, field: str) -> str | None:
    match = _FIELD_PATTERNS[field].search(text)
    return match.group(1).strip(" .") if match else None
