from email.message import EmailMessage

from job_bot.domain.models import EmploymentFormat
from job_bot.sources.email_alerts import parse_alert_message


def _message(html: str, *, subject: str = "Новые вакансии: удалённая работа") -> bytes:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = "Rabota.by <jobs@news.rabota.by>"
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
    assert vacancy.country == "Беларусь"
    assert vacancy.employment_format is EmploymentFormat.REMOTE
    assert vacancy.remote_from_belarus is True


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
