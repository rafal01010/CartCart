"""Model-running IKEA regional official-store specialist."""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Protocol

from agents import Agent, ModelSettings, RunConfig
from pydantic import Field, WithJsonSchema

from app.agents.context_management import BoundedRunner, ContextBudgetExceeded
from app.agents.contracts import IKEAStoreIntelligenceAgentInput
from app.agents.ikea_regional_tools import IKEARegionalStoreTools
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
from app.core.ikea_regions import IKEA_REGION_PATHS
from app.core.settings import Settings
from app.providers import (
    IKEAStoreIntelligenceProvider,
    build_ikea_store_intelligence_provider,
)
from app.providers.source_quality import REGION_CURRENCIES
from app.schemas.base import CartCartBaseModel
from app.schemas.ids import ProductId, SourceId
from app.schemas.money import Money
from app.schemas.search_sources import (
    EvidenceTarget,
    EvidenceTargetType,
    IKEAStoreContext,
    IKEAStoreEvidenceBundle,
    RegionalStoreAvailability,
    SourceEvidenceGap,
    SourceIntelligenceCapability,
)
from app.services.ikea_evidence_creation import (
    IKEAStoreEvidenceCreator,
    IKEAStoreEvidenceInput,
)


class IKEAProductIdentity(StrEnum):
    MATCH = "match"
    AMBIGUOUS = "ambiguous"
    MISMATCH = "mismatch"


class SelectedIKEARegionalSource(CartCartBaseModel):
    product_id: ProductId
    source_id: SourceId
    identity: IKEAProductIdentity
    identity_reason: str = Field(min_length=1, max_length=500)
    product_name: str | None = Field(default=None, min_length=1, max_length=300)
    product_code: str | None = Field(default=None, min_length=1, max_length=120)
    # Money's Decimal precision rules generate a lookaround regex that OpenAI
    # structured outputs reject. Keep Money's runtime validation, but expose a
    # simple decimal string in this model-facing JSON schema.
    price: Annotated[
        Money | None,
        WithJsonSchema(
            {
                "anyOf": [
                    {
                        "type": "object",
                        "properties": {
                            "amount": {"type": "string"},
                            "currency": {"type": "string"},
                        },
                        "required": ["amount", "currency"],
                        "additionalProperties": False,
                    },
                    {"type": "null"},
                ]
            }
        ),
    ] = None
    availability: RegionalStoreAvailability = RegionalStoreAvailability.UNKNOWN
    store_name: str | None = Field(default=None, min_length=1, max_length=200)
    delivery_area: str | None = Field(default=None, min_length=1, max_length=200)


class IKEAStoreModelOutput(CartCartBaseModel):
    selected_sources: tuple[SelectedIKEARegionalSource, ...] = Field(max_length=5)
    evidence_gaps: tuple[str, ...] = Field(default_factory=tuple, max_length=5)
    retained_web_urls: tuple[str, ...] = Field(default_factory=tuple, max_length=8)


class IKEAStoreModelRunner(Protocol):
    async def run(
        self,
        agent: Agent[Any],
        model_input: str,
        *,
        run_config: RunConfig,
        max_turns: int,
        tools: IKEARegionalStoreTools,
    ) -> Any: ...


@dataclass
class OpenAIAgentsSDKIKEAStoreModelRunner:
    async def run(
        self,
        agent: Agent[Any],
        model_input: str,
        *,
        run_config: RunConfig,
        max_turns: int,
        tools: IKEARegionalStoreTools,
    ) -> Any:
        del tools
        return await BoundedRunner.run(
            agent, model_input, run_config=run_config, max_turns=max_turns
        )


@dataclass
class MockIKEAStoreModelRunner:
    """Offline workbench runner exercising the same search/read contract."""

    output: IKEAStoreModelOutput | dict[str, Any] | None = None
    error: BaseException | None = None
    calls: int = 0

    async def run(
        self,
        agent: Agent[Any],
        model_input: str,
        *,
        run_config: RunConfig,
        max_turns: int,
        tools: IKEARegionalStoreTools,
    ) -> Any:
        del agent, model_input, run_config, max_turns
        self.calls += 1
        if self.error:
            raise self.error
        if self.output is not None:
            return _MockResult(self.output)
        selected: list[SelectedIKEARegionalSource] = []
        for product in tools.product_summaries()[: tools.max_searches]:
            found = await tools.search(product["product_id"])
            for source in found["sources"][: tools.max_reads - len(selected)]:
                read = await tools.read(source["source_id"])
                if read["status"] != "ok":
                    continue
                text = read["text"]
                price_match = re.search(
                    r"\b([A-Z]{3})\s+(\d[\d,]*(?:\.\d{1,2})?)\b", text
                )
                price = (
                    Money(
                        currency=price_match[1], amount=Decimal(price_match[2].replace(",", ""))
                    )
                    if price_match
                    else None
                )
                normalized = text.casefold()
                availability = RegionalStoreAvailability.UNKNOWN
                if "out of stock" in normalized:
                    availability = RegionalStoreAvailability.OUT_OF_STOCK
                elif "pickup only" in normalized or "collection only" in normalized:
                    availability = RegionalStoreAvailability.PICKUP_ONLY
                elif "not available for delivery" in normalized:
                    availability = RegionalStoreAvailability.DELIVERY_UNAVAILABLE
                elif "available for delivery" in normalized or "in stock" in normalized:
                    availability = RegionalStoreAvailability.AVAILABLE
                identity_hint = product["model"] or product["name"]
                selected.append(
                    SelectedIKEARegionalSource(
                        product_id=ProductId(product["product_id"]),
                        source_id=SourceId(source["source_id"]),
                        identity=(
                            IKEAProductIdentity.MATCH
                            if identity_hint.casefold() in normalized
                            else IKEAProductIdentity.AMBIGUOUS
                        ),
                        identity_reason="Recorded official regional fixture identity check.",
                        product_name="MICKE desk, white"
                        if "MICKE desk, white" in text
                        else None,
                        product_code="902.143.08" if "902.143.08" in text else None,
                        price=price,
                        availability=availability,
                        store_name="IKEA Pasay City"
                        if "IKEA Pasay City" in text
                        else None,
                        delivery_area="Available for delivery in Metro Manila."
                        if "Available for delivery in Metro Manila." in text
                        else None,
                    )
                )
        return _MockResult(IKEAStoreModelOutput(selected_sources=tuple(selected)))


@dataclass
class _MockResult:
    final_output: Any


@dataclass
class IKEAStoreIntelligenceAgent:
    settings: Settings
    ikea_provider: IKEAStoreIntelligenceProvider | None = None
    citation_store: HostedCitationStore | None = None
    model_runner: IKEAStoreModelRunner = field(
        default_factory=OpenAIAgentsSDKIKEAStoreModelRunner
    )
    _workbench_activity: tuple[dict[str, Any], ...] = field(
        default=(), init=False, repr=False
    )

    @property
    def workbench_activity(self) -> tuple[dict[str, Any], ...]:
        return self._workbench_activity

    def prepare_delegated_run(
        self, input_data: IKEAStoreIntelligenceAgentInput
    ) -> tuple[Agent[Any], IKEARegionalStoreTools, Any]:
        config = build_openai_agent_run_configuration(
            self.settings,
            agent_name="IKEAStoreIntelligenceAgent",
            run_id=str(input_data.run_id),
        )
        tools = IKEARegionalStoreTools(
            input_data=input_data,
            ikea_provider=self.ikea_provider
            or build_ikea_store_intelligence_provider(self.settings),
        )
        hosted_tool = source_hosted_tool(
            config=config,
            input_data=input_data,
            agent_name="IKEAStoreIntelligenceAgent",
            citation_store=self.citation_store,
        )
        agent = Agent(
            name="IKEAStoreIntelligenceAgent",
            model=config.model,
            model_settings=ModelSettings(
                max_tokens=3000, include_usage=True, tool_choice="auto"
            ),
            instructions=(
                "You are a regional official IKEA evidence specialist, not a shopping recommender. "
                "Choose relevant supplied product IDs, call search_ikea_products and read_ikea_product for selected source IDs. "
                "Decide whether each read official product result matches, mismatches, or ambiguously matches the requested item. "
                "Only return source IDs actually read and fields explicitly present in that source's text or official product URL. "
                "Separate item identity from region-specific price, currency, stock, store and delivery. "
                "Missing or unclear fields must be null or unknown. Do not infer worldwide availability, shipping, local delivery, or store inventory. "
                "Do not use non-official listings as official evidence; return honest gaps for unsupported regions or no matching sources. "
                "You may use web_search for official regional IKEA page discovery, or skip it. Put useful exact cited URLs in retained_web_urls. "
                "A hosted snippet is only a lead; use search_ikea_products and read_ikea_product for item, price, stock, and delivery evidence."
            ),
            tools=[*tools.sdk_tools(), *([hosted_tool] if hosted_tool else [])],
            output_type=IKEAStoreModelOutput,
        )
        apply_openai_agent_run_profile(agent, config)
        return agent, tools, config

    async def run(
        self, input_data: IKEAStoreIntelligenceAgentInput
    ) -> IKEAStoreEvidenceBundle:
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
                    json.dumps(
                        {
                            "brief": input_data.brief.model_dump(mode="json"),
                            "region": tools.region,
                            "products": tools.product_summaries(),
                            "product_queries": input_data.product_queries,
                            "official_snapshots": tools.snapshot_summaries(),
                            "limits": {
                                "searches": tools.max_searches,
                                "reads": tools.max_reads,
                            },
                        },
                        sort_keys=True,
                    ),
                    run_config=run_config,
                    max_turns=config.max_turns,
                    tools=tools,
                ),
                timeout=config.timeout_seconds,
            )
            decision = IKEAStoreModelOutput.model_validate(
                getattr(raw, "final_output", raw)
            )
            decision, hosted_activity = await process_source_specialist_output(
                raw=raw,
                decision=decision,
                input_data=input_data,
                agent_name=agent.name,
                citation_store=self.citation_store,
                require_sdk_metadata=isinstance(
                    self.model_runner, OpenAIAgentsSDKIKEAStoreModelRunner
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
                tools, "Model interpretation failed; no IKEA claim was accepted."
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
                    "allowed_tools": [t.name for t in agent.tools],
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


def _supported_fields(
    selected: SelectedIKEARegionalSource, text: str, url: str, region: str | None
) -> None:
    searchable = f"{text} {url}".casefold()
    for value in (selected.product_name, selected.store_name, selected.delivery_area):
        if value and value.casefold() not in searchable:
            raise ValueError("IKEA model field is not supported by the read source.")
    if selected.product_code and re.sub(r"\D", "", selected.product_code) not in re.sub(
        r"\D", "", searchable
    ):
        raise ValueError("IKEA product code is not supported by the read source.")
    if selected.price:
        expected_currency = REGION_CURRENCIES.get(region or "")
        matches = re.findall(r"\b([A-Z]{3})\s*(\d[\d,]*(?:\.\d{1,2})?)\b", text.upper())
        if (
            expected_currency and selected.price.currency != expected_currency
        ) or not any(
            currency == selected.price.currency
            and Decimal(amount.replace(",", "")) == selected.price.amount
            for currency, amount in matches
        ):
            raise ValueError("IKEA price is not supported by the read source.")
    if selected.availability != RegionalStoreAvailability.UNKNOWN:
        normalized = " ".join(text.casefold().split())
        if selected.availability == RegionalStoreAvailability.AVAILABLE and any(
            marker in normalized
            for marker in (
                "not available",
                "unavailable",
                "out of stock",
                "pickup only",
                "collection only",
            )
        ):
            raise ValueError("IKEA availability conflicts with the read source.")
        markers = {
            RegionalStoreAvailability.AVAILABLE: (
                "available for delivery",
                "available online",
                "in stock",
            ),
            RegionalStoreAvailability.OUT_OF_STOCK: ("out of stock",),
            RegionalStoreAvailability.PICKUP_ONLY: ("pickup only", "collection only"),
            RegionalStoreAvailability.DELIVERY_UNAVAILABLE: (
                "delivery unavailable",
                "not available for delivery",
            ),
        }.get(selected.availability, ())
        if not markers or not any(marker in normalized for marker in markers):
            raise ValueError("IKEA availability is not supported by the read source.")


def _validated_bundle(
    tools: IKEARegionalStoreTools, decision: IKEAStoreModelOutput
) -> IKEAStoreEvidenceBundle:
    inputs = []
    gaps = []
    seen: set[str] = set()
    for selected in decision.selected_sources:
        source_id = str(selected.source_id)
        record = tools._records.get(source_id)
        if (
            source_id in seen
            or source_id not in tools._read
            or record is None
            or record.product_id != str(selected.product_id)
        ):
            raise ValueError(
                "IKEA source must be unique, searched and read for its supplied product."
            )
        seen.add(source_id)
        if selected.identity != IKEAProductIdentity.MATCH:
            gaps.append(
                _gap(
                    "IKEA product identity is ambiguous."
                    if selected.identity == IKEAProductIdentity.AMBIGUOUS
                    else "IKEA product identity did not match.",
                    selected.identity_reason,
                )
            )
            continue
        _supported_fields(
            selected, record.text, str(record.reference.url), tools.region
        )
        assert tools.region is not None
        context = IKEAStoreContext(
            source_id=selected.source_id,
            country_code=tools.region,
            official_url=record.reference.url,
            product_code=selected.product_code,
            product_name=selected.product_name,
            store_name=selected.store_name,
            delivery_area=selected.delivery_area,
            price=selected.price,
            availability=selected.availability,
        )
        claim = None
        if selected.product_name or selected.product_code:
            claim = "Official IKEA regional product result: " + (
                selected.product_name or "product"
            )
            if selected.product_code:
                claim += f". Product number: {selected.product_code}"
            claim += "."
        inputs.append(
            IKEAStoreEvidenceInput(
                product_id=selected.product_id,
                source_reference=record.reference,
                store_context=context,
                source_quality=record.quality,
                product_page_claim=claim,
            )
        )
    if not inputs:
        fallback = _gap_bundle(
            tools,
            "No sufficiently matched official IKEA regional product was selected.",
        )
        return IKEAStoreEvidenceBundle(
            evidence_gaps=(
                *gaps,
                *(
                    _gap("IKEA regional evidence remains incomplete.", reason)
                    for reason in decision.evidence_gaps
                ),
                *fallback.evidence_gaps,
            )
        )
    gaps.extend(
        _gap("IKEA regional evidence remains incomplete.", reason)
        for reason in decision.evidence_gaps
    )
    return IKEAStoreEvidenceCreator().create(tuple(inputs), evidence_gaps=tuple(gaps))


def _gap(summary: str, reason: str) -> SourceEvidenceGap:
    return SourceEvidenceGap(
        capability=SourceIntelligenceCapability.IKEA_REGIONAL_OFFICIAL_STORE,
        summary=summary,
        reason=reason,
    )


def _gap_bundle(tools: IKEARegionalStoreTools, reason: str) -> IKEAStoreEvidenceBundle:
    if tools.region is None:
        reason = "No target region was supplied. " + reason
    elif tools.region not in IKEA_REGION_PATHS:
        reason = (
            f"No supported IKEA regional presence is configured for {tools.region}. "
            + reason
        )
    elif tools._last_status not in {None, "succeeded"}:
        reason = f"IKEA provider returned {tools._last_status}. " + reason
    gap = _gap("IKEA regional official-store evidence was unavailable.", reason)
    if tools.region:
        gap = gap.model_copy(
            update={
                "target": EvidenceTarget(
                    target_type=EvidenceTargetType.REGION, region_code=tools.region
                )
            }
        )
    return IKEAStoreEvidenceBundle(evidence_gaps=(gap,))
