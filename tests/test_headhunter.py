import sys
import unittest
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from job_bot.domain import EmploymentFormat
from job_bot.sources.headhunter import HeadHunterSource


class HeadHunterSourceTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def areas_response() -> list[dict[str, object]]:
        return [
            {
                "id": "16",
                "name": "Беларусь",
                "areas": [{"id": "1002", "name": "Минск", "areas": []}],
            },
            {
                "id": "40",
                "name": "Казахстан",
                "areas": [{"id": "160", "name": "Алматы", "areas": []}],
            },
        ]

    async def test_fetches_and_normalizes_unique_vacancy(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.url.path == "/areas":
                return httpx.Response(200, json=self.areas_response())
            return httpx.Response(
                200,
                json={
                    "pages": 1,
                    "items": [
                        {
                            "id": "123",
                            "name": "Junior Project Manager",
                            "alternate_url": "https://rabota.by/vacancy/123",
                            "employer": {"name": "Example"},
                            "area": {"id": "1002", "name": "Минск"},
                            "experience": {"id": "between1And3", "name": "От 1 до 3 лет"},
                            "work_format": [{"id": "REMOTE", "name": "Удалённо"}],
                            "snippet": {
                                "requirement": "Английский язык <highlighttext>B1</highlighttext>"
                            },
                            "salary": {"from": 1200, "to": 1600, "currency": "USD"},
                            "published_at": "2026-07-23T10:00:00+03:00",
                        }
                    ],
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            source = HeadHunterSource(client, user_agent="test/1.0")
            vacancies = [vacancy async for vacancy in source.fetch()]

        self.assertEqual(len(vacancies), 1)
        vacancy = vacancies[0]
        self.assertEqual(vacancy.external_id, "123")
        self.assertEqual(vacancy.country, "Беларусь")
        self.assertEqual(vacancy.employment_format, EmploymentFormat.REMOTE)
        self.assertEqual(vacancy.experience_min_years, 1)
        self.assertEqual(vacancy.experience_max_years, 3)
        self.assertEqual(vacancy.required_english_level, "B1")
        self.assertEqual(vacancy.salary_min_usd, 1200)
        self.assertEqual(vacancy.salary_max_usd, 1600)
        self.assertTrue(all(request.headers["User-Agent"] == "test/1.0" for request in requests))
        vacancy_requests = [request for request in requests if request.url.path == "/vacancies"]
        work_formats = {request.url.params["work_format"] for request in vacancy_requests}
        self.assertEqual(work_formats, {"REMOTE", "HYBRID"})
        remote_request = next(
            request
            for request in vacancy_requests
            if request.url.params["work_format"] == "REMOTE"
        )
        self.assertEqual(set(remote_request.url.params.get_list("area")), {"16", "40"})

    async def test_preserves_non_usd_salary_without_treating_it_as_usd(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/areas":
                return httpx.Response(200, json=self.areas_response())
            return httpx.Response(
                200,
                json={
                    "pages": 1,
                    "items": [
                        {
                            "id": "456",
                            "name": "Project Manager",
                            "alternate_url": "https://rabota.by/vacancy/456",
                            "area": {"id": "1002", "name": "Минск"},
                            "work_format": [{"id": "HYBRID", "name": "Гибрид"}],
                            "salary": {"from": 3500, "to": 5000, "currency": "BYR"},
                        }
                    ],
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            vacancies = [
                vacancy
                async for vacancy in HeadHunterSource(client, user_agent="test/1.0").fetch()
            ]

        vacancy = vacancies[0]
        self.assertEqual(vacancy.employment_format, EmploymentFormat.HYBRID)
        self.assertIsNone(vacancy.salary_min_usd)
        self.assertEqual(vacancy.salary_min, 3500)
        self.assertEqual(vacancy.salary_currency, "BYR")

    async def test_rejects_foreign_remote_limited_to_russia(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/areas":
                return httpx.Response(200, json=self.areas_response())
            return httpx.Response(
                200,
                json={
                    "pages": 1,
                    "items": [
                        {
                            "id": "789",
                            "name": "Project Manager",
                            "alternate_url": "https://hh.kz/vacancy/789",
                            "area": {"id": "160", "name": "Алматы"},
                            "work_format": [{"id": "REMOTE", "name": "Удалённо"}],
                            "snippet": {
                                "requirement": "Удалённая работа только для резидентов РФ"
                            },
                        }
                    ],
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            vacancies = [
                vacancy
                async for vacancy in HeadHunterSource(client, user_agent="test/1.0").fetch()
            ]

        self.assertEqual(vacancies[0].country, "Казахстан")
        self.assertFalse(vacancies[0].remote_from_belarus)


if __name__ == "__main__":
    unittest.main()
