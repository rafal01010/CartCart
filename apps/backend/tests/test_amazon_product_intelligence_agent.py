from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
from agents import Agent, RunConfig

from app.agents.amazon_marketplace_tools import AmazonMarketplaceTools
from app.agents.contracts import AmazonProductIntelligenceAgentInput
from app.agents.live_amazon_product_intelligence import (
    AmazonProductIntelligenceAgent,
    AmazonProductModelOutput,
    MarketplaceIdentity,
    MockAmazonProductModelRunner,
    OpenAIAgentsSDKAmazonProductModelRunner,
    SelectedMarketplaceSource,
)
from app.agents.workbench import (
    _WorkbenchAmazonProductIntelligenceProvider,
    _scenario_amazon_third_party_seller_region_gap,
)
from app.core.settings import Settings
from app.providers import AmazonProductIntelligenceProviderResult
from app.providers.amazon import SerpApiAmazonProductIntelligenceProvider
from app.providers.fixtures import load_provider_fixture, provider_fixture_transport
from app.schemas.products import CanonicalProduct
from app.schemas.ids import new_id
from app.schemas.search_sources import (
    AmazonEvidenceFactType,
    ExtractedPageContent,
    ExtractionStatus,
    ProviderMetadata,
    SourceSnapshot,
    SourceType,
)


def _input() -> AmazonProductIntelligenceAgentInput:
    return AmazonProductIntelligenceAgentInput.model_validate(
        _scenario_amazon_third_party_seller_region_gap().input
    )


def _agent(runner: Any) -> AmazonProductIntelligenceAgent:
    return AmazonProductIntelligenceAgent(
        settings=Settings(_env_file=None),  # type: ignore[call-arg]
        amazon_provider=_WorkbenchAmazonProductIntelligenceProvider(),
        model_runner=runner,
    )


@dataclass
class _SelectingRunner:
    unknown_id: bool = False
    unknown_evidence_id: bool = False
    skip_read: bool = False
    identity: MarketplaceIdentity = MarketplaceIdentity.MATCH
    calls: int = 0

    async def run(
        self,
        agent: Agent[Any],
        model_input: str,
        *,
        run_config: Any,
        max_turns: int,
        tools: AmazonMarketplaceTools,
    ) -> Any:
        del model_input, run_config, max_turns
        self.calls += 1
        assert agent.name == "AmazonProductIntelligenceAgent"
        assert {tool.name for tool in agent.tools} == {
            "complete_research_result",
            "read_research_result",
            "search_amazon_products",
            "read_amazon_product",
        }
        product_id = str(tools.input_data.products[0].product_id)
        result = await tools.search(product_id)
        source_id = result["sources"][0]["source_id"]
        read = await tools.read(source_id) if not self.skip_read else None
        evidence_ids = (
            tuple(item["evidence_id"] for item in read["provider_evidence"])
            if read
            else ()
        )
        if self.unknown_evidence_id:
            evidence_ids = (*evidence_ids, str(new_id()))
        return type(
            "Result",
            (),
            {
                "final_output": AmazonProductModelOutput(
                    selected_sources=(
                        SelectedMarketplaceSource(
                            product_id=tools.input_data.products[0].product_id,
                            source_id=new_id() if self.unknown_id else source_id,
                            identity=self.identity,
                            identity_reason="Fixture identity assessment",
                            selected_evidence_ids=evidence_ids,
                        ),
                    ),
                )
            },
        )()


@pytest.mark.asyncio
async def test_model_selects_read_marketplace_source_and_preserves_seller_boundary() -> (
    None
):
    runner = _SelectingRunner()
    output = await _agent(runner).run(_input())
    assert runner.calls == 1
    assert len(output.listing_contexts) == 1
    context = output.listing_contexts[0]
    assert context.seller_name == "Fixture Deals"
    assert context.ships_to_region is None
    assert "tag=" not in str(context.listing_url)
    assert {item.fact_type for item in output.evidence} >= {
        AmazonEvidenceFactType.LISTING_IDENTITY,
        AmazonEvidenceFactType.SELLER_FULFILLMENT,
        AmazonEvidenceFactType.MARKETPLACE_WARNING,
        AmazonEvidenceFactType.REVIEW_SUMMARY,
    }
    assert all(item.source_id == context.source_id for item in output.evidence)
    assert any(
        "could not be confirmed" in item.summary for item in output.evidence_gaps
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("unknown_id,skip_read", [(True, False), (False, True)])
async def test_unknown_or_unread_source_fails_closed(
    unknown_id: bool, skip_read: bool
) -> None:
    output = await _agent(
        _SelectingRunner(unknown_id=unknown_id, skip_read=skip_read)
    ).run(_input())
    assert output.evidence == ()
    assert output.evidence_gaps


@pytest.mark.asyncio
async def test_fabricated_evidence_id_and_model_failure_return_only_gaps() -> None:
    fabricated = await _agent(_SelectingRunner(unknown_evidence_id=True)).run(_input())
    failed = await _agent(
        MockAmazonProductModelRunner(error=RuntimeError("model unavailable"))
    ).run(_input())
    assert fabricated.evidence == ()
    assert failed.evidence == ()
    assert fabricated.evidence_gaps and failed.evidence_gaps


@pytest.mark.asyncio
async def test_ambiguous_identity_withholds_product_and_review_claims() -> None:
    output = await _agent(_SelectingRunner(identity=MarketplaceIdentity.AMBIGUOUS)).run(
        _input()
    )
    types = {item.fact_type for item in output.evidence}
    assert AmazonEvidenceFactType.PRODUCT_PAGE_FACT not in types
    assert AmazonEvidenceFactType.REVIEW_SUMMARY not in types
    assert AmazonEvidenceFactType.MARKETPLACE_WARNING in types
    assert any("ambiguous" in item.summary for item in output.evidence_gaps)


@pytest.mark.asyncio
async def test_tool_rejects_unknown_ids_and_enforces_search_budget() -> None:
    tools = AmazonMarketplaceTools(
        _input(), _WorkbenchAmazonProductIntelligenceProvider(), max_searches=0
    )
    assert (await tools.search(str(new_id())))["status"] == "unknown_product"
    assert (await tools.search(str(tools.input_data.products[0].product_id)))[
        "status"
    ] == "budget_exhausted"
    assert (await tools.read(str(new_id())))["status"] == "unknown_source"


@pytest.mark.asyncio
async def test_tool_reads_only_permitted_persisted_amazon_snapshots() -> None:
    valid = SourceSnapshot(
        url="https://www.amazon.com/dp/B0CART5901",
        source_type=SourceType.RETAILER_LISTING,
        provider=ProviderMetadata(provider_name="fixture"),
        extraction_status=ExtractionStatus.SUCCEEDED,
        extracted_content=ExtractedPageContent(
            text="Fixture monitor title and ASIN B0CART5901",
            extractor="fixture",
            word_count=6,
        ),
    )
    excluded = valid.model_copy(
        update={"source_id": new_id(), "extraction_status": ExtractionStatus.EXCLUDED}
    )
    hostile = valid.model_copy(
        update={
            "source_id": new_id(),
            "url": "https://amazon.com.evil.example/dp/B0CART5901",
        }
    )
    input_data = _input().model_copy(
        update={"source_snapshots": (valid, excluded, hostile)}
    )
    tools = AmazonMarketplaceTools(
        input_data, _WorkbenchAmazonProductIntelligenceProvider()
    )
    assert (await tools.read(str(valid.source_id)))["status"] == "persisted_source"
    assert (await tools.read(str(excluded.source_id)))["status"] == "unknown_source"
    assert (await tools.read(str(hostile.source_id)))["status"] == "unknown_source"


@pytest.mark.asyncio
async def test_tool_discards_affiliate_provider_urls() -> None:
    class TrackedProvider(_WorkbenchAmazonProductIntelligenceProvider):
        async def fetch_product_evidence(
            self, product: Any, listings: Any = (), options: Any = None
        ) -> AmazonProductIntelligenceProviderResult:
            result = await super().fetch_product_evidence(product, listings, options)
            assert result.bundle is not None
            bundle = result.bundle
            tracked = "https://www.amazon.com/dp/B0CART5901?tag=affiliate-20"
            return result.model_copy(
                update={
                    "bundle": bundle.model_copy(
                        update={
                            "source_references": (
                                bundle.source_references[0].model_copy(
                                    update={"url": tracked}
                                ),
                            ),
                            "listing_contexts": (
                                bundle.listing_contexts[0].model_copy(
                                    update={"listing_url": tracked}
                                ),
                            ),
                        }
                    )
                }
            )

    tools = AmazonMarketplaceTools(_input(), TrackedProvider())
    found = await tools.search(str(tools.input_data.products[0].product_id))
    assert found["sources"] == []


@pytest.mark.asyncio
async def test_tool_rejects_third_party_offer_without_hard_risk_warning() -> None:
    class UnwarnedProvider(_WorkbenchAmazonProductIntelligenceProvider):
        async def fetch_product_evidence(
            self, product: Any, listings: Any = (), options: Any = None
        ) -> AmazonProductIntelligenceProviderResult:
            result = await super().fetch_product_evidence(product, listings, options)
            assert result.bundle is not None
            bundle = result.bundle
            return result.model_copy(
                update={
                    "bundle": bundle.model_copy(
                        update={
                            "evidence": tuple(
                                item
                                for item in bundle.evidence
                                if item.fact_type
                                != AmazonEvidenceFactType.MARKETPLACE_WARNING
                            )
                        }
                    )
                }
            )

    tools = AmazonMarketplaceTools(_input(), UnwarnedProvider())
    result = await tools.search(str(tools.input_data.products[0].product_id))
    assert result["sources"] == []


@pytest.mark.asyncio
async def test_recorded_serpapi_search_exposes_candidates_for_agent_choice() -> None:
    fixture_dir = Path(__file__).parent / "fixtures" / "providers"
    fixtures = tuple(
        load_provider_fixture(fixture_dir / name)
        for name in ("amazon_search.json", "amazon_product.json")
    )
    product = CanonicalProduct(name="Portable Monitor", brand="Acme", model="View 15")
    input_data = _input().model_copy(
        update={"products": (product,), "listings": (), "target_region_code": "PH"}
    )
    async with httpx.AsyncClient(
        transport=provider_fixture_transport(fixtures)
    ) as client:
        provider = SerpApiAmazonProductIntelligenceProvider(
            api_key="recorded-test-key", client=client
        )
        tools = AmazonMarketplaceTools(input_data, provider)
        found = await tools.search(str(product.product_id))
        assert found["status"] == "succeeded"
        assert found["sources"][0]["candidate_only"] is True
        assert found["sources"][0]["asin"] == "B0CART5901"
        assert (await tools.read(str(new_id())))["status"] == "unknown_source"
        read = await tools.read(found["sources"][0]["source_id"])
        agent_output = await AmazonProductIntelligenceAgent(
            settings=Settings(_env_file=None),  # type: ignore[call-arg]
            amazon_provider=provider,
            model_runner=MockAmazonProductModelRunner(),
        ).run(input_data)
    assert read["status"] == "ok"
    assert read["source_reference"]["source_id"] != found["sources"][0]["source_id"]
    assert read["listing_context"]["seller_name"] == "Acme Deals"
    assert "tag=" not in read["source_reference"]["url"]
    assert any(
        item["fact_type"] == "review_quality_warning"
        for item in read["provider_evidence"]
    )
    assert agent_output.evidence
    assert agent_output.listing_contexts[0].asin == "B0CART5901"


@pytest.mark.asyncio
async def test_candidate_search_does_not_preemptively_discard_unmatched_title() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "organic_results": [
                    {"asin": "B0CART5901", "title": "Different Brand Coffee Maker"}
                ]
            },
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = SerpApiAmazonProductIntelligenceProvider(
            api_key="test-key", client=client
        )
        product = CanonicalProduct(
            name="Portable Monitor", brand="Acme", model="View 15"
        )
        candidates = await provider.search_product_candidates(product)
    assert candidates[0].title == "Different Brand Coffee Maker"
    assert candidates[0].asin == "B0CART5901"


@pytest.mark.asyncio
async def test_mock_runner_exercises_agent_contract_without_live_model() -> None:
    runner = MockAmazonProductModelRunner()
    output = await _agent(runner).run(_input())
    assert runner.calls == 1
    assert output.source_references
    assert output.evidence


@pytest.mark.asyncio
async def test_sdk_runner_delegates_to_agents_sdk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[Any, Any, Any]] = []

    async def fake_run(agent: Any, model_input: Any, **kwargs: Any) -> object:
        calls.append((agent, model_input, kwargs))
        return object()

    monkeypatch.setattr(
        "app.agents.context_management.Runner.run", fake_run
    )
    runner = OpenAIAgentsSDKAmazonProductModelRunner()
    tools = AmazonMarketplaceTools(
        _input(), _WorkbenchAmazonProductIntelligenceProvider()
    )
    await runner.run(
        Agent(name="fixture", instructions="fixture"),
        "fixture",
        run_config=RunConfig(tracing_disabled=True),
        max_turns=3,
        tools=tools,
    )  # type: ignore[arg-type]
    assert calls[0][2]["max_turns"] == 3
