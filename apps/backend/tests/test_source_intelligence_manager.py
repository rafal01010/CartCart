"""Task 89O: parent SDK agent-tools over two real source specialists, offline."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from agents import Runner
from agents.tool_context import ToolContext

from app.agents.catalog import DEFAULT_AGENT_CATALOG, InvocationMode
from app.agents.contracts import IKEAStoreIntelligenceAgentInput
from app.agents.live_amazon_product_intelligence import (
    AmazonProductModelOutput,
    MarketplaceIdentity,
    SelectedMarketplaceSource,
)
from app.agents.live_ikea_store_intelligence import (
    IKEAProductIdentity,
    IKEAStoreModelOutput,
    SelectedIKEARegionalSource,
)
from app.agents.live_source_intelligence_manager import (
    SkippedSource,
    SourceIntelligenceManagerAgent,
    SourceManagerDecision,
    SourceManagerInput,
)
from app.agents.workbench import (
    _WorkbenchAmazonProductIntelligenceProvider,
    _WorkbenchIKEAStoreIntelligenceProvider,
    _scenario_ikea_available_regional_product,
)
from app.core.settings import Settings
from app.core.settings import AgentWorkflowMode
from app.db.base import Base
from app.db.repositories.products import ProductRepository
from app.db.repositories.results import ResultRepository
from app.db.repositories.runs import RunRepository
from app.db.repositories.search_sources import SearchSourceRepository
from app.db.repositories.sessions import SessionRepository
from app.db.repositories.source_intelligence import SourceIntelligenceRepository
from app.db.repositories.video_sources import VideoReviewRepository
from app.db.session import create_database_engine, create_session_factory
from app.orchestration.shopping_runs import (
    RepositoryShoppingRunPersistenceHooks,
    ShoppingRunContext,
    ShoppingRunOrchestrator,
    SourceIntelligenceCandidates,
    SourceIntelligenceRunOutput,
)
from app.schemas.intake import CreateSessionRequest
from app.schemas.search_sources import (
    ReusableSourceIntelligenceRequest,
    SourceIntelligenceCapability,
    SourceIntelligenceCapabilityDescriptor,
)
import app.db.models  # noqa: F401


async def _invoke(tool: Any, payload: dict[str, str]) -> Any:
    arguments = json.dumps(payload)
    return await tool.on_invoke_tool(
        ToolContext(
            context=None,
            tool_name=tool.name,
            tool_call_id="mock-call",
            tool_arguments=arguments,
        ),
        arguments,
    )


@dataclass
class _ParentRunner:
    calls: int = 0

    async def run(
        self, agent: Any, model_input: str, *, run_config: Any, max_turns: int
    ) -> Any:
        del model_input, run_config, max_turns
        self.calls += 1
        assert agent.name == "SourceIntelligenceManagerAgent"
        by_name = {tool.name: tool for tool in agent.tools}
        assert len(by_name) == 4
        for name in (
            "consult_amazon_product_listing_review",
            "consult_ikea_regional_official_store",
        ):
            output = await _invoke(by_name[name], {"input": "Relevant to this desk"})
            assert json.loads(output)["bundle"]["source_references"]
        return type(
            "Result",
            (),
            {
                "final_output": SourceManagerDecision(
                    skipped_sources=(
                        SkippedSource(
                            capability=SourceIntelligenceCapability.VIDEO_REVIEW,
                            reason="No review-video need for this official desk check.",
                        ),
                        SkippedSource(
                            capability=SourceIntelligenceCapability.COMMUNITY_DISCUSSION,
                            reason="No owner-discussion need for this availability check.",
                        ),
                    ),
                    summary="Marketplace and official-region evidence checked.",
                )
            },
        )()


@pytest.mark.asyncio
async def test_parent_invokes_two_sdk_agent_tools_and_preserves_cited_bundles(
    monkeypatch: Any, tmp_path: Path
) -> None:
    nested_names: list[str] = []

    async def nested_run(*, starting_agent: Any, input: str, **kwargs: Any) -> Any:
        del kwargs
        agent = starting_agent
        model_input = input
        nested_names.append(agent.name)
        context = json.loads(model_input)
        product_id = context["products"][0]["product_id"]
        by_name = {tool.name: tool for tool in agent.tools}
        if agent.name == "AmazonProductIntelligenceAgent":
            found = json.loads(
                await _invoke(
                    by_name["search_amazon_products"], {"product_id": product_id}
                )
            )
            source_id = found["sources"][0]["source_id"]
            read = json.loads(
                await _invoke(by_name["read_amazon_product"], {"source_id": source_id})
            )
            output = AmazonProductModelOutput(
                selected_sources=(
                    SelectedMarketplaceSource(
                        product_id=product_id,
                        source_id=read["source_reference"]["source_id"],
                        identity=MarketplaceIdentity.MATCH,
                        identity_reason="Recorded fixture identity match.",
                        selected_evidence_ids=tuple(
                            item["evidence_id"] for item in read["provider_evidence"]
                        ),
                    ),
                )
            )
        else:
            assert agent.name == "IKEAStoreIntelligenceAgent"
            found = json.loads(
                await _invoke(
                    by_name["search_ikea_products"], {"product_id": product_id}
                )
            )
            source_id = found["sources"][0]["source_id"]
            await _invoke(by_name["read_ikea_product"], {"source_id": source_id})
            output = IKEAStoreModelOutput(
                selected_sources=(
                    SelectedIKEARegionalSource(
                        product_id=product_id,
                        source_id=source_id,
                        identity=IKEAProductIdentity.MATCH,
                        identity_reason="Recorded official fixture identity match.",
                        product_name="MICKE desk, white",
                    ),
                )
            )
        return type("NestedResult", (), {"final_output": output})()

    monkeypatch.setattr(Runner, "run", nested_run)
    scenario = _scenario_ikea_available_regional_product()
    payload = IKEAStoreIntelligenceAgentInput.model_validate(scenario.input)
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        openai_run_profiles={
            "fast": {"model": "mock-fast-model"},
            "strong": {"model": "mock-strong-model"},
        },
    )
    runner = _ParentRunner()
    manager = SourceIntelligenceManagerAgent(
        settings=settings,
        amazon_provider=_WorkbenchAmazonProductIntelligenceProvider(),
        ikea_provider=_WorkbenchIKEAStoreIntelligenceProvider(),
        model_runner=runner,
    )
    result = await manager.run(
        SourceManagerInput(
            run_id=payload.run_id,
            brief=payload.brief,
            products=payload.products,
            listings=payload.listings,
            source_snapshots=(),
            query_hints=("MICKE desk",),
            region_code="PH",
            allowed_capabilities=tuple(SourceIntelligenceCapability),
        )
    )
    assert runner.calls == 1, (result.notes, result.activity)
    assert nested_names == [
        "AmazonProductIntelligenceAgent",
        "IKEAStoreIntelligenceAgent",
    ], (result.notes, result.activity)
    assert result.amazon_bundles[0].evidence
    assert result.ikea_bundles[0].evidence
    assert all(
        item.source_id
        in {ref.source_id for ref in result.amazon_bundles[0].source_references}
        for item in result.amazon_bundles[0].evidence
    )
    assert any("video_review skipped" in note for note in result.notes)
    assert (
        len([item for item in result.activity if item["tool_name"] == "agent_as_tool"])
        == 2
    )
    assert result.model_name == "mock-strong-model"
    assert {
        item["input"]["model"]
        for item in result.activity
        if item["tool_name"] == "agent_as_tool"
    } == {"mock-fast-model"}

    # The existing repository boundary must persist the validated nested bundles,
    # retaining source/evidence relationships used by downstream stages.
    db_settings = Settings(
        _env_file=None, database_path=tmp_path / "delegation.sqlite3"
    )  # type: ignore[call-arg]
    engine = create_database_engine(db_settings)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        session_factory = create_session_factory(engine)
        async with session_factory() as db_session:
            request = CreateSessionRequest(query=payload.brief.original_query)
            session = await SessionRepository(db_session).create(
                original_input=request, current_brief=payload.brief
            )
            run = await RunRepository(db_session).create(session.session_id)
            hooks = RepositoryShoppingRunPersistenceHooks(
                run_repository=RunRepository(db_session),
                result_repository=ResultRepository(db_session),
                search_source_repository=SearchSourceRepository(db_session),
                product_repository=ProductRepository(db_session),
                source_intelligence_repository=SourceIntelligenceRepository(db_session),
                video_review_repository=VideoReviewRepository(db_session),
            )
            orchestrator = ShoppingRunOrchestrator(
                hooks,
                agent_workflow_mode=AgentWorkflowMode.LIVE,
                source_intelligence_manager=manager,
            )
            context = ShoppingRunContext(
                run_id=run.run_id,
                session_id=session.session_id,
                trace_id="mock-parent-trace",
                active_brief=payload.brief,
            )
            source_request = ReusableSourceIntelligenceRequest(
                brief=payload.brief,
                target_region_code="PH",
                product_ids=(payload.products[0].product_id,),
                requested_capabilities=tuple(SourceIntelligenceCapability),
                allowed_capabilities=tuple(
                    SourceIntelligenceCapabilityDescriptor(capability=capability)
                    for capability in SourceIntelligenceCapability
                ),
            )

            class _RecordedManager:
                async def run(self, input_data: Any) -> Any:
                    assert input_data.products == payload.products
                    return result

            orchestrator._source_intelligence_manager = _RecordedManager()  # type: ignore[assignment]
            stage = await orchestrator._run_agent_source_intelligence(
                context,
                payload.brief,
                "PH",
                SourceIntelligenceCandidates(
                    products=payload.products, listings=payload.listings
                ),
                source_request,
            )
            await db_session.commit()
            assert stage.agent_name == "SourceIntelligenceManagerAgent"
            assert stage.model_name == result.model_name
            assert stage.runtime_mode == "live"
            assert context.source_intelligence == SourceIntelligenceRunOutput(
                request=source_request,
                amazon_bundles=result.amazon_bundles,
                ikea_bundles=result.ikea_bundles,
                notes=result.notes,
            )
        async with session_factory() as db_session:
            repo = SourceIntelligenceRepository(db_session)
            assert await repo.list_amazon_evidence(run.run_id)
            assert await repo.list_ikea_evidence(run.run_id)
    finally:
        await engine.dispose()


def test_source_catalog_exposes_real_manager_delegation() -> None:
    manager = DEFAULT_AGENT_CATALOG.require("SourceIntelligenceManagerAgent")
    assert manager.invocation_mode == InvocationMode.TYPED_STEP
    assert len(manager.approved_sdk_tools) == 4
    for specialist in DEFAULT_AGENT_CATALOG.reusable_source_agents():
        assert specialist.invocation_mode == InvocationMode.REUSABLE_SOURCE_TOOL
        assert specialist.parent_agent_name == manager.agent_name
        assert specialist.agent_as_tool_available


@pytest.mark.asyncio
async def test_parent_model_failure_returns_only_explicit_source_gaps() -> None:
    payload = IKEAStoreIntelligenceAgentInput.model_validate(
        _scenario_ikea_available_regional_product().input
    )

    class _FailingRunner:
        async def run(self, agent: Any, model_input: str, **kwargs: Any) -> Any:
            del agent, model_input, kwargs
            raise RuntimeError("mock model unavailable")

    manager = SourceIntelligenceManagerAgent(
        settings=Settings(_env_file=None),  # type: ignore[call-arg]
        model_runner=_FailingRunner(),
    )
    result = await manager.run(
        SourceManagerInput(
            run_id=payload.run_id,
            brief=payload.brief,
            products=payload.products,
            listings=payload.listings,
            source_snapshots=(),
            query_hints=(),
            region_code="PH",
            allowed_capabilities=(
                SourceIntelligenceCapability.COMMUNITY_DISCUSSION,
                SourceIntelligenceCapability.IKEA_REGIONAL_OFFICIAL_STORE,
            ),
        )
    )
    assert result.community_bundles[0].evidence == ()
    assert result.ikea_bundles[0].evidence == ()
    assert result.community_bundles[0].evidence_gaps
    assert result.ikea_bundles[0].evidence_gaps
    assert result.model_name
    assert result.activity[0]["status"] == "model_or_validation_failure"


@pytest.mark.asyncio
async def test_nested_model_failure_is_recorded_as_a_gap(monkeypatch: Any) -> None:
    payload = IKEAStoreIntelligenceAgentInput.model_validate(
        _scenario_ikea_available_regional_product().input
    )

    async def broken_nested_run(**kwargs: Any) -> Any:
        del kwargs
        raise RuntimeError("mock nested model unavailable")

    class _CallingParent:
        async def run(self, agent: Any, model_input: str, **kwargs: Any) -> Any:
            del model_input, kwargs
            await _invoke(agent.tools[0], {"input": "Check public discussions"})
            raise AssertionError("A failed nested tool must propagate to the manager")

    monkeypatch.setattr(Runner, "run", broken_nested_run)
    manager = SourceIntelligenceManagerAgent(
        settings=Settings(_env_file=None),  # type: ignore[call-arg]
        model_runner=_CallingParent(),
    )
    result = await manager.run(
        SourceManagerInput(
            run_id=payload.run_id,
            brief=payload.brief,
            products=payload.products,
            listings=payload.listings,
            source_snapshots=(),
            query_hints=(),
            region_code="PH",
            allowed_capabilities=(SourceIntelligenceCapability.COMMUNITY_DISCUSSION,),
        )
    )
    assert result.community_bundles[0].evidence == ()
    assert result.community_bundles[0].evidence_gaps
    assert result.activity[0]["output"]["called_specialists"] == [
        "RedditCommunityIntelligenceAgent"
    ]
    assert any(item["status"] == "model_or_provider_failed" for item in result.activity)
