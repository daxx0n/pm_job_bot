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
    return None
