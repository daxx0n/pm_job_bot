import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from job_bot.domain import Decision, EmploymentFormat, Vacancy
from job_bot.telegram.formatting import format_vacancy


class TelegramFormattingTests(unittest.TestCase):
    def vacancy(self, **overrides: object) -> Vacancy:
        values: dict[str, object] = {
            "source": "HeadHunter",
            "external_id": "42",
            "title": "Junior Project Manager",
            "url": "https://example.test/jobs/42",
            "company": "Example & Partners",
            "country": "Belarus",
            "employment_format": EmploymentFormat.REMOTE,
            "required_english_level": "B1",
            "salary_min_usd": 1000,
            "salary_max_usd": 1500,
        }
        values.update(overrides)
        return Vacancy(**values)  # type: ignore[arg-type]

    def test_formats_vacancy_card(self) -> None:
        message = format_vacancy(self.vacancy(), Decision(accepted=True, score=95))

        self.assertIn("<b>🔥 Junior Project Manager</b>", message)
        self.assertIn("Example &amp; Partners", message)
        self.assertIn("$1000–1500", message)
        self.assertIn("<b>Совпадение:</b> 95%", message)

    def test_formats_missing_salary(self) -> None:
        message = format_vacancy(
            self.vacancy(salary_min_usd=None, salary_max_usd=None),
            Decision(accepted=True, score=90),
        )

        self.assertIn("<b>Зарплата:</b> Не указана", message)

    def test_escapes_warning_text(self) -> None:
        message = format_vacancy(
            self.vacancy(),
            Decision(accepted=True, score=90, warnings=("проверить A < B",)),
        )

        self.assertIn("проверить A &lt; B", message)

    def test_formats_original_non_usd_salary(self) -> None:
        message = format_vacancy(
            self.vacancy(
                salary_min_usd=None,
                salary_max_usd=None,
                salary_min=3500,
                salary_max=5000,
                salary_currency="BYR",
            ),
            Decision(accepted=True, score=90),
        )

        self.assertIn("<b>Зарплата:</b> 3500–5000 BYR", message)


if __name__ == "__main__":
    unittest.main()
