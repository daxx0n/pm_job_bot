from __future__ import annotations

from html import escape

from job_bot.domain import Decision, EmploymentFormat, Vacancy

_FORMAT_LABELS = {
    EmploymentFormat.REMOTE: "Удалённо",
    EmploymentFormat.HYBRID: "Гибрид",
    EmploymentFormat.OFFICE: "Офис",
    EmploymentFormat.UNKNOWN: "Не указан",
}


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


def format_vacancy(vacancy: Vacancy, decision: Decision) -> str:
    """Render a compact, HTML-safe vacancy card for Telegram."""

    company = escape(vacancy.company or "Не указана")
    country = escape(vacancy.country or "Не указана")
    source = escape(vacancy.source)
    title = escape(vacancy.title)
    english = escape(vacancy.required_english_level or "Не указан")

    lines = [
        f"<b>🔥 {title}</b>",
        "",
        f"<b>Компания:</b> {company}",
        f"<b>Локация:</b> {country}",
        f"<b>Формат:</b> {_FORMAT_LABELS[vacancy.employment_format]}",
        f"<b>Зарплата:</b> {_salary(vacancy)}",
        f"<b>Английский:</b> {english}",
        f"<b>Совпадение:</b> {decision.score}%",
        f"<b>Источник:</b> {source}",
    ]

    if decision.warnings:
        warnings = "; ".join(escape(item) for item in decision.warnings)
        lines.extend(("", f"⚠️ <b>Проверить:</b> {warnings}"))

    return "\n".join(lines)
