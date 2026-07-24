import sys
import unittest
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from job_bot.domain import Decision, EligibilityFilter, EmploymentFormat, Vacancy
from job_bot.pipeline import VacancyPipeline


class FakeSource:
    name = "test"

    def __init__(self, vacancies: list[Vacancy]) -> None:
        self._vacancies = vacancies

    async def fetch(self) -> AsyncIterator[Vacancy]:
        for vacancy in self._vacancies:
            yield vacancy


class MemoryStore:
    def __init__(self) -> None:
        self.keys: dict[tuple[str, str], bool] = {}
        self.matches: list[tuple[Vacancy, Decision]] = []
        self.refreshed: list[tuple[Vacancy, Decision]] = []

    async def claim(self, vacancy: Vacancy) -> bool:
        key = (vacancy.source, vacancy.external_id)
        if key in self.keys:
            return not self.keys[key]
        self.keys[key] = False
        return True

    async def complete(self, vacancy: Vacancy, *, notified: bool) -> None:
        self.keys[(vacancy.source, vacancy.external_id)] = True

    async def record_match(self, vacancy: Vacancy, decision: Decision) -> None:
        if not any(
            item.source == vacancy.source and item.external_id == vacancy.external_id
            for item, _ in self.matches
        ):
            self.matches.append((vacancy, decision))

    async def refresh_match(self, vacancy: Vacancy, decision: Decision) -> None:
        self.refreshed.append((vacancy, decision))


class RecordingNotifier:
    def __init__(self, *, enabled: bool = True) -> None:
        self.sent: list[tuple[Vacancy, Decision]] = []
        self.enabled = enabled

    async def send_vacancy(self, vacancy: Vacancy, decision: Decision) -> bool:
        if not self.enabled:
            return False
        self.sent.append((vacancy, decision))
        return True


class FailingNotifier:
    async def send_vacancy(self, vacancy: Vacancy, decision: Decision) -> bool:
        raise RuntimeError("temporary Telegram failure")


class VacancyPipelineTests(unittest.IsolatedAsyncioTestCase):
    def vacancy(self, external_id: str, **overrides: object) -> Vacancy:
        values: dict[str, object] = {
            "source": "test",
            "external_id": external_id,
            "title": "Junior Project Manager",
            "url": f"https://example.test/{external_id}",
            "country": "Belarus",
            "employment_format": EmploymentFormat.REMOTE,
            "remote_from_belarus": True,
            "experience_min_years": 1,
            "required_english_level": "B1",
            "salary_min_usd": 1200,
        }
        values.update(overrides)
        return Vacancy(**values)  # type: ignore[arg-type]

    async def test_sends_only_new_accepted_vacancies(self) -> None:
        accepted = self.vacancy("1")
        rejected = self.vacancy("2", required_english_level="B2")
        source = FakeSource([accepted, rejected])
        store = MemoryStore()
        notifier = RecordingNotifier()
        pipeline = VacancyPipeline(
            source=source,
            store=store,
            notifier=notifier,
            eligibility_filter=EligibilityFilter(),
        )

        first_result = await pipeline.run_once()
        second_result = await pipeline.run_once()

        self.assertEqual(first_result, (2, 1))
        self.assertEqual(second_result, (2, 0))
        self.assertEqual([item[0].external_id for item in notifier.sent], ["1"])
        self.assertEqual([item[0].external_id for item in store.matches], ["1"])
        self.assertEqual(
            [item[0].external_id for item in store.refreshed],
            ["1", "2"],
        )

    async def test_refreshes_existing_metadata_without_resending(self) -> None:
        original = self.vacancy("1", published_at=None)
        refreshed = self.vacancy(
            "1",
            published_at=datetime.fromisoformat("2026-07-20T10:00:00+03:00"),
        )
        store = MemoryStore()
        notifier = RecordingNotifier()
        first_pipeline = VacancyPipeline(
            source=FakeSource([original]),
            store=store,
            notifier=notifier,
            eligibility_filter=EligibilityFilter(),
        )
        second_pipeline = VacancyPipeline(
            source=FakeSource([refreshed]),
            store=store,
            notifier=notifier,
            eligibility_filter=EligibilityFilter(),
        )

        self.assertEqual(await first_pipeline.run_once(), (1, 1))
        self.assertEqual(await second_pipeline.run_once(), (1, 0))
        self.assertEqual(len(notifier.sent), 1)
        self.assertEqual(store.refreshed[0][0].published_at, refreshed.published_at)

    async def test_records_muted_match_without_sending_notification(self) -> None:
        vacancy = self.vacancy("1")
        store = MemoryStore()
        notifier = RecordingNotifier(enabled=False)
        pipeline = VacancyPipeline(
            source=FakeSource([vacancy]),
            store=store,
            notifier=notifier,
            eligibility_filter=EligibilityFilter(),
        )

        result = await pipeline.run_once()

        self.assertEqual(result, (1, 0))
        self.assertEqual(notifier.sent, [])
        self.assertEqual([item[0].external_id for item in store.matches], ["1"])

    async def test_retries_vacancy_after_notification_failure(self) -> None:
        vacancy = self.vacancy("1")
        store = MemoryStore()
        failed_pipeline = VacancyPipeline(
            source=FakeSource([vacancy]),
            store=store,
            notifier=FailingNotifier(),
            eligibility_filter=EligibilityFilter(),
        )

        with self.assertRaisesRegex(RuntimeError, "temporary Telegram failure"):
            await failed_pipeline.run_once()

        notifier = RecordingNotifier()
        retry_pipeline = VacancyPipeline(
            source=FakeSource([vacancy]),
            store=store,
            notifier=notifier,
            eligibility_filter=EligibilityFilter(),
        )
        result = await retry_pipeline.run_once()

        self.assertEqual(result, (1, 1))
        self.assertEqual(len(notifier.sent), 1)


if __name__ == "__main__":
    unittest.main()
