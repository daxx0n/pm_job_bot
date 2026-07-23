import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from job_bot.storage import feedback_source_token
from job_bot.telegram.bot import _feedback_data, _parse_feedback_data


class TelegramFeedbackTests(unittest.TestCase):
    def test_round_trips_feedback_callback(self) -> None:
        data = _feedback_data("saved", "HeadHunter", "123")

        self.assertEqual(
            _parse_feedback_data(data),
            ("saved", feedback_source_token("HeadHunter"), "123"),
        )

    def test_rejects_unknown_feedback_callback(self) -> None:
        self.assertIsNone(_parse_feedback_data("fb:unknown:HeadHunter:123"))
        self.assertIsNone(_parse_feedback_data("other:saved:HeadHunter:123"))

    def test_enforces_telegram_callback_size_limit(self) -> None:
        with self.assertRaisesRegex(ValueError, "64 bytes"):
            _feedback_data("saved", "HeadHunter", "x" * 100)

    def test_long_source_name_still_fits_with_lever_uuid(self) -> None:
        data = _feedback_data(
            "rejected",
            "Lever/a-company-with-a-very-long-site-name",
            "12345678-1234-1234-1234-123456789012",
        )

        self.assertLessEqual(len(data.encode()), 64)


if __name__ == "__main__":
    unittest.main()
