import sys
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from job_bot.domain import Decision, EmploymentFormat, Vacancy
from job_bot.storage import MatchedVacancy
from job_bot.telegram.formatting import format_latest_matches, format_vacancy


class TelegramFormattingTests(unittest.TestCase):
    def vacancy(self, **overrides: object) -> Vacancy:
        values: dict[str, object] = {
            "source": "HeadHunter",
            "external_id": "42",
            "title": "Junior Project Manager",
            "url": "https://example.test/jobs/42",
            "company": "Example & Partners",
            "country": "Belarus",
            "location": "Минск",
            "employment_format": EmploymentFormat.REMOTE,
            "experience_min_years": 1,
            "experience_max_years": 3,
            "required_english_level": "B1",
            "salary_min_usd": 1000,
            "salary_max_usd": 1500,
            "published_at": datetime.fromisoformat("2026-07-24T10:00:00+00:00"),
        }
        values.update(overrides)
        return Vacancy(**values)  # type: ignore[arg-type]

    def test_formats_vacancy_card(self) -> None:
        message = format_vacancy(self.vacancy(), Decision(accepted=True, score=95))

        self.assertIn("<b>🔥 Junior Project Manager</b>", message)
        self.assertIn("Example &amp; Partners", message)
        self.assertIn("<b>Локация:</b> Минск", message)
        self.assertIn("<b>Опыт:</b> 1–3 года", message)
        self.assertIn("$1000–1500", message)
        self.assertIn("<b>Опубликовано:</b> 24.07.2026 13:00 (Минск)", message)
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

    def test_formats_missing_source_details(self) -> None:
        message = format_vacancy(
            self.vacancy(
                company=None,
                country=None,
                location=None,
                experience_min_years=None,
                experience_max_years=None,
                published_at=None,
            ),
            Decision(accepted=True, score=90),
        )

        self.assertIn("<b>Компания:</b> Не указана", message)
        self.assertIn("<b>Локация:</b> Не указана", message)
        self.assertIn("<b>Опыт:</b> Не указан", message)
        self.assertIn("<b>Опубликовано:</b> Не указаны", message)

    def test_formats_latest_matches_for_one_source(self) -> None:
        vacancies = (
            MatchedVacancy(
                source="Telegram/@igaming_work",
                external_id="1",
                title="Junior Project Manager",
                url="https://example.test/jobs/1?a=1&b=2",
                company="Example & Partners",
                location="Remote",
                published_at=datetime.fromisoformat("2026-07-24T10:00:00+00:00"),
                score=95,
            ),
        )

        message = format_latest_matches("Telegram/@igaming_work", vacancies)

        self.assertIn("Последние подходящие — Telegram/@igaming_work", message)
        self.assertIn(
            '<a href="https://example.test/jobs/1?a=1&amp;b=2">'
            "Junior Project Manager</a>",
            message,
        )
        self.assertIn("Example &amp; Partners · Remote · 24.07.2026 · 95%", message)

    def test_formats_empty_latest_matches(self) -> None:
        message = format_latest_matches("HeadHunter", ())

        self.assertIn("Подходящих вакансий из этого источника пока нет.", message)


if __name__ == "__main__":
    unittest.main()
