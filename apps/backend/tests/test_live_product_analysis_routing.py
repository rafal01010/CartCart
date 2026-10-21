import json
from typing import Any

import pytest

from app.agents import (
    DEFAULT_AGENT_CATALOG,
    CategoryRouterAgentInput,
    LiveCategoryRouterAgent,
    LiveEarphonesHeadphonesSpecialistAgent,
    LiveGenericProductAnalystAgent,
    LiveLaptopSpecialistAgent,
    LiveMonitorSpecialistAgent,
    LiveSmartphoneSpecialistAgent,
    LiveSmartwatchSpecialistAgent,
    LiveTVSpecialistAgent,
    LiveTechnologyDomainAnalystAgent,
    MockCategoryRouterModelRunner,
    MockEarphonesHeadphonesSpecialistModelRunner,
    MockGenericProductAnalystModelRunner,
    MockLaptopSpecialistModelRunner,
    MockMonitorSpecialistModelRunner,
    MockSmartphoneSpecialistModelRunner,
    MockSmartwatchSpecialistModelRunner,
    MockTVSpecialistModelRunner,
    MockTechnologyDomainAnalystModelRunner,
    ProductAnalysisAgentInput,
)
from app.evals.routing import product_specialist_scope_eval_cases
from app.core.settings import Settings
from app.evals import (
    ProductAnalysisRoutingEvalKind,
    evaluate_product_analysis_routing_case,
    product_analysis_fallback_eval_cases,
    product_analysis_routing_eval_cases,
)
from app.schemas.confidence import Confidence, ConfidenceLevel
from app.schemas.ids import new_id
from app.schemas.intake import (
    BudgetConstraint,
    BudgetMode,
    FieldSource,
    PreferenceConstraint,
    PreferenceMode,
    RegionPreference,
    ShoppingBrief,
)
from app.schemas.money import Money
from app.schemas.products import CanonicalProduct, ProductListing, SellerProfile
from app.schemas.regions import Region
from app.schemas.search_sources import (
    EvidenceTarget,
    EvidenceTargetType,
    EvidenceType,
    SourceEvidence,
    SourceQuality,
    SourceQualityLevel,
)


SPECIALIST_AGENT_FACTORIES: dict[str, tuple[type[Any], type[Any]]] = {
    "MonitorSpecialistAgent": (
        LiveMonitorSpecialistAgent,
        MockMonitorSpecialistModelRunner,
    ),
    "SmartphoneSpecialistAgent": (
        LiveSmartphoneSpecialistAgent,
        MockSmartphoneSpecialistModelRunner,
    ),
    "LaptopSpecialistAgent": (
        LiveLaptopSpecialistAgent,
        MockLaptopSpecialistModelRunner,
    ),
    "EarphonesHeadphonesSpecialistAgent": (
        LiveEarphonesHeadphonesSpecialistAgent,
        MockEarphonesHeadphonesSpecialistModelRunner,
    ),
    "TVSpecialistAgent": (
        LiveTVSpecialistAgent,
        MockTVSpecialistModelRunner,
    ),
    "SmartwatchSpecialistAgent": (
        LiveSmartwatchSpecialistAgent,
        MockSmartwatchSpecialistModelRunner,
    ),
}


def test_current_routes_are_separate_from_target_owner_handoffs() -> None:
    catalog = DEFAULT_AGENT_CATALOG
    general = catalog.require(catalog.target_general_owner_agent_name)
    technology = catalog.require(catalog.technology_domain_agent_name)

    assert general.target_handoff_agent_names == (technology.agent_name,)
    assert set(technology.target_handoff_agent_names) == set(SPECIALIST_AGENT_FACTORIES)
    for eval_case in product_analysis_routing_eval_cases():
        route = catalog.route_product_analysis(eval_case.category)
        assert "GeneralShoppingAgent" not in route.agent_path
        if len(route.agent_path) == 2:
            assert route.agent_path[0] == technology.agent_name
            assert route.agent_path[1] in technology.target_handoff_agent_names


def _settings(**overrides: object) -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        environment="test",
        **overrides,
    )


def _case_id(eval_case: Any) -> str:
    return eval_case.name


@pytest.mark.parametrize(
    "eval_case",
    product_analysis_routing_eval_cases(),
    ids=_case_id,
)
def test_product_analysis_routing_eval_cases_pass(eval_case: Any) -> None:
    result = evaluate_product_analysis_routing_case(eval_case)

    assert result.passed, result.failure_reason


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "eval_case",
    product_analysis_routing_eval_cases(),
    ids=_case_id,
)
async def test_live_category_router_matches_routing_eval_cases(eval_case: Any) -> None:
    runner = MockCategoryRouterModelRunner()
    agent = LiveCategoryRouterAgent(settings=_settings(), model_runner=runner)

    result = await agent.run(_router_input(eval_case.category, eval_case.shopper_query))

    assert runner.calls == 1
    assert result.agent_path == eval_case.expected_agent_path
    assert result.fallback_agent_names == eval_case.expected_fallback_agent_names
    assert agent.workbench_activity[0]["status"] == "model_category_route_completed"
    assert agent.workbench_activity[0]["input"]["allowed_tools"] == []


@pytest.mark.asyncio
async def test_live_generic_fallback_handles_broad_non_technology_eval_case() -> None:
    eval_case = _first_routing_case(ProductAnalysisRoutingEvalKind.GENERIC_FALLBACK)
    runner = MockGenericProductAnalystModelRunner()
    agent = LiveGenericProductAnalystAgent(settings=_settings(), model_runner=runner)

    result = await agent.run(_analysis_input(eval_case.category, eval_case.shopper_query))

    assert runner.calls == 1
    assert result.category == eval_case.category
    assert result.evidence_ids
    assert result.source_ids
    assert "unsupported" not in _combined_text(result)
    assert "no specialist" not in _combined_text(result)
    assert agent.workbench_activity[0]["status"] == "model_generic_analysis_completed"
    assert agent.workbench_activity[0]["input"]["allowed_tools"] == []


@pytest.mark.asyncio
async def test_live_technology_domain_handles_domain_and_generic_eval_routes() -> None:
    domain_case = _first_routing_case(ProductAnalysisRoutingEvalKind.TECHNOLOGY_DOMAIN)
    runner = MockTechnologyDomainAnalystModelRunner()
    agent = LiveTechnologyDomainAnalystAgent(settings=_settings(), model_runner=runner)

    domain_result = await agent.run(
        _analysis_input(domain_case.category, domain_case.shopper_query)
    )

    assert runner.calls == 1
    assert domain_result.category == domain_case.category
    assert "unsupported" not in _combined_text(domain_result)
    assert "no specialist" not in _combined_text(domain_result)
    activity = agent.workbench_activity[0]
    assert activity["status"] == "model_technology_analysis_completed"
    assert activity["input"]["declared_route"]["agent_path"] == [
        "TechnologyDomainAnalystAgent"
    ]
    assert activity["input"]["declared_route"]["fallback_agent_names"] == [
        "GenericProductAnalystAgent"
    ]

    generic_case = _first_routing_case(ProductAnalysisRoutingEvalKind.GENERIC_FALLBACK)
    generic_result = await agent.run(
        _analysis_input(generic_case.category, generic_case.shopper_query)
    )

    assert runner.calls == 1
    assert generic_result.category == generic_case.category
    assert agent.workbench_activity[0]["status"] == "generic_fallback_non_technology"
    assert agent.workbench_activity[0]["input"]["declared_route"]["agent_path"] == [
        "GenericProductAnalystAgent"
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "eval_case",
    product_analysis_fallback_eval_cases(),
    ids=_case_id,
)
async def test_mvp_specialists_fall_back_to_domain_then_generic(
    eval_case: Any,
) -> None:
    route = DEFAULT_AGENT_CATALOG.route_product_analysis(eval_case.own_category)

    assert route.agent_path == eval_case.expected_specialist_agent_path
    assert route.fallback_agent_names == (
        eval_case.expected_specialist_fallback_agent_names
    )

    agent_class, runner_class = SPECIALIST_AGENT_FACTORIES[
        eval_case.specialist_agent_name
    ]

    technology_runner = runner_class()
    technology_agent = agent_class(settings=_settings(), model_runner=technology_runner)
    technology_result = await technology_agent.run(
        _analysis_input(eval_case.non_specialist_technology_category)
    )

    assert technology_runner.calls == 0
    assert technology_result.category == eval_case.non_specialist_technology_category
    assert "unsupported" not in _combined_text(technology_result)
    assert "no specialist" not in _combined_text(technology_result)
    technology_activity = technology_agent.workbench_activity[0]
    assert technology_activity["status"] == (
        eval_case.expected_technology_fallback_status
    )
    assert technology_activity["input"]["declared_route"]["agent_path"] == list(
        eval_case.expected_technology_fallback_agent_path
    )
    assert technology_activity["input"]["declared_route"]["fallback_agent_names"] == list(
        eval_case.expected_technology_fallback_agent_names
    )

    generic_runner = runner_class()
    generic_agent = agent_class(settings=_settings(), model_runner=generic_runner)
    generic_result = await generic_agent.run(_analysis_input(eval_case.non_technology_category))

    assert generic_runner.calls == 0
    assert generic_result.category == eval_case.non_technology_category
    assert "unsupported" not in _combined_text(generic_result)
    assert "no specialist" not in _combined_text(generic_result)
    generic_activity = generic_agent.workbench_activity[0]
    assert generic_activity["status"] == eval_case.expected_generic_fallback_status
    assert generic_activity["input"]["declared_route"]["agent_path"] == list(
        eval_case.expected_generic_fallback_agent_path
    )
    assert generic_activity["input"]["declared_route"]["fallback_agent_names"] == list(
        eval_case.expected_generic_fallback_agent_names
    )


def _first_routing_case(kind: ProductAnalysisRoutingEvalKind) -> Any:
    return next(
        eval_case
        for eval_case in product_analysis_routing_eval_cases()
        if eval_case.kind == kind
    )


def _router_input(category: str, shopper_query: str) -> CategoryRouterAgentInput:
    product = CanonicalProduct(
        name=f"Fixture {category.title()}",
        category=category,
    )
    return CategoryRouterAgentInput(
        run_id=new_id(),
        brief=ShoppingBrief(
            original_query=shopper_query,
            category=category,
            category_source=FieldSource.INFERRED,
        ),
        products=(product,),
    )


def _analysis_input(
    category: str,
    shopper_query: str | None = None,
) -> ProductAnalysisAgentInput:
    source_id = new_id()
    review_source_id = new_id()
    product = CanonicalProduct(
        name=f"Fixture {category.title()}",
        brand="Fixture",
        model=f"{category.title()} 1",
        category=category,
        source_ids=(source_id, review_source_id),
    )
    slug = category.replace(" ", "-")
    listing = ProductListing(
        product_id=product.product_id,
        title=f"Fixture {category.title()} - Official Store",
        url=f"https://example.com/{slug}/fixture-1",
        seller=SellerProfile(
            seller_name="Fixture Official Store",
            is_marketplace_seller=False,
        ),
        price=Money(amount="249", currency="USD"),
        source_ids=(source_id,),
        source_quality=SourceQuality(
            level=SourceQualityLevel.ADEQUATE,
            score=0.72,
            rationale="Synthetic routing regression listing evidence.",
        ),
    )
    product = product.model_copy(update={"listing_ids": (listing.listing_id,)})
    evidence = (
        SourceEvidence(
            source_id=source_id,
            target=EvidenceTarget(
                target_type=EvidenceTargetType.PRODUCT,
                product_id=product.product_id,
            ),
            evidence_type=EvidenceType.PRODUCT_SPEC,
            claim=f"The listing describes a {category} candidate.",
            confidence=_confidence(0.72),
            source_quality=SourceQuality(
                level=SourceQualityLevel.ADEQUATE,
                score=0.72,
                rationale="Synthetic routing regression product evidence.",
            ),
        ),
        SourceEvidence(
            source_id=review_source_id,
            target=EvidenceTarget(
                target_type=EvidenceTargetType.PRODUCT,
                product_id=product.product_id,
            ),
            evidence_type=EvidenceType.REVIEW_CLAIM,
            claim=(
                "A review source mentions fit, compatibility, durability, "
                "and practical tradeoffs."
            ),
            confidence=_confidence(0.66),
            source_quality=SourceQuality(
                level=SourceQualityLevel.ADEQUATE,
                score=0.66,
                rationale="Synthetic routing regression review evidence.",
            ),
        ),
    )
    return ProductAnalysisAgentInput(
        run_id=new_id(),
        brief=ShoppingBrief(
            original_query=shopper_query or f"Help me choose a {category}.",
            category=category,
            category_source=FieldSource.INFERRED,
            region=RegionPreference(
                region=Region(country_code="US", currency="USD"),
                source=FieldSource.USER_PROVIDED,
            ),
            budget=BudgetConstraint(
                amount=Money(amount="300", currency="USD"),
                mode=BudgetMode.PREFERRED,
                source=FieldSource.USER_PROVIDED,
            ),
            preferences=(
                PreferenceConstraint(
                    text="Good everyday value.",
                    mode=PreferenceMode.SOFT,
                    source=FieldSource.USER_PROVIDED,
                ),
            ),
        ),
        product=product,
        listings=(listing,),
        evidence=evidence,
    )


def _combined_text(analysis: Any) -> str:
    return " ".join(
        (
            analysis.fit_summary,
            *analysis.strengths,
            *analysis.weaknesses,
            *analysis.warnings,
        )
    ).casefold()


def _confidence(score: float) -> Confidence:
    if score < 0.5:
        level = ConfidenceLevel.LOW
    elif score < 0.75:
        level = ConfidenceLevel.MEDIUM
    else:
        level = ConfidenceLevel.HIGH
    return Confidence(score=score, level=level, rationale="Synthetic confidence.")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "eval_case",
    product_specialist_scope_eval_cases(),
    ids=_case_id,
)
async def test_typed_specialist_scope_uses_candidate_category(eval_case: Any) -> None:
    input_data = _analysis_input(eval_case.candidate_category or "unknown product")
    input_data = input_data.model_copy(
        update={
            "product": input_data.product.model_copy(
                update={
                    "category": eval_case.candidate_category,
                }
            ),
            "brief": input_data.brief.model_copy(
                update={
                    "category": eval_case.brief_category,
                    "original_query": f"Help me choose a {eval_case.brief_category}.",
                }
            ),
        }
    )
    agent_class, runner_class = SPECIALIST_AGENT_FACTORIES[
        eval_case.specialist_agent_name
    ]
    delegate = runner_class()
    inputs: list[dict[str, Any]] = []

    class RecordingRunner:
        async def run(self, agent: Any, model_input: str, **kwargs: Any) -> Any:
            inputs.append(json.loads(model_input))
            return await delegate.run(agent, model_input, **kwargs)

    agent = agent_class(settings=_settings(), model_runner=RecordingRunner())
    result = await agent.run(input_data)

    assert (
        "CandidateScopedProductAnalysis"
        in DEFAULT_AGENT_CATALOG.require(
            eval_case.specialist_agent_name
        ).planned_tool_boundaries
    )
    assert delegate.calls == eval_case.expected_model_calls
    assert result.category == eval_case.expected_category
    assert result.product_id == input_data.product.product_id
    assert result.evidence_ids == tuple(
        item.evidence_id for item in input_data.evidence
    )
    assert result.source_ids == tuple(
        dict.fromkeys(item.source_id for item in input_data.evidence)
    )
    if eval_case.expected_model_calls:
        assert inputs[0]["brief"] == input_data.brief.model_dump(mode="json")
        assert inputs[0]["product"]["category"] == eval_case.candidate_category
        assert agent.workbench_activity[0]["status"].startswith("model_")
    else:
        assert result.strengths == ()
        assert result.weaknesses == ()
        assert "fallback_non_" in agent.workbench_activity[0]["status"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "eval_case", product_analysis_fallback_eval_cases(), ids=_case_id
)
async def test_typed_specialist_rejects_model_category_mismatch(eval_case: Any) -> None:
    input_data = _analysis_input(eval_case.own_category)
    agent_class, runner_class = SPECIALIST_AGENT_FACTORIES[
        eval_case.specialist_agent_name
    ]
    runner = runner_class()
    agent = agent_class(settings=_settings(), model_runner=runner)
    matching = await agent.run(input_data)
    runner.output = matching.model_copy(update={"category": "office chair"})

    result = await agent.run(input_data)

    assert runner.calls == 2
    assert result.category == eval_case.own_category
    assert result.evidence_ids == tuple(
        item.evidence_id for item in input_data.evidence
    )
    assert (
        agent.workbench_activity[0]["status"]
        == "schema_invalid_technology_domain_fallback"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "eval_case", product_analysis_fallback_eval_cases(), ids=_case_id
)
@pytest.mark.parametrize("failure", ("error", "timeout", "schema_invalid"))
async def test_typed_specialist_failure_preserves_candidate_despite_brief(
    eval_case: Any,
    failure: str,
) -> None:
    input_data = _analysis_input(eval_case.own_category)
    input_data = input_data.model_copy(
        update={
            "brief": input_data.brief.model_copy(update={"category": "office chair"}),
        }
    )
    agent_class, runner_class = SPECIALIST_AGENT_FACTORIES[
        eval_case.specialist_agent_name
    ]
    runner = runner_class(
        error=TimeoutError()
        if failure == "timeout"
        else (
            RuntimeError("bounded offline model error") if failure == "error" else None
        ),
        output={"invalid": True} if failure == "schema_invalid" else None,
    )
    agent = agent_class(settings=_settings(), model_runner=runner)

    result = await agent.run(input_data)

    assert runner.calls == 1
    assert result.category == eval_case.own_category
    assert result.evidence_ids == tuple(
        item.evidence_id for item in input_data.evidence
    )
    assert (
        agent.workbench_activity[0]["status"] == f"{failure}_technology_domain_fallback"
    )
