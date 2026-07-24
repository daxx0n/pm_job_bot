import httpx
import pytest

from job_bot.domain.models import EmploymentFormat
from job_bot.sources.public_pages import HabrCareerSource, TelegramPublicChannelSource


@pytest.mark.asyncio
async def test_habr_career_parses_public_vacancy_cards() -> None:
    html = """
    <article class="vacancy-card">
      <div>
        <a class="vacancy-card__title-link" href="/vacancies/1000123">
          Junior Project Manager
        </a>
        <div class="vacancy-card__company-title">Example</div>
        <div class="vacancy-card__meta">Intern Можно удалённо Минск</div>
        <div class="vacancy-card__skills">Agile Scrum English B1</div>
      </div>
    </article>
    """

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "career.habr.com"
        return httpx.Response(200, text=html)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        source = HabrCareerSource(client)
        vacancies = [vacancy async for vacancy in source.fetch()]
        repeated = [vacancy async for vacancy in source.fetch()]

    assert repeated == []
    assert len(vacancies) == 1
    vacancy = vacancies[0]
    assert vacancy.external_id == "1000123"
    assert vacancy.title == "Junior Project Manager"
    assert vacancy.company == "Example"
    assert vacancy.url == "https://career.habr.com/vacancies/1000123"
    assert vacancy.employment_format is EmploymentFormat.REMOTE
    assert vacancy.required_english_level == "B1"


@pytest.mark.asyncio
async def test_telegram_preview_parses_public_project_vacancy() -> None:
    html = """
    <div class="tgme_widget_message js-widget_message"
         data-post="projects_jobs_feed/12345">
      <div class="tgme_widget_message_text js-message_text">
        #вакансия<br>
        Junior Project Manager<br>
        Удалённо, можно работать из Беларуси.<br>
        Опыт от 2 лет. English B1.<br>
        <a href="https://example.com/jobs/pm">Описание вакансии</a>
      </div>
      <a class="tgme_widget_message_date"
         href="https://t.me/projects_jobs_feed/12345">
        <time datetime="2026-07-24T10:00:00+00:00"></time>
      </a>
    </div>
    """

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/s/projects_jobs_feed"
        return httpx.Response(200, text=html)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        source = TelegramPublicChannelSource(client, "projects_jobs_feed")
        vacancies = [vacancy async for vacancy in source.fetch()]

    assert len(vacancies) == 1
    vacancy = vacancies[0]
    assert vacancy.source == "Telegram/@projects_jobs_feed"
    assert vacancy.external_id == "projects_jobs_feed/12345"
    assert vacancy.title == "Junior Project Manager"
    assert vacancy.url == "https://example.com/jobs/pm"
    assert vacancy.country == "Беларусь"
    assert vacancy.employment_format is EmploymentFormat.REMOTE
    assert vacancy.remote_from_belarus is True
    assert vacancy.experience_min_years == 2
    assert vacancy.required_english_level == "B1"
    assert vacancy.published_at is not None


@pytest.mark.asyncio
async def test_telegram_preview_keeps_post_url_without_external_link() -> None:
    html = """
    <div class="tgme_widget_message js-widget_message" data-post="pmclub/42">
      <div class="tgme_widget_message_text js-message_text">
        Подборка: Project Manager<br>Remote worldwide
      </div>
    </div>
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=html)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        source = TelegramPublicChannelSource(client, "@pmclub")
        vacancies = [vacancy async for vacancy in source.fetch()]

    assert vacancies[0].url == "https://t.me/pmclub/42"
    assert vacancies[0].remote_from_belarus is True
