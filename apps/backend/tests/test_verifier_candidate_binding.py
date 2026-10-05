import pytest

from app.agents import (
    LiveVerifierCriticAgent,
    MockVerifierCriticModelRunner,
    VerificationReport,
)
from app.agents.live_verifier_critic import verify_recommendation_guardrails
from app.schemas.analysis import RejectedItem, RejectionSeverity
from app.schemas.ids import new_id
from app.schemas.search_sources import EvidenceTarget, EvidenceTargetType
from test_live_verifier_critic_agent import _verification_input, _settings


def candidate_input(
    text="Alpha Monitor supports 60Hz refresh rate.",
    *,
    citations="both",
    surface="final",
):
    original = _verification_input()
    alpha = original.products[0].model_copy(
        update={"name": "Alpha Monitor", "brand": "Shared", "model": "Alpha"}
    )
    beta = alpha.model_copy(
        update={
            "product_id": new_id(),
            "name": "Beta Monitor",
            "model": "Beta",
            "source_ids": (new_id(),),
        }
    )
    alpha_listing = original.listings[0].model_copy(update={"title": "Alpha Monitor"})
    beta_listing = alpha_listing.model_copy(
        update={
            "listing_id": new_id(),
            "product_id": beta.product_id,
            "title": "Beta Monitor",
            "source_ids": beta.source_ids,
        }
    )
    beta = beta.model_copy(update={"listing_ids": (beta_listing.listing_id,)})
    alpha_evidence = original.evidence[0].model_copy(
        update={"claim": "Alpha Monitor supports 60Hz refresh rate."}
    )
    beta_evidence = alpha_evidence.model_copy(
        update={
            "evidence_id": new_id(),
            "source_id": beta.source_ids[0],
            "target": EvidenceTarget(
                target_type=EvidenceTargetType.PRODUCT, product_id=beta.product_id
            ),
            "claim": "Beta Monitor supports 120Hz refresh rate.",
        }
    )
    ids = (
        (alpha_evidence.evidence_id, beta_evidence.evidence_id)
        if citations == "both"
        else (beta_evidence.evidence_id,)
    )
    bundle = original.recommendation_bundle
    mode = bundle.mode_results[0].model_copy(
        update={
            "rationale": alpha_evidence.claim,
            "evidence_ids": (alpha_evidence.evidence_id,),
        }
    )
    row = bundle.comparison_matrix.rows[0].model_copy(
        update={
            "summary": alpha_evidence.claim,
            "evidence_ids": (alpha_evidence.evidence_id,),
        }
    )
    updates = {
        "final_rationale": alpha_evidence.claim,
        "evidence_ids": ids
        if surface == "final"
        else (alpha_evidence.evidence_id, beta_evidence.evidence_id),
        "source_ids": (*alpha.source_ids, *beta.source_ids),
    }
    if surface == "final":
        updates["final_rationale"] = text
    elif surface in {"mode", "title"}:
        mode = mode.model_copy(
            update={
                "rationale" if surface == "mode" else "title": text,
                "evidence_ids": ids,
            }
        )
    elif surface == "row":
        row = row.model_copy(update={"summary": text, "evidence_ids": ids})
    elif surface == "rejection":
        updates["rejected_items"] = (
            RejectedItem(
                product_id=alpha.product_id,
                reason=text,
                severity=RejectionSeverity.LOW,
                evidence_ids=ids,
            ),
        )
    updates["mode_results"] = (mode,)
    updates["comparison_matrix"] = bundle.comparison_matrix.model_copy(
        update={"rows": (row,)}
    )
    return original.model_copy(
        update={
            "products": (alpha, beta),
            "listings": (alpha_listing, beta_listing),
            "evidence": (alpha_evidence, beta_evidence),
            "recommendation_bundle": bundle.model_copy(update=updates),
        }
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["final", "mode", "row", "rejection", "title"])
@pytest.mark.parametrize("citations", ["beta", "both"])
async def test_wrong_candidate_fact_blocks_public_and_shared_verifier(
    surface, citations
):
    request = candidate_input(
        "Alpha Monitor supports 120Hz refresh rate.",
        surface=surface,
        citations=citations,
    )
    assert verify_recommendation_guardrails(request).approved is False
    report = await LiveVerifierCriticAgent(
        settings=_settings(),
        model_runner=MockVerifierCriticModelRunner(
            output=VerificationReport(
                approved=True,
                recommendation_bundle=request.recommendation_bundle,
                notes=("Reviewed.",),
            )
        ),
    ).run(request)
    assert report.approved is False
    assert any("factual claim" in issue for issue in report.blocking_issues)


@pytest.mark.parametrize(
    "text, approved",
    [
        ("Alpha Monitor supports 60Hz; Beta Monitor supports 120Hz.", True),
        ("Alpha Monitor has 60Hz while Beta Monitor has 120Hz.", True),
        ("Alpha Monitor has 60Hz versus Beta Monitor's 120Hz.", True),
        ("Alpha Monitor supports 120Hz; Beta Monitor supports 60Hz.", False),
        ("Alpha Monitor and Beta Monitor both have 120Hz.", False),
        ("Alpha Monitor has 120Hz, unlike Beta Monitor.", False),
        ("Beta Monitor has 120Hz. It has 120Hz.", False),
        ("It supports 120Hz.", False),
        ("Alpha Monitor, unlike Beta Monitor, supports 120Hz.", False),
        ("Alpha Monitor, unlike Beta Monitor, supports 60Hz.", True),
        ("Alpha Monitor rather than Beta Monitor supports 120Hz.", False),
        ("Shared Alpha supports 60Hz, and Shared Beta supports 120Hz.", True),
    ],
)
def test_facts_bind_locally_in_comparisons(text, approved):
    assert verify_recommendation_guardrails(candidate_input(text)).approved is approved


def test_listing_only_identity_remains_authoritative():
    request = candidate_input()
    evidence = request.evidence[0].model_copy(
        update={
            "target": EvidenceTarget(
                target_type=EvidenceTargetType.LISTING,
                listing_id=request.listings[0].listing_id,
            )
        }
    )
    assert (
        verify_recommendation_guardrails(
            request.model_copy(update={"evidence": (evidence, request.evidence[1])})
        ).approved
        is True
    )
    evidence = evidence.model_copy(
        update={
            "target": EvidenceTarget(
                target_type=EvidenceTargetType.LISTING,
                listing_id=request.listings[1].listing_id,
            )
        }
    )
    assert (
        verify_recommendation_guardrails(
            request.model_copy(update={"evidence": (evidence, request.evidence[1])})
        ).approved
        is False
    )


def test_source_metadata_needs_source_relationship_and_distinctive_identity():
    request = candidate_input()
    evidence = request.evidence[0].model_copy(
        update={
            "target": EvidenceTarget(
                target_type=EvidenceTargetType.SOURCE_METADATA,
                source_id=request.evidence[0].source_id,
            )
        }
    )
    assert (
        verify_recommendation_guardrails(
            request.model_copy(update={"evidence": (evidence, request.evidence[1])})
        ).approved
        is True
    )
    for claim in (
        "Shared supports 60Hz refresh rate.",
        "Beta Monitor supports 60Hz refresh rate.",
    ):
        bad = evidence.model_copy(update={"claim": claim})
        assert (
            verify_recommendation_guardrails(
                request.model_copy(update={"evidence": (bad, request.evidence[1])})
            ).approved
            is False
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("revision", [False, True], ids=["precheck", "postcheck"])
async def test_live_verification_step_blocks_permissive_verifier(revision):
    from app.core.settings import AgentWorkflowMode
    from app.orchestration.shopping_runs import (
        ShoppingRunContext,
        ShoppingRunOrchestrator,
    )

    wrong = candidate_input("Alpha Monitor supports 120Hz refresh rate.")
    request = candidate_input() if revision else wrong

    class PermissiveVerifier:
        calls = 0

        async def run(self, input_data):
            self.calls += 1
            reviewed = input_data.recommendation_bundle.model_copy(
                update={"final_rationale": "Alpha Monitor supports 120Hz refresh rate."}
            )
            return VerificationReport(
                approved=True,
                recommendation_bundle=reviewed,
                notes=("Reviewed the explanation.",),
            )

    verifier = PermissiveVerifier()
    context = ShoppingRunContext(
        run_id=request.run_id,
        session_id=new_id(),
        trace_id="candidate-binding",
        active_brief=request.brief,
        owner_products=request.products,
        owner_listings=request.listings,
        owner_evidence=request.evidence,
        recommendation_bundle=request.recommendation_bundle,
    )
    orchestrator = ShoppingRunOrchestrator(
        object(),
        agent_workflow_mode=AgentWorkflowMode.LIVE,
        verifier_critic_agent=verifier,
    )
    await orchestrator._run_verification(context)
    assert verifier.calls == (1 if revision else 0)
    assert context.verification_report.approved is False
    assert context.recommendation_bundle.verification_action == "blocked"
    assert context.recommendation_bundle.final_product_id is None
    assert any(
        "factual claim" in issue
        for issue in context.recommendation_bundle.verification_changes
    )


@pytest.mark.asyncio
async def test_supported_individual_candidate_rows_and_modes_approve():
    request = candidate_input()
    bundle = request.recommendation_bundle
    beta, beta_listing, beta_evidence = (
        request.products[1],
        request.listings[1],
        request.evidence[1],
    )
    beta_row = bundle.comparison_matrix.rows[0].model_copy(
        update={
            "product_id": beta.product_id,
            "listing_id": beta_listing.listing_id,
            "summary": beta_evidence.claim,
            "evidence_ids": (beta_evidence.evidence_id,),
        }
    )
    from app.schemas.analysis import RecommendationMode

    beta_mode = bundle.mode_results[0].model_copy(
        update={
            "mode": RecommendationMode.BEST_VALUE,
            "product_id": beta.product_id,
            "listing_id": beta_listing.listing_id,
            "rationale": beta_evidence.claim,
            "evidence_ids": (beta_evidence.evidence_id,),
            "source_ids": beta.source_ids,
        }
    )
    bundle = bundle.model_copy(
        update={
            "mode_results": (*bundle.mode_results, beta_mode),
            "comparison_matrix": bundle.comparison_matrix.model_copy(
                update={"rows": (*bundle.comparison_matrix.rows, beta_row)}
            ),
        }
    )
    request = request.model_copy(update={"recommendation_bundle": bundle})
    assert verify_recommendation_guardrails(request).approved is True
    report = await LiveVerifierCriticAgent(
        settings=_settings(), model_runner=MockVerifierCriticModelRunner()
    ).run(request)
    assert report.approved is True


@pytest.mark.parametrize(
    "target_type, fact, evidence_type",
    [
        ("seller", "shipping", "seller_trust"),
        ("region", "in stock", "region_availability"),
        ("review", "reviews", "review_summary"),
    ],
)
def test_source_relationship_supports_legacy_domains_only(
    target_type, fact, evidence_type
):
    from app.schemas.search_sources import EvidenceType

    request = candidate_input(f"Alpha Monitor has {fact} information.")
    original = request.evidence[0]
    kwargs = (
        {"seller_name": request.listings[0].seller.seller_name}
        if target_type == "seller"
        else {"region_code": "US"}
        if target_type == "region"
        else {"review_id": "alpha-review"}
    )
    evidence = original.model_copy(
        update={
            "target": EvidenceTarget(
                target_type=EvidenceTargetType(target_type), **kwargs
            ),
            "evidence_type": EvidenceType(evidence_type),
            "claim": f"Alpha Monitor supports 60Hz refresh rate and has {fact} information.",
        }
    )
    request = request.model_copy(
        update={
            "evidence": (evidence, request.evidence[1]),
            "recommendation_bundle": request.recommendation_bundle.model_copy(
                update={
                    "mode_results": (
                        request.recommendation_bundle.mode_results[0].model_copy(
                            update={"rationale": "Alpha Monitor information."}
                        ),
                    ),
                    "comparison_matrix": request.recommendation_bundle.comparison_matrix.model_copy(
                        update={
                            "rows": (
                                request.recommendation_bundle.comparison_matrix.rows[
                                    0
                                ].model_copy(
                                    update={"summary": "Alpha Monitor information."}
                                ),
                            )
                        }
                    ),
                }
            ),
        }
    )
    assert verify_recommendation_guardrails(request).approved is True
    hardware = request.recommendation_bundle.model_copy(
        update={"final_rationale": "Alpha Monitor supports 60Hz."}
    )
    assert (
        verify_recommendation_guardrails(
            request.model_copy(update={"recommendation_bundle": hardware})
        ).approved
        is False
    )


def test_wrong_listing_shipping_cannot_support_another_offer():
    request = candidate_input("Alpha Monitor has shipping information.")
    other = request.listings[0].model_copy(update={"listing_id": new_id()})
    evidence = request.evidence[0].model_copy(
        update={
            "target": EvidenceTarget(
                target_type=EvidenceTargetType.LISTING, listing_id=other.listing_id
            ),
            "claim": "Alpha Monitor supports 60Hz and has shipping information.",
        }
    )
    request = request.model_copy(
        update={
            "listings": (*request.listings, other),
            "evidence": (evidence, request.evidence[1]),
        }
    )
    assert verify_recommendation_guardrails(request).approved is False


def test_candidate_target_maps_only_confirmed_user_added_product():
    from app.schemas.products import UserAddedProduct

    request = candidate_input()
    candidate = UserAddedProduct(
        product=request.products[0], listing=request.listings[0]
    )
    evidence = request.evidence[0].model_copy(
        update={
            "target": EvidenceTarget(
                target_type=EvidenceTargetType.CANDIDATE,
                candidate_id=candidate.candidate_id,
            )
        }
    )
    assert (
        verify_recommendation_guardrails(
            request.model_copy(
                update={
                    "user_added_products": (candidate,),
                    "evidence": (evidence, request.evidence[1]),
                }
            )
        ).approved
        is True
    )
    candidate = candidate.model_copy(
        update={"product": request.products[1], "listing": request.listings[1]}
    )
    assert (
        verify_recommendation_guardrails(
            request.model_copy(
                update={
                    "user_added_products": (candidate,),
                    "evidence": (evidence, request.evidence[1]),
                }
            )
        ).approved
        is False
    )


def test_contradictory_explicit_candidate_target_cannot_be_overridden():
    from app.schemas.products import UserAddedProduct

    request = candidate_input()
    candidate = UserAddedProduct(
        product=request.products[1], listing=request.listings[1]
    )
    evidence = request.evidence[0].model_copy(
        update={
            "target": EvidenceTarget(
                target_type=EvidenceTargetType.CANDIDATE,
                candidate_id=candidate.candidate_id,
                product_id=request.products[0].product_id,
            )
        }
    )
    request = request.model_copy(
        update={
            "user_added_products": (candidate,),
            "evidence": (evidence, request.evidence[1]),
        }
    )
    assert verify_recommendation_guardrails(request).approved is False


def test_source_metadata_identity_requires_stored_source_membership():
    request = candidate_input()
    evidence = request.evidence[0].model_copy(
        update={
            "source_id": request.evidence[1].source_id,
            "target": EvidenceTarget(
                target_type=EvidenceTargetType.SOURCE_METADATA,
                source_id=request.evidence[1].source_id,
            ),
        }
    )
    assert (
        verify_recommendation_guardrails(
            request.model_copy(update={"evidence": (evidence, request.evidence[1])})
        ).approved
        is False
    )


@pytest.mark.parametrize(
    "shared_source, text, approved",
    [
        (False, "Alpha Monitor supports 60Hz.", True),
        (False, "Alpha Monitor supports 120Hz.", False),
        (False, "Alpha Monitor supports 60Hz; Beta Monitor supports 120Hz.", False),
        (True, "Alpha Monitor supports 60Hz; Beta Monitor supports 120Hz.", True),
        (True, "Alpha Monitor supports 120Hz; Beta Monitor supports 60Hz.", False),
    ],
)
def test_metadata_comparison_binds_each_fact_with_stored_source_ownership(
    shared_source, text, approved
):
    request = candidate_input(text)
    evidence = request.evidence[0].model_copy(
        update={
            "target": EvidenceTarget(
                target_type=EvidenceTargetType.SOURCE_METADATA,
                source_id=request.evidence[0].source_id,
            ),
            "claim": "Alpha Monitor has 60Hz while Beta Monitor has 120Hz.",
        }
    )
    products = request.products
    if shared_source:
        products = (
            products[0],
            products[1].model_copy(
                update={"source_ids": (*products[1].source_ids, evidence.source_id)}
            ),
        )
    bundle = request.recommendation_bundle.model_copy(
        update={"evidence_ids": (evidence.evidence_id,)}
    )
    request = request.model_copy(
        update={
            "products": products,
            "evidence": (evidence, request.evidence[1]),
            "recommendation_bundle": bundle,
        }
    )
    assert verify_recommendation_guardrails(request).approved is approved


@pytest.mark.parametrize(
    "refresh_rate, gamma_rate, text, approved",
    [
        (
            "120Hz",
            "120Hz",
            "Alpha Monitor, Beta Monitor and Gamma Monitor all support 120Hz.",
            False,
        ),
        (
            "60Hz",
            "60Hz",
            "Alpha Monitor, Beta Monitor and Gamma Monitor all support 60Hz.",
            True,
        ),
        (
            "120Hz",
            "60Hz",
            "Alpha Monitor has 60Hz while Beta Monitor, unlike Gamma Monitor, has 120Hz.",
            True,
        ),
        (
            "120Hz",
            "60Hz",
            "Alpha Monitor has 60Hz while Beta Monitor, unlike Gamma Monitor, has 60Hz.",
            False,
        ),
    ],
)
def test_joint_and_comparative_assertions_check_all_named_candidates(
    refresh_rate, gamma_rate, text, approved
):
    request = candidate_input(text)
    beta = request.products[1]
    gamma = beta.model_copy(
        update={
            "product_id": new_id(),
            "name": "Gamma Monitor",
            "model": "Gamma",
            "source_ids": (new_id(),),
        }
    )
    listing = request.listings[1].model_copy(
        update={
            "listing_id": new_id(),
            "product_id": gamma.product_id,
            "source_ids": gamma.source_ids,
            "title": gamma.name,
        }
    )
    gamma = gamma.model_copy(update={"listing_ids": (listing.listing_id,)})
    beta_evidence = request.evidence[1].model_copy(
        update={"claim": f"Beta Monitor supports {refresh_rate} refresh rate."}
    )
    gamma_evidence = beta_evidence.model_copy(
        update={
            "evidence_id": new_id(),
            "source_id": gamma.source_ids[0],
            "target": EvidenceTarget(
                target_type=EvidenceTargetType.PRODUCT, product_id=gamma.product_id
            ),
            "claim": f"Gamma Monitor supports {gamma_rate} refresh rate.",
        }
    )
    bundle = request.recommendation_bundle.model_copy(
        update={
            "evidence_ids": (
                *request.recommendation_bundle.evidence_ids,
                gamma_evidence.evidence_id,
            )
        }
    )
    request = request.model_copy(
        update={
            "products": (*request.products, gamma),
            "listings": (*request.listings, listing),
            "evidence": (request.evidence[0], beta_evidence, gamma_evidence),
            "recommendation_bundle": bundle,
        }
    )
    assert verify_recommendation_guardrails(request).approved is approved
