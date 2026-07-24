import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from job_bot.storage import feedback_external_id_token, feedback_source_token
from job_bot.telegram.bot import (
    _feedback_data,
    _parse_feedback_data,
    _source_map,
    _source_token,
    _sources_keyboard,
    _sources_text,
)


class TelegramFeedbackTests(unittest.TestCase):
    def test_round_trips_feedback_callback(self) -> None:
        data = _feedback_data("saved", "HeadHunter", "123")

        self.assertEqual(
            _parse_feedback_data(data),
            (
                "saved",
                feedback_source_token("HeadHunter"),
                feedback_external_id_token("123"),
            ),
        )

    def test_rejects_unknown_feedback_callback(self) -> None:
        self.assertIsNone(_parse_feedback_data("fb:unknown:HeadHunter:123"))
        self.assertIsNone(_parse_feedback_data("other:saved:HeadHunter:123"))

    def test_long_external_id_is_compacted(self) -> None:
        data = _feedback_data("saved", "HeadHunter", "x" * 1000)

        self.assertLessEqual(len(data.encode()), 64)
        self.assertNotIn("x" * 20, data)

    def test_long_source_name_still_fits_with_lever_uuid(self) -> None:
        data = _feedback_data(
            "rejected",
            "Lever/a-company-with-a-very-long-site-name",
            "12345678-1234-1234-1234-123456789012",
        )

        self.assertLessEqual(len(data.encode()), 64)

    def test_source_tokens_round_trip_through_source_map(self) -> None:
        sources = ("HeadHunter", "Telegram/@igaming_work")

        self.assertEqual(
            _source_map(sources)[_source_token("Telegram/@igaming_work")],
            "Telegram/@igaming_work",
        )

    def test_sources_menu_shows_states_and_bulk_actions(self) -> None:
        states = {"HeadHunter": True, "Telegram/@igaming_work": False}

        text = _sources_text(states)
        keyboard = _sources_keyboard(states)

        self.assertIn("Включено: 1 из 2", text)
        self.assertEqual(keyboard.inline_keyboard[0][0].text, "✅ HeadHunter")
        self.assertEqual(
            keyboard.inline_keyboard[1][0].text,
            "⛔ Telegram/@igaming_work",
        )
        self.assertEqual(keyboard.inline_keyboard[-1][0].text, "🕘 Последние вакансии")


if __name__ == "__main__":
    unittest.main()
