"""Agent-owned interpretation of persisted shopping-source snapshots."""

import asyncio
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol
from urllib.parse import urlsplit

from agents import Agent, ModelSettings, RunConfig, Runner
from pydantic import ValidationError

from app.agents.contracts import (
    ExtractionAgentInput,
    ExtractionAgentOutput,
    ExtractionEvidenceGap,
)
from app.agents.extraction_tools import SnapshotInterpretationTools
from app.agents.openai_config import (
    apply_openai_agent_run_profile,
    build_openai_agent_run_configuration,
)
from app.core.settings import Settings
from app.schemas.ids import SourceId
from app.schemas.search_sources import EvidenceType


class ExtractionModelRunner(Protocol):
    async def run(
        self,
        agent: Agent[Any],
        model_input: str,
        *,
        run_config: RunConfig,
        max_turns: int,
    ) -> Any: ...


@dataclass
class OpenAIAgentsSDKExtractionModelRunner:
    async def run(
        self,
        agent: Agent[Any],
        model_input: str,
        *,
        run_config: RunConfig,
        max_turns: int,
    ) -> Any:
        return await Runner.run(
            agent, model_input, run_config=run_config, max_turns=max_turns
        )


@dataclass
class MockExtractionModelRunner:
    output: ExtractionAgentOutput | dict[str, Any]
    calls: int = 0

    async def run(
        self,
        agent: Agent[Any],
        model_input: str,
        *,
        run_config: RunConfig,
        max_turns: int,
    ) -> Any:
        del agent, model_input, run_config, max_turns
        self.calls += 1
        return self.output


@dataclass
class LiveExtractionAgent:
    settings: Settings
    snapshot_tools_factory: Callable[
        [ExtractionAgentInput], SnapshotInterpretationTools
    ]
    model_runner: ExtractionModelRunner = field(
        default_factory=OpenAIAgentsSDKExtractionModelRunner
    )
    _workbench_activity: tuple[dict[str, Any], ...] = field(default=(), init=False)

    @property
    def workbench_activity(self) -> tuple[dict[str, Any], ...]:
        return self._workbench_activity

    async def run(self, input_data: ExtractionAgentInput) -> ExtractionAgentOutput:
        tools = self.snapshot_tools_factory(input_data)
        # Read through the same bounded, run-scoped tool even if a model skips
        # its optional tool call. A missing snapshot never becomes a product.
        pages = [
            await tools.read(str(source_id)) for source_id in input_data.snapshot_ids
        ]
        readable = {
            page.snapshot_id: page for page in pages if page.text and page.snapshot_id
        }
        if not readable:
            return self._gap_output(input_data, tools, "No readable snapshot text.")

        configuration = build_openai_agent_run_configuration(
            self.settings, agent_name="ExtractionAgent", run_id=str(input_data.run_id)
        )
        agent = Agent(
            name="CartCartExtractionAgent",
            model=configuration.model,
            model_settings=ModelSettings(max_tokens=5000, include_usage=True),
            instructions=(
                "Interpret the supplied persisted page text semantically. The provider "
                "source type and mechanical signals are hints, not permission to invent "
                "facts. Return zero, one, or many separate products and listings. "
                "A review is evidence, not a store listing. Distinguish product facts "
                "from listing price, seller, availability, and region facts. A product "
                "mention in a review may be returned without a listing. Use "
                "product_mentions for cited named products that still need a "
                "direct official or retailer offer lookup, even if the same "
                "page also yielded other usable listings. Do not request "
                "lookup for a product already backed by a direct offer. Cite the exact "
                "supplied snapshot ID in every product, listing, evidence, mention, and "
                "gap; evidence targets must reference returned entity IDs. Do not infer "
                "price, currency, specification, seller, availability or item URL from "
                "ambiguous page text. Leave unknown fields empty and report gaps. "
                "Never use a review URL as a retail listing URL."
                " If research_leads are supplied, match a newly extracted product "
                "to a prior cited research lead only when page-level model or "
                "identity evidence supports it. Return lead_matches with the "
                "prior lead evidence IDs for confident matches; leave "
                "ambiguous matches out. Editorial snapshots may yield mentions "
                "and review claims, but never retailer listings. For a multi-item "
                "collection page, create separate products/listings only for "
                "item-level identities and prices the text supports. Do not "
                "reuse the collection URL as every item's offer URL; when an "
                "item URL is absent, return a cited mention and explicit gap "
                "so discovery can seek a direct offer."
            ),
            tools=list(tools.sdk_tools()),
            output_type=ExtractionAgentOutput,
        )
        apply_openai_agent_run_profile(agent, configuration)
        run_config = RunConfig(
            model_settings=ModelSettings(max_tokens=5000, include_usage=True),
            tracing_disabled=not configuration.tracing_enabled,
            trace_include_sensitive_data=configuration.trace_include_sensitive_data,
            workflow_name=configuration.trace_workflow_name,
            trace_metadata=configuration.trace_metadata,
        )
        prompt = json.dumps(
            {
                "run_id": str(input_data.run_id),
                "category": input_data.category,
                "pages": [page.model_dump(mode="json") for page in pages],
                "editorial_snapshot_ids": [
                    str(item) for item in input_data.editorial_snapshot_ids
                ],
                "collection_snapshot_ids": [
                    str(item) for item in input_data.collection_snapshot_ids
                ],
                "research_leads": [
                    lead.model_dump(mode="json") for lead in input_data.research_leads
                ],
            },
            sort_keys=True,
        )
        try:
            raw = await asyncio.wait_for(
                self.model_runner.run(
                    agent,
                    prompt,
                    run_config=run_config,
                    max_turns=configuration.max_turns,
                ),
                timeout=configuration.timeout_seconds,
            )
            output = ExtractionAgentOutput.model_validate(
                getattr(raw, "final_output", raw)
            )
            _validate_extraction(output, readable, input_data)
        except (TimeoutError, ValidationError, ValueError, TypeError):
            return self._gap_output(
                input_data, tools, "Agent extraction was invalid or timed out."
            )
        except Exception:
            return self._gap_output(
                input_data, tools, "Agent extraction was unavailable."
            )
        self._workbench_activity = (
            *tools.workbench_activity,
            {
                "tool_name": "openai_agents_structured_output",
                "status": "model_extraction_completed",
                "input": {"agent": "ExtractionAgent", "snapshot_count": len(pages)},
                "output": {
                    "product_count": len(output.products),
                    "listing_count": len(output.listings),
                },
            },
        )
        return output

    def _gap_output(
        self,
        input_data: ExtractionAgentInput,
        tools: SnapshotInterpretationTools,
        reason: str,
    ) -> ExtractionAgentOutput:
        self._workbench_activity = (
            *tools.workbench_activity,
            {
                "tool_name": "openai_agents_structured_output",
                "status": "explicit_gap",
                "input": {"agent": "ExtractionAgent"},
                "output": {"reason": reason},
            },
        )
        return ExtractionAgentOutput(
            evidence_gaps=tuple(
                ExtractionEvidenceGap(source_id=source_id, summary=reason)
                for source_id in input_data.snapshot_ids
            )
        )


def _validate_extraction(
    output: ExtractionAgentOutput,
    readable: dict[SourceId, Any],
    input_data: ExtractionAgentInput,
) -> None:
    if not any(
        (
            output.products,
            output.listings,
            output.source_evidence,
            output.product_mentions,
            output.evidence_gaps,
        )
    ):
        raise ValueError("empty extraction requires an explicit evidence gap")
    allowed = set(readable)
    editorial = set(input_data.editorial_snapshot_ids)
    collections = set(input_data.collection_snapshot_ids)
    if not editorial.issubset(allowed):
        raise ValueError("editorial snapshot must be an assigned readable source")
    if not collections.issubset(allowed):
        raise ValueError("collection snapshot must be an assigned readable source")
    lead_evidence_ids = {
        evidence.evidence_id
        for lead in input_data.research_leads
        for evidence in lead.source_evidence
    }
    for product in output.products:
        if not product.source_ids or not set(product.source_ids).issubset(allowed):
            raise ValueError("product cites unknown or missing snapshot")
    for listing in output.listings:
        if set(listing.source_ids) & editorial:
            raise ValueError("editorial source cannot support a retailer listing")
        if not set(listing.source_ids).issubset(allowed):
            raise ValueError("listing cites unknown snapshot")
        listing_url = str(listing.url).rstrip("/")
        if any(
            listing_url == (readable[source_id].url or "").rstrip("/")
            for source_id in set(listing.source_ids) & collections
        ):
            raise ValueError("collection URL is not an item-level offer URL")
        if urlsplit(listing_url).query or urlsplit(listing_url).fragment:
            raise ValueError("listing URL must be a neutral outbound URL")
        if not any(
            listing_url == (readable[source_id].url or "").rstrip("/")
            or listing_url in (readable[source_id].text or "")
            for source_id in listing.source_ids
        ):
            raise ValueError("listing URL is absent from cited page")
        if not listing.seller.source_ids or not set(listing.seller.source_ids).issubset(
            allowed
        ):
            raise ValueError("seller cites unknown snapshot")
        for availability in listing.region_availability:
            if not availability.source_ids or not set(availability.source_ids).issubset(
                allowed
            ):
                raise ValueError("availability cites unknown snapshot")
        if listing.price is not None:
            if not any(
                _page_supports_amount(
                    readable[source_id].text or "", listing.price.amount
                )
                for source_id in listing.source_ids
            ):
                raise ValueError("listing price is absent from cited page text")
    for evidence in output.source_evidence:
        if evidence.source_id not in allowed:
            raise ValueError("evidence cites unknown snapshot")
        if evidence.evidence_type == EvidenceType.PRICE and not output.listings:
            raise ValueError("price evidence requires a listing")
    for mention in output.product_mentions:
        if mention.source_id not in allowed:
            raise ValueError("mention cites unknown snapshot")
    for gap in output.evidence_gaps:
        if gap.source_id not in allowed:
            raise ValueError("gap cites unknown snapshot")
    for match in output.lead_matches:
        if not set(match.lead_evidence_ids).issubset(lead_evidence_ids):
            raise ValueError("lead match cites unknown source evidence")


def _page_supports_amount(text: str, amount: Decimal) -> bool:
    # Mechanical corroboration only: this does not decide which product a
    # visible price belongs to; the agent must still make that cited judgment.
    for match in re.finditer(
        r"(?<![\w.])(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?(?![\w.])",
        text,
    ):
        if Decimal(match.group().replace(",", "")) == amount:
            return True
    return False
