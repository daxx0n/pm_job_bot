from __future__ import annotations

from datetime import UTC, datetime
from html import escape
from zoneinfo import ZoneInfo

from job_bot.domain import Decision, EmploymentFormat, Vacancy
from job_bot.storage import MatchedVacancy

_FORMAT_LABELS = {
    EmploymentFormat.REMOTE: "Удалённо",
    EmploymentFormat.HYBRID: "Гибрид",
    EmploymentFormat.OFFICE: "Офис",
    EmploymentFormat.UNKNOWN: "Не указан",
}
_DISPLAY_TIMEZONE = ZoneInfo("Europe/Minsk")


def _salary(vacancy: Vacancy) -> str:
    minimum = vacancy.salary_min_usd
    maximum = vacancy.salary_max_usd
    currency = "USD"
    prefix = "$"
    if minimum is None and maximum is None and vacancy.salary_currency:
        minimum = vacancy.salary_min
        maximum = vacancy.salary_max
        currency = vacancy.salary_currency
        prefix = ""

    if minimum is None and maximum is None:
        return "Не указана"
    suffix = "" if prefix else f" {escape(currency)}"
    if minimum is not None and maximum is not None:
        return f"{prefix}{minimum}–{maximum}{suffix}"
    if minimum is not None:
        return f"от {prefix}{minimum}{suffix}"
    return f"до {prefix}{maximum}{suffix}"


def _experience(vacancy: Vacancy) -> str:
    minimum = vacancy.experience_min_years
    maximum = vacancy.experience_max_years
    if minimum is None and maximum is None:
        return "Не указан"
    if minimum is not None and maximum is not None:
        if minimum == maximum:
            return f"{minimum:g} {_years_label(minimum)}"
        return f"{minimum:g}–{maximum:g} {_years_label(maximum)}"
    if minimum is not None:
        suffix = "года" if minimum == 1 else "лет"
        return f"от {minimum:g} {suffix}"
    suffix = "года" if maximum == 1 else "лет"
    return f"до {maximum:g} {suffix}"


def _years_label(value: float) -> str:
    if not float(value).is_integer():
        return "года"
    years = int(value)
    if years % 10 == 1 and years % 100 != 11:
        return "год"
    if years % 10 in {2, 3, 4} and years % 100 not in {12, 13, 14}:
        return "года"
    return "лет"


def _published_at(vacancy: Vacancy) -> str:
    value = vacancy.published_at
    if value is None:
        return "Не указаны"
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    local_value = value.astimezone(_DISPLAY_TIMEZONE)
    if not vacancy.publication_time_known:
        return f"{local_value:%d.%m.%Y} (время не указано)"
    return f"{local_value:%d.%m.%Y %H:%M} (Минск)"


def _short_date(value: datetime | None) -> str:
    if value is None:
        return "дата не указана"
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(_DISPLAY_TIMEZONE).strftime("%d.%m.%Y")


def _clip(value: str, limit: int) -> str:
    return value if len(value) <= limit else f"{value[: limit - 1]}…"


def format_vacancy(vacancy: Vacancy, decision: Decision) -> str:
    """Render a compact, HTML-safe vacancy card for Telegram."""

    company = escape(vacancy.company or "Не указана")
    location = escape(vacancy.location or vacancy.country or "Не указана")
    source = escape(vacancy.source)
    title = escape(vacancy.title)
    english = escape(vacancy.required_english_level or "Не указан")

    lines = [
        f"<b>🔥 {title}</b>",
        "",
        f"<b>Компания:</b> {company}",
        f"<b>Локация:</b> {location}",
        f"<b>Формат:</b> {_FORMAT_LABELS[vacancy.employment_format]}",
        f"<b>Опыт:</b> {_experience(vacancy)}",
        f"<b>Зарплата:</b> {_salary(vacancy)}",
        f"<b>Английский:</b> {english}",
        f"<b>Опубликовано:</b> {_published_at(vacancy)}",
        f"<b>Совпадение:</b> {decision.score}%",
        f"<b>Источник:</b> {source}",
    ]

    if decision.warnings:
        warnings = "; ".join(escape(item) for item in decision.warnings)
        lines.extend(("", f"⚠️ <b>Проверить:</b> {warnings}"))

    return "\n".join(lines)


def format_latest_matches(source: str, vacancies: tuple[MatchedVacancy, ...]) -> str:
    """Render up to ten recent accepted vacancies from one source."""

    lines = [f"<b>Последние подходящие — {escape(source)}</b>", ""]
    if not vacancies:
        lines.append("Подходящих вакансий из этого источника пока нет.")
        return "\n".join(lines)

    for index, vacancy in enumerate(vacancies, start=1):
        company = escape(_clip(vacancy.company or "Компания не указана", 80))
        location = escape(_clip(vacancy.location or "локация не указана", 80))
        title = escape(_clip(vacancy.title, 140))
        url = escape(vacancy.url, quote=True)
        score = f" · {vacancy.score}%" if vacancy.score is not None else ""
        lines.append(
            f'{index}. <a href="{url}">{title}</a>\n'
            f"   {company} · {location} · {_short_date(vacancy.published_at)}{score}"
        )
    return "\n".join(lines)
