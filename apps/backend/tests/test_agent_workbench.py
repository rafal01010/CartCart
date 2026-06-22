import pytest
from fastapi.testclient import TestClient

from app.agents.workbench import (
    AgentWorkbenchError,
    AgentWorkbenchRunRequest,
    AgentWorkbenchRunner,
)
from app.core.settings import Settings
from app.main import create_app


def make_test_client(**settings_overrides: object) -> TestClient:
    values = {
        "environment": "test",
        "frontend_origins": ("http://frontend.test",),
        **settings_overrides,
    }
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        **values,
    )
    return TestClient(create_app(settings))


def test_workbench_route_is_disabled_by_default() -> None:
    client = make_test_client()

    response = client.get("/internal/agent-workbench")

    assert response.status_code == 404


def test_workbench_route_is_unavailable_outside_allowed_environments() -> None:
    client = make_test_client(
        agent_workbench_enabled=True,
        environment="production",
    )

    response = client.get("/internal/agent-workbench")

    assert response.status_code == 404


def test_workbench_route_is_excluded_from_openapi() -> None:
    client = make_test_client(agent_workbench_enabled=True)

    response = client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/internal/agent-workbench" not in paths
    assert "/internal/agent-workbench/runs" not in paths


def test_workbench_catalog_lists_allowlisted_fake_agent_scenarios() -> None:
    client = make_test_client(agent_workbench_enabled=True)

    response = client.get("/internal/agent-workbench")

    assert response.status_code == 200
    body = response.json()
    agent_names = {agent["agent_name"] for agent in body["agents"]}
    assert "ShoppingScopeGuardrail" in agent_names
    assert "SellerListingTrustAgent" in agent_names
    guardrail = next(
        agent
        for agent in body["agents"]
        if agent["agent_name"] == "ShoppingScopeGuardrail"
    )
    assert {scenario["name"] for scenario in guardrail["scenarios"]} >= {
        "guardrail/allowed-monitor",
        "guardrail/blocked-off-topic",
        "guardrail/allowed-coffee-grinder",
        "guardrail/blocked-dangerous-product",
    }
    assert guardrail["modes"] == ["fixture", "mock", "live"]
    guide = next(
        agent for agent in body["agents"] if agent["agent_name"] == "ShoppingGuideAgent"
    )
    assert {scenario["name"] for scenario in guide["scenarios"]} >= {
        "guide/headphones-missing-budget",
        "guide/ready-monitor-brief",
    }
    assert guide["modes"] == ["fixture", "mock", "live"]
    intake = next(
        agent for agent in body["agents"] if agent["agent_name"] == "IntakeAgent"
    )
    assert {scenario["name"] for scenario in intake["scenarios"]} >= {
        "intake/monitor-ph-budget",
        "intake/ambiguous-category",
    }
    assert intake["modes"] == ["fixture", "mock", "live"]
    query_planner = next(
        agent for agent in body["agents"] if agent["agent_name"] == "QueryPlannerAgent"
    )
    assert {scenario["name"] for scenario in query_planner["scenarios"]} >= {
        "query-planner/coffee-grinder-us",
        "query-planner/unknown-category-generic",
    }
    assert query_planner["modes"] == ["fixture", "mock", "live"]
    discovery = next(
        agent for agent in body["agents"] if agent["agent_name"] == "DiscoveryAgent"
    )
    assert {scenario["name"] for scenario in discovery["scenarios"]} >= {
        "discovery/select-valid-sources",
        "discovery/no-good-results",
    }
    assert discovery["modes"] == ["fixture", "mock", "live"]
    router = next(
        agent
        for agent in body["agents"]
        if agent["agent_name"] == "CategoryRouterAgent"
    )
    assert {scenario["name"] for scenario in router["scenarios"]} >= {
        "router/monitor-to-specialist",
        "router/office-chair-generic",
    }
    assert router["modes"] == ["fixture", "mock", "live"]
    generic = next(
        agent
        for agent in body["agents"]
        if agent["agent_name"] == "GenericProductAnalystAgent"
    )
    assert {scenario["name"] for scenario in generic["scenarios"]} >= {
        "generic/office-chair-analysis",
        "generic/weak-evidence",
    }
    assert generic["modes"] == ["fixture", "mock", "live"]
    technology = next(
        agent
        for agent in body["agents"]
        if agent["agent_name"] == "TechnologyDomainAnalystAgent"
    )
    assert {scenario["name"] for scenario in technology["scenarios"]} >= {
        "technology/router-monitor",
        "technology/router-keyboard-domain",
    }
    assert technology["modes"] == ["fixture", "mock", "live"]
    monitor = next(
        agent
        for agent in body["agents"]
        if agent["agent_name"] == "MonitorSpecialistAgent"
    )
    assert {scenario["name"] for scenario in monitor["scenarios"]} >= {
        "monitor/coding-movies-1440p",
        "monitor/non-monitor-reject",
    }
    assert monitor["modes"] == ["fixture", "mock", "live"]
    smartphone = next(
        agent
        for agent in body["agents"]
        if agent["agent_name"] == "SmartphoneSpecialistAgent"
    )
    assert {scenario["name"] for scenario in smartphone["scenarios"]} >= {
        "smartphone/midrange-camera-battery",
        "smartphone/non-phone-reject",
    }
    assert smartphone["modes"] == ["fixture", "mock", "live"]
    laptop = next(
        agent
        for agent in body["agents"]
        if agent["agent_name"] == "LaptopSpecialistAgent"
    )
    assert {scenario["name"] for scenario in laptop["scenarios"]} >= {
        "laptop/student-portable",
        "laptop/non-laptop-reject",
    }
    assert laptop["modes"] == ["fixture", "mock", "live"]
    headphones = next(
        agent
        for agent in body["agents"]
        if agent["agent_name"] == "EarphonesHeadphonesSpecialistAgent"
    )
    assert {scenario["name"] for scenario in headphones["scenarios"]} >= {
        "headphones/noise-cancelling-commute",
        "headphones/non-audio-reject",
    }
    assert headphones["modes"] == ["fixture", "mock", "live"]
    tv = next(
        agent for agent in body["agents"] if agent["agent_name"] == "TVSpecialistAgent"
    )
    assert {scenario["name"] for scenario in tv["scenarios"]} >= {
        "tv/55-inch-movies-gaming",
        "tv/non-tv-reject",
    }
    assert tv["modes"] == ["fixture", "mock", "live"]
    smartwatch = next(
        agent
        for agent in body["agents"]
        if agent["agent_name"] == "SmartwatchSpecialistAgent"
    )
    assert {scenario["name"] for scenario in smartwatch["scenarios"]} >= {
        "smartwatch/fitness-android",
        "smartwatch/non-watch-reject",
    }
    assert smartwatch["modes"] == ["fixture", "mock", "live"]
    trust = next(
        agent
        for agent in body["agents"]
        if agent["agent_name"] == "SellerListingTrustAgent"
    )
    assert {scenario["name"] for scenario in trust["scenarios"]} >= {
        "trust/unknown-marketplace-cheap",
        "trust/established-retailer",
    }
    assert trust["modes"] == ["fixture", "mock", "live"]
    youtube = next(
        agent
        for agent in body["agents"]
        if agent["agent_name"] == "YouTubeReviewIntelligenceAgent"
    )
    assert {scenario["name"] for scenario in youtube["scenarios"]} >= {
        "youtube/monitor-review-transcript",
        "youtube/no-transcript-gap",
    }
    assert youtube["modes"] == ["fixture", "mock", "live"]
    reddit = next(
        agent
        for agent in body["agents"]
        if agent["agent_name"] == "RedditCommunityIntelligenceAgent"
    )
    assert {scenario["name"] for scenario in reddit["scenarios"]} >= {
        "reddit/headphones-recurring-complaint",
        "reddit/inaccessible-gap",
    }
    assert reddit["modes"] == ["fixture", "mock", "live"]
    amazon = next(
        agent
        for agent in body["agents"]
        if agent["agent_name"] == "AmazonProductIntelligenceAgent"
    )
    assert {scenario["name"] for scenario in amazon["scenarios"]} >= {
        "amazon/third-party-seller-region-gap",
        "amazon/variant-ambiguity",
    }
    assert amazon["modes"] == ["fixture", "mock", "live"]
    ikea = next(
        agent
        for agent in body["agents"]
        if agent["agent_name"] == "IKEAStoreIntelligenceAgent"
    )
    assert {scenario["name"] for scenario in ikea["scenarios"]} >= {
        "ikea/available-regional-product",
        "ikea/no-regional-presence",
    }
    assert ikea["modes"] == ["fixture", "mock", "live"]
    comparison = next(
        agent
        for agent in body["agents"]
        if agent["agent_name"] == "ComparisonDecisionAgent"
    )
    assert {scenario["name"] for scenario in comparison["scenarios"]} >= {
        "comparison/monitor-shortlist",
        "comparison/no-strong-buy",
    }
    assert comparison["modes"] == ["fixture", "mock", "live"]
    verifier = next(
        agent
        for agent in body["agents"]
        if agent["agent_name"] == "VerifierCriticAgent"
    )
    assert {scenario["name"] for scenario in verifier["scenarios"]} >= {
        "verifier/approved-fixture",
        "verifier/unsupported-claim-block",
        "verifier/suspicious-listing-warning",
    }
    assert verifier["modes"] == ["fixture", "mock", "live"]


def test_workbench_runs_allowlisted_fake_agent_from_internal_endpoint() -> None:
    client = make_test_client(agent_workbench_enabled=True)

    response = client.post(
        "/internal/agent-workbench/runs",
        json={
            "agent_name": "ShoppingScopeGuardrail",
            "scenario_name": "guardrail/allowed-monitor",
            "mode": "fixture",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["agent_name"] == "ShoppingScopeGuardrail"
    assert body["input_schema"] == "ShoppingScopeGuardrailInput"
    assert body["output_schema"] == "ShoppingGuardrailResult"
    assert body["output"]["decision"] == "allowed"
    assert body["allowed_tool_activity"] == []
    assert body["fallback"]["used"] is False
    assert body["usage"] is None
    assert body["trace_id"].startswith("agent_workbench_")
    assert body["elapsed_ms"] >= 0


def test_workbench_mock_guardrail_accepts_required_coffee_grinder_scenario() -> None:
    client = make_test_client(agent_workbench_enabled=True)

    response = client.post(
        "/internal/agent-workbench/runs",
        json={
            "agent_name": "ShoppingScopeGuardrail",
            "scenario_name": "guardrail/allowed-coffee-grinder",
            "mode": "mock",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["output"]["decision"] == "allowed"
    assert body["allowed_tool_activity"][0]["status"] == "model_guardrail_completed"


def test_workbench_mock_guardrail_blocks_dangerous_product_before_model() -> None:
    client = make_test_client(agent_workbench_enabled=True)

    response = client.post(
        "/internal/agent-workbench/runs",
        json={
            "agent_name": "ShoppingScopeGuardrail",
            "scenario_name": "guardrail/blocked-dangerous-product",
            "mode": "mock",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["output"]["decision"] == "blocked"
    assert body["output"]["reason"] == "unsafe_product"
    assert body["allowed_tool_activity"][0]["status"] == (
        "not_started_deterministic_block"
    )


def test_workbench_mock_verifier_blocks_unsupported_claim() -> None:
    client = make_test_client(agent_workbench_enabled=True)

    response = client.post(
        "/internal/agent-workbench/runs",
        json={
            "agent_name": "VerifierCriticAgent",
            "scenario_name": "verifier/unsupported-claim-block",
            "mode": "mock",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["output"]["approved"] is False
    assert any(
        "factual claim" in issue
        for issue in body["output"]["blocking_issues"]
    )
    assert body["allowed_tool_activity"][0]["status"] == "output_guardrail_blocked"


def test_workbench_mock_verifier_blocks_suspicious_listing_without_warning() -> None:
    client = make_test_client(agent_workbench_enabled=True)

    response = client.post(
        "/internal/agent-workbench/runs",
        json={
            "agent_name": "VerifierCriticAgent",
            "scenario_name": "verifier/suspicious-listing-warning",
            "mode": "mock",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["output"]["approved"] is False
    assert any(
        "suspicious" in issue
        for issue in body["output"]["blocking_issues"]
    )
    warnings = body["output"]["recommendation_bundle"]["warnings"]
    assert any("blocked for review" in warning.casefold() for warning in warnings)


def test_workbench_mock_intake_infers_monitor_ph_budget_scenario() -> None:
    client = make_test_client(agent_workbench_enabled=True)

    response = client.post(
        "/internal/agent-workbench/runs",
        json={
            "agent_name": "IntakeAgent",
            "scenario_name": "intake/monitor-ph-budget",
            "mode": "mock",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["output"]["category"] == "monitor"
    assert body["output"]["category_source"] == "inferred"
    assert body["output"]["region"]["region"]["country_code"] == "PH"
    assert body["output"]["budget"]["amount"]["currency"] == "PHP"
    assert body["output"]["budget"]["amount"]["amount"] == "18000"
    assert {item["text"] for item in body["output"]["constraints"]} >= {
        "27-inch size",
        "1440p resolution",
    }
    assert {item["text"] for item in body["output"]["preferences"]} >= {
        "Good for coding",
        "Good for movies",
    }
    assert body["allowed_tool_activity"][0]["status"] == "model_intake_completed"
    assert body["allowed_tool_activity"][0]["input"]["allowed_tools"] == []


def test_workbench_mock_comparison_monitor_shortlist_returns_modes() -> None:
    client = make_test_client(agent_workbench_enabled=True)

    response = client.post(
        "/internal/agent-workbench/runs",
        json={
            "agent_name": "ComparisonDecisionAgent",
            "scenario_name": "comparison/monitor-shortlist",
            "mode": "mock",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["output"]["no_strong_buy"] is False
    assert body["output"]["final_product_id"] is not None
    assert {item["mode"] for item in body["output"]["mode_results"]} >= {
        "best_overall",
        "best_value",
        "within_budget",
        "stretch_pick",
    }
    assert body["output"]["runner_up_product_ids"]
    assert body["allowed_tool_activity"][0]["status"] == (
        "model_comparison_decision_completed"
    )
    assert body["allowed_tool_activity"][0]["input"]["allowed_tools"] == []


def test_workbench_mock_comparison_no_strong_buy_returns_explicit_outcome() -> None:
    client = make_test_client(agent_workbench_enabled=True)

    response = client.post(
        "/internal/agent-workbench/runs",
        json={
            "agent_name": "ComparisonDecisionAgent",
            "scenario_name": "comparison/no-strong-buy",
            "mode": "mock",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["output"]["no_strong_buy"] is True
    assert body["output"]["final_product_id"] is None
    assert body["output"]["no_strong_buy_reason"]
    assert body["output"]["rejected_items"]


def test_workbench_mock_intake_preserves_ambiguous_category() -> None:
    client = make_test_client(agent_workbench_enabled=True)

    response = client.post(
        "/internal/agent-workbench/runs",
        json={
            "agent_name": "IntakeAgent",
            "scenario_name": "intake/ambiguous-category",
            "mode": "mock",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["output"]["category"] is None
    assert body["output"]["category_source"] is None
    assert body["allowed_tool_activity"][0]["status"] == "model_intake_completed"


def test_workbench_mock_guide_asks_missing_budget_without_recommendation() -> None:
    client = make_test_client(agent_workbench_enabled=True)

    response = client.post(
        "/internal/agent-workbench/runs",
        json={
            "agent_name": "ShoppingGuideAgent",
            "scenario_name": "guide/headphones-missing-budget",
            "mode": "mock",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["output"]["status"] == "collecting"
    assert body["output"]["current_question"]["purpose"] in {"budget", "use_case"}
    question_text = body["output"]["current_question"]["text"].lower()
    assert "recommend" not in question_text
    assert "link" not in question_text
    assert body["allowed_tool_activity"][0]["status"] == "model_guide_completed"
    assert body["allowed_tool_activity"][0]["input"]["allowed_tools"] == []


def test_workbench_mock_guide_readies_complete_monitor_brief() -> None:
    client = make_test_client(agent_workbench_enabled=True)

    response = client.post(
        "/internal/agent-workbench/runs",
        json={
            "agent_name": "ShoppingGuideAgent",
            "scenario_name": "guide/ready-monitor-brief",
            "mode": "mock",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["output"]["status"] == "ready_for_analysis"
    assert body["output"]["current_question"] is None
    assert body["output"]["ready_brief"]["category"] == "monitor"
    assert body["output"]["ready_brief"]["region"]["region"]["country_code"] == "PH"
    assert body["output"]["ready_brief"]["budget"]["amount"]["currency"] == "PHP"
    assert body["allowed_tool_activity"][0]["status"] == "model_guide_completed"


def test_workbench_mock_query_planner_plans_coffee_grinder_searches() -> None:
    client = make_test_client(agent_workbench_enabled=True)

    response = client.post(
        "/internal/agent-workbench/runs",
        json={
            "agent_name": "QueryPlannerAgent",
            "scenario_name": "query-planner/coffee-grinder-us",
            "mode": "mock",
        },
    )

    assert response.status_code == 200
    body = response.json()
    queries = body["output"]["queries"]
    intents = {query["intent"] for query in queries}
    assert {"discovery", "review"} <= intents
    assert all(query["region_code"] == "US" for query in queries)
    assert all(query["required_source_types"] for query in queries)
    assert any("coffee grinder" in query["query"] for query in queries)
    assert body["allowed_tool_activity"][0]["status"] == "model_query_plan_completed"
    assert body["allowed_tool_activity"][0]["input"]["allowed_tools"] == []


def test_workbench_mock_query_planner_keeps_unknown_category_generic() -> None:
    client = make_test_client(agent_workbench_enabled=True)

    response = client.post(
        "/internal/agent-workbench/runs",
        json={
            "agent_name": "QueryPlannerAgent",
            "scenario_name": "query-planner/unknown-category-generic",
            "mode": "mock",
        },
    )

    assert response.status_code == 200
    body = response.json()
    queries = body["output"]["queries"]
    combined_text = " ".join(query["query"] for query in queries).casefold()
    assert {"discovery", "review"} <= {query["intent"] for query in queries}
    assert all(query["region_code"] == "US" for query in queries)
    assert "organize a small entryway" in combined_text
    assert "unsupported category" not in combined_text
    assert "no specialist" not in combined_text
    assert body["allowed_tool_activity"][0]["status"] == "model_query_plan_completed"


def test_workbench_fixture_amazon_preserves_seller_region_gap_and_review_context() -> None:
    client = make_test_client(agent_workbench_enabled=True)

    response = client.post(
        "/internal/agent-workbench/runs",
        json={
            "agent_name": "AmazonProductIntelligenceAgent",
            "scenario_name": "amazon/third-party-seller-region-gap",
            "mode": "fixture",
        },
    )

    assert response.status_code == 200
    body = response.json()
    output = body["output"]
    source_url = output["source_references"][0]["url"]
    context = output["listing_contexts"][0]
    fact_types = {item["fact_type"] for item in output["evidence"]}
    gap_text = " ".join(
        f"{gap['summary']} {gap.get('reason') or ''}"
        for gap in output["evidence_gaps"]
    ).casefold()

    assert body["output_schema"] == "AmazonProductEvidenceBundle"
    assert source_url == "https://www.amazon.com/dp/B0CART5901"
    assert "tag=" not in source_url
    assert context["asin"] == "B0CART5901"
    assert context["seller_name"] == "Fixture Deals"
    assert context["fulfillment"] == "Ships from Fixture Deals"
    assert context["ships_to_region_code"] == "PH"
    assert context["ships_to_region"] is None
    assert {
        "listing_identity",
        "seller_fulfillment",
        "marketplace_warning",
        "review_summary",
        "review_quality_warning",
    } <= fact_types
    assert "could not be confirmed" in gap_text
    assert [activity["tool_name"] for activity in body["allowed_tool_activity"]] == [
        "AmazonProductIntelligenceProvider.fetch_product_evidence",
        "AmazonProductEvidenceBundle.returned",
    ]


def test_workbench_fixture_ikea_preserves_regional_price_availability_and_sources() -> (
    None
):
    client = make_test_client(agent_workbench_enabled=True)

    response = client.post(
        "/internal/agent-workbench/runs",
        json={
            "agent_name": "IKEAStoreIntelligenceAgent",
            "scenario_name": "ikea/available-regional-product",
            "mode": "fixture",
        },
    )

    assert response.status_code == 200
    body = response.json()
    output = body["output"]
    context = output["store_contexts"][0]
    source_id = output["source_references"][0]["source_id"]
    fact_types = {item["fact_type"] for item in output["evidence"]}
    warnings = " ".join(
        warning
        for item in output["evidence"]
        for warning in item["evidence_quality_warnings"]
    ).casefold()

    assert body["output_schema"] == "IKEAStoreEvidenceBundle"
    assert "final_product_id" not in output
    assert context["country_code"] == "PH"
    assert context["official_url"] == (
        "https://www.ikea.com/ph/en/p/micke-desk-white-90214308/"
    )
    assert context["price"]["amount"] == "3990"
    assert context["price"]["currency"] == "PHP"
    assert context["availability"] == "available"
    assert context["source_id"] == source_id
    assert all(item["source_id"] == source_id for item in output["evidence"])
    assert {
        "official_product_fact",
        "regional_price",
        "regional_availability",
        "store_delivery_context",
    } <= fact_types
    assert "shipping elsewhere" in warnings
    assert [activity["tool_name"] for activity in body["allowed_tool_activity"]] == [
        "IKEAStoreIntelligenceProvider.fetch_store_evidence",
        "IKEAStoreEvidenceBundle.returned",
    ]


def test_workbench_fixture_ikea_preserves_no_regional_presence_gap() -> None:
    client = make_test_client(agent_workbench_enabled=True)

    response = client.post(
        "/internal/agent-workbench/runs",
        json={
            "agent_name": "IKEAStoreIntelligenceAgent",
            "scenario_name": "ikea/no-regional-presence",
            "mode": "fixture",
        },
    )

    assert response.status_code == 200
    body = response.json()
    output = body["output"]
    assert output["source_references"] == []
    assert output["store_contexts"] == []
    assert output["evidence"] == []
    assert output["evidence_gaps"]
    gap = output["evidence_gaps"][0]
    assert gap["target"]["target_type"] == "region"
    assert gap["target"]["region_code"] == "AQ"
    gap_text = f"{gap['summary']} {gap.get('reason') or ''}".casefold()
    assert "no supported ikea regional presence" in gap_text
    assert "global" not in gap_text
    assert "shipping" not in gap_text


def test_workbench_mock_discovery_selects_valid_sources_only() -> None:
    client = make_test_client(agent_workbench_enabled=True)

    response = client.post(
        "/internal/agent-workbench/runs",
        json={
            "agent_name": "DiscoveryAgent",
            "scenario_name": "discovery/select-valid-sources",
            "mode": "mock",
        },
    )

    assert response.status_code == 200
    body = response.json()
    search_results = body["input"]["seed_results"]
    expected_ids = {
        result["source_id"]
        for result in search_results
        if result["source_type"] in {"retailer_listing", "professional_review"}
        and result["quality"]["level"] != "weak"
    }
    weak_ids = {
        result["source_id"]
        for result in search_results
        if result["quality"]["level"] == "weak"
    }
    selected_ids = set(body["output"]["selected_source_ids"])
    assert body["output"]["outcome"] == "selected"
    assert selected_ids == expected_ids
    assert not selected_ids & weak_ids
    assert body["allowed_tool_activity"][0]["status"] == "model_discovery_completed"
    assert body["allowed_tool_activity"][0]["input"]["allowed_tools"] == []


def test_workbench_mock_discovery_reports_no_good_results() -> None:
    client = make_test_client(agent_workbench_enabled=True)

    response = client.post(
        "/internal/agent-workbench/runs",
        json={
            "agent_name": "DiscoveryAgent",
            "scenario_name": "discovery/no-good-results",
            "mode": "mock",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["output"]["outcome"] == "insufficient_candidates"
    assert body["output"]["selected_source_ids"] == []
    assert set(body["output"]) == {
        "schema_version",
        "search_results",
        "selected_source_ids",
        "outcome",
        "notes",
    }
    assert body["allowed_tool_activity"][0]["status"] == "model_discovery_completed"


def test_workbench_mock_router_sends_monitor_to_specialist() -> None:
    client = make_test_client(agent_workbench_enabled=True)

    response = client.post(
        "/internal/agent-workbench/runs",
        json={
            "agent_name": "CategoryRouterAgent",
            "scenario_name": "router/monitor-to-specialist",
            "mode": "mock",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["output"]["agent_path"] == [
        "TechnologyDomainAnalystAgent",
        "MonitorSpecialistAgent",
    ]
    assert body["output"]["fallback_agent_names"] == [
        "TechnologyDomainAnalystAgent",
        "GenericProductAnalystAgent",
    ]
    assert body["allowed_tool_activity"][0]["status"] == (
        "model_category_route_completed"
    )
    assert body["allowed_tool_activity"][0]["input"]["allowed_tools"] == []


def test_workbench_mock_router_keeps_office_chair_generic() -> None:
    client = make_test_client(agent_workbench_enabled=True)

    response = client.post(
        "/internal/agent-workbench/runs",
        json={
            "agent_name": "CategoryRouterAgent",
            "scenario_name": "router/office-chair-generic",
            "mode": "mock",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["output"]["agent_path"] == ["GenericProductAnalystAgent"]
    assert body["output"]["fallback_agent_names"] == []
    combined_text = " ".join(body["output"]["agent_path"]).casefold()
    assert "unsupported category" not in combined_text
    assert "no specialist" not in combined_text
    assert body["allowed_tool_activity"][0]["status"] == (
        "model_category_route_completed"
    )


def test_workbench_mock_generic_analyzes_office_chair_with_source_ids() -> None:
    client = make_test_client(agent_workbench_enabled=True)

    response = client.post(
        "/internal/agent-workbench/runs",
        json={
            "agent_name": "GenericProductAnalystAgent",
            "scenario_name": "generic/office-chair-analysis",
            "mode": "mock",
        },
    )

    assert response.status_code == 200
    body = response.json()
    input_evidence = body["input"]["evidence"]
    expected_evidence_ids = {evidence["evidence_id"] for evidence in input_evidence}
    expected_source_ids = {evidence["source_id"] for evidence in input_evidence}
    assert body["output"]["category"] == "office chair"
    assert set(body["output"]["evidence_ids"]) == expected_evidence_ids
    assert set(body["output"]["source_ids"]) == expected_source_ids
    combined_text = " ".join(
        (
            body["output"]["fit_summary"],
            *body["output"]["strengths"],
            *body["output"]["weaknesses"],
            *body["output"]["warnings"],
        )
    ).casefold()
    assert "tradeoff" in combined_text
    assert "evidence" in combined_text
    assert "unsupported" not in combined_text
    assert "no specialist" not in combined_text
    assert body["allowed_tool_activity"][0]["status"] == (
        "model_generic_analysis_completed"
    )
    assert body["allowed_tool_activity"][0]["input"]["allowed_tools"] == []


def test_workbench_mock_generic_returns_limitations_for_weak_evidence() -> None:
    client = make_test_client(agent_workbench_enabled=True)

    response = client.post(
        "/internal/agent-workbench/runs",
        json={
            "agent_name": "GenericProductAnalystAgent",
            "scenario_name": "generic/weak-evidence",
            "mode": "mock",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["output"]["category"] == "lamp"
    assert body["output"]["confidence"]["level"] == "low"
    combined_text = " ".join(
        (
            body["output"]["fit_summary"],
            *body["output"]["strengths"],
            *body["output"]["weaknesses"],
            *body["output"]["warnings"],
        )
    ).casefold()
    assert "limited" in combined_text or "gap" in combined_text
    assert "unsupported" not in combined_text
    assert "no specialist" not in combined_text
    assert body["allowed_tool_activity"][0]["input"]["weak_or_sparse_evidence"] is True


def test_workbench_mock_trust_flags_unknown_cheap_marketplace_listing() -> None:
    client = make_test_client(agent_workbench_enabled=True)

    response = client.post(
        "/internal/agent-workbench/runs",
        json={
            "agent_name": "SellerListingTrustAgent",
            "scenario_name": "trust/unknown-marketplace-cheap",
            "mode": "mock",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["output"]["level"] == "suspicious"
    combined_text = " ".join(
        (
            body["output"]["summary"],
            *body["output"]["red_flags"],
            *body["output"]["positive_signals"],
        )
    ).casefold()
    assert "price" in combined_text
    assert "return" in combined_text or "warranty" in combined_text
    activity = body["allowed_tool_activity"][0]
    assert activity["status"] == "hard_suspicious_flag_preserved"
    assert activity["input"]["allowed_tools"] == []
    assert "suspicious_price" in activity["input"]["hard_suspicious_signal_kinds"]


def test_workbench_mock_trust_accepts_established_retailer_listing() -> None:
    client = make_test_client(agent_workbench_enabled=True)

    response = client.post(
        "/internal/agent-workbench/runs",
        json={
            "agent_name": "SellerListingTrustAgent",
            "scenario_name": "trust/established-retailer",
            "mode": "mock",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["output"]["level"] in {"reasonable", "strong"}
    assert body["output"]["positive_signals"]
    assert not body["output"]["red_flags"]
    assert body["allowed_tool_activity"][0]["status"] == (
        "model_listing_trust_completed"
    )


def test_workbench_mock_youtube_returns_timestamped_review_evidence() -> None:
    client = make_test_client(agent_workbench_enabled=True)

    response = client.post(
        "/internal/agent-workbench/runs",
        json={
            "agent_name": "YouTubeReviewIntelligenceAgent",
            "scenario_name": "youtube/monitor-review-transcript",
            "mode": "mock",
        },
    )

    assert response.status_code == 200
    body = response.json()
    output = body["output"]
    assert body["output_schema"] == "VideoReviewEvidenceBundle"
    assert "final_product_id" not in output
    assert output["videos"][0]["sponsorship_disclosed"] is True
    assert output["videos"][0]["affiliate_links_disclosed"] is True
    claims = {item["claim"] for item in output["evidence"]}
    assert any(claim.startswith("Pro:") for claim in claims)
    assert any(claim.startswith("Con:") for claim in claims)
    assert any(claim.startswith("Concern:") for claim in claims)
    assert all(
        item["timestamp_references"] and item["transcript_segment_ids"]
        for item in output["evidence"]
        if not item["metadata_only"]
    )
    assert {
        activity["tool_name"] for activity in body["allowed_tool_activity"]
    } >= {
        "TranscriptProvider.fetch_transcript",
        "VideoEvidenceCreator.create",
    }


def test_workbench_mock_youtube_preserves_no_transcript_gap() -> None:
    client = make_test_client(agent_workbench_enabled=True)

    response = client.post(
        "/internal/agent-workbench/runs",
        json={
            "agent_name": "YouTubeReviewIntelligenceAgent",
            "scenario_name": "youtube/no-transcript-gap",
            "mode": "mock",
        },
    )

    assert response.status_code == 200
    body = response.json()
    output = body["output"]
    assert output["videos"][0]["transcript_availability"] == "unavailable"
    assert output["transcript_segments"] == []
    assert output["transcript_gap_notes"]
    assert len(output["evidence"]) == 1
    assert output["evidence"][0]["metadata_only"] is True
    assert output["evidence"][0]["transcript_gap"]
    assert "sharp text" not in output["evidence"][0]["claim"].casefold()


def test_workbench_mock_reddit_returns_recurring_qualitative_evidence() -> None:
    client = make_test_client(agent_workbench_enabled=True)

    response = client.post(
        "/internal/agent-workbench/runs",
        json={
            "agent_name": "RedditCommunityIntelligenceAgent",
            "scenario_name": "reddit/headphones-recurring-complaint",
            "mode": "mock",
        },
    )

    assert response.status_code == 200
    body = response.json()
    output = body["output"]
    assert body["output_schema"] == "CommunityDiscussionEvidenceBundle"
    assert "final_product_id" not in output
    assert len(output["discussions"]) >= 2
    assert all(discussion["thread_id"] for discussion in output["discussions"])
    recurring = [item for item in output["evidence"] if item["recurring_signal"]]
    assert recurring
    evidence = recurring[0]
    assert evidence["qualitative_signal"] is True
    assert len(evidence["context_source_ids"]) >= 2
    warnings = " ".join(evidence["evidence_quality_warnings"]).casefold()
    assert "qualitative" in warnings
    assert "authoritative product fact" in warnings
    assert "brigaded" in warnings
    assert "astroturfed" in warnings
    assert {
        activity["tool_name"] for activity in body["allowed_tool_activity"]
    } >= {
        "CommunityDiscussionProvider.search_discussions",
        "CommunityEvidenceCreator.create",
    }


def test_workbench_mock_reddit_preserves_inaccessible_gap() -> None:
    client = make_test_client(agent_workbench_enabled=True)

    response = client.post(
        "/internal/agent-workbench/runs",
        json={
            "agent_name": "RedditCommunityIntelligenceAgent",
            "scenario_name": "reddit/inaccessible-gap",
            "mode": "mock",
        },
    )

    assert response.status_code == 200
    body = response.json()
    output = body["output"]
    assert output["evidence"] == []
    assert output["evidence_gaps"]
    gap_text = " ".join(
        f"{gap['summary']} {gap.get('reason') or ''}"
        for gap in output["evidence_gaps"]
    ).casefold()
    assert "inaccessible" in gap_text
    assert "deleted" in gap_text or "removed" in gap_text


def test_workbench_mock_technology_routes_monitor_toward_specialist() -> None:
    client = make_test_client(agent_workbench_enabled=True)

    response = client.post(
        "/internal/agent-workbench/runs",
        json={
            "agent_name": "TechnologyDomainAnalystAgent",
            "scenario_name": "technology/router-monitor",
            "mode": "mock",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["output"]["category"] == "monitor"
    activity = body["allowed_tool_activity"][0]
    assert activity["status"] == "model_technology_analysis_completed"
    assert activity["input"]["allowed_tools"] == []
    assert activity["input"]["declared_route"]["agent_path"] == [
        "TechnologyDomainAnalystAgent",
        "MonitorSpecialistAgent",
    ]
    assert activity["input"]["specialist_agent_name"] == "MonitorSpecialistAgent"


def test_workbench_mock_technology_analyzes_keyboard_domain() -> None:
    client = make_test_client(agent_workbench_enabled=True)

    response = client.post(
        "/internal/agent-workbench/runs",
        json={
            "agent_name": "TechnologyDomainAnalystAgent",
            "scenario_name": "technology/router-keyboard-domain",
            "mode": "mock",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["output"]["category"] == "keyboard"
    combined_text = " ".join(
        (
            body["output"]["fit_summary"],
            *body["output"]["strengths"],
            *body["output"]["weaknesses"],
            *body["output"]["warnings"],
        )
    ).casefold()
    assert "evidence" in combined_text
    assert "unsupported" not in combined_text
    assert "no specialist" not in combined_text
    activity = body["allowed_tool_activity"][0]
    assert activity["status"] == "model_technology_analysis_completed"
    assert activity["input"]["declared_route"]["agent_path"] == [
        "TechnologyDomainAnalystAgent"
    ]
    assert activity["input"]["specialist_agent_name"] is None


def test_workbench_mock_monitor_analyzes_coding_movies_1440p() -> None:
    client = make_test_client(agent_workbench_enabled=True)

    response = client.post(
        "/internal/agent-workbench/runs",
        json={
            "agent_name": "MonitorSpecialistAgent",
            "scenario_name": "monitor/coding-movies-1440p",
            "mode": "mock",
        },
    )

    assert response.status_code == 200
    body = response.json()
    input_evidence = body["input"]["evidence"]
    expected_evidence_ids = {evidence["evidence_id"] for evidence in input_evidence}
    expected_source_ids = {evidence["source_id"] for evidence in input_evidence}
    assert body["output"]["category"] == "monitor"
    assert set(body["output"]["evidence_ids"]) == expected_evidence_ids
    assert set(body["output"]["source_ids"]) == expected_source_ids
    combined_text = " ".join(
        (
            body["output"]["fit_summary"],
            *body["output"]["strengths"],
            *body["output"]["weaknesses"],
            *body["output"]["warnings"],
        )
    ).casefold()
    for marker in ("panel", "resolution", "refresh", "ergonomic", "port", "tradeoff"):
        assert marker in combined_text
    activity = body["allowed_tool_activity"][0]
    assert activity["status"] == "model_monitor_analysis_completed"
    assert activity["input"]["allowed_tools"] == []
    assert activity["input"]["declared_route"]["agent_path"] == [
        "TechnologyDomainAnalystAgent",
        "MonitorSpecialistAgent",
    ]


def test_workbench_mock_monitor_rejects_non_monitor_scope_with_fallback() -> None:
    client = make_test_client(agent_workbench_enabled=True)

    response = client.post(
        "/internal/agent-workbench/runs",
        json={
            "agent_name": "MonitorSpecialistAgent",
            "scenario_name": "monitor/non-monitor-reject",
            "mode": "mock",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["output"]["category"] == "office chair"
    combined_text = " ".join(
        (
            body["output"]["fit_summary"],
            *body["output"]["strengths"],
            *body["output"]["weaknesses"],
            *body["output"]["warnings"],
        )
    ).casefold()
    assert "unsupported" not in combined_text
    assert "no specialist" not in combined_text
    activity = body["allowed_tool_activity"][0]
    assert activity["status"] == "generic_fallback_non_monitor"
    assert activity["input"]["declared_route"]["agent_path"] == [
        "GenericProductAnalystAgent"
    ]


def test_workbench_mock_smartphone_analyzes_midrange_camera_battery() -> None:
    client = make_test_client(agent_workbench_enabled=True)

    response = client.post(
        "/internal/agent-workbench/runs",
        json={
            "agent_name": "SmartphoneSpecialistAgent",
            "scenario_name": "smartphone/midrange-camera-battery",
            "mode": "mock",
        },
    )

    assert response.status_code == 200
    body = response.json()
    input_evidence = body["input"]["evidence"]
    expected_evidence_ids = {evidence["evidence_id"] for evidence in input_evidence}
    expected_source_ids = {evidence["source_id"] for evidence in input_evidence}
    assert body["output"]["category"] == "smartphone"
    assert set(body["output"]["evidence_ids"]) == expected_evidence_ids
    assert set(body["output"]["source_ids"]) == expected_source_ids
    combined_text = " ".join(
        (
            body["output"]["fit_summary"],
            *body["output"]["strengths"],
            *body["output"]["weaknesses"],
            *body["output"]["warnings"],
        )
    ).casefold()
    for marker in ("camera", "battery", "update", "performance", "region"):
        assert marker in combined_text
    activity = body["allowed_tool_activity"][0]
    assert activity["status"] == "model_smartphone_analysis_completed"
    assert activity["input"]["allowed_tools"] == []
    assert activity["input"]["declared_route"]["agent_path"] == [
        "TechnologyDomainAnalystAgent",
        "SmartphoneSpecialistAgent",
    ]


def test_workbench_mock_smartphone_rejects_non_phone_scope_with_fallback() -> None:
    client = make_test_client(agent_workbench_enabled=True)

    response = client.post(
        "/internal/agent-workbench/runs",
        json={
            "agent_name": "SmartphoneSpecialistAgent",
            "scenario_name": "smartphone/non-phone-reject",
            "mode": "mock",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["output"]["category"] == "monitor"
    combined_text = " ".join(
        (
            body["output"]["fit_summary"],
            *body["output"]["strengths"],
            *body["output"]["weaknesses"],
            *body["output"]["warnings"],
        )
    ).casefold()
    assert "unsupported" not in combined_text
    assert "no specialist" not in combined_text
    activity = body["allowed_tool_activity"][0]
    assert activity["status"] == "technology_domain_fallback_non_phone"
    assert activity["input"]["declared_route"]["agent_path"] == [
        "TechnologyDomainAnalystAgent",
        "MonitorSpecialistAgent",
    ]


def test_workbench_mock_laptop_analyzes_student_portable() -> None:
    client = make_test_client(agent_workbench_enabled=True)

    response = client.post(
        "/internal/agent-workbench/runs",
        json={
            "agent_name": "LaptopSpecialistAgent",
            "scenario_name": "laptop/student-portable",
            "mode": "mock",
        },
    )

    assert response.status_code == 200
    body = response.json()
    input_evidence = body["input"]["evidence"]
    expected_evidence_ids = {evidence["evidence_id"] for evidence in input_evidence}
    expected_source_ids = {evidence["source_id"] for evidence in input_evidence}
    assert body["output"]["category"] == "laptop"
    assert set(body["output"]["evidence_ids"]) == expected_evidence_ids
    assert set(body["output"]["source_ids"]) == expected_source_ids
    combined_text = " ".join(
        (
            body["output"]["fit_summary"],
            *body["output"]["strengths"],
            *body["output"]["weaknesses"],
            *body["output"]["warnings"],
        )
    ).casefold()
    for marker in (
        "cpu",
        "ram",
        "storage",
        "battery",
        "display",
        "port",
        "weight",
        "upgrade",
    ):
        assert marker in combined_text
    activity = body["allowed_tool_activity"][0]
    assert activity["status"] == "model_laptop_analysis_completed"
    assert activity["input"]["allowed_tools"] == []
    assert activity["input"]["declared_route"]["agent_path"] == [
        "TechnologyDomainAnalystAgent",
        "LaptopSpecialistAgent",
    ]


def test_workbench_mock_laptop_rejects_non_laptop_scope_with_fallback() -> None:
    client = make_test_client(agent_workbench_enabled=True)

    response = client.post(
        "/internal/agent-workbench/runs",
        json={
            "agent_name": "LaptopSpecialistAgent",
            "scenario_name": "laptop/non-laptop-reject",
            "mode": "mock",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["output"]["category"] == "monitor"
    combined_text = " ".join(
        (
            body["output"]["fit_summary"],
            *body["output"]["strengths"],
            *body["output"]["weaknesses"],
            *body["output"]["warnings"],
        )
    ).casefold()
    assert "unsupported" not in combined_text
    assert "no specialist" not in combined_text
    activity = body["allowed_tool_activity"][0]
    assert activity["status"] == "technology_domain_fallback_non_laptop"
    assert activity["input"]["declared_route"]["agent_path"] == [
        "TechnologyDomainAnalystAgent",
        "MonitorSpecialistAgent",
    ]


def test_workbench_mock_headphones_analyzes_noise_cancelling_commute() -> None:
    client = make_test_client(agent_workbench_enabled=True)

    response = client.post(
        "/internal/agent-workbench/runs",
        json={
            "agent_name": "EarphonesHeadphonesSpecialistAgent",
            "scenario_name": "headphones/noise-cancelling-commute",
            "mode": "mock",
        },
    )

    assert response.status_code == 200
    body = response.json()
    input_evidence = body["input"]["evidence"]
    expected_evidence_ids = {evidence["evidence_id"] for evidence in input_evidence}
    expected_source_ids = {evidence["source_id"] for evidence in input_evidence}
    assert body["output"]["category"] == "headphones"
    assert set(body["output"]["evidence_ids"]) == expected_evidence_ids
    assert set(body["output"]["source_ids"]) == expected_source_ids
    combined_text = " ".join(
        (
            body["output"]["fit_summary"],
            *body["output"]["strengths"],
            *body["output"]["weaknesses"],
            *body["output"]["warnings"],
        )
    ).casefold()
    for marker in (
        "anc",
        "comfort",
        "fit",
        "microphone",
        "battery",
        "codec",
        "device",
    ):
        assert marker in combined_text
    activity = body["allowed_tool_activity"][0]
    assert activity["status"] == "model_earphones_headphones_analysis_completed"
    assert activity["input"]["allowed_tools"] == []
    assert activity["input"]["declared_route"]["agent_path"] == [
        "TechnologyDomainAnalystAgent",
        "EarphonesHeadphonesSpecialistAgent",
    ]


def test_workbench_mock_headphones_rejects_non_audio_scope_with_fallback() -> None:
    client = make_test_client(agent_workbench_enabled=True)

    response = client.post(
        "/internal/agent-workbench/runs",
        json={
            "agent_name": "EarphonesHeadphonesSpecialistAgent",
            "scenario_name": "headphones/non-audio-reject",
            "mode": "mock",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["output"]["category"] == "monitor"
    combined_text = " ".join(
        (
            body["output"]["fit_summary"],
            *body["output"]["strengths"],
            *body["output"]["weaknesses"],
            *body["output"]["warnings"],
        )
    ).casefold()
    assert "unsupported" not in combined_text
    assert "no specialist" not in combined_text
    activity = body["allowed_tool_activity"][0]
    assert activity["status"] == "technology_domain_fallback_non_audio"
    assert activity["input"]["declared_route"]["agent_path"] == [
        "TechnologyDomainAnalystAgent",
        "MonitorSpecialistAgent",
    ]


def test_workbench_mock_tv_analyzes_55_inch_movies_gaming() -> None:
    client = make_test_client(agent_workbench_enabled=True)

    response = client.post(
        "/internal/agent-workbench/runs",
        json={
            "agent_name": "TVSpecialistAgent",
            "scenario_name": "tv/55-inch-movies-gaming",
            "mode": "mock",
        },
    )

    assert response.status_code == 200
    body = response.json()
    input_evidence = body["input"]["evidence"]
    expected_evidence_ids = {evidence["evidence_id"] for evidence in input_evidence}
    expected_source_ids = {evidence["source_id"] for evidence in input_evidence}
    assert body["output"]["category"] == "tv"
    assert set(body["output"]["evidence_ids"]) == expected_evidence_ids
    assert set(body["output"]["source_ids"]) == expected_source_ids
    combined_text = " ".join(
        (
            body["output"]["fit_summary"],
            *body["output"]["strengths"],
            *body["output"]["weaknesses"],
            *body["output"]["warnings"],
        )
    ).casefold()
    for marker in (
        "panel",
        "backlight",
        "hdr",
        "motion",
        "gaming",
        "room brightness",
        "size fit",
    ):
        assert marker in combined_text
    activity = body["allowed_tool_activity"][0]
    assert activity["status"] == "model_tv_analysis_completed"
    assert activity["input"]["allowed_tools"] == []
    assert activity["input"]["declared_route"]["agent_path"] == [
        "TechnologyDomainAnalystAgent",
        "TVSpecialistAgent",
    ]


def test_workbench_mock_tv_rejects_non_tv_scope_with_fallback() -> None:
    client = make_test_client(agent_workbench_enabled=True)

    response = client.post(
        "/internal/agent-workbench/runs",
        json={
            "agent_name": "TVSpecialistAgent",
            "scenario_name": "tv/non-tv-reject",
            "mode": "mock",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["output"]["category"] == "laptop"
    combined_text = " ".join(
        (
            body["output"]["fit_summary"],
            *body["output"]["strengths"],
            *body["output"]["weaknesses"],
            *body["output"]["warnings"],
        )
    ).casefold()
    assert "unsupported" not in combined_text
    assert "no specialist" not in combined_text
    activity = body["allowed_tool_activity"][0]
    assert activity["status"] == "technology_domain_fallback_non_tv"
    assert activity["input"]["declared_route"]["agent_path"] == [
        "TechnologyDomainAnalystAgent",
        "LaptopSpecialistAgent",
    ]


def test_workbench_mock_smartwatch_analyzes_fitness_android() -> None:
    client = make_test_client(agent_workbench_enabled=True)

    response = client.post(
        "/internal/agent-workbench/runs",
        json={
            "agent_name": "SmartwatchSpecialistAgent",
            "scenario_name": "smartwatch/fitness-android",
            "mode": "mock",
        },
    )

    assert response.status_code == 200
    body = response.json()
    input_evidence = body["input"]["evidence"]
    expected_evidence_ids = {evidence["evidence_id"] for evidence in input_evidence}
    expected_source_ids = {evidence["source_id"] for evidence in input_evidence}
    assert body["output"]["category"] == "smartwatch"
    assert set(body["output"]["evidence_ids"]) == expected_evidence_ids
    assert set(body["output"]["source_ids"]) == expected_source_ids
    combined_text = " ".join(
        (
            body["output"]["fit_summary"],
            *body["output"]["strengths"],
            *body["output"]["weaknesses"],
            *body["output"]["warnings"],
        )
    ).casefold()
    for marker in (
        "phone compatibility",
        "android",
        "health sensor",
        "battery",
        "durability",
        "water resistance",
        "app ecosystem",
    ):
        assert marker in combined_text
    activity = body["allowed_tool_activity"][0]
    assert activity["status"] == "model_smartwatch_analysis_completed"
    assert activity["input"]["allowed_tools"] == []
    assert activity["input"]["declared_route"]["agent_path"] == [
        "TechnologyDomainAnalystAgent",
        "SmartwatchSpecialistAgent",
    ]


def test_workbench_mock_smartwatch_rejects_non_watch_with_fallback() -> None:
    client = make_test_client(agent_workbench_enabled=True)

    response = client.post(
        "/internal/agent-workbench/runs",
        json={
            "agent_name": "SmartwatchSpecialistAgent",
            "scenario_name": "smartwatch/non-watch-reject",
            "mode": "mock",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["output"]["category"] == "phone"
    combined_text = " ".join(
        (
            body["output"]["fit_summary"],
            *body["output"]["strengths"],
            *body["output"]["weaknesses"],
            *body["output"]["warnings"],
        )
    ).casefold()
    assert "unsupported" not in combined_text
    assert "no specialist" not in combined_text
    activity = body["allowed_tool_activity"][0]
    assert activity["status"] == "technology_domain_fallback_non_smartwatch"
    assert activity["input"]["declared_route"]["agent_path"] == [
        "TechnologyDomainAnalystAgent",
        "SmartphoneSpecialistAgent",
    ]


def test_workbench_rejects_unregistered_agents() -> None:
    client = make_test_client(agent_workbench_enabled=True)

    response = client.post(
        "/internal/agent-workbench/runs",
        json={
            "agent_name": "ArbitraryAgent",
            "scenario_name": "anything",
            "mode": "fixture",
        },
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "agent_workbench_agent_not_allowed"


def test_workbench_rejects_invalid_input_override() -> None:
    client = make_test_client(agent_workbench_enabled=True)

    response = client.post(
        "/internal/agent-workbench/runs",
        json={
            "agent_name": "ShoppingScopeGuardrail",
            "scenario_name": "guardrail/allowed-monitor",
            "mode": "fixture",
            "input": {"user_input": ""},
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "agent_workbench_invalid_input"


def test_workbench_live_mode_requires_live_agent_configuration() -> None:
    client = make_test_client(
        agent_workbench_enabled=True,
        live_agents_enabled=False,
        openai_api_key=None,
    )

    response = client.post(
        "/internal/agent-workbench/runs",
        json={
            "agent_name": "ShoppingScopeGuardrail",
            "scenario_name": "guardrail/allowed-monitor",
            "mode": "live",
        },
    )

    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "agent_workbench_live_mode_unavailable"
    assert "CARTCART_LIVE_AGENTS_ENABLED=true" in body["error"]["message"]


@pytest.mark.asyncio
async def test_workbench_direct_runner_requires_opt_in_flag() -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    runner = AgentWorkbenchRunner(settings)

    with pytest.raises(AgentWorkbenchError) as exc_info:
        await runner.run(
            AgentWorkbenchRunRequest(
                agent_name="ShoppingScopeGuardrail",
                scenario_name="guardrail/allowed-monitor",
            )
        )

    assert exc_info.value.code == "agent_workbench_disabled"
