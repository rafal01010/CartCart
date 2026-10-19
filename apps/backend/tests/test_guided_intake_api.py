import asyncio
import json
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID

from agents import Agent, RunConfig
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

import app.db.models  # noqa: F401
from app.agents.contracts import QueryPlannerAgentInput
from app.agents.live_query_planner import _model_input
from app.agents.live_guardrails import (
    LiveShoppingScopeGuardrail,
    MockShoppingGuardrailModelRunner,
)
from app.core.settings import AgentWorkflowMode, Settings
from app.db.base import Base
from app.db.session import (
    create_database_engine,
    create_session_factory,
    get_db_session,
)
from app.main import create_app
from app.schemas.ids import new_id
from app.schemas.guided_intake import ShoppingGuardrailResult
from app.schemas.intake import ShoppingBrief
from app.schemas.products import UserAddedProduct


async def _create_tables(settings: Settings) -> None:
    engine = create_database_engine(settings)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
    finally:
        await engine.dispose()


@pytest.fixture
def guided_api_client(tmp_path: Path) -> Iterator[TestClient]:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        database_path=tmp_path / "guided-intake-api.sqlite3",
        agent_workflow_mode="fixture",
        search_provider_enabled=False,
        extraction_provider_enabled=False,
        video_search_provider_enabled=False,
        transcript_provider_enabled=False,
        amazon_product_intelligence_provider_enabled=False,
        ikea_store_intelligence_provider_enabled=False,
        telemetry_enabled=False,
    )
    asyncio.run(_create_tables(settings))

    engine = create_database_engine(settings)
    session_factory = create_session_factory(engine)
    app = create_app(settings)

    async def override_get_db_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_get_db_session

    try:
        with TestClient(app) as client:
            yield client
    finally:
        asyncio.run(engine.dispose())


def _create_guided_session(client: TestClient, query: str) -> dict:
    response = client.post("/api/sessions/guided", json={"query": query})

    assert response.status_code == 201
    body = response.json()
    UUID(body["session_id"])
    return body


def test_phone_with_unconstrained_budget_does_not_ask_budget_again(
    guided_api_client: TestClient,
) -> None:
    created = _create_guided_session(
        guided_api_client, "I need to buy a phone, budget is not a problem"
    )
    assert created["guide"]["current_question"]["question_id"] == "considered-products"
    response = guided_api_client.post(
        f"/api/sessions/{created['session_id']}/answers",
        json={
            "question_id": "considered-products",
            "answer": {"answer_type": "natural_language", "text": "iPhone"},
        },
    )
    assert response.status_code == 200
    brief = response.json()["ready_brief"]
    assert brief["budget"] is None
    assert any(
        item["text"] == "Budget is not a constraint." for item in brief["preferences"]
    )


@pytest.mark.parametrize(
    ("country", "currency", "amount"),
    [("PH", "PHP", "20,000"), ("JP", "JPY", "30,000"), ("US", "USD", "300")],
)
def test_initial_regional_headphone_budget_keeps_audio_category(
    guided_api_client: TestClient, country: str, currency: str, amount: str
) -> None:
    query = f"I need noise-cancelling headphones for long flights, my budget is {currency} {amount}."
    response = guided_api_client.post(
        "/api/sessions/guided",
        json={"query": query, "region_setup": {"status": "provided", "region": {"country_code": country, "currency": currency}}},
    )
    assert response.status_code == 201
    created = response.json()
    assert created["guide"]["current_question"]["question_id"] == "considered-products"
    ready = guided_api_client.post(f"/api/sessions/{created['session_id']}/guide/skip-all")
    assert ready.status_code == 200
    brief = ready.json()["ready_brief"]
    assert brief["category"] == "headphones"
    assert brief["original_query"] == query
    assert brief["budget"]["amount"] == {"amount": amount.replace(",", ""), "currency": currency}
    assert brief["budget"]["mode"] == "preferred"
    saved = guided_api_client.get(f"/api/sessions/{created['session_id']}").json()
    assert saved["current_brief"] == brief


def test_create_guided_session_starts_from_single_question_and_loads_state(
    guided_api_client: TestClient,
) -> None:
    created = guided_api_client.post(
        "/api/sessions/guided",
        json={
            "query": "Which laptop should I buy?",
            "region_setup": {
                "status": "provided",
                "region": {"country_code": "us", "currency": "usd"},
            },
        },
    )

    assert created.status_code == 201
    body = created.json()
    guide = body["guide"]
    assert guide["status"] == "collecting"
    assert guide["current_question"]["question_id"] == "budget"
    assert guide["current_question"]["answer_surface"] == "textbox"
    assert guide["region_setup"]["status"] == "provided"
    assert guide["region_setup"]["region"]["country_code"] == "US"
    assert "link" not in guide["current_question"]["text"].lower()

    loaded = guided_api_client.get(f"/api/sessions/{body['session_id']}/guide")

    assert loaded.status_code == 200
    assert loaded.json() == guide


def test_submit_followup_answer_captures_budget_and_known_product_without_links(
    guided_api_client: TestClient,
) -> None:
    created = _create_guided_session(
        guided_api_client,
        "Which laptop should I buy for travel?",
    )
    session_id = created["session_id"]

    budget_response = guided_api_client.post(
        f"/api/sessions/{session_id}/answers",
        json={
            "question_id": "budget",
            "answer": {
                "answer_type": "natural_language",
                "text": "Around $1,200.",
            },
        },
    )
    assert budget_response.status_code == 200
    assert budget_response.json()["status"] == "collecting"
    assert (
        budget_response.json()["current_question"]["question_id"]
        == "considered-products"
    )
    considered_question_text = budget_response.json()["current_question"]["text"]
    assert "link" not in considered_question_text.casefold()
    assert "url" not in considered_question_text.casefold()

    response = guided_api_client.post(
        f"/api/sessions/{session_id}/answers",
        json={
            "question_id": "considered-products",
            "answer": {
                "answer_type": "natural_language",
                "text": "ThinkPad X1 Carbon. I need long battery life.",
            },
        },
    )

    assert response.status_code == 200
    guide = response.json()
    assert guide["status"] == "ready_for_analysis"
    assert guide["ready_brief"]["category"] == "laptop"
    assert guide["ready_brief"]["budget"]["amount"]["amount"] == "1200"
    assert guide["ready_brief"]["budget"]["mode"] == "preferred"
    assert guide["ready_brief"]["constraints"][0]["text"].endswith("long battery life.")

    session = guided_api_client.get(f"/api/sessions/{session_id}").json()
    assert session["current_brief"] == guide["ready_brief"]
    assert session["user_added_products"][0]["input_text"].startswith("ThinkPad X1")


def test_link_only_question_asks_for_goal_and_keeps_url_candidate(
    guided_api_client: TestClient,
) -> None:
    created = _create_guided_session(
        guided_api_client, "https://shop.example/items/kettle-42?utm_source=share"
    )
    session_id = created["session_id"]
    assert created["guide"]["current_question"]["question_id"] == "shopping-goal"
    assert (
        created["guide"]["analysis_start"]["can_skip_all_and_start_analysis"] is False
    )
    assert (
        guided_api_client.post(f"/api/sessions/{session_id}/guide/skip-all").status_code
        == 409
    )
    saved = guided_api_client.get(f"/api/sessions/{session_id}").json()
    assert len(saved["user_added_products"]) == 1
    assert saved["user_added_products"][0]["url"].startswith(
        "https://shop.example/items/kettle-42"
    )

    answered = guided_api_client.post(
        f"/api/sessions/{session_id}/answers",
        json={
            "question_id": "shopping-goal",
            "answer": {
                "answer_type": "natural_language",
                "text": "Is this kettle a good buy?",
            },
        },
    )
    assert answered.status_code == 200
    assert answered.json()["current_question"]["question_id"] == "budget"
    assert (
        guided_api_client.post(f"/api/sessions/{session_id}/guide/skip-all").status_code
        == 200
    )
    assert guided_api_client.post(f"/api/sessions/{session_id}/runs").status_code == 201
    researched = guided_api_client.get(f"/api/sessions/{session_id}").json()[
        "user_added_products"
    ]
    assert researched[0]["research_attempted"] is True


def test_sentence_link_and_named_products_become_separate_candidates(
    guided_api_client: TestClient,
) -> None:
    query = (
        "Compare ThinkPad X1 Carbon and Dell XPS 13 for travel; "
        "also check https://shop.example/items/xps-13."
    )
    created = _create_guided_session(guided_api_client, query)
    session = guided_api_client.get(f"/api/sessions/{created['session_id']}").json()
    candidates = session["user_added_products"]
    assert {item["input_text"] for item in candidates if item["url"] is None} == {
        "ThinkPad X1 Carbon",
        "Dell XPS 13",
    }
    assert [item["url"] for item in candidates if item["url"]] == [
        "https://shop.example/items/xps-13"
    ]
    assert session["current_brief"]["original_query"] == query


def test_first_question_comparison_tracks_models_without_generic_category(
    guided_api_client: TestClient,
) -> None:
    created = _create_guided_session(
        guided_api_client,
        "Which is better, Sony WH-1000XM5 or Bose QC Ultra for travel?",
    )
    candidates = guided_api_client.get(f"/api/sessions/{created['session_id']}").json()[
        "user_added_products"
    ]
    assert {item["input_text"] for item in candidates} == {
        "Sony WH-1000XM5",
        "Bose QC Ultra",
    }


@pytest.mark.parametrize(
    ("query", "name"),
    (
        ("Is the ThinkPad X1 Carbon good for travel?", "ThinkPad X1 Carbon"),
        ("Would a Dell XPS 13 suit me for travel?", "Dell XPS 13"),
    ),
)
def test_first_question_assessment_retains_unverified_named_research_hint(
    guided_api_client: TestClient, query: str, name: str
) -> None:
    created = _create_guided_session(guided_api_client, query)
    saved = guided_api_client.get(f"/api/sessions/{created['session_id']}").json()
    assert saved["current_brief"]["original_query"] == query
    assert len(saved["user_added_products"]) == 1
    candidate = saved["user_added_products"][0]
    assert candidate["input_text"] == name
    assert candidate["intake_source_question_ids"] == ["first-question"]
    assert candidate["research_attempted"] is False
    assert candidate["product"] is None
    assert candidate["listing"] is None
    assert candidate["possible_product_ids"] == []

    research_request = QueryPlannerAgentInput(
        run_id=new_id(),
        brief=ShoppingBrief.model_validate(saved["current_brief"]),
        user_added_products=(
            UserAddedProduct.model_validate(
                {
                    key: value
                    for key, value in candidate.items()
                    if key != "manual_evidence_status"
                }
            ),
        ),
    )
    hint = json.loads(_model_input(research_request))["user_added_products"][0]
    assert hint == {
        "candidate_id": candidate["candidate_id"],
        "input_text": name,
        "product_name": None,
        "has_url": False,
    }


@pytest.mark.parametrize(
    "query",
    (
        "Which laptop should I buy for travel?",
        "Is a laptop good for travel?",
        "Is long battery life good for travel?",
        "Would a laptop suit me for travel?",
        "Would long battery life suit me for travel?",
        "Is the Philippines good for travel?",
    ),
)
def test_first_question_assessment_does_not_invent_nonproduct_candidates(
    guided_api_client: TestClient, query: str
) -> None:
    created = _create_guided_session(guided_api_client, query)
    saved = guided_api_client.get(f"/api/sessions/{created['session_id']}").json()
    assert saved["current_brief"]["original_query"] == query
    assert saved["user_added_products"] == []


@pytest.mark.parametrize(
    "budget_text", ("Coding and movies", "Is the Dell XPS 13 good for travel?")
)
def test_assessment_capture_preserves_initial_url_and_nonproduct_budget_answer(
    guided_api_client: TestClient, budget_text: str,
) -> None:
    query = (
        "Is the ThinkPad X1 Carbon good for travel? "
        "https://shop.example/items/x1?utm_source=share"
    )
    created = _create_guided_session(guided_api_client, query)
    session_id = created["session_id"]
    answered = guided_api_client.post(
        f"/api/sessions/{session_id}/answers",
        json={
            "question_id": "budget",
            "answer": {"answer_type": "natural_language", "text": budget_text},
        },
    )
    assert answered.status_code == 200
    saved = guided_api_client.get(f"/api/sessions/{session_id}").json()
    assert saved["original_input"]["query"] == query
    assert saved["current_brief"]["original_query"] == (
        "Is the ThinkPad X1 Carbon good for travel?"
    )
    assert len(saved["user_added_products"]) == 2
    assert {item["input_text"] for item in saved["user_added_products"]} == {
        "ThinkPad X1 Carbon",
        None,
    }
    assert [item["url"] for item in saved["user_added_products"] if item["url"]] == [
        "https://shop.example/items/x1?utm_source=share"
    ]


def test_standalone_product_name_is_tracked_without_mistaking_budget_for_product(
    guided_api_client: TestClient,
) -> None:
    created = _create_guided_session(guided_api_client, "ThinkPad X1 Carbon")
    session_id = created["session_id"]
    answered = guided_api_client.post(
        f"/api/sessions/{session_id}/answers",
        json={
            "question_id": "budget",
            "answer": {"answer_type": "natural_language", "text": "Around $1200"},
        },
    )
    assert answered.status_code == 200
    candidates = guided_api_client.get(f"/api/sessions/{session_id}").json()[
        "user_added_products"
    ]
    assert [item["input_text"] for item in candidates] == ["ThinkPad X1 Carbon"]


def test_guided_answer_links_dedupe_and_reanswer_removes_stale_candidates(
    guided_api_client: TestClient,
) -> None:
    created = _create_guided_session(guided_api_client, "Which laptop should I buy?")
    session_id = created["session_id"]
    guided_api_client.post(f"/api/sessions/{session_id}/guide/skip")
    answer = guided_api_client.post(
        f"/api/sessions/{session_id}/answers",
        json={
            "question_id": "considered-products",
            "answer": {
                "answer_type": "natural_language",
                "text": "ThinkPad X1 Carbon and https://shop.example/items/x1?utm_source=one. Also https://shop.example/items/x1?utm_source=two",
            },
        },
    )
    assert answer.status_code == 200
    saved = guided_api_client.get(f"/api/sessions/{session_id}").json()[
        "user_added_products"
    ]
    assert len(saved) == 2
    assert {item["url"] is not None for item in saved} == {True, False}
    old_ids = {item["candidate_id"] for item in saved}

    assert (
        guided_api_client.post(
            f"/api/sessions/{session_id}/guide/reanswer",
            json={"question_id": "considered-products"},
        ).status_code
        == 200
    )
    revised = guided_api_client.post(
        f"/api/sessions/{session_id}/answers",
        json={
            "question_id": "considered-products",
            "answer": {"answer_type": "natural_language", "text": "Dell XPS 13"},
        },
    )
    assert revised.status_code == 200
    current = guided_api_client.get(f"/api/sessions/{session_id}").json()[
        "user_added_products"
    ]
    assert len(current) == 1
    assert current[0]["input_text"] == "Dell XPS 13"
    assert current[0]["candidate_id"] not in old_ids


def test_skip_question_readies_existing_brief(
    guided_api_client: TestClient,
) -> None:
    created = _create_guided_session(guided_api_client, "Which camera should I buy?")

    first_skip = guided_api_client.post(
        f"/api/sessions/{created['session_id']}/guide/skip",
    )
    assert first_skip.status_code == 200
    assert first_skip.json()["status"] == "collecting"
    assert first_skip.json()["current_question"]["question_id"] == "considered-products"

    response = guided_api_client.post(
        f"/api/sessions/{created['session_id']}/guide/skip",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready_for_analysis"
    assert body["ready_brief"]["category"] == "camera"


def test_skip_all_starts_analysis_when_enough_information_exists(
    guided_api_client: TestClient,
) -> None:
    created = _create_guided_session(guided_api_client, "Which desk should I buy?")

    guide_response = guided_api_client.post(
        f"/api/sessions/{created['session_id']}/guide/skip-all",
    )
    loaded_response = guided_api_client.get(
        f"/api/sessions/{created['session_id']}/guide",
    )
    run_response = guided_api_client.post(
        f"/api/sessions/{created['session_id']}/runs",
    )

    assert guide_response.status_code == 200
    assert guide_response.json()["status"] == "ready_for_analysis"
    assert loaded_response.status_code == 200
    assert loaded_response.json()["status"] == "ready_for_analysis"
    assert run_response.status_code == 201
    assert run_response.json()["status"] == "succeeded"


def test_yes_no_choice_answers_move_to_next_prompt(
    guided_api_client: TestClient,
) -> None:
    created = _create_guided_session(
        guided_api_client,
        "Need a portable monitor for travel",
    )
    guide = created["guide"]
    assert guide["current_question"]["answer_surface"] == "inline_choice"
    assert guide["current_question"]["inline_choice"]["control_type"] == "yes_no"

    response = guided_api_client.post(
        f"/api/sessions/{created['session_id']}/answers",
        json={
            "question_id": "monitor-connection",
            "answer": {"answer_type": "yes_no", "value": False},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "collecting"
    assert body["current_question"]["question_id"] == "budget"
    assert body["navigation"]["can_go_back"] is True


def test_two_option_plus_type_answer_is_supported_when_justified(
    guided_api_client: TestClient,
) -> None:
    created = _create_guided_session(
        guided_api_client,
        "Between an iPhone and a Samsung, which is better?",
    )
    guide = created["guide"]
    control = guide["current_question"]["inline_choice"]
    assert control["control_type"] == "two_option_plus_type_answer"
    assert control["custom_answer_label"] == "Type my answer"

    response = guided_api_client.post(
        f"/api/sessions/{created['session_id']}/answers",
        json={
            "question_id": "comparison-priority",
            "answer": {
                "answer_type": "choice_with_text",
                "choice_id": "something-else",
                "text": "Camera quality matters most.",
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "collecting"
    assert body["current_question"]["question_id"] == "budget"


def test_reanswer_prior_question_before_analysis(
    guided_api_client: TestClient,
) -> None:
    created = _create_guided_session(
        guided_api_client,
        "Need a portable monitor for travel",
    )
    session_id = created["session_id"]
    first_answer = guided_api_client.post(
        f"/api/sessions/{session_id}/answers",
        json={
            "question_id": "monitor-connection",
            "answer": {"answer_type": "yes_no", "value": True},
        },
    )
    assert first_answer.status_code == 200

    reanswer = guided_api_client.post(
        f"/api/sessions/{session_id}/guide/reanswer",
        json={"question_id": "monitor-connection"},
    )

    assert reanswer.status_code == 200
    assert reanswer.json()["current_question"]["question_id"] == "monitor-connection"
    assert (
        reanswer.json()["navigation"]["current_reanswer_question_id"]
        == "monitor-connection"
    )

    revised = guided_api_client.post(
        f"/api/sessions/{session_id}/answers",
        json={
            "question_id": "monitor-connection",
            "answer": {"answer_type": "yes_no", "value": False},
        },
    )

    assert revised.status_code == 200
    assert revised.json()["status"] == "ready_for_analysis"
    assert revised.json()["current_question"] is None


def test_region_setup_can_be_refused_or_supplied_after_creation(
    guided_api_client: TestClient,
) -> None:
    created = _create_guided_session(guided_api_client, "Which phone should I buy?")
    session_id = created["session_id"]
    assert created["guide"]["region_setup"]["status"] == "needs_answer"

    refused = guided_api_client.post(
        f"/api/sessions/{session_id}/guide/region",
        json={"status": "refused"},
    )
    assert refused.status_code == 200
    assert refused.json()["region_setup"]["status"] == "refused"

    supplied = guided_api_client.post(
        f"/api/sessions/{session_id}/guide/region",
        json={
            "status": "provided",
            "region": {"country_code": "ph", "currency": "php"},
        },
    )
    assert supplied.status_code == 200
    assert supplied.json()["region_setup"]["region"]["country_code"] == "PH"


@pytest.mark.parametrize(
    "query", ("Write a poem about a laptop", "Which gun should I buy?")
)
def test_fixture_guide_does_not_semantically_classify_request(
    guided_api_client: TestClient,
    query: str,
) -> None:
    session = _create_guided_session(guided_api_client, query)

    assert session["guide"]["status"] == "collecting"
    assert session["guide"]["guardrail"] is None
    assert session["guide"]["current_question"] is not None


@dataclass
class RecordingGuidedClassifier(MockShoppingGuardrailModelRunner):
    inputs: list[dict[str, Any]] = field(default_factory=list)

    async def run(
        self,
        agent: Agent[Any],
        model_input: str,
        *,
        run_config: RunConfig,
        max_turns: int,
    ) -> Any:
        self.inputs.append(json.loads(model_input))
        return await super().run(
            agent, model_input, run_config=run_config, max_turns=max_turns
        )


@pytest.fixture
def guided_classifier(
    guided_api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> RecordingGuidedClassifier:
    classifier = RecordingGuidedClassifier()
    guided_api_client.app.state.settings.agent_workflow_mode = AgentWorkflowMode.LIVE
    monkeypatch.setattr(
        "app.api.routes.guided_intake.LiveShoppingScopeGuardrail",
        lambda *, settings: LiveShoppingScopeGuardrail(
            settings=settings, model_runner=classifier
        ),
    )
    return classifier


def _answer_guided_question(
    client: TestClient, session_id: str, question_id: str, text: str
):
    return client.post(
        f"/api/sessions/{session_id}/answers",
        json={
            "question_id": question_id,
            "answer": {"answer_type": "natural_language", "text": text},
        },
    )


def _assert_blocked_guide(guide: dict) -> None:
    assert guide["status"] == "blocked"
    assert guide["guardrail"]["decision"] == "blocked"
    assert guide["current_question"] is None
    assert guide["ready_brief"] is None
    assert guide["analysis_start"]["enough_information"] is False
    assert guide["analysis_start"]["can_skip_all_and_start_analysis"] is False
    assert guide["progress"]["kind"] == "blocked"


GUIDED_GOAL_CASES = json.loads(
    (
        Path(__file__).parents[1]
        / "app/evals/fixtures/task146_guided_goals.json"
    ).read_text()
)["cases"]


@pytest.mark.parametrize("case", GUIDED_GOAL_CASES, ids=lambda case: case["name"])
def test_clarified_goal_uses_mocked_sdk_decision_before_writes_and_skip_all(
    guided_api_client: TestClient,
    guided_classifier: RecordingGuidedClassifier,
    case: dict,
) -> None:
    original_query = "https://shop.example/items/shared-item"
    created = _create_guided_session(guided_api_client, original_query)
    session_id = created["session_id"]
    before = guided_api_client.get(f"/api/sessions/{session_id}").json()
    assert created["guide"]["current_question"]["question_id"] == "shopping-goal"
    assert guided_classifier.calls == 0
    guided_classifier.output = ShoppingGuardrailResult(
        decision=case["decision"], reason=case["reason"], message=case["message"]
    )

    response = _answer_guided_question(
        guided_api_client, session_id, "shopping-goal", case["goal"]
    )

    assert response.status_code == 200
    assert guided_classifier.calls == 1
    assert guided_classifier.inputs == [
        {
            "user_input": case["goal"],
            "prior_answers": [
                {
                    "schema_version": 1,
                    "question_id": "shopping-goal",
                    "answer": {"answer_type": "natural_language", "text": case["goal"]},
                }
            ],
        }
    ]
    skipped = guided_api_client.post(f"/api/sessions/{session_id}/guide/skip-all")
    assert skipped.status_code == 200
    assert guided_classifier.calls == 1
    saved = guided_api_client.get(f"/api/sessions/{session_id}").json()
    assert saved["original_input"]["query"] == original_query
    if case["decision"] == "blocked":
        _assert_blocked_guide(response.json())
        _assert_blocked_guide(skipped.json())
        assert response.json()["guardrail"]["message"] == case["message"]
        assert saved["current_brief"] == before["current_brief"]
        assert saved["user_added_products"] == before["user_added_products"]
    else:
        assert response.json()["status"] == "collecting"
        assert response.json()["analysis_start"]["can_skip_all_and_start_analysis"] is True
        assert skipped.json()["status"] == "ready_for_analysis"
        assert skipped.json()["ready_brief"]["original_query"] == case["goal"]
        assert saved["current_brief"]["original_query"] == case["goal"]


@pytest.mark.parametrize("question_id", ("shopping-goal", "considered-products"))
def test_reanswer_rechecks_goal_and_answers_before_candidate_or_brief_writes(
    guided_api_client: TestClient,
    guided_classifier: RecordingGuidedClassifier,
    question_id: str,
) -> None:
    session_id = _create_guided_session(
        guided_api_client, "https://shop.example/items/laptop"
    )["session_id"]
    for field_name, text in (
        ("shopping-goal", "Help me choose a laptop for homework."),
        ("budget", "$1200"),
        ("considered-products", "ThinkPad X1 Carbon"),
    ):
        assert _answer_guided_question(
            guided_api_client, session_id, field_name, text
        ).status_code == 200
    before = guided_api_client.get(f"/api/sessions/{session_id}").json()
    reopened = guided_api_client.post(
        f"/api/sessions/{session_id}/guide/reanswer", json={"question_id": question_id}
    )
    assert reopened.status_code == 200
    assert reopened.json()["current_question"]["question_id"] == question_id
    calls_before = guided_classifier.calls
    guided_classifier.output = ShoppingGuardrailResult(
        decision="blocked",
        reason="unsafe_product",
        message="I can help with ordinary consumer purchases.",
    )
    revised_text = "Choose a firearm at https://shop.example/items/firearm"

    response = _answer_guided_question(
        guided_api_client, session_id, question_id, revised_text
    )

    assert response.status_code == 200
    _assert_blocked_guide(response.json())
    assert guided_classifier.calls == calls_before + 1
    assert any(
        answer["question_id"] == question_id and answer["answer"]["text"] == revised_text
        for answer in guided_classifier.inputs[-1]["prior_answers"]
    )
    if question_id == "shopping-goal":
        assert guided_classifier.inputs[-1]["user_input"] == revised_text
    skipped = guided_api_client.post(f"/api/sessions/{session_id}/guide/skip-all")
    _assert_blocked_guide(skipped.json())
    assert guided_classifier.calls == calls_before + 1
    saved = guided_api_client.get(f"/api/sessions/{session_id}").json()
    assert saved["current_brief"] == before["current_brief"]
    assert saved["user_added_products"] == before["user_added_products"]


@pytest.mark.parametrize("failure", ("error", "timeout", "invalid_output"))
def test_classifier_failure_keeps_reanswer_state_and_can_retry(
    guided_api_client: TestClient,
    guided_classifier: RecordingGuidedClassifier,
    failure: str,
) -> None:
    session_id = _create_guided_session(
        guided_api_client, "https://shop.example/items/laptop"
    )["session_id"]
    assert _answer_guided_question(
        guided_api_client, session_id, "shopping-goal", "Help me choose a laptop."
    ).status_code == 200
    reopened = guided_api_client.post(
        f"/api/sessions/{session_id}/guide/reanswer", json={"question_id": "shopping-goal"}
    )
    assert reopened.status_code == 200
    before_guide = reopened.json()
    before = guided_api_client.get(f"/api/sessions/{session_id}").json()
    if failure == "invalid_output":
        guided_classifier.output = {"decision": "invalid"}
    else:
        guided_classifier.error = (
            TimeoutError() if failure == "timeout" else RuntimeError("classifier failed")
        )
    revised_goal = "Compare laptops at https://shop.example/items/new-laptop"

    failed = _answer_guided_question(
        guided_api_client, session_id, "shopping-goal", revised_goal
    )

    assert failed.status_code == 503
    assert failed.json()["error"]["code"] == "shopping_guardrail_unavailable"
    assert failed.json()["error"]["details"] == {"retryable": True}
    assert guided_api_client.get(f"/api/sessions/{session_id}/guide").json() == before_guide
    saved = guided_api_client.get(f"/api/sessions/{session_id}").json()
    assert saved["current_brief"] == before["current_brief"]
    assert saved["user_added_products"] == before["user_added_products"]
    assert guided_classifier.calls == 2
    guided_classifier.error = None
    guided_classifier.output = None

    retried = _answer_guided_question(
        guided_api_client, session_id, "shopping-goal", revised_goal
    )

    assert retried.status_code == 200
    assert retried.json()["status"] == "ready_for_analysis"
    assert retried.json()["ready_brief"]["original_query"] == revised_goal
    assert guided_classifier.calls == 3
    saved = guided_api_client.get(f"/api/sessions/{session_id}").json()
    assert any(
        item["url"] == "https://shop.example/items/new-laptop"
        for item in saved["user_added_products"]
    )


def test_guardrail_cache_matches_full_typed_answer_context(
    guided_api_client: TestClient,
    guided_classifier: RecordingGuidedClassifier,
) -> None:
    session_id = _create_guided_session(
        guided_api_client, "Help me choose a laptop."
    )["session_id"]
    assert guided_classifier.calls == 1
    assert guided_api_client.get(f"/api/sessions/{session_id}/guide").status_code == 200
    assert guided_classifier.calls == 1
    assert _answer_guided_question(
        guided_api_client, session_id, "budget", "$1200"
    ).status_code == 200
    assert guided_classifier.calls == 2
    for budget, expected_calls in (("$1200", 2), ("$1500", 3)):
        reopened = guided_api_client.post(
            f"/api/sessions/{session_id}/guide/reanswer", json={"question_id": "budget"}
        )
        assert reopened.status_code == 200
        revised = _answer_guided_question(guided_api_client, session_id, "budget", budget)
        assert revised.status_code == 200
        assert revised.json()["status"] == "ready_for_analysis"
        assert guided_classifier.calls == expected_calls
    assert guided_classifier.inputs[-1]["user_input"] == "Help me choose a laptop."
    assert guided_classifier.inputs[-1]["prior_answers"][0]["answer"]["text"] == "$1500"


def test_initial_blocked_request_does_not_capture_volunteered_candidates(
    guided_api_client: TestClient,
    guided_classifier: RecordingGuidedClassifier,
) -> None:
    guided_classifier.output = ShoppingGuardrailResult(
        decision="blocked",
        reason="unsafe_product",
        message="I can help with ordinary consumer purchases.",
    )
    created = _create_guided_session(
        guided_api_client, "Choose a firearm at https://shop.example/items/firearm"
    )

    _assert_blocked_guide(created["guide"])
    saved = guided_api_client.get(f"/api/sessions/{created['session_id']}").json()
    assert saved["user_added_products"] == []
    assert guided_classifier.calls == 1
