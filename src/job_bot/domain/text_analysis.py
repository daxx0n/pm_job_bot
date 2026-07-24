from __future__ import annotations

import re
from html import unescape

_LEVEL_PATTERN = (
    r"upper[\s-]?intermediate|intermediate|advanced|proficiency|beginner|elementary|"
    r"[abc][12]"
)
_ENGLISH_PATTERN = r"english|английск(?:ий|ого|ому|им|ом|ая|ую|ое|ие)\s*(?:язык[а-я]*)?"
_OPTIONAL_MARKERS = (
    "будет плюсом",
    "будет преимуществом",
    "желательно",
    "необязательно",
    "nice to have",
    "preferred",
    "optional",
)
_CANONICAL_LEVELS = {
    "upper intermediate": "B2",
    "upper-intermediate": "B2",
    "intermediate": "B1",
    "advanced": "C1",
    "proficiency": "C2",
    "beginner": "A1",
    "elementary": "A2",
}
_EXPERIENCE_PATTERNS = (
    r"(?:at\s+least|minimum|min\.?)\s*(?P<years>\d+(?:\.\d+)?)\+?\s*(?:years?|yrs?)",
    r"(?P<years>\d+(?:\.\d+)?)\+?\s*(?:years?|yrs?)"
    r"(?:\s+of)?\s+(?:relevant\s+|professional\s+|work\s+)?experience",
    r"(?:от|минимум|не\s+менее)\s*(?P<years>\d+(?:[.,]\d+)?)\s*лет",
    r"опыт(?:а|\s+работы)?\s*(?:от|не\s+менее)?\s*(?P<years>\d+(?:[.,]\d+)?)\s*лет",
)


def plain_text(value: str) -> str:
    """Remove the small amount of HTML found in HeadHunter snippets."""

    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", value))).strip()


def infer_required_english_level(text: str) -> str | None:
    """Extract an explicit English level, ignoring clearly optional mentions."""

    normalized = plain_text(text).casefold()
    patterns = (
        rf"(?:{_ENGLISH_PATTERN}).{{0,50}}\b(?P<level>{_LEVEL_PATTERN})\b",
        rf"\b(?P<level>{_LEVEL_PATTERN})\b.{{0,50}}(?:{_ENGLISH_PATTERN})",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, normalized):
            context_start = max(0, match.start() - 40)
            context_end = min(len(normalized), match.end() + 40)
            context = normalized[context_start:context_end]
            if any(marker in context for marker in _OPTIONAL_MARKERS):
                continue
            level = match.group("level").replace("  ", " ")
            return _CANONICAL_LEVELS.get(level, level.upper())

    fluent_patterns = (
        (r"\b(?:native|mother[\s-]?tongue)\s+english\b", "C2"),
        (
            r"\b(?:fluent|excellent|advanced)\s+(?:written\s+and\s+spoken\s+)?english\b",
            "C1",
        ),
        (r"\bprofessional\s+working\s+proficiency\s+in\s+english\b", "B2"),
    )
    for pattern, level in fluent_patterns:
        for match in re.finditer(pattern, normalized):
            context_start = max(0, match.start() - 40)
            context_end = min(len(normalized), match.end() + 40)
            context = normalized[context_start:context_end]
            if not any(marker in context for marker in _OPTIONAL_MARKERS):
                return level
    return None


def infer_experience_min_years(text: str) -> float | None:
    """Extract the lowest explicit minimum experience requirement."""

    normalized = plain_text(text).casefold()
    values: list[float] = []
    for pattern in _EXPERIENCE_PATTERNS:
        for match in re.finditer(pattern, normalized):
            values.append(float(match.group("years").replace(",", ".")))
    return min(values) if values else None
