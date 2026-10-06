import pytest
from pydantic import AnyHttpUrl
from typing import Literal

from app.agents import (
    ComparisonDecisionAgentInput,
    LiveComparisonDecisionAgent,
    LiveVerifierCriticAgent,
    MockComparisonDecisionModelRunner,
    MockVerifierCriticModelRunner,
    VerificationAgentInput,
)
from app.agents.live_verifier_critic import verify_recommendation_guardrails
from app.schemas.analysis import (
    ListingTrustLevel,
    RecommendationMode,
    RejectedItem,
    RejectionReason,
    RejectionSeverity,
)
from app.schemas.ids import new_id
from app.schemas.intake import BudgetMode
from app.schemas.money import Money
from test_live_verifier_critic_agent import _settings, _verification_input


def _alternate_offer_input(
    *,
    unsafe: Literal["safe", "trust", "budget"] = "safe",
    role: Literal["mode", "runner_up", "comparison"] = "mode",
    no_buy: bool = False,
) -> VerificationAgentInput:
    request = _verification_input(budget_mode=BudgetMode.HARD_CAP)
    product = request.products[0].model_copy(
        update={"product_id": new_id(), "name": "Alternate Monitor"}
    )
    listing = request.listings[0].model_copy(
        update={
            "listing_id": new_id(),
            "product_id": product.product_id,
            "title": "Alternate Monitor Store Offer",
            "url": AnyHttpUrl("https://example.com/alternate"),
            "price": Money(
                amount="399" if unsafe == "budget" else "199", currency="USD"
            ),
        }
    )
    product = product.model_copy(update={"listing_ids": (listing.listing_id,)})
    evidence = request.evidence[0].model_copy(
        update={
            "evidence_id": new_id(),
            "target": request.evidence[0].target.model_copy(
                update={"product_id": product.product_id}
            ),
        }
    )
    assessment = request.trust_assessments[0].model_copy(
        update={
            "listing_id": listing.listing_id,
            "level": ListingTrustLevel.SUSPICIOUS
            if unsafe == "trust"
            else ListingTrustLevel.REASONABLE,
            "evidence_ids": (evidence.evidence_id,),
        }
    )
    mode = request.recommendation_bundle.mode_results[0].model_copy(
        update={
            "mode": RecommendationMode.BEST_VALUE,
            "product_id": product.product_id,
            "listing_id": listing.listing_id,
            "evidence_ids": (evidence.evidence_id,),
        }
    )
    bundle = request.recommendation_bundle
    modes = (*bundle.mode_results, mode) if role == "mode" else bundle.mode_results
    row = bundle.comparison_matrix.rows[0].model_copy(
        update={
            "product_id": product.product_id,
            "listing_id": listing.listing_id,
            "evidence_ids": (evidence.evidence_id,),
        }
    )
    bundle = bundle.model_copy(
        update={
            "mode_results": modes,
            "runner_up_product_ids": (product.product_id,)
            if role == "runner_up"
            else (),
            "comparison_matrix": bundle.comparison_matrix.model_copy(
                update={"rows": (*bundle.comparison_matrix.rows, row)}
            ),
            "evidence_ids": (*bundle.evidence_ids, evidence.evidence_id),
            **(
                {
                    "no_strong_buy": True,
                    "no_strong_buy_reason": "Fixture evidence describes the monitor candidate.",
                    "final_product_id": None,
                    "final_listing_id": None,
                    "final_rationale": None,
                }
                if no_buy
                else {}
            ),
        }
    )
    return request.model_copy(
        update={
            "recommendation_bundle": bundle,
            "products": (*request.products, product),
            "listings": (*request.listings, listing),
            "trust_assessments": (*request.trust_assessments, assessment),
            "evidence": (*request.evidence, evidence),
        }
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "unsafe,issue", [("trust", "suspicious"), ("budget", "hard budget")]
)
@pytest.mark.parametrize("role", ["mode", "runner_up"])
@pytest.mark.parametrize("no_buy", [False, True])
async def test_public_verifier_and_shared_guard_block_unsafe_alternate(
    unsafe: Literal["trust", "budget"],
    issue: str,
    role: Literal["mode", "runner_up"],
    no_buy: bool,
) -> None:
    request = _alternate_offer_input(unsafe=unsafe, role=role, no_buy=no_buy)
    shared = verify_recommendation_guardrails(request)
    public = await LiveVerifierCriticAgent(
        settings=_settings(), model_runner=MockVerifierCriticModelRunner()
    ).run(request)
    for result in (shared, public):
        assert result.approved is False
        assert any(issue in text for text in result.blocking_issues)


@pytest.mark.parametrize("unsafe", ["trust", "budget"])
def test_comparison_only_unsafe_offer_does_not_block_safe_pick(
    unsafe: Literal["trust", "budget"],
) -> None:
    request = _alternate_offer_input(unsafe=unsafe, role="comparison")
    assert verify_recommendation_guardrails(request).approved is True


@pytest.mark.parametrize("role", ["mode", "runner_up"])
def test_safe_alternate_is_approved(role: Literal["mode", "runner_up"]) -> None:
    assert (
        verify_recommendation_guardrails(_alternate_offer_input(role=role)).approved
        is True
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["mode", "runner_up"])
async def test_public_comparison_excludes_suspicious_alternate(
    role: Literal["mode", "runner_up"],
) -> None:
    request = _alternate_offer_input(unsafe="trust", role=role)
    comparison = ComparisonDecisionAgentInput(
        **request.model_dump(exclude={"recommendation_bundle"})
    )
    agent = LiveComparisonDecisionAgent(
        settings=_settings(),
        model_runner=MockComparisonDecisionModelRunner(
            output=request.recommendation_bundle
        ),
    )
    result = await agent.run(comparison)
    assert agent.workbench_activity[0]["status"] == "schema_invalid_fallback"
    assert all(
        mode.listing_id != request.listings[1].listing_id
        for mode in result.mode_results
    )
    assert request.products[1].product_id not in result.runner_up_product_ids


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text,approved",
    [
        ("The seller has a listing here.", False),
        ("This listing is suspicious.", False),
        ("Do not avoid this seller; it is safe to buy.", False),
        ("This listing is not blocked.", False),
        ("It is not unsafe to buy this listing.", False),
        ("It is not true that this listing is blocked.", False),
        ("Do not buy the other listing; this offer is the best value.", False),
        ("Some other offers are not a safe buy.", False),
        ("Do not recommend avoiding this listing.", False),
        ("Do not buy Fixture Monitor.", False),
        ("There is no need to avoid Alternate Monitor Store Offer.", False),
        ("There is no reason to avoid Alternate Monitor Store Offer.", False),
        ("Do not buy this suspicious listing.", True),
        ("Do not buy this listing.", True),
        ("Do not buy.", True),
        ("Avoid this seller.", True),
        ("Do not buy this listing, use another seller instead.", True),
        ("Do not buy Alternate Monitor Store Offer, use another seller instead.", True),
        ("This suspicious listing is not a safe buy.", True),
    ],
)
async def test_mode_warning_must_block_purchase(text: str, approved: bool) -> None:
    request = _alternate_offer_input(unsafe="trust")
    bundle = request.recommendation_bundle
    bundle = bundle.model_copy(
        update={
            "mode_results": (
                bundle.mode_results[0],
                bundle.mode_results[1].model_copy(update={"rationale": text}),
            ),
        }
    )
    evidence = tuple(
        item.model_copy(update={"claim": f"{item.claim} {text}"})
        for item in request.evidence
    )
    request = request.model_copy(
        update={"recommendation_bundle": bundle, "evidence": evidence}
    )
    shared = verify_recommendation_guardrails(request)
    public = await LiveVerifierCriticAgent(
        settings=_settings(), model_runner=MockVerifierCriticModelRunner()
    ).run(request)
    for result in (shared, public):
        assert result.approved is approved
        assert any("suspicious" in issue for issue in result.blocking_issues) is (
            not approved
        )


@pytest.mark.parametrize(
    "target", ["unscoped", "other_offer", "rejected", "target_offer"]
)
def test_global_warning_and_rejection_cannot_caveat_another_offer(target: str) -> None:
    request = _alternate_offer_input(unsafe="trust")
    bundle = request.recommendation_bundle
    warning = {
        "unscoped": "Do not buy a suspicious listing.",
        "other_offer": f"Do not buy {request.listings[0].title}.",
        "rejected": None,
        "target_offer": f"Do not buy {request.listings[1].title}.",
    }[target]
    rejection = RejectedItem(
        listing_id=request.listings[1].listing_id,
        product_id=request.products[1].product_id,
        reason="Do not buy this suspicious listing.",
        reason_code=RejectionReason.SUSPICIOUS_LISTING,
        severity=RejectionSeverity.BLOCKING,
        evidence_ids=(request.evidence[1].evidence_id,),
    )
    bundle = bundle.model_copy(
        update={
            "warnings": (warning,) if warning else (),
            "rejected_items": (rejection,) if target == "rejected" else (),
        }
    )
    evidence = tuple(
        item.model_copy(update={"claim": warning or rejection.reason})
        for item in request.evidence
    )
    result = verify_recommendation_guardrails(
        request.model_copy(
            update={"recommendation_bundle": bundle, "evidence": evidence}
        )
    )
    assert any("suspicious" in issue for issue in result.blocking_issues) is (
        target != "target_offer"
    )


@pytest.mark.parametrize(
    "target", ["shared_title", "other_seller", "target_seller", "direct_avoid"]
)
def test_same_product_two_sellers_require_warning_for_exact_offer(target: str) -> None:
    request = _alternate_offer_input(unsafe="trust")
    listings = (
        request.listings[0].model_copy(
            update={
                "title": "Fixture Monitor",
                "seller": request.listings[0].seller.model_copy(
                    update={"seller_name": "Safe Store"}
                ),
            }
        ),
        request.listings[1].model_copy(
            update={
                "product_id": request.products[0].product_id,
                "title": "Fixture Monitor",
                "seller": request.listings[1].seller.model_copy(
                    update={"seller_name": "Risk Store"}
                ),
            }
        ),
    )
    warning = {
        "shared_title": "Do not buy Fixture Monitor.",
        "other_seller": "Do not buy Fixture Monitor from Safe Store.",
        "target_seller": "Do not buy Fixture Monitor from Risk Store.",
        "direct_avoid": "Avoid Risk Store.",
    }[target]
    bundle = request.recommendation_bundle
    bundle = bundle.model_copy(
        update={
            "warnings": (warning,),
            "mode_results": (
                bundle.mode_results[0],
                bundle.mode_results[1].model_copy(
                    update={"product_id": request.products[0].product_id}
                ),
            ),
        }
    )
    result = verify_recommendation_guardrails(
        request.model_copy(
            update={"recommendation_bundle": bundle, "listings": listings}
        )
    )
    assert any("suspicious" in issue for issue in result.blocking_issues) is (
        target not in {"target_seller", "direct_avoid"}
    )


@pytest.mark.parametrize("price", [None, Money(amount="399", currency="EUR")])
def test_unknown_and_foreign_currency_prices_remain_non_comparable(
    price: Money | None,
) -> None:
    request = _alternate_offer_input(unsafe="budget")
    request = request.model_copy(
        update={
            "listings": (
                request.listings[0],
                request.listings[1].model_copy(update={"price": price}),
            )
        }
    )
    assert verify_recommendation_guardrails(request).approved is True


def test_product_only_alternate_does_not_infer_a_listing() -> None:
    request = _alternate_offer_input(unsafe="trust")
    bundle = request.recommendation_bundle
    bundle = bundle.model_copy(
        update={
            "mode_results": (
                bundle.mode_results[0],
                bundle.mode_results[1].model_copy(update={"listing_id": None}),
            )
        }
    )
    assert (
        verify_recommendation_guardrails(
            request.model_copy(update={"recommendation_bundle": bundle})
        ).approved
        is True
    )


@pytest.mark.parametrize("unsafe", ["trust", "budget"])
def test_no_buy_comparison_only_rows_remain_permitted(
    unsafe: Literal["trust", "budget"],
) -> None:
    request = _alternate_offer_input(unsafe=unsafe, role="comparison", no_buy=True)
    bundle = request.recommendation_bundle.model_copy(update={"mode_results": ()})
    assert (
        verify_recommendation_guardrails(
            request.model_copy(update={"recommendation_bundle": bundle})
        ).approved
        is True
    )


@pytest.mark.asyncio
async def test_public_comparison_excludes_over_cap_runner_row() -> None:
    request = _alternate_offer_input(unsafe="budget", role="runner_up")
    comparison = ComparisonDecisionAgentInput(
        **request.model_dump(exclude={"recommendation_bundle"})
    )
    agent = LiveComparisonDecisionAgent(
        settings=_settings(),
        model_runner=MockComparisonDecisionModelRunner(
            output=request.recommendation_bundle
        ),
    )
    result = await agent.run(comparison)
    assert agent.workbench_activity[0]["status"] == "schema_invalid_fallback"
    assert request.products[1].product_id not in result.runner_up_product_ids


@pytest.mark.parametrize("unsafe", ["trust", "budget"])
def test_safe_runner_mode_keeps_unsafe_same_product_row_for_comparison(
    unsafe: Literal["trust", "budget"],
) -> None:
    request = _alternate_offer_input(unsafe=unsafe, role="runner_up")
    bundle = request.recommendation_bundle
    safe_listing = request.listings[1].model_copy(
        update={"listing_id": new_id(), "price": Money(amount="199", currency="USD")}
    )
    mode = bundle.mode_results[0].model_copy(
        update={
            "mode": RecommendationMode.RUNNER_UP,
            "product_id": request.products[1].product_id,
            "listing_id": safe_listing.listing_id,
            "evidence_ids": (request.evidence[1].evidence_id,),
        }
    )
    request = request.model_copy(
        update={
            "listings": (*request.listings, safe_listing),
            "recommendation_bundle": bundle.model_copy(
                update={"mode_results": (*bundle.mode_results, mode)}
            ),
        }
    )
    assert verify_recommendation_guardrails(request).approved is True


@pytest.mark.parametrize("listing_reference", ["different_listing", "product_only"])
def test_ambiguous_runner_rows_do_not_infer_an_unsafe_offer(
    listing_reference: str,
) -> None:
    request = _alternate_offer_input(unsafe="trust", role="runner_up")
    bundle = request.recommendation_bundle
    second_listing = request.listings[1].model_copy(update={"listing_id": new_id()})
    row = bundle.comparison_matrix.rows[1].model_copy(
        update={
            "listing_id": second_listing.listing_id
            if listing_reference == "different_listing"
            else None
        }
    )
    request = request.model_copy(
        update={
            "listings": (*request.listings, second_listing),
            "recommendation_bundle": bundle.model_copy(
                update={
                    "comparison_matrix": bundle.comparison_matrix.model_copy(
                        update={"rows": (*bundle.comparison_matrix.rows, row)}
                    )
                }
            ),
        }
    )
    assert verify_recommendation_guardrails(request).approved is True


@pytest.mark.asyncio
@pytest.mark.parametrize("warned", [False, True])
async def test_public_comparison_requires_real_offer_scoped_caution(
    warned: bool,
) -> None:
    request = _alternate_offer_input(unsafe="trust")
    bundle = request.recommendation_bundle
    bundle = bundle.model_copy(
        update={
            "mode_results": (
                bundle.mode_results[0],
                bundle.mode_results[1].model_copy(
                    update={
                        "rationale": "Do not buy this listing."
                        if warned
                        else "This seller has a listing here."
                    }
                ),
            )
        }
    )
    comparison = ComparisonDecisionAgentInput(
        **request.model_dump(exclude={"recommendation_bundle"})
    )
    agent = LiveComparisonDecisionAgent(
        settings=_settings(),
        model_runner=MockComparisonDecisionModelRunner(output=bundle),
    )
    result = await agent.run(comparison)
    assert agent.workbench_activity[0]["status"] == (
        "model_comparison_decision_completed" if warned else "schema_invalid_fallback"
    )
    assert (
        any(
            mode.listing_id == request.listings[1].listing_id
            for mode in result.mode_results
        )
        is warned
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("warned", [False, True])
async def test_final_suspicious_listing_retains_blocking_warning_requirement(
    warned: bool,
) -> None:
    request = _verification_input()
    text = "Do not buy this listing." if warned else "This seller has a listing here."
    bundle = request.recommendation_bundle.model_copy(update={"final_rationale": text})
    request = request.model_copy(
        update={
            "recommendation_bundle": bundle,
            "trust_assessments": (
                request.trust_assessments[0].model_copy(
                    update={"level": ListingTrustLevel.SUSPICIOUS}
                ),
            ),
            "evidence": (
                request.evidence[0].model_copy(
                    update={"claim": f"{request.evidence[0].claim} {text}"}
                ),
            ),
        }
    )
    shared = verify_recommendation_guardrails(request)
    public = await LiveVerifierCriticAgent(
        settings=_settings(), model_runner=MockVerifierCriticModelRunner()
    ).run(request)
    for result in (shared, public):
        assert result.approved is warned
