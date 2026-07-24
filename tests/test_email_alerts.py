from email.message import EmailMessage

import pytest

from job_bot.domain.models import EmploymentFormat
from job_bot.sources.email_alerts import EmailAlertSource, parse_alert_message


def _message(
    html: str,
    *,
    subject: str = "Новые вакансии: удалённая работа",
    sender: str = "Rabota.by <jobs@news.rabota.by>",
) -> bytes:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["Date"] = "Fri, 24 Jul 2026 10:00:00 +0200"
    message["Message-ID"] = "<alert-1@example.test>"
    message.set_content("Откройте HTML-версию письма")
    message.add_alternative(html, subtype="html")
    return message.as_bytes()


def test_parses_rabota_by_vacancy_link() -> None:
    vacancies = parse_alert_message(
        _message(
            """
            <html><body>
              <p>Компания: Example</p>
              <p>Локация: Минск, Беларусь</p>
              <a href="https://rabota.by/vacancy/123456?from=email">
                Junior Project Manager
              </a>
              <a href="https://rabota.by/vacancy/123456?from=response">
                Откликнуться
              </a>
            </body></html>
            """
        )
    )

    assert len(vacancies) == 1
    vacancy = vacancies[0]
    assert vacancy.external_id == "123456"
    assert vacancy.title == "Junior Project Manager"
    assert vacancy.url == "https://rabota.by/vacancy/123456"
    assert vacancy.company == "Example"
    assert vacancy.location == "Минск, Беларусь"
    assert vacancy.country == "Беларусь"
    assert vacancy.employment_format is EmploymentFormat.REMOTE
    assert vacancy.remote_from_belarus is True
    assert vacancy.published_at is not None
    assert vacancy.published_at.isoformat() == "2026-07-24T10:00:00+02:00"
    assert vacancy.raw["published_at"] == "2026-07-24T10:00:00+02:00"


def test_ignores_non_vacancy_links_and_unrelated_titles() -> None:
    vacancies = parse_alert_message(
        _message(
            """
            <html><body>
              <a href="https://rabota.by/account/login">Войти</a>
              <a href="https://example.com/vacancy/777">Project Manager</a>
              <a href="https://rabota.by/vacancy/999">Откликнуться</a>
            </body></html>
            """
        )
    )

    assert vacancies == []


def test_extracts_vacancy_from_tracking_redirect() -> None:
    vacancies = parse_alert_message(
        _message(
            """
            <a href="https://click.example.test/open?url=https%3A%2F%2Fhh.ru%2Fvacancy%2F42">
              Project Coordinator
            </a>
            """
        )
    )

    assert len(vacancies) == 1
    assert vacancies[0].external_id == "42"
    assert vacancies[0].url == "https://hh.ru/vacancy/42"


def test_ignores_vacancy_link_from_unrelated_sender() -> None:
    message = EmailMessage()
    message["Subject"] = "Forwarded vacancy"
    message["From"] = "someone@example.com"
    message.set_content("https://rabota.by/vacancy/123456")

    assert parse_alert_message(message.as_bytes()) == []


def test_parses_getmatch_alert_from_official_sender() -> None:
    vacancies = parse_alert_message(
        _message(
            """
            <a href="https://getmatch.ru/vacancies/21364-project-manager?utm_source=email">
              Junior Project Manager
            </a>
            """,
            sender="getmatch <jobs@news.getmatch.ru>",
        )
    )

    assert len(vacancies) == 1
    vacancy = vacancies[0]
    assert vacancy.source == "Email/getmatch.ru"
    assert vacancy.external_id == "getmatch.ru:21364-project-manager"
    assert vacancy.url == "https://getmatch.ru/vacancies/21364-project-manager"


def test_parses_habr_career_alert_from_official_sender() -> None:
    vacancies = parse_alert_message(
        _message(
            """
            <a href="https://career.habr.com/vacancies/1000123?from=email">
              Project Coordinator
            </a>
            """,
            sender="Хабр Карьера <career@habr.com>",
        )
    )

    assert len(vacancies) == 1
    assert vacancies[0].source == "Email/career.habr.com"
    assert vacancies[0].external_id == "career.habr.com:1000123"


def test_imap_search_omits_charset(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeImapClient:
        def __init__(self) -> None:
            self.uid_calls: list[tuple[str, tuple[object, ...]]] = []

        def login(self, username: str, password: str) -> None:
            pass

        def select(self, folder: str, *, readonly: bool) -> tuple[str, list[bytes]]:
            return "OK", []

        def uid(self, command: str, *args: object) -> tuple[str, list[bytes]]:
            self.uid_calls.append((command, args))
            return "OK", [b""]

        def logout(self) -> None:
            pass

    client = FakeImapClient()
    monkeypatch.setattr(
        "job_bot.sources.email_alerts.imaplib.IMAP4_SSL",
        lambda host, port: client,
    )
    source = EmailAlertSource(
        host="imap.example.com",
        port=993,
        username="bot@example.com",
        app_password="app-password",
    )

    assert source._fetch_sync() == []
    assert client.uid_calls[0][0] == "search"
    assert client.uid_calls[0][1][0] is None
