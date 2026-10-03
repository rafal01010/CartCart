"""Explicit shopper intent that must survive intake and query generation."""

import re
from datetime import datetime, timezone

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


RESEARCH_QUERY_GUIDANCE = (
    "Form search queries for a specific research purpose rather than copying the shopper's sentence. "
    "Use the current brief, candidate identities, buying region, research_context.current_date "
    "and unresolved evidence gaps. Follow-up queries should target the missing fact, variant, "
    "seller or conflicting claim. Keep original shopper wording unchanged in the brief. "
    "An unlimited budget does not mean budget or cheap products; a missing budget does not "
    "authorize inventing a cap. Do not invent preferences, product generations, availability "
    "or confirmed launch dates. Record derived queries separately through the research tools. "
)


def research_context(brief: ShoppingBrief) -> dict[str, str]:
    return {
        "current_date": datetime.now(timezone.utc).date().isoformat(),
        "budget_status": (
            "specified"
            if brief.budget is not None
            else "unlimited"
            if brief_has_unconstrained_budget(brief)
            else "missing"
        ),
    }
