"""Exact bounded reads from canonical text, including support after the first excerpt."""

from dataclasses import dataclass
from hashlib import sha256
import re


@dataclass(frozen=True)
class SourceSpan:
    text: str
    start: int
    total_characters: int
    content_sha256: str


def source_span(
    text: str, *, start: int = 0, focus: str | None = None, limit: int = 4000
) -> SourceSpan:
    if start < 0 or start > len(text) or not 1 <= limit <= 12000:
        raise ValueError("Invalid source span.")
    if focus is not None:
        if not focus.strip() or len(focus) > 200:
            raise ValueError("Invalid focus term.")
        match = re.compile(re.escape(focus), re.IGNORECASE).search(text, start)
        if match is None:
            raise ValueError("Focus term was not found in this source.")
        start = max(start, match.start() - min(500, limit // 4))
    return SourceSpan(
        text[start : start + limit], start, len(text), sha256(text.encode()).hexdigest()
    )
