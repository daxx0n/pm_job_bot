import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from job_bot.domain.text_analysis import infer_required_english_level, plain_text


class TextAnalysisTests(unittest.TestCase):
    def test_strips_html_from_snippet(self) -> None:
        self.assertEqual(
            plain_text("Опыт <highlighttext>Project Manager</highlighttext> &amp; Jira"),
            "Опыт Project Manager & Jira",
        )

    def test_extracts_required_english_level(self) -> None:
        self.assertEqual(
            infer_required_english_level("Требуется английский язык не ниже B2."),
            "B2",
        )
        self.assertEqual(
            infer_required_english_level("Upper-Intermediate English is required."),
            "B2",
        )

    def test_ignores_clearly_optional_english_level(self) -> None:
        self.assertIsNone(
            infer_required_english_level("English B2 будет плюсом, но не обязателен.")
        )


if __name__ == "__main__":
    unittest.main()
