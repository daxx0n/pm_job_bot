import sys
import unittest
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from job_bot.domain import EmploymentFormat
from job_bot.sources.career_pages import GreenhouseSource, LeverSource


class CareerPageSourceTests(unittest.IsolatedAsyncioTestCase):
    async def test_greenhouse_parses_remote_project_vacancy(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.params["content"], "true")
            return httpx.Response(
                200,
                json={
                    "jobs": [
                        {
                            "id": 42,
                            "title": "Junior Project Manager",
                            "absolute_url": "https://example.test/jobs/42",
                            "updated_at": "2026-07-23T10:00:00Z",
                            "location": {"name": "Remote, Worldwide"},
                            "content": "<p>English B1. Work from anywhere.</p>",
                        }
                    ]
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            vacancies = [
                vacancy async for vacancy in GreenhouseSource(client, "example").fetch()
            ]

        self.assertEqual(vacancies[0].source, "Greenhouse/example")
        self.assertEqual(vacancies[0].employment_format, EmploymentFormat.REMOTE)
        self.assertTrue(vacancies[0].remote_from_belarus)
        self.assertEqual(vacancies[0].required_english_level, "B1")

    async def test_lever_detects_disallowed_russia_only_remote(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.params["mode"], "json")
            return httpx.Response(
                200,
                json=[
                    {
                        "id": "abc",
                        "text": "Project Manager",
                        "hostedUrl": "https://jobs.lever.co/example/abc",
                        "createdAt": 1784800800000,
                        "categories": {"location": "Remote"},
                        "descriptionPlain": "Remote only from Russia. English B1.",
                    }
                ],
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            vacancies = [vacancy async for vacancy in LeverSource(client, "example").fetch()]

        self.assertEqual(vacancies[0].source, "Lever/example")
        self.assertEqual(vacancies[0].country, "Россия")
        self.assertFalse(vacancies[0].remote_from_belarus)
        self.assertIsNotNone(vacancies[0].published_at)
        self.assertEqual(
            vacancies[0].published_at.isoformat(),
            "2026-07-23T10:00:00+00:00",
        )


if __name__ == "__main__":
    unittest.main()
