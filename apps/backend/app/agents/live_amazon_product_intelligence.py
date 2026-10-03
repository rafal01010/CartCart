"""Model-running Amazon marketplace specialist with source-bound output."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

from agents import Agent, ModelSettings, RunConfig
from pydantic import Field

from app.agents.context_management import BoundedRunner, ContextBudgetExceeded
from app.agents.amazon_marketplace_tools import AmazonMarketplaceTools
from app.agents.contracts import AmazonProductIntelligenceAgentInput
from app.agents.openai_config import (
    OpenAIAgentConfigurationError,
    apply_openai_agent_run_profile,
    build_openai_agent_run_configuration,
)
from app.agents.research_tools import HostedCitationStore
from app.agents.source_hosted_search import (
    process_source_specialist_output,
    source_hosted_tool,
    source_tool_activity,
)
from app.core.settings import Settings
from app.providers import (
    AmazonProductIntelligenceProvider,
    build_amazon_product_intelligence_provider,
)
from app.schemas.base import CartCartBaseModel
from app.schemas.ids import ProductId, SourceId
from app.schemas.search_sources import (
    AmazonEvidenceFactType,
    AmazonProductEvidenceBundle,
    SourceEvidenceGap,
    SourceReference,
    AmazonProductEvidence,
    SourceIntelligenceCapability,
)


class MarketplaceIdentity(StrEnum):
    MATCH = "match"
    AMBIGUOUS = "ambiguous"
    MISMATCH = "mismatch"


class SelectedMarketplaceSource(CartCartBaseModel):
    product_id: ProductId
    source_id: SourceId
    identity: MarketplaceIdentity
    identity_reason: str = Field(min_length=1, max_length=500)
    selected_evidence_ids: tuple[SourceId, ...] = Field(max_length=20)


class AmazonProductModelOutput(CartCartBaseModel):
    selected_sources: tuple[SelectedMarketplaceSource, ...] = Field(max_length=5)
    evidence_gaps: tuple[str, ...] = Field(default_factory=tuple, max_length=5)
    retained_web_urls: tuple[str, ...] = Field(default_factory=tuple, max_length=8)


class AmazonProductModelRunner(Protocol):
    async def run(
        self,
        agent: Agent[Any],
        model_input: str,
        *,
        run_config: RunConfig,
        max_turns: int,
        tools: AmazonMarketplaceTools,
    ) -> Any: ...


@dataclass
class OpenAIAgentsSDKAmazonProductModelRunner:
    async def run(
        self,
        agent: Agent[Any],
        model_input: str,
        *,
        run_config: RunConfig,
        max_turns: int,
        tools: AmazonMarketplaceTools,
    ) -> Any:
        del tools
        return await BoundedRunner.run(
            agent, model_input, run_config=run_config, max_turns=max_turns
        )


@dataclass
class MockAmazonProductModelRunner:
    """Offline contract runner for workbench fixtures, never a live model call."""

    output: AmazonProductModelOutput | dict[str, Any] | None = None
    error: BaseException | None = None
    calls: int = 0

    async def run(
        self,
        agent: Agent[Any],
        model_input: str,
        *,
        run_config: RunConfig,
        max_turns: int,
        tools: AmazonMarketplaceTools,
    ) -> Any:
        del agent, model_input, run_config, max_turns
        self.calls += 1
        if self.error:
            raise self.error
        if self.output is not None:
            return _MockResult(self.output)
        selected: list[SelectedMarketplaceSource] = []
        for product in tools.product_summaries()[: tools.max_searches]:
            found = await tools.search(product["product_id"])
            for source in found["sources"][: tools.max_reads - len(selected)]:
                read = await tools.read(source["source_id"])
                if read["status"] != "ok":
                    continue
                selected.append(
                    SelectedMarketplaceSource(
                        product_id=ProductId(product["product_id"]),
                        source_id=SourceId(read["source_reference"]["source_id"]),
                        identity=MarketplaceIdentity.MATCH,
                        identity_reason="Recorded fixture product and listing identity match.",
                        selected_evidence_ids=tuple(
                            SourceId(item["evidence_id"])
                            for item in read["provider_evidence"]
                        ),
                    )
                )
        return _MockResult(AmazonProductModelOutput(selected_sources=tuple(selected)))


@dataclass
class _MockResult:
    final_output: Any


@dataclass
class AmazonProductIntelligenceAgent:
    settings: Settings
    amazon_provider: AmazonProductIntelligenceProvider | None = None
    citation_store: HostedCitationStore | None = None
    model_runner: AmazonProductModelRunner = field(
        default_factory=OpenAIAgentsSDKAmazonProductModelRunner
    )
    _workbench_activity: tuple[dict[str, Any], ...] = field(
        default=(), init=False, repr=False
    )

    @property
    def workbench_activity(self) -> tuple[dict[str, Any], ...]:
        return self._workbench_activity

    def prepare_delegated_run(
        self, input_data: AmazonProductIntelligenceAgentInput
    ) -> tuple[Agent[Any], AmazonMarketplaceTools, Any]:
        config = build_openai_agent_run_configuration(
            self.settings,
            agent_name="AmazonProductIntelligenceAgent",
            run_id=str(input_data.run_id),
        )
        tools = AmazonMarketplaceTools(
            input_data=input_data,
            amazon_provider=self.amazon_provider
            or build_amazon_product_intelligence_provider(self.settings),
        )
        hosted_tool = source_hosted_tool(
            config=config,
            input_data=input_data,
            agent_name="AmazonProductIntelligenceAgent",
            citation_store=self.citation_store,
        )
        agent = Agent(
            name="AmazonProductIntelligenceAgent",
            model=config.model,
            model_settings=ModelSettings(
                max_tokens=3000, include_usage=True, tool_choice="auto"
            ),
            instructions=(
                "You are an Amazon marketplace evidence specialist, not a purchase recommender. "
                "Choose relevant candidate product IDs and call search_amazon_products. Search hits may be candidate-only; read_amazon_product with the returned candidate/source ID before selecting. Use the read result's authoritative source_reference.source_id in final output. "
                "Interpret ASIN, variant, title, and brand/model identity conservatively. Mark mismatches and ambiguity; never merge variants by guesswork. "
                "Select only evidence IDs returned by the read tool. Distinguish product-page claims from each offer's seller, fulfillment, price, availability, and shipping; these are not product-quality facts. "
                "Treat ratings, counts, and review summaries as marketplace-provided signals, not authenticated review quality. Preserve variant-mixing warnings and region/ship-to uncertainty. "
                "Never invent prices, review counts, delivery promises, seller legitimacy, source IDs, or evidence IDs. "
                "Do not fetch arbitrary URLs or use affiliate links. Return gaps when source or identity evidence is insufficient. "
                "You may use web_search for regional Amazon offer discovery, or skip it. Put useful exact cited URLs in retained_web_urls. "
                "A hosted snippet is only a lead; only search_amazon_products and read_amazon_product can establish marketplace evidence."
            ),
            tools=[*tools.sdk_tools(), *([hosted_tool] if hosted_tool else [])],
            output_type=AmazonProductModelOutput,
        )
        apply_openai_agent_run_profile(agent, config)
        return agent, tools, config

    async def run(
        self, input_data: AmazonProductIntelligenceAgentInput
    ) -> AmazonProductEvidenceBundle:
        agent, tools, config = self.prepare_delegated_run(input_data)
        hosted_activity: tuple[dict[str, Any], ...] = ()
        run_config = RunConfig(
            tracing_disabled=not config.tracing_enabled,
            trace_include_sensitive_data=config.trace_include_sensitive_data,
            workflow_name=config.trace_workflow_name,
            trace_metadata=config.trace_metadata,
        )
        try:
            raw = await asyncio.wait_for(
                self.model_runner.run(
                    agent,
                    _model_input(input_data, tools),
                    run_config=run_config,
                    max_turns=config.max_turns,
                    tools=tools,
                ),
                timeout=config.timeout_seconds,
            )
            decision = AmazonProductModelOutput.model_validate(
                getattr(raw, "final_output", raw)
            )
            decision, hosted_activity = await process_source_specialist_output(
                raw=raw,
                decision=decision,
                input_data=input_data,
                agent_name=agent.name,
                citation_store=self.citation_store,
                require_sdk_metadata=isinstance(
                    self.model_runner, OpenAIAgentsSDKAmazonProductModelRunner
                ),
            )
            output = _validated_bundle(tools, decision)
            status = "model_evidence_completed"
        except ContextBudgetExceeded:
            raise
        except Exception as exc:
            if isinstance(exc, OpenAIAgentConfigurationError):
                hosted_activity = (
                    *hosted_activity,
                    {
                        "tool_name": "web_search",
                        "status": "metadata_or_persistence_failed",
                        "input": {"agent": agent.name},
                        "output": {"reason": str(exc)},
                    },
                )
            output = _gap_bundle(
                tools, "Model interpretation failed; no marketplace claim was accepted."
            )
            status = "model_or_validation_failure_gap"
        self._workbench_activity = (
            *source_tool_activity(tools.workbench_activity, agent.name),
            *hosted_activity,
            {
                "tool_name": "openai_agents_structured_output",
                "status": status,
                "input": {
                    "agent": agent.name,
                    "allowed_tools": [tool.name for tool in agent.tools],
                    "model": config.model,
                },
                "output": {
                    "source_count": len(output.source_references),
                    "evidence_count": len(output.evidence),
                    "gap_count": len(output.evidence_gaps),
                },
            },
        )
        return output


def _model_input(
    input_data: AmazonProductIntelligenceAgentInput, tools: AmazonMarketplaceTools
) -> str:
    return json.dumps(
        {
            "brief": input_data.brief.model_dump(mode="json"),
            "target_region_code": input_data.target_region_code,
            "product_queries": input_data.product_queries,
            "products": tools.product_summaries(),
            "persisted_amazon_sources": tools.snapshot_summaries(),
            "limits": {"searches": tools.max_searches, "reads": tools.max_reads},
        },
        sort_keys=True,
    )


def _validated_bundle(
    tools: AmazonMarketplaceTools, decision: AmazonProductModelOutput
) -> AmazonProductEvidenceBundle:
    refs: list[SourceReference] = []
    contexts = []
    evidence: list[AmazonProductEvidence] = []
    gaps: list[SourceEvidenceGap] = []
    seen: set[SourceId] = set()
    for selected in decision.selected_sources:
        if selected.source_id in seen or str(selected.source_id) not in tools._read:
            raise ValueError(
                "Amazon source must be unique and read through the approved tool."
            )
        seen.add(selected.source_id)
        bundle = tools._bundles.get(str(selected.product_id))
        if bundle is None:
            raise ValueError(
                "Amazon product ID was not searched through the approved tool."
            )
        context = next(
            (
                item
                for item in bundle.listing_contexts
                if item.source_id == selected.source_id
            ),
            None,
        )
        if context is None:
            raise ValueError("Amazon source and product identity do not match.")
        available = {
            item.evidence_id: item
            for item in bundle.evidence
            if item.source_id == selected.source_id
        }
        if len(set(selected.selected_evidence_ids)) != len(
            selected.selected_evidence_ids
        ) or not set(selected.selected_evidence_ids).issubset(available):
            raise ValueError("Amazon model selected unknown or duplicate evidence IDs.")
        if selected.identity == MarketplaceIdentity.MISMATCH:
            gaps.append(
                _gap(
                    "Amazon product identity did not match the requested candidate.",
                    selected.identity_reason,
                    selected.source_id,
                )
            )
            continue
        refs.extend(
            item
            for item in bundle.source_references
            if item.source_id == selected.source_id
        )
        contexts.append(context)
        allowed = set(selected.selected_evidence_ids)
        # Provider hard listing-risk signals cannot be silently discarded by a model.
        allowed.update(
            item.evidence_id
            for item in available.values()
            if item.fact_type
            in {
                AmazonEvidenceFactType.MARKETPLACE_WARNING,
                AmazonEvidenceFactType.REVIEW_QUALITY_WARNING,
            }
        )
        if selected.identity == MarketplaceIdentity.AMBIGUOUS:
            allowed = {
                evidence_id
                for evidence_id in allowed
                if available[evidence_id].fact_type
                not in {
                    AmazonEvidenceFactType.PRODUCT_PAGE_FACT,
                    AmazonEvidenceFactType.REVIEW_SUMMARY,
                }
            }
            gaps.append(
                _gap(
                    "Amazon ASIN or variant identity is ambiguous.",
                    selected.identity_reason,
                    selected.source_id,
                )
            )
        evidence.extend(item for item in bundle.evidence if item.evidence_id in allowed)
        gaps.extend(
            item
            for item in bundle.evidence_gaps
            if item.source_id in {None, selected.source_id}
        )
    if not refs:
        return _gap_bundle(tools, "No sufficiently matched Amazon source was selected.")
    # The model may describe missing evidence, but free text is never promoted to product facts.
    gaps.extend(
        _gap("Amazon evidence remains incomplete.", reason)
        for reason in decision.evidence_gaps
    )
    return AmazonProductEvidenceBundle(
        source_references=tuple(refs),
        listing_contexts=tuple(contexts),
        evidence=tuple(evidence),
        evidence_gaps=tuple(gaps),
    )


def _gap(
    summary: str, reason: str, source_id: SourceId | None = None
) -> SourceEvidenceGap:
    return SourceEvidenceGap(
        capability=SourceIntelligenceCapability.AMAZON_PRODUCT_LISTING_REVIEW,
        source_id=source_id,
        summary=summary,
        reason=reason,
    )


def _gap_bundle(
    tools: AmazonMarketplaceTools, reason: str
) -> AmazonProductEvidenceBundle:
    provider_gaps = tuple(
        gap
        for bundle in tools._bundles.values()
        for gap in bundle.evidence_gaps
        if gap.source_id is None
    )
    status = f" Provider status: {tools._last_status}." if tools._last_status else ""
    return AmazonProductEvidenceBundle(
        evidence_gaps=(
            *provider_gaps,
            _gap(
                "Amazon product/listing/review evidence is insufficient.",
                reason + status,
            ),
        )
    )
