"""Domain rules for vacancy matching."""

from job_bot.domain.filtering import EligibilityFilter
from job_bot.domain.models import Decision, EmploymentFormat, Vacancy

__all__ = ["Decision", "EligibilityFilter", "EmploymentFormat", "Vacancy"]

