from dataclasses import dataclass
import re

from app.schemas.guided_intake import (
    GuidedAnswerSubmission,
    ShoppingGuardrailDecision,
    ShoppingGuardrailReason,
    ShoppingGuardrailResult,
)


_OFF_TOPIC_MESSAGE = (
    "I can help with shopping decisions. Try asking what to buy or compare."
)
_UNSAFE_PRODUCT_MESSAGE = (
    "I cannot help choose unsafe products. I can help with ordinary consumer purchases."
)
_ILLEGAL_PRODUCT_MESSAGE = (
    "I cannot help with illegal purchases. I can help with ordinary consumer products."
)
_INAPPROPRIATE_PRODUCT_MESSAGE = (
    "I cannot help with that request. I can help with ordinary consumer purchases."
)


@dataclass(frozen=True)
class _GuardrailRule:
    reason: ShoppingGuardrailReason
    message: str
    patterns: tuple[re.Pattern[str], ...]

    def matches(self, text: str) -> bool:
        return any(pattern.search(text) is not None for pattern in self.patterns)


def _phrase(value: str) -> re.Pattern[str]:
    escaped = re.escape(value.lower())
    return re.compile(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])")


_RULES = (
    _GuardrailRule(
        reason=ShoppingGuardrailReason.OFF_TOPIC,
        message=_OFF_TOPIC_MESSAGE,
        patterns=(
            _phrase("homework"),
            _phrase("write an essay"),
            _phrase("write my essay"),
            _phrase("write a poem"),
            _phrase("make a poem"),
            _phrase("tell me a joke"),
            _phrase("capital of france"),
        ),
    ),
    _GuardrailRule(
        reason=ShoppingGuardrailReason.UNSAFE_PRODUCT,
        message=_UNSAFE_PRODUCT_MESSAGE,
        patterns=(
            _phrase("gun"),
            _phrase("firearm"),
            _phrase("handgun"),
            _phrase("rifle"),
            _phrase("shotgun"),
            _phrase("ammunition"),
            _phrase("ammo"),
            _phrase("explosive"),
            _phrase("bomb"),
            _phrase("weapon"),
            _phrase("taser"),
            _phrase("silencer"),
            _phrase("switchblade"),
        ),
    ),
    _GuardrailRule(
        reason=ShoppingGuardrailReason.ILLEGAL_PRODUCT,
        message=_ILLEGAL_PRODUCT_MESSAGE,
        patterns=(
            _phrase("fake passport"),
            _phrase("fake id"),
            _phrase("counterfeit money"),
            _phrase("stolen"),
            _phrase("illegal"),
            _phrase("cocaine"),
            _phrase("heroin"),
            _phrase("meth"),
        ),
    ),
    _GuardrailRule(
        reason=ShoppingGuardrailReason.INAPPROPRIATE_PRODUCT,
        message=_INAPPROPRIATE_PRODUCT_MESSAGE,
        patterns=(
            _phrase("porn"),
            _phrase("explicit sexual"),
            _phrase("sex toy"),
            _phrase("adult video"),
        ),
    ),
)


def evaluate_shopping_guardrail(
    user_input: str,
    *,
    prior_answers: tuple[GuidedAnswerSubmission, ...] = (),
) -> ShoppingGuardrailResult:
    """Return the deterministic shopping-scope/safe-product decision."""

    searchable_text = _normalized_search_text(user_input, prior_answers)
    for rule in _RULES:
        if rule.matches(searchable_text):
            return ShoppingGuardrailResult(
                decision=ShoppingGuardrailDecision.BLOCKED,
                reason=rule.reason,
                message=rule.message,
            )

    return ShoppingGuardrailResult(decision=ShoppingGuardrailDecision.ALLOWED)


def blocked_guardrail_or_none(
    user_input: str,
    *,
    prior_answers: tuple[GuidedAnswerSubmission, ...] = (),
) -> ShoppingGuardrailResult | None:
    result = evaluate_shopping_guardrail(
        user_input,
        prior_answers=prior_answers,
    )
    if result.decision == ShoppingGuardrailDecision.BLOCKED:
        return result
    return None


def safe_guardrail_failure_result() -> ShoppingGuardrailResult:
    return ShoppingGuardrailResult(
        decision=ShoppingGuardrailDecision.BLOCKED,
        reason=ShoppingGuardrailReason.OFF_TOPIC,
        message=(
            "I could not safely check that request. "
            "Try rephrasing it as an ordinary shopping question."
        ),
    )

def _normalized_search_text(
    user_input: str,
    prior_answers: tuple[GuidedAnswerSubmission, ...],
) -> str:
    parts = [user_input]
    for answer in prior_answers:
        parts.append(answer.model_dump_json())
    return " ".join(parts).lower()
