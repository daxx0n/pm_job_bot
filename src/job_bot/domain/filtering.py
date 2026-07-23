from __future__ import annotations

import re

from job_bot.domain.models import Decision, EmploymentFormat, Vacancy

_TITLE_PATTERNS = (
    r"\bproject manager\b",
    r"\bit project manager\b",
    r"\btechnical project manager\b",
    r"\bimplementation project manager\b",
    r"\bproject coordinator\b",
    r"\bdelivery coordinator\b",
    r"\bменеджер проектов\b",
    r"\bруководитель проектов\b",
)

_SENIOR_TITLE_MARKERS = ("senior", "lead", "head", "director", "руководитель направления")
_DISALLOWED_COUNTRIES = {"украина", "ukraine", "ua"}
_BELARUS_NAMES = {"беларусь", "belarus", "by"}
_ENGLISH_RANK = {
    "a1": 1,
    "beginner": 1,
    "a2": 2,
    "elementary": 2,
    "b1": 3,
    "intermediate": 3,
    "b2": 4,
    "upper-intermediate": 4,
    "c1": 5,
    "advanced": 5,
    "c2": 6,
    "proficiency": 6,
}


class EligibilityFilter:
    """Apply the agreed hard filters before a vacancy reaches Telegram."""

    def evaluate(self, vacancy: Vacancy) -> Decision:
        reasons: list[str] = []
        warnings: list[str] = []
        score = 100

        title = vacancy.title.casefold()
        if not any(re.search(pattern, title) for pattern in _TITLE_PATTERNS):
            reasons.append("должность не относится к Project Management")

        if any(marker in title for marker in _SENIOR_TITLE_MARKERS):
            reasons.append("senior/lead/head/director позиция")

        country = (vacancy.country or "").strip().casefold()
        if country in _DISALLOWED_COUNTRIES:
            reasons.append("вакансии из Украины исключены")

        is_belarus = country in _BELARUS_NAMES
        if vacancy.employment_format is EmploymentFormat.OFFICE:
            reasons.append("офисный формат не подходит")
        elif vacancy.employment_format is EmploymentFormat.HYBRID and not is_belarus:
            reasons.append("гибрид разрешён только для Беларуси")

        if vacancy.remote_from_belarus is False:
            reasons.append("нельзя работать удалённо из Беларуси")
        elif vacancy.remote_from_belarus is None:
            warnings.append("доступность работы из Беларуси не подтверждена")
            score -= 10

        if vacancy.experience_min_years is not None and vacancy.experience_min_years > 3:
            reasons.append("требуется более 3 лет опыта")

        english = (vacancy.required_english_level or "").strip().casefold()
        if english and _ENGLISH_RANK.get(english, 0) > _ENGLISH_RANK["b1"]:
            reasons.append("обязательный английский выше B1")
        elif english and english not in _ENGLISH_RANK:
            warnings.append(
                f"уровень английского «{vacancy.required_english_level}» требует проверки"
            )
            score -= 5

        if vacancy.salary_max_usd is not None and vacancy.salary_max_usd < 1000:
            reasons.append("верхняя граница зарплаты ниже 1000 USD")
        elif vacancy.salary_min_usd is not None and vacancy.salary_min_usd < 1000:
            warnings.append("нижняя граница зарплаты ниже 1000 USD")
            score -= 10
        elif (
            vacancy.salary_currency
            and vacancy.salary_currency != "USD"
            and vacancy.salary_min_usd is None
            and vacancy.salary_max_usd is None
        ):
            warnings.append(
                f"не удалось пересчитать зарплату из {vacancy.salary_currency} в USD"
            )
            score -= 5

        if vacancy.experience_min_years is None:
            warnings.append("требуемый опыт не указан")
            score -= 5

        return Decision(
            accepted=not reasons,
            score=max(0, score if not reasons else 0),
            reasons=tuple(reasons),
            warnings=tuple(warnings),
        )
