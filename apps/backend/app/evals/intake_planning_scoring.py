"""Named field assertions and bounded reasoning proxies; no model judge."""

import re
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError
from pydantic_evals.evaluators import EvaluationReason, Evaluator, EvaluatorContext

from app.evals.intake_planning import (
    IntakePlanningExpectation,
    IntakePlanningInput,
    IntakePlanningOutput,
    IntakePlanningResult,
    PlanCriteria,
)
from app.evals.schemas import EvalMetadata
from app.schemas.guided_intake import GuidedQuestionPurpose
from app.schemas.intake import BudgetMode
from app.schemas.search_sources import SearchIntent, SearchPlan, SourceType


def _assertion(passed: bool, requirement: str, actual: object) -> EvaluationReason:
    return EvaluationReason(value=passed, reason=f"{requirement} Actual: {actual!r}")


def _field_values(value: Any, tokens: list[str]) -> list[Any]:
    if not tokens:
        return [value]
    head, *tail = tokens
    if head == "*" and isinstance(value, list):
        return [item for child in value for item in _field_values(child, tail)]
    if isinstance(value, dict) and head in value:
        return _field_values(value[head], tail)
    if isinstance(value, list) and head.isdecimal() and int(head) < len(value):
        return _field_values(value[int(head)], tail)
    raise KeyError("Field is missing or has the wrong shape.")


def _has_term(text: str, term: str) -> bool:
    return (
        re.search(r"(?<!\w)" + re.escape(term.casefold()) + r"(?!\w)", text.casefold())
        is not None
    )


def _plan_assertions(
    plan: SearchPlan | None, expected: PlanCriteria
) -> dict[str, EvaluationReason]:
    if plan is None:
        return {
            "reasoning.search_plan": _assertion(False, "Return a search plan.", None)
        }
    results = {}
    queries = plan.queries
    results["search_plan.queries.region_code"] = _assertion(
        all(query.region_code == expected.region_code for query in queries),
        f"Every query must preserve region {expected.region_code!r}, including unknown region.",
        [query.region_code for query in queries],
    )
    shopping = [
        query
        for query in queries
        if query.intent
        in {
            SearchIntent.DISCOVERY,
            SearchIntent.PRICE_CHECK,
            SearchIntent.OFFICIAL_SOURCE,
        }
        and set(query.required_source_types)
        & {
            SourceType.RETAILER_LISTING,
            SourceType.PRODUCT_PAGE,
            SourceType.OFFICIAL_BRAND_PAGE,
        }
    ]
    reviews = [
        query
        for query in queries
        if query.intent in {SearchIntent.REVIEW, SearchIntent.VIDEO_REVIEW}
        and set(query.required_source_types)
        & {
            SourceType.PROFESSIONAL_REVIEW,
            SourceType.COMMUNITY_DISCUSSION,
            SourceType.VIDEO,
        }
    ]
    results["reasoning.source_strategy"] = _assertion(
        bool(shopping and reviews)
        and all(query.required_source_types for query in queries),
        "Use separate shopping/listing and review intents with appropriate source types; every query needs a source strategy.",
        [(query.intent.value, query.required_source_types) for query in queries],
    )
    results["reasoning.topic_relevance"] = _assertion(
        bool(queries)
        and all(
            any(
                _has_term(query.query, term)
                for term in (*expected.topic_terms, *expected.considered_products)
            )
            for query in queries
        ),
        f"Each query must concern {expected.topic_terms!r} or a considered product.",
        [query.query for query in queries],
    )
    combined = " ".join(query.query for query in queries)
    for index, alternatives in enumerate(expected.context_terms):
        results[f"reasoning.context[{index}]"] = _assertion(
            any(_has_term(combined, term) for term in alternatives),
            f"Searches must cover shopper context using one of {alternatives!r}.",
            combined,
        )
    for index, name in enumerate(expected.considered_products):
        results[f"reasoning.considered_products[{index}]"] = _assertion(
            any(_has_term(query.query, name) for query in shopping),
            f"Include a shopping/official lookup for {name!r} without requiring a link.",
            [query.query for query in shopping],
        )
    if expected.budget is not None:
        budget = expected.budget
        amount = format(budget.amount.amount.normalize(), "f")
        mode_terms = (
            ("under", "below", "maximum", "max")
            if budget.mode == BudgetMode.HARD_CAP
            else ("around", "near", "about", "preferred")
        )
        results["reasoning.budget"] = _assertion(
            any(
                _has_term(query.query.replace(",", ""), amount)
                and _has_term(query.query, budget.amount.currency)
                and any(_has_term(query.query, term) for term in mode_terms)
                for query in shopping
            ),
            f"A shopping query must preserve {amount} {budget.amount.currency} with {budget.mode.value} wording.",
            [query.query for query in shopping],
        )
    keys = [
        (query.intent, " ".join(query.query.casefold().split())) for query in queries
    ]
    results["reasoning.duplicate_queries"] = _assertion(
        len(keys) == len(set(keys)),
        "Do not repeat the same normalized query and intent.",
        keys,
    )
    text = combined + " " + (plan.rationale or "")
    blocked = (
        "unsupported category",
        "no specialist",
        "not supported",
        "cannot search",
        "can't search",
        *expected.forbidden_terms,
    )
    results["reasoning.generic_support"] = _assertion(
        not any(_has_term(text, term) for term in blocked),
        f"Support ordinary categories and avoid these unsupported assumptions: {blocked!r}.",
        text,
    )
    results["search_plan.rationale"] = _assertion(
        bool(plan.rationale and plan.rationale.strip()),
        "Explain why this source strategy helps the buying decision.",
        plan.rationale,
    )
    return results


def score_intake_planning(
    inputs: IntakePlanningInput,
    output: object,
    expected: IntakePlanningExpectation,
) -> dict[str, EvaluationReason]:
    """Also usable in focused scorer tests without executing Pydantic Evals."""
    try:
        actual = IntakePlanningOutput.model_validate(output)
    except ValidationError as error:
        return {
            "schema." + ".".join(str(part) for part in issue["loc"]): _assertion(
                False, issue["msg"], issue.get("input")
            )
            for issue in error.errors()
        }
    results = {}
    data = actual.model_dump(mode="json")
    for index, rule in enumerate(expected.fields):
        key = f"field.{rule.field}[{index}]"
        try:
            values = _field_values(data, rule.field.split("."))
            if rule.operator == "equals":
                passed = values == [rule.value]
            elif rule.operator == "contains_text":
                passed = any(
                    isinstance(value, str)
                    and str(rule.value).casefold() in value.casefold()
                    for value in values
                )
            else:
                flattened = [
                    item
                    for value in values
                    for item in (value if isinstance(value, list) else [value])
                ]
                assert isinstance(rule.value, list)
                passed = all(item in flattened for item in rule.value)
            results[key] = _assertion(
                passed,
                f"{rule.field}: {rule.requirement}; expected {rule.operator} {rule.value!r}.",
                values,
            )
        except KeyError as error:
            results[key] = _assertion(
                False, f"{rule.field}: {rule.requirement}", str(error)
            )
    if inputs.stage == "guide":
        results["guide.question_sequence.length"] = _assertion(
            len(actual.guide_states) == len(inputs.guide_turns),
            "Return exactly one state for every shopper-context turn.",
            len(actual.guide_states),
        )
        for index, (turn, state) in enumerate(
            zip(inputs.guide_turns, actual.guide_states)
        ):
            question = state.current_question
            if question is None:
                continue
            done = {answer.question_id for answer in turn.prior_answers} | set(
                turn.skipped_question_ids
            )
            results[f"guide_states.{index}.current_question.no_repeat"] = _assertion(
                question.question_id not in done
                or question.question_id == turn.reanswer_question_id,
                "Do not repeat answered/skipped questions unless the shopper requests reanswering.",
                question.question_id,
            )
            results[f"guide_states.{index}.current_question.focus"] = _assertion(
                question.text.count("?") <= 1
                or question.purpose == GuidedQuestionPurpose.COMBINED_OPTIONAL,
                "Ask one focused question; group only explicitly optional prompts.",
                question.text,
            )
            results[f"guide_states.{index}.current_question.no_recommendation"] = (
                _assertion(
                    not any(
                        _has_term(question.text, term)
                        for term in (
                            "I recommend",
                            "best pick",
                            "buy this",
                            "chat history",
                        )
                    ),
                    "Guide intake without premature recommendations or visible chat history.",
                    question.text,
                )
            )
    if expected.plan is not None:
        results.update(_plan_assertions(actual.search_plan, expected.plan))
    return results


@dataclass
class IntakePlanningEvaluator(
    Evaluator[IntakePlanningInput, IntakePlanningResult, EvalMetadata]
):
    def evaluate(
        self,
        ctx: EvaluatorContext[IntakePlanningInput, IntakePlanningResult, EvalMetadata],
    ) -> dict[str, EvaluationReason]:
        if not isinstance(ctx.expected_output, IntakePlanningExpectation):
            raise ValueError("Independent intake/planning expectations are required.")
        return score_intake_planning(ctx.inputs, ctx.output, ctx.expected_output)
