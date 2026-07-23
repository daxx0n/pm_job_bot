import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from job_bot.domain import EligibilityFilter, EmploymentFormat, Vacancy


class EligibilityFilterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.filter = EligibilityFilter()

    def vacancy(self, **overrides: object) -> Vacancy:
        values: dict[str, object] = {
            "source": "test",
            "external_id": "1",
            "title": "Junior Project Manager",
            "url": "https://example.test/jobs/1",
            "country": "Belarus",
            "employment_format": EmploymentFormat.REMOTE,
            "remote_from_belarus": True,
            "experience_min_years": 1,
            "required_english_level": "B1",
            "salary_min_usd": 1200,
        }
        values.update(overrides)
        return Vacancy(**values)  # type: ignore[arg-type]

    def test_accepts_matching_remote_vacancy(self) -> None:
        decision = self.filter.evaluate(self.vacancy())

        self.assertTrue(decision.accepted)
        self.assertEqual(decision.score, 100)

    def test_rejects_ukraine(self) -> None:
        decision = self.filter.evaluate(self.vacancy(country="Ukraine"))

        self.assertFalse(decision.accepted)
        self.assertIn("вакансии из Украины исключены", decision.reasons)

    def test_rejects_hybrid_outside_belarus(self) -> None:
        decision = self.filter.evaluate(
            self.vacancy(country="Kazakhstan", employment_format=EmploymentFormat.HYBRID)
        )

        self.assertFalse(decision.accepted)
        self.assertIn("гибрид разрешён только для Беларуси", decision.reasons)

    def test_rejects_required_b2(self) -> None:
        decision = self.filter.evaluate(self.vacancy(required_english_level="B2"))

        self.assertFalse(decision.accepted)
        self.assertIn("обязательный английский выше B1", decision.reasons)

    def test_warns_when_salary_range_starts_below_target(self) -> None:
        decision = self.filter.evaluate(
            self.vacancy(salary_min_usd=900, salary_max_usd=1200)
        )

        self.assertTrue(decision.accepted)
        self.assertIn("нижняя граница зарплаты ниже 1000 USD", decision.warnings)

    def test_rejects_salary_below_target(self) -> None:
        decision = self.filter.evaluate(
            self.vacancy(salary_min_usd=700, salary_max_usd=900)
        )

        self.assertFalse(decision.accepted)
        self.assertIn("верхняя граница зарплаты ниже 1000 USD", decision.reasons)

    def test_rejects_more_than_three_years_experience(self) -> None:
        decision = self.filter.evaluate(self.vacancy(experience_min_years=4))

        self.assertFalse(decision.accepted)
        self.assertIn("требуется более 3 лет опыта", decision.reasons)

    def test_warns_when_non_usd_salary_needs_conversion(self) -> None:
        decision = self.filter.evaluate(
            self.vacancy(
                salary_min_usd=None,
                salary_currency="BYR",
                salary_min=3500,
                salary_max=5000,
            )
        )

        self.assertTrue(decision.accepted)
        self.assertIn("зарплата указана в BYR, нужен пересчёт в USD", decision.warnings)


if __name__ == "__main__":
    unittest.main()
