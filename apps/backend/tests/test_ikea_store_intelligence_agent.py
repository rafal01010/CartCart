from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
from agents import Agent

from app.agents.contracts import IKEAStoreIntelligenceAgentInput
from app.agents.ikea_regional_tools import IKEARegionalStoreTools
from app.agents.live_ikea_store_intelligence import (
    IKEAProductIdentity,
    IKEAStoreIntelligenceAgent,
    IKEAStoreModelOutput,
    MockIKEAStoreModelRunner,
    OpenAIAgentsSDKIKEAStoreModelRunner,
    SelectedIKEARegionalSource,
    _supported_fields,
)
from app.agents.workbench import (
    _WorkbenchIKEAStoreIntelligenceProvider,
    _scenario_ikea_available_regional_product,
    _scenario_ikea_no_regional_presence,
)
from app.core.settings import Settings
from app.providers import FakeIKEAStoreIntelligenceProvider, TavilySearchProvider
from app.providers.fixtures import load_provider_fixture, provider_fixture_transport
from app.providers.ikea import IKEARegionalStoreDiscoveryProvider
from app.schemas.ids import new_id
from app.schemas.money import Money
from app.schemas.search_sources import (
    ExtractedPageContent,
    ExtractionStatus,
    IKEAEvidenceFactType,
    ProviderMetadata,
    SearchQuery,
    SearchResult,
    SourceSnapshot,
    SourceType,
)


def _input() -> IKEAStoreIntelligenceAgentInput:
    return IKEAStoreIntelligenceAgentInput.model_validate(
        _scenario_ikea_available_regional_product().input
    )


def _agent(runner: Any) -> IKEAStoreIntelligenceAgent:
    return IKEAStoreIntelligenceAgent(
        settings=Settings(_env_file=None),  # type: ignore[call-arg]
        ikea_provider=_WorkbenchIKEAStoreIntelligenceProvider(),
        model_runner=runner,
    )


@dataclass
class _SelectingRunner:
    source_id_override: str | None = None
    skip_read: bool = False
    identity: IKEAProductIdentity = IKEAProductIdentity.MATCH
    price: Money | None = None
    calls: int = 0

    async def run(
        self,
        agent: Agent[Any],
        model_input: str,
        *,
        run_config: Any,
        max_turns: int,
        tools: IKEARegionalStoreTools,
    ) -> Any:
        del model_input, run_config, max_turns
        self.calls += 1
        assert agent.name == "IKEAStoreIntelligenceAgent"
        assert {tool.name for tool in agent.tools} == {
            "search_ikea_products",
            "read_ikea_product",
        }
        product_id = str(tools.input_data.products[0].product_id)
        found = await tools.search(product_id)
        source_id = found["sources"][0]["source_id"]
        if not self.skip_read:
            await tools.read(source_id)
        return type(
            "Result",
            (),
            {
                "final_output": IKEAStoreModelOutput(
                    selected_sources=(
                        SelectedIKEARegionalSource(
                            product_id=tools.input_data.products[0].product_id,
                            source_id=self.source_id_override or source_id,
                            identity=self.identity,
                            identity_reason="Recorded official-region identity assessment.",
                            product_name="MICKE desk, white",
                            product_code="902.143.08",
                            price=self.price or Money(amount="3990", currency="PHP"),
                            availability="available",
                            store_name="IKEA Pasay City",
                            delivery_area="Available for delivery in Metro Manila.",
                        ),
                    ),
                )
            },
        )()


@pytest.mark.asyncio
async def test_model_interprets_read_official_regional_source() -> None:
    runner = _SelectingRunner()
    output = await _agent(runner).run(_input())
    assert runner.calls == 1
    assert len(output.store_contexts) == 1
    context = output.store_contexts[0]
    assert context.country_code == "PH"
    assert context.price == Money(amount="3990", currency="PHP")
    assert context.availability.value == "available"
    assert str(context.official_url).startswith("https://ikea.com/ph/en/p/")
    assert {item.fact_type for item in output.evidence} >= {
        IKEAEvidenceFactType.OFFICIAL_PRODUCT_FACT,
        IKEAEvidenceFactType.REGIONAL_PRICE,
        IKEAEvidenceFactType.REGIONAL_AVAILABILITY,
        IKEAEvidenceFactType.STORE_DELIVERY_CONTEXT,
    }
    assert all(item.source_id == context.source_id for item in output.evidence)
    assert all(
        "shipping elsewhere" in " ".join(item.evidence_quality_warnings)
        for item in output.evidence
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("unknown_id,skip_read", [(True, False), (False, True)])
async def test_unknown_or_unread_source_is_rejected(
    unknown_id: bool, skip_read: bool
) -> None:
    runner = _SelectingRunner(
        source_id_override=str(new_id()) if unknown_id else None,
        skip_read=skip_read,
    )
    output = await _agent(runner).run(_input())
    assert output.evidence == ()
    assert output.evidence_gaps


@pytest.mark.asyncio
async def test_fabricated_price_and_model_failure_yield_only_gaps() -> None:
    fabricated = await _agent(
        _SelectingRunner(price=Money(amount="1", currency="USD"))
    ).run(_input())
    failed = await _agent(
        MockIKEAStoreModelRunner(error=RuntimeError("model unavailable"))
    ).run(_input())
    assert fabricated.evidence == ()
    assert failed.evidence == ()
    assert fabricated.evidence_gaps and failed.evidence_gaps


def test_available_claim_cannot_use_negated_delivery_text() -> None:
    selected = SelectedIKEARegionalSource(
        product_id=_input().products[0].product_id,
        source_id=new_id(),
        identity=IKEAProductIdentity.MATCH,
        identity_reason="Fixture",
        availability="available",
    )
    with pytest.raises(ValueError, match="availability"):
        _supported_fields(
            selected,
            "MICKE desk is not available for delivery in this region.",
            "https://ikea.com/ph/en/p/micke-desk-90214308/",
            "PH",
        )


@pytest.mark.asyncio
async def test_ambiguous_identity_does_not_become_product_or_region_fact() -> None:
    output = await _agent(_SelectingRunner(identity=IKEAProductIdentity.AMBIGUOUS)).run(
        _input()
    )
    assert output.evidence == ()
    assert output.store_contexts == ()
    assert output.evidence_gaps


@pytest.mark.asyncio
async def test_unsupported_region_returns_explicit_region_gap() -> None:
    input_data = IKEAStoreIntelligenceAgentInput.model_validate(
        _scenario_ikea_no_regional_presence().input
    )
    output = await _agent(MockIKEAStoreModelRunner()).run(input_data)
    assert output.source_references == ()
    assert output.evidence == ()
    assert output.evidence_gaps[0].target.region_code == "AQ"
    assert "No supported IKEA regional presence" in output.evidence_gaps[0].reason


@pytest.mark.asyncio
async def test_tool_rejects_unknown_ids_budgets_and_unsupported_region() -> None:
    tools = IKEARegionalStoreTools(
        _input(), _WorkbenchIKEAStoreIntelligenceProvider(), max_searches=0
    )
    assert (await tools.search(str(new_id())))["status"] == "unknown_product"
    assert (await tools.search(str(tools.input_data.products[0].product_id)))[
        "status"
    ] == "budget_exhausted"
    assert (await tools.read(str(new_id())))["status"] == "unknown_source"
    unsupported = IKEAStoreIntelligenceAgentInput.model_validate(
        _scenario_ikea_no_regional_presence().input
    )
    tools = IKEARegionalStoreTools(
        unsupported, _WorkbenchIKEAStoreIntelligenceProvider()
    )
    assert (await tools.search(str(unsupported.products[0].product_id)))[
        "status"
    ] == "unsupported_region"


@pytest.mark.asyncio
async def test_tool_rejects_nonofficial_cross_region_and_excluded_snapshots() -> None:
    good = SourceSnapshot(
        url="https://www.ikea.com/ph/en/p/micke-desk-white-90214308/",
        source_type=SourceType.OFFICIAL_BRAND_PAGE,
        provider=ProviderMetadata(provider_name="fixture"),
        extraction_status=ExtractionStatus.SUCCEEDED,
        extracted_content=ExtractedPageContent(
            text="MICKE desk, white. PHP 3990. Available for delivery in Metro Manila.",
            extractor="fixture",
            word_count=10,
        ),
    )
    excluded = good.model_copy(
        update={"source_id": new_id(), "extraction_status": ExtractionStatus.EXCLUDED}
    )
    cross_region = good.model_copy(
        update={
            "source_id": new_id(),
            "url": "https://www.ikea.com/us/en/p/micke-desk-white-90214308/",
        }
    )
    hostile = good.model_copy(
        update={
            "source_id": new_id(),
            "url": "https://ikea.com.evil.example/ph/en/p/micke-desk-white-90214308/",
        }
    )
    input_data = _input().model_copy(
        update={"source_snapshots": (good, excluded, cross_region, hostile)}
    )
    tools = IKEARegionalStoreTools(
        input_data, FakeIKEAStoreIntelligenceProvider(disabled=True)
    )
    found = await tools.search(str(input_data.products[0].product_id))
    assert any(item["source_id"] == str(good.source_id) for item in found["sources"])
    assert (await tools.read(str(good.source_id)))["status"] == "ok"
    for item in (excluded, cross_region, hostile):
        assert (await tools.read(str(item.source_id)))["status"] == "unknown_source"


@pytest.mark.asyncio
async def test_recorded_tavily_candidates_reach_agent_without_name_gate() -> None:
    fixture = load_provider_fixture(
        Path(__file__).parent / "fixtures" / "providers" / "ikea_available.json"
    )
    async with httpx.AsyncClient(
        transport=provider_fixture_transport(fixture)
    ) as client:
        provider = IKEARegionalStoreDiscoveryProvider(
            search_provider=TavilySearchProvider(
                api_key="recorded-test-key", client=client
            )
        )
        tools = IKEARegionalStoreTools(_input(), provider)
        found = await tools.search(str(tools.input_data.products[0].product_id))
        assert found["status"] == "succeeded"
        assert len(found["sources"]) == 1
        read = await tools.read(found["sources"][0]["source_id"])
    assert read["status"] == "ok"
    assert read["region"] == "PH"
    assert "utm_source" not in read["source_reference"]["url"]
    assert "PHP 3990" in read["text"]


@pytest.mark.asyncio
async def test_candidate_search_keeps_official_unmatched_title_for_model() -> None:
    class Search:
        async def search(
            self, query: SearchQuery, options: Any = None
        ) -> tuple[SearchResult, ...]:
            return (
                SearchResult(
                    query=query,
                    url="https://www.ikea.com/ph/en/p/other-desk-12345678/",
                    title="Different IKEA product",
                    snippet="PHP 4990",
                    provider=ProviderMetadata(provider_name="fixture"),
                ),
            )

    provider = IKEARegionalStoreDiscoveryProvider(search_provider=Search())
    candidates = await provider.search_product_candidates(
        _input().products[0], region_code="PH"
    )
    assert candidates[0].title == "Different IKEA product"


@pytest.mark.asyncio
async def test_sdk_runner_calls_openai_agents_sdk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    async def fake_run(agent: Any, model_input: Any, **kwargs: Any) -> object:
        calls.append((agent, model_input, kwargs))
        return object()

    monkeypatch.setattr("app.agents.live_ikea_store_intelligence.Runner.run", fake_run)
    runner = OpenAIAgentsSDKIKEAStoreModelRunner()
    await runner.run(
        Agent(name="fixture", instructions="fixture"),
        "fixture",
        run_config=None,
        max_turns=3,
        tools=IKEARegionalStoreTools(
            _input(), _WorkbenchIKEAStoreIntelligenceProvider()
        ),
    )  # type: ignore[arg-type]
    assert calls[0][2]["max_turns"] == 3
