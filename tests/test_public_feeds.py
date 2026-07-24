import sys
import unittest
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from job_bot.sources.public_feeds import PublicRssSource, RemotiveSource


class PublicFeedSourceTests(unittest.IsolatedAsyncioTestCase):
    async def test_remotive_parses_worldwide_project_manager(self) -> None:
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            self.assertEqual(request.url.params["category"], "project-management")
            return httpx.Response(
                200,
                json={
                    "jobs": [
                        {
                            "id": 17,
                            "url": "https://remotive.example/jobs/17",
                            "title": "Junior Project Manager",
                            "company_name": "Example",
                            "candidate_required_location": "Worldwide",
                            "salary": "$24,000 - $36,000 per year",
                            "publication_date": "2026-07-24T10:00:00",
                            "description": "<p>At least 2 years experience. English B1.</p>",
                        }
                    ]
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            source = RemotiveSource(client)
            first = [vacancy async for vacancy in source.fetch()]
            second = [vacancy async for vacancy in source.fetch()]

        vacancy = first[0]
        self.assertEqual(second, [])
        self.assertEqual(calls, 1)
        self.assertTrue(vacancy.remote_from_belarus)
        self.assertEqual(vacancy.experience_min_years, 2)
        self.assertEqual(vacancy.required_english_level, "B1")
        self.assertEqual(vacancy.salary_min_usd, 2000)
        self.assertEqual(vacancy.salary_max_usd, 3000)

    async def test_rss_parses_namespaced_location_and_company(self) -> None:
        rss = """<?xml version="1.0" encoding="UTF-8"?>
        <rss xmlns:himalayasJobs="https://himalayas.app/jobs">
          <channel>
            <item>
              <title>Junior Project Manager</title>
              <link>https://himalayas.example/jobs/abc</link>
              <guid>abc</guid>
              <pubDate>Fri, 24 Jul 2026 10:00:00 +0000</pubDate>
              <description>
                <![CDATA[<p>2+ years of relevant experience. English B1.</p>]]>
              </description>
              <himalayasJobs:companyName>Example Inc</himalayasJobs:companyName>
              <himalayasJobs:locationRestriction>Worldwide</himalayasJobs:locationRestriction>
            </item>
          </channel>
        </rss>"""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=rss)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            source = PublicRssSource(
                client,
                name="Himalayas",
                url="https://himalayas.example/rss",
            )
            vacancies = [vacancy async for vacancy in source.fetch()]

        vacancy = vacancies[0]
        self.assertEqual(vacancy.company, "Example Inc")
        self.assertEqual(vacancy.external_id, "abc")
        self.assertTrue(vacancy.remote_from_belarus)
        self.assertEqual(vacancy.experience_min_years, 2)

    async def test_rss_recovers_from_unbound_himalayas_prefix(self) -> None:
        rss = """<?xml version="1.0" encoding="UTF-8"?>
        <rss>
          <channel>
            <item>
              <title>Junior Project Manager</title>
              <link>https://himalayas.example/jobs/unbound-prefix</link>
              <guid>unbound-prefix</guid>
              <content:encoded>
                <![CDATA[<p>1 year of experience. English B1.</p>]]>
              </content:encoded>
              <himalayasJobs:companyName>Example Inc</himalayasJobs:companyName>
              <himalayasJobs:locationRestriction>Worldwide</himalayasJobs:locationRestriction>
            </item>
          </channel>
        </rss>"""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=rss)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            source = PublicRssSource(
                client,
                name="Himalayas",
                url="https://himalayas.example/rss",
            )
            vacancies = [vacancy async for vacancy in source.fetch()]

        vacancy = vacancies[0]
        self.assertEqual(vacancy.company, "Example Inc")
        self.assertEqual(vacancy.external_id, "unbound-prefix")
        self.assertTrue(vacancy.remote_from_belarus)
        self.assertEqual(vacancy.experience_min_years, 1)

    async def test_rss_deduplicates_repeated_long_guid(self) -> None:
        link = f"https://himalayas.example/jobs/{'long-slug-' * 20}"
        rss = f"""<rss><channel><item>
          <title>Junior Project Manager</title>
          <link>{link}</link>
          <guid>{link}</guid>
          <guid>{link}</guid>
          <description>1 year of experience. English B1.</description>
        </item></channel></rss>"""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=rss)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            source = PublicRssSource(
                client,
                name="Himalayas",
                url="https://himalayas.example/rss",
            )
            vacancies = [vacancy async for vacancy in source.fetch()]

        self.assertEqual(vacancies[0].external_id, link)
        self.assertLessEqual(len(vacancies[0].external_id), 255)

    async def test_rss_hashes_external_id_longer_than_database_limit(self) -> None:
        guid = "custom-id-" * 40
        rss = f"""<rss><channel><item>
          <title>Junior Project Manager</title>
          <link>https://himalayas.example/jobs/1</link>
          <guid>{guid}</guid>
          <description>1 year of experience. English B1.</description>
        </item></channel></rss>"""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=rss)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            source = PublicRssSource(
                client,
                name="Himalayas",
                url="https://himalayas.example/rss",
            )
            vacancies = [vacancy async for vacancy in source.fetch()]

        self.assertRegex(vacancies[0].external_id, r"^sha256:[0-9a-f]{64}$")
        self.assertLessEqual(len(vacancies[0].external_id), 255)

    async def test_rss_marks_specific_country_as_unavailable_from_belarus(self) -> None:
        rss = """<rss><channel><item>
          <title>Example: Project Manager</title>
          <link>https://example.test/jobs/1</link>
          <region>United States only</region>
          <description>Project delivery experience.</description>
        </item></channel></rss>"""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=rss)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            source = PublicRssSource(client, name="WWR", url="https://example.test/rss")
            vacancies = [vacancy async for vacancy in source.fetch()]

        self.assertEqual(vacancies[0].title, "Project Manager")
        self.assertEqual(vacancies[0].company, "Example")
        self.assertFalse(vacancies[0].remote_from_belarus)


if __name__ == "__main__":
    unittest.main()
