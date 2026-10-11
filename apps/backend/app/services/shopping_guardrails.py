from app.schemas.guided_intake import (
    GuidedAnswerSubmission,
    ShoppingGuardrailDecision,
    ShoppingGuardrailResult,
)


def evaluate_shopping_guardrail(
    user_input: str,
    *,
    prior_answers: tuple[GuidedAnswerSubmission, ...] = (),
) -> ShoppingGuardrailResult:
    """Offline fixtures do not classify requests. Live runs use the SDK input guardrail."""
    del user_input, prior_answers
    return ShoppingGuardrailResult(decision=ShoppingGuardrailDecision.ALLOWED)
