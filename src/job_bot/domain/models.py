from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class EmploymentFormat(StrEnum):
    REMOTE = "remote"
    HYBRID = "hybrid"
    OFFICE = "office"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class Vacancy:
    source: str
    external_id: str
    title: str
    url: str
    description: str = ""
    company: str | None = None
    country: str | None = None
    employment_format: EmploymentFormat = EmploymentFormat.UNKNOWN
    remote_from_belarus: bool | None = None
    experience_min_years: float | None = None
    experience_max_years: float | None = None
    required_english_level: str | None = None
    salary_min_usd: int | None = None
    salary_max_usd: int | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    salary_currency: str | None = None
    published_at: datetime | None = None
    raw: dict[str, Any] = field(default_factory=dict, compare=False, repr=False)


@dataclass(frozen=True, slots=True)
class Decision:
    accepted: bool
    score: int
    reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
