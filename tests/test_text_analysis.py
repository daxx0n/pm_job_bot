import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from job_bot.domain.text_analysis import (
    infer_experience_min_years,
    infer_required_english_level,
    plain_text,
)


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

    def test_detects_fluent_english_as_c1(self) -> None:
        self.assertEqual(infer_required_english_level("Fluent English is required."), "C1")

    def test_extracts_minimum_experience(self) -> None:
        text = "At least 2 years experience; 4 years of delivery experience is a plus."

        self.assertEqual(infer_experience_min_years(text), 2)


if __name__ == "__main__":
    unittest.main()
