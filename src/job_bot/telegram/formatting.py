from __future__ import annotations

from datetime import UTC
from html import escape
from zoneinfo import ZoneInfo

from job_bot.domain import Decision, EmploymentFormat, Vacancy

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
