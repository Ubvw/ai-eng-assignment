"""Classify review text using the scraper's original modification patterns."""

import re


_MODIFICATION_PATTERNS = (
    r"I (added|used|substituted|replaced|made with|changed)",
    r"(instead of|rather than|in place of)",
    r"(next time|will make again|definitely make)",
    r"(doubled|tripled|halved|increased|decreased)",
    r"(more|less|extra) ([\w\s]+)",
)


def has_modification(text: str) -> bool:
    """Apply the original case-insensitive scraper classifier to review text."""
    return isinstance(text, str) and bool(text) and any(
        re.search(pattern, text, re.IGNORECASE) for pattern in _MODIFICATION_PATTERNS
    )
