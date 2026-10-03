"""Explicit shopper intent that must survive intake and query generation."""

import re

from app.schemas.intake import ShoppingBrief


_UNCONSTRAINED_BUDGET = re.compile(
    r"\b(?:(?:budget|price|cost|money)\s+(?:is\s+(?:not|no)|isn't)\s+"
    r"(?:(?:a|an)\s+)?(?:problem|concern|constraint|issue)|"
    r"money\s+(?:is\s+)?no\s+object|unlimited\s+budget|no\s+budget\s+limit|"
    r"budget\s+(?:is\s+)?unlimited|"
    r"(?:budget|price|cost)\s+(?:does\s+not|doesn't)\s+matter)\b",
    re.IGNORECASE,
)


def has_unconstrained_budget(text: str) -> bool:
    return _UNCONSTRAINED_BUDGET.search(text) is not None


def brief_has_unconstrained_budget(brief: ShoppingBrief) -> bool:
    return brief.budget is None and any(
        has_unconstrained_budget(text)
        for text in (
            brief.original_query,
            *(item.text for item in (*brief.constraints, *brief.preferences)),
        )
    )


def search_intent_text(text: str) -> str:
    return _UNCONSTRAINED_BUDGET.sub("", text).strip(" ,.;")
