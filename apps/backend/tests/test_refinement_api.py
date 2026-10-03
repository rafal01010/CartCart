import asyncio
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

import app.db.models  # noqa: F401
from app.core.settings import Settings
from app.db.base import Base
from app.db.repositories.refinements import RefinementRepository
from app.db.repositories.products import ProductRepository
from app.db.repositories.results import ResultRepository
from app.db.repositories.search_sources import SearchSourceRepository
from app.db.session import (
    create_database_engine,
    create_session_factory,
    get_db_session,
)
from app.main import create_app
from app.schemas.analysis import (
    ComparisonCriterion,
    ComparisonMatrix,
    ComparisonRow,
    RecommendationBundle,
)
from app.schemas.ids import new_id
from app.schemas.products import CanonicalProduct, UserAddedProduct
from app.schemas.search_sources import SourceSnapshot, SourceEvidence


async def _create_tables(settings: Settings) -> None:
    engine = create_database_engine(settings)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
    finally:
        await engine.dispose()


@pytest.fixture
def refinement_api_client(tmp_path: Path) -> Iterator[TestClient]:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        database_path=tmp_path / "refinement-api.sqlite3",
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


def create_session(client: TestClient) -> str:
    response = client.post(
        "/api/sessions",
        json={"query": "Need quiet headphones"},
    )

    assert response.status_code == 201
    return response.json()["session_id"]


def create_run(client: TestClient, session_id: str) -> str:
    response = client.post(f"/api/sessions/{session_id}/runs")

    assert response.status_code == 201
    return response.json()["run_id"]


def make_fixture_recommendation(reason: str) -> RecommendationBundle:
    product_id = new_id()
    evidence_id = new_id()
    comparison_matrix = ComparisonMatrix(
        criteria=(ComparisonCriterion(name="fit", weight=1.0),),
        rows=(
            ComparisonRow(
                product_id=product_id,
                scores={"fit": 0.3},
                evidence_ids=(evidence_id,),
                summary=reason,
            ),
        ),
    )
    return RecommendationBundle(
        no_strong_buy=True,
        no_strong_buy_reason=reason,
        comparison_matrix=comparison_matrix,
        evidence_ids=(evidence_id,),
    )


async def save_fixture_result(
    settings: Settings,
    run_id: str,
    recommendation: RecommendationBundle,
) -> None:
    engine = create_database_engine(settings)
    try:
        session_factory = create_session_factory(engine)
        async with session_factory() as session:
            await ResultRepository(session).save_result_bundle(
                UUID(run_id),
                trust_assessments=(),
                category_analyses=(),
                agent_records=(),
                recommendation_bundle=recommendation,
            )
            await session.commit()
    finally:
        await engine.dispose()


async def add_product_evidence(settings: Settings, run_id: str) -> None:
    engine = create_database_engine(settings)
    try:
        async with create_session_factory(engine)() as session:
            product = CanonicalProduct(name="Quiet Headphones")
            await ProductRepository(session).add_canonical_product(
                UUID(run_id), product
            )
            snapshot = SourceSnapshot.model_validate(
                {
                    "url": "https://example.test/headphones",
                    "source_type": "professional_review",
                    "provider": {"provider_name": "fixture"},
                }
            )
            await SearchSourceRepository(session).add_source_snapshot(
                UUID(run_id), snapshot
            )
            evidence = SourceEvidence.model_validate(
                {
                    "source_id": snapshot.source_id,
                    "target": {
                        "target_type": "product",
                        "product_id": product.product_id,
                    },
                    "evidence_type": "review_claim",
                    "claim": "Noise cancellation was measured in this review.",
                    "confidence": {"score": 0.8, "level": "high"},
                    "source_quality": {"level": "adequate"},
                }
            )
            await SearchSourceRepository(session).add_source_evidence(
                UUID(run_id), evidence
            )
            await session.commit()
    finally:
        await engine.dispose()


async def load_result_version_and_refinement(
    settings: Settings,
    original_run_id: str,
    refinement_run_id: str,
) -> tuple[int, str, bool, str, bool]:
    engine = create_database_engine(settings)
    try:
        session_factory = create_session_factory(engine)
        async with session_factory() as session:
            result_repository = ResultRepository(session)
            original = await result_repository.load_latest_result_bundle(
                UUID(original_run_id)
            )
            refined = await result_repository.load_latest_result_bundle(
                UUID(refinement_run_id)
            )
            refinement = await RefinementRepository(session).get_for_run(
                UUID(refinement_run_id)
            )
    finally:
        await engine.dispose()

    assert original is not None
    assert refinement is not None
    return (
        original.result_version.version,
        original.recommendation_bundle.no_strong_buy_reason or "",
        refined is None,
        refinement.instruction,
        (await _load_plan_for_run(settings, refinement_run_id)) is not None,
    )


async def _load_plan_for_run(settings: Settings, run_id: str) -> object | None:
    engine = create_database_engine(settings)
    try:
        async with create_session_factory(engine)() as session:
            return await RefinementRepository(session).get_plan_for_run(UUID(run_id))
    finally:
        await engine.dispose()


def test_create_refinement_requires_an_existing_result(
    refinement_api_client: TestClient,
) -> None:
    session_id = create_session(refinement_api_client)

    response = refinement_api_client.post(
        f"/api/sessions/{session_id}/refinements",
        json={
            "instruction": "Tighten the budget and prioritize noise cancellation.",
            "budget": {
                "amount": {"amount": "200.00", "currency": "USD"},
                "mode": "hard_cap",
            },
            "preferences": [
                {
                    "text": "Prefer strong active noise cancellation.",
                    "mode": "soft",
                }
            ],
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "refinement_requires_result"


def test_refinement_run_result_version_does_not_overwrite_original(
    refinement_api_client: TestClient,
) -> None:
    session_id = create_session(refinement_api_client)
    original_run_id = create_run(refinement_api_client, session_id)
    original_result = make_fixture_recommendation("Original result remains saved.")
    asyncio.run(
        save_fixture_result(
            refinement_api_client.app.state.settings,
            original_run_id,
            original_result,
        )
    )

    refinement_response = refinement_api_client.post(
        f"/api/sessions/{session_id}/refinements",
        json={"instruction": "Prefer cheaper options."},
    )
    assert refinement_response.status_code == 201
    body = refinement_response.json()
    refinement_run_id = body["run"]["run_id"]
    assert body["run"]["status"] == "pending"
    assert body["plan"]["prior_run_id"] == original_run_id
    assert body["plan"]["prior_result_version_id"]
    assert body["plan"]["stages"] == [
        "re_intake",
        "search",
        "extraction",
        "analysis",
        "result_mode",
    ]
    loaded = refinement_api_client.get(
        f"/api/sessions/{session_id}/refinements/{body['refinement']['refinement_id']}/plan"
    )
    assert loaded.status_code == 200
    assert loaded.json() == body["plan"]
    other_session_id = create_session(refinement_api_client)
    denied = refinement_api_client.get(
        f"/api/sessions/{other_session_id}/refinements/{body['refinement']['refinement_id']}/plan"
    )
    assert denied.status_code == 404

    original_version, original_reason, new_result_missing, instruction, plan_saved = (
        asyncio.run(
            load_result_version_and_refinement(
                refinement_api_client.app.state.settings,
                original_run_id,
                refinement_run_id,
            )
        )
    )

    assert original_version == 2
    assert original_reason == "Original result remains saved."
    assert new_result_missing
    assert instruction == "Prefer cheaper options."
    assert plan_saved


def test_create_refinement_rejects_missing_session(
    refinement_api_client: TestClient,
) -> None:
    response = refinement_api_client.post(
        "/api/sessions/00000000-0000-4000-8000-000000000000/refinements",
        json={"instruction": "Prefer cheaper options."},
    )

    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "session_not_found"


def test_budget_and_mode_plans_reuse_saved_candidate_evidence(
    refinement_api_client: TestClient,
) -> None:
    session_id = create_session(refinement_api_client)
    original_run_id = create_run(refinement_api_client, session_id)
    settings = refinement_api_client.app.state.settings
    asyncio.run(add_product_evidence(settings, original_run_id))

    budget_response = refinement_api_client.post(
        f"/api/sessions/{session_id}/refinements",
        json={
            "instruction": "Use a lower budget.",
            "budget": {
                "amount": {"amount": "150", "currency": "USD"},
                "mode": "hard_cap",
            },
        },
    )
    assert budget_response.status_code == 201
    budget_plan = budget_response.json()["plan"]
    assert budget_plan["stages"] == ["analysis", "result_mode"]
    assert (
        next(
            row["disposition"]
            for row in budget_plan["artifacts"]
            if row["artifact"] == "source_evidence"
        )
        == "reused"
    )
    assert (
        refinement_api_client.get(f"/api/sessions/{session_id}/results").json()[
            "result_version"
        ]["run_id"]
        == original_run_id
    )

    mode_response = refinement_api_client.post(
        f"/api/sessions/{session_id}/refinements",
        json={"instruction": "Show value first.", "result_mode": "best_value"},
    )
    assert mode_response.status_code == 201
    assert mode_response.json()["plan"]["stages"] == ["result_mode"]
    assert mode_response.json()["plan"]["requested_result_mode"] == "best_value"


def test_budget_execution_reuses_research_and_keeps_prior_version(
    refinement_api_client: TestClient,
) -> None:
    session_id = create_session(refinement_api_client)
    original_run_id = create_run(refinement_api_client, session_id)
    asyncio.run(
        add_product_evidence(refinement_api_client.app.state.settings, original_run_id)
    )
    original = refinement_api_client.get(f"/api/sessions/{session_id}/results").json()
    response = refinement_api_client.post(
        f"/api/sessions/{session_id}/refinements",
        json={
            "instruction": "Keep the price below $150.",
            "budget": {
                "amount": {"amount": "150", "currency": "USD"},
                "mode": "hard_cap",
            },
        },
    )
    assert response.status_code == 201
    body = response.json()
    refinement_id = body["refinement"]["refinement_id"]
    run_id = body["run"]["run_id"]
    executed = refinement_api_client.post(
        f"/api/sessions/{session_id}/refinements/{refinement_id}/execute"
    )
    assert executed.status_code == 200
    assert executed.json()["status"] == "succeeded"
    events = refinement_api_client.get(
        f"/api/sessions/{session_id}/runs/{run_id}/events"
    ).text
    assert '"stage":"category_analysis"' in events
    assert '"stage":"verification"' in events
    assert '"stage":"discovery"' not in events
    current = refinement_api_client.get(f"/api/sessions/{session_id}/results").json()
    assert current["result_version"]["run_id"] == run_id
    assert (
        current["result_version"]["version"]
        == original["result_version"]["version"] + 1
    )
    assert current["result_version"]["refinement_id"] == refinement_id
    assert (
        current["result_version"]["prior_result_version_id"]
        == original["result_version"]["result_version_id"]
    )
    assert current["products"] == original["products"]
    previous = refinement_api_client.get(
        f"/api/sessions/{session_id}/results/{original['result_version']['result_version_id']}"
    )
    assert previous.status_code == 200
    assert previous.json()["result_version"]["run_id"] == original_run_id
    other_session = create_session(refinement_api_client)
    assert (
        refinement_api_client.get(
            f"/api/sessions/{other_session}/results/{original['result_version']['result_version_id']}"
        ).status_code
        == 404
    )
    assert (
        refinement_api_client.post(
            f"/api/sessions/{session_id}/refinements/{refinement_id}/execute"
        ).status_code
        == 409
    )


def test_category_execution_runs_research(
    refinement_api_client: TestClient,
) -> None:
    session_id = create_session(refinement_api_client)
    create_run(refinement_api_client, session_id)
    original = refinement_api_client.get(f"/api/sessions/{session_id}/results").json()
    response = refinement_api_client.post(
        f"/api/sessions/{session_id}/refinements",
        json={"instruction": "Look for a monitor instead.", "category": "monitor"},
    )
    assert response.status_code == 201
    body = response.json()
    assert "search" in body["plan"]["stages"]
    executed = refinement_api_client.post(
        f"/api/sessions/{session_id}/refinements/{body['refinement']['refinement_id']}/execute"
    )
    assert executed.status_code == 200
    assert executed.json()["status"] == "succeeded"
    events = refinement_api_client.get(
        f"/api/sessions/{session_id}/runs/{body['run']['run_id']}/events"
    ).text
    assert '"stage":"discovery"' in events
    assert '"stage":"extraction"' in events
    current = refinement_api_client.get(f"/api/sessions/{session_id}/results").json()
    assert current["result_version"]["run_id"] == body["run"]["run_id"]
    assert (
        current["result_version"]["version"]
        == original["result_version"]["version"] + 1
    )


def test_region_execution_runs_research(
    refinement_api_client: TestClient,
) -> None:
    session_id = create_session(refinement_api_client)
    create_run(refinement_api_client, session_id)
    response = refinement_api_client.post(
        f"/api/sessions/{session_id}/refinements",
        json={
            "instruction": "Check availability in Canada.",
            "region": {"region": {"country_code": "CA"}, "source": "user_provided"},
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert "search" in body["plan"]["stages"]
    executed = refinement_api_client.post(
        f"/api/sessions/{session_id}/refinements/{body['refinement']['refinement_id']}/execute"
    )
    assert executed.status_code == 200
    events = refinement_api_client.get(
        f"/api/sessions/{session_id}/runs/{body['run']['run_id']}/events"
    ).text
    assert '"stage":"discovery"' in events


def test_failed_recomputation_keeps_previous_result(
    refinement_api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.orchestration.shopping_runs import ShoppingRunOrchestrator
    from app.schemas.runs import RunStage

    session_id = create_session(refinement_api_client)
    original_run_id = create_run(refinement_api_client, session_id)
    original = refinement_api_client.get(f"/api/sessions/{session_id}/results").json()
    response = refinement_api_client.post(
        f"/api/sessions/{session_id}/refinements",
        json={"instruction": "Try a monitor.", "category": "monitor"},
    )
    assert response.status_code == 201
    body = response.json()
    original_stage = ShoppingRunOrchestrator._run_stage

    async def failing_stage(
        self: ShoppingRunOrchestrator, context: object, definition: object
    ) -> None:
        if definition.stage == RunStage.DISCOVERY:  # type: ignore[attr-defined]
            raise RuntimeError("fixture discovery failed")
        await original_stage(self, context, definition)  # type: ignore[arg-type]

    monkeypatch.setattr(ShoppingRunOrchestrator, "_run_stage", failing_stage)
    executed = refinement_api_client.post(
        f"/api/sessions/{session_id}/refinements/{body['refinement']['refinement_id']}/execute"
    )
    assert executed.status_code == 200
    assert executed.json()["status"] == "failed"
    assert (
        refinement_api_client.get(
            f"/api/sessions/{session_id}/runs/{body['run']['run_id']}"
        ).json()["status"]
        == "failed"
    )
    current = refinement_api_client.get(f"/api/sessions/{session_id}/results").json()
    assert current["result_version"]["run_id"] == original_run_id
    assert (
        current["result_version"]["result_version_id"]
        == original["result_version"]["result_version_id"]
    )


def test_consecutive_refinements_follow_saved_research(
    refinement_api_client: TestClient,
) -> None:
    session_id = create_session(refinement_api_client)
    original_run_id = create_run(refinement_api_client, session_id)
    asyncio.run(
        add_product_evidence(refinement_api_client.app.state.settings, original_run_id)
    )
    first = refinement_api_client.post(
        f"/api/sessions/{session_id}/refinements",
        json={
            "instruction": "Use a $150 hard cap.",
            "budget": {
                "amount": {"amount": "150", "currency": "USD"},
                "mode": "hard_cap",
            },
        },
    ).json()
    assert (
        refinement_api_client.post(
            f"/api/sessions/{session_id}/refinements/{first['refinement']['refinement_id']}/execute"
        ).json()["status"]
        == "succeeded"
    )
    second_response = refinement_api_client.post(
        f"/api/sessions/{session_id}/refinements",
        json={"instruction": "Show best value.", "result_mode": "best_value"},
    )
    assert second_response.status_code == 201
    second = second_response.json()
    assert second["plan"]["stages"] == ["result_mode"]
    assert second["plan"]["base_brief"]["budget"]["amount"]["amount"] == "150"
    assert (
        refinement_api_client.post(
            f"/api/sessions/{session_id}/refinements/{second['refinement']['refinement_id']}/execute"
        ).json()["status"]
        == "succeeded"
    )
    events = refinement_api_client.get(
        f"/api/sessions/{session_id}/runs/{second['run']['run_id']}/events"
    ).text
    assert '"stage":"category_analysis"' not in events
    assert '"stage":"discovery"' not in events
    current = refinement_api_client.get(f"/api/sessions/{session_id}/results").json()
    assert current["result_version"]["version"] == 3
    assert current["result_version"]["requested_result_mode"] == "best_value"
    assert current["products"]
    prior = refinement_api_client.get(
        f"/api/sessions/{session_id}/results/{second['plan']['prior_result_version_id']}"
    ).json()
    assert current["comparison_matrix"] == prior["comparison_matrix"]


def test_earlier_result_keeps_considered_product_outcome_after_later_correction(
    refinement_api_client: TestClient,
) -> None:
    session_id = create_session(refinement_api_client)
    first_run_id = create_run(refinement_api_client, session_id)
    first_version_id = refinement_api_client.get(
        f"/api/sessions/{session_id}/results"
    ).json()["result_version"]["result_version_id"]
    second_run_id = create_run(refinement_api_client, session_id)
    settings = refinement_api_client.app.state.settings

    async def save_candidate_outcomes() -> None:
        engine = create_database_engine(settings)
        try:
            async with create_session_factory(engine)() as session:
                repository = ProductRepository(session)
                first = UserAddedProduct(input_text="Model A")
                await repository.add_user_added_product(
                    UUID(session_id), first, run_id=UUID(first_run_id)
                )
                await repository.update_user_added_product_for_run(
                    UUID(session_id),
                    first.model_copy(update={"input_text": "Model B"}),
                    run_id=UUID(second_run_id),
                )
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(save_candidate_outcomes())
    old = refinement_api_client.get(
        f"/api/sessions/{session_id}/results/{first_version_id}"
    ).json()
    current = refinement_api_client.get(f"/api/sessions/{session_id}/results").json()
    assert old["considered_products"][0]["candidate"]["input_text"] == "Model A"
    assert current["considered_products"][0]["candidate"]["input_text"] == "Model B"


def test_decision_history_preserves_context_and_excludes_pending_changes(
    refinement_api_client: TestClient,
) -> None:
    client = refinement_api_client
    session_id = create_session(client)
    assert client.get(f"/api/sessions/{session_id}/results/history").json()["versions"] == []
    create_run(client, session_id)
    initial = client.get(f"/api/sessions/{session_id}").json()["current_brief"]
    planned = client.post(
        f"/api/sessions/{session_id}/refinements",
        json={"instruction": "Compare monitors instead.", "category": "monitor"},
    ).json()
    history = client.get(f"/api/sessions/{session_id}/results/history").json()
    assert history["original_query"] == "Need quiet headphones"
    assert len(history["versions"]) == 1
    assert history["versions"][0]["brief"] == initial
    assert history["versions"][0]["change"] is None
    executed = client.post(
        f"/api/sessions/{session_id}/refinements/{planned['refinement']['refinement_id']}/execute"
    )
    assert executed.json()["status"] == "succeeded"
    history = client.get(f"/api/sessions/{session_id}/results/history").json()
    assert len(history["versions"]) == 2
    assert history["versions"][0]["brief"] == initial
    assert history["versions"][1]["brief"]["category"] == "monitor"
    assert history["versions"][1]["change"] == "Compare monitors instead."
    for entry in history["versions"]:
        saved = client.get(
            f"/api/sessions/{session_id}/results/{entry['result_version_id']}"
        )
        assert saved.status_code == 200
        assert saved.json()["result_version"]["version"] == entry["version"]
    other = create_session(client)
    assert client.get(f"/api/sessions/{other}/results/history").json()["versions"] == []
    assert client.get(f"/api/sessions/{new_id()}/results/history").status_code == 404


def test_preference_execution_saves_history_without_changing_original_context(
    refinement_api_client: TestClient,
) -> None:
    client = refinement_api_client
    session_id = create_session(client)
    create_run(client, session_id)
    original = client.get(f"/api/sessions/{session_id}/results/history").json()
    planned = client.post(
        f"/api/sessions/{session_id}/refinements",
        json={
            "instruction": "Prioritize easy returns.",
            "preferences": [{"text": "easy returns", "mode": "soft", "source": "user_provided"}],
        },
    ).json()
    assert "search" in planned["plan"]["stages"]
    assert client.post(
        f"/api/sessions/{session_id}/refinements/{planned['refinement']['refinement_id']}/execute"
    ).json()["status"] == "succeeded"
    history = client.get(f"/api/sessions/{session_id}/results/history").json()
    assert history["versions"][0] == original["versions"][0]
    assert history["versions"][1]["brief"]["preferences"][-1]["text"] == "easy returns"
