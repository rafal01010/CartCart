"""Model-running Reddit/community specialist over approved public-source tools."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, Protocol

from agents import Agent, ModelSettings, RunConfig
from pydantic import Field

from app.agents.context_management import (
    BoundedRunner, ContextBudgetExceeded, context_budget_failure,
)
from app.agents.contracts import RedditCommunityIntelligenceAgentInput
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
from app.agents.reddit_community_tools import RedditCommunityTools
from app.core.settings import Settings
from app.providers import (
    CommunityDiscussionProvider,
    build_community_discussion_provider,
)
from app.schemas.base import CartCartBaseModel
from app.schemas.confidence import Confidence, ConfidenceLevel
from app.schemas.ids import ProductId, SourceId
from app.schemas.search_sources import (
    CommunityDiscussionEvidenceBundle,
    CommunitySupportingQuote,
    EvidenceTarget,
    EvidenceTargetType,
    SourceEvidenceGap,
    SourceIntelligenceCapability,
    SourceQuality,
    SourceQualityLevel,
)
from app.services.community_evidence_creation import (
    CommunityEvidenceCreator,
    SourceBackedCommunityClaim,
)


class SelectedDiscussion(CartCartBaseModel):
    source_id: SourceId
    relevance_reason: str = Field(min_length=1, max_length=500)


class InterpretedCommunitySignal(CartCartBaseModel):
    source_id: SourceId
    product_id: ProductId | None = None
    claim: str = Field(min_length=1, max_length=500)
    supporting_quotes: tuple[CommunitySupportingQuote, ...] = Field(
        min_length=1, max_length=4
    )
    recurring_signal: bool = False
    evidence_quality_warnings: tuple[str, ...] = Field(
        default_factory=tuple, max_length=5
    )


class RedditCommunityModelOutput(CartCartBaseModel):
    selected_discussions: tuple[SelectedDiscussion, ...] = Field(max_length=6)
    signals: tuple[InterpretedCommunitySignal, ...] = Field(max_length=6)
    evidence_gaps: tuple[str, ...] = Field(default_factory=tuple, max_length=6)
    retained_web_urls: tuple[str, ...] = Field(default_factory=tuple, max_length=8)


class RedditCommunityModelRunner(Protocol):
    async def run(
        self,
        agent: Agent[Any],
        model_input: str,
        *,
        run_config: RunConfig,
        max_turns: int,
        tools: RedditCommunityTools,
    ) -> Any: ...


@dataclass
class OpenAIAgentsSDKRedditCommunityModelRunner:
    async def run(
        self,
        agent: Agent[Any],
        model_input: str,
        *,
        run_config: RunConfig,
        max_turns: int,
        tools: RedditCommunityTools,
    ) -> Any:
        del tools
        return await BoundedRunner.run(
            agent, model_input, run_config=run_config, max_turns=max_turns
        )


@dataclass
class MockRedditCommunityModelRunner:
    """Offline contract runner; it never impersonates a live model call."""

    output: RedditCommunityModelOutput | dict[str, Any] | None = None
    error: BaseException | None = None
    calls: int = 0

    async def run(
        self,
        agent: Agent[Any],
        model_input: str,
        *,
        run_config: RunConfig,
        max_turns: int,
        tools: RedditCommunityTools,
    ) -> Any:
        del agent, run_config, max_turns
        self.calls += 1
        if self.error:
            raise self.error
        if self.output is not None:
            return _MockResult(self.output)
        payload = json.loads(model_input)
        if not tools.bundle or not tools.bundle.discussions:
            await tools.search(
                (
                    payload["community_queries"]
                    or [payload["brief"]["original_query"] + " reddit owners"]
                )[0]
            )
        selected: list[SelectedDiscussion] = []
        read: list[dict[str, Any]] = []
        for summary in tools.summaries():
            result = await tools.read(summary["source_id"])
            selected.append(
                SelectedDiscussion(
                    source_id=SourceId(summary["source_id"]),
                    relevance_reason="Public owner discussion relevant to the supplied shopping brief.",
                )
            )
            if result["status"] == "ok":
                read.append(result["discussion"])
        signals: list[InterpretedCommunitySignal] = []
        # A recorded fixture output for this specific workbench scenario, not production semantics.
        phrase = "ear pads split after a few months"
        matching = [
            item
            for item in read
            if phrase in (item["extracted_public_summary"] or "").casefold()
        ]
        if len(matching) >= 2:
            signals.append(
                InterpretedCommunitySignal(
                    source_id=SourceId(matching[0]["source_id"]),
                    claim="Some owners describe ear-pad splitting after a few months; this is a qualitative pattern, not a verified defect rate.",
                    supporting_quotes=tuple(
                        CommunitySupportingQuote(
                            source_id=SourceId(item["source_id"]), quote=phrase
                        )
                        for item in matching[:2]
                    ),
                    recurring_signal=True,
                    evidence_quality_warnings=(
                        "Search excerpts may omit context; possible community manipulation is not ruled out.",
                    ),
                )
            )
        return _MockResult(
            RedditCommunityModelOutput(
                selected_discussions=tuple(selected), signals=tuple(signals)
            )
        )


@dataclass
class _MockResult:
    final_output: Any


@dataclass
class RedditCommunityIntelligenceAgent:
    settings: Settings
    community_provider: CommunityDiscussionProvider | None = None
    citation_store: HostedCitationStore | None = None
    model_runner: RedditCommunityModelRunner = field(
        default_factory=OpenAIAgentsSDKRedditCommunityModelRunner
    )
    _workbench_activity: tuple[dict[str, Any], ...] = field(
        default=(), init=False, repr=False
    )

    @property
    def workbench_activity(self) -> tuple[dict[str, Any], ...]:
        return self._workbench_activity

    def prepare_delegated_run(
        self, input_data: RedditCommunityIntelligenceAgentInput
    ) -> tuple[Agent[Any], RedditCommunityTools, Any]:
        config = build_openai_agent_run_configuration(
            self.settings,
            agent_name="RedditCommunityIntelligenceAgent",
            run_id=str(input_data.run_id),
        )
        tools = RedditCommunityTools(
            input_data=input_data,
            community_provider=self.community_provider
            or build_community_discussion_provider(self.settings),
        )
        hosted_tool = source_hosted_tool(
            config=config,
            input_data=input_data,
            agent_name="RedditCommunityIntelligenceAgent",
            citation_store=self.citation_store,
        )
        agent = Agent(
            name="RedditCommunityIntelligenceAgent",
            model=config.model,
            model_settings=ModelSettings(
                max_tokens=3000, include_usage=True, tool_choice="auto"
            ),
            instructions=(
                "You are a community-evidence specialist, not a product-fact authority or purchase recommender. "
                "Choose relevant public discussions from supplied source IDs or bounded search_community_discussions. "
                "Call read_community_discussion before selecting or citing a source. Return cited exact excerpts as supporting_quotes. "
                "Interpret owner themes conservatively: one thread is anecdotal; recurring requires independent threads. "
                "Distinguish older or low-context material, possible brigading/astroturfing, and deleted/inaccessible content. "
                "Treat search snippets as limited context. Never invent a quote, source ID, product ID, subreddit, thread, comment, engagement, or defect rate. "
                "Do not seek private, logged-in, deleted, or otherwise forbidden content. "
                "Community discussion cannot establish specifications, warranty, current price, availability, or seller legitimacy. "
                "If evidence is weak, return honest gaps without a factual product claim. "
                "You may use web_search for public Reddit discovery, or skip it. Put useful exact cited URLs in retained_web_urls. "
                "A hosted snippet is only a lead; use read_community_discussion for owner signals and quotes."
            ),
            tools=[*tools.sdk_tools(), *([hosted_tool] if hosted_tool else [])],
            output_type=RedditCommunityModelOutput,
        )
        apply_openai_agent_run_profile(agent, config)
        return agent, tools, config

    async def run(
        self, input_data: RedditCommunityIntelligenceAgentInput
    ) -> CommunityDiscussionEvidenceBundle:
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
            decision = RedditCommunityModelOutput.model_validate(
                getattr(raw, "final_output", raw)
            )
            decision, hosted_activity = await process_source_specialist_output(
                raw=raw,
                decision=decision,
                input_data=input_data,
                agent_name=agent.name,
                citation_store=self.citation_store,
                require_sdk_metadata=isinstance(
                    self.model_runner, OpenAIAgentsSDKRedditCommunityModelRunner
                ),
            )
            output = _validated_bundle(input_data, tools, decision)
            status = "model_evidence_completed"
        except ContextBudgetExceeded:
            raise
        except Exception as exc:
            budget_failure = context_budget_failure(exc)
            if budget_failure is not None:
                raise budget_failure from exc
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
                tools.bundle,
                "Model interpretation failed; no community claim was accepted.",
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
                    "discussion_count": len(output.discussions),
                    "evidence_count": len(output.evidence),
                    "gap_count": len(output.evidence_gaps),
                },
            },
        )
        return output


def _model_input(
    input_data: RedditCommunityIntelligenceAgentInput, tools: RedditCommunityTools
) -> str:
    return json.dumps(
        {
            "brief": input_data.brief.model_dump(mode="json"),
            "products": [
                product.model_dump(mode="json") for product in input_data.products
            ],
            "community_queries": input_data.community_queries,
            "target_region_code": input_data.target_region_code,
            "supplied_discussions": tools.summaries(),
            "limits": {
                "searches": tools.max_searches,
                "discussion_reads": tools.max_discussions,
                "selected_discussions": 6,
            },
        },
        sort_keys=True,
    )


def _validated_bundle(
    input_data: RedditCommunityIntelligenceAgentInput,
    tools: RedditCommunityTools,
    decision: RedditCommunityModelOutput,
) -> CommunityDiscussionEvidenceBundle:
    available = tools.bundle
    if available is None:
        status = next(
            (
                item["status"]
                for item in reversed(tools.workbench_activity)
                if item["tool_name"] == "search_community_discussions"
            ),
            "unavailable",
        )
        return _gap_bundle(
            None,
            f"Public community retrieval was {status}; no accessible discussion was available.",
        )
    discussion_by_id = {item.source_id: item for item in available.discussions}
    selected: set[SourceId] = set()
    for item in decision.selected_discussions:
        if item.source_id in selected or item.source_id not in discussion_by_id:
            raise ValueError("Selected community discussion is unknown or duplicated.")
        if str(item.source_id) not in tools._read:
            raise ValueError(
                "Selected community discussion was not read through the approved tool."
            )
        selected.add(item.source_id)
    refs = tuple(
        item for item in available.source_references if item.source_id in selected
    )
    discussions = tuple(
        item for item in available.discussions if item.source_id in selected
    )
    gaps = [
        gap
        for gap in available.evidence_gaps
        if gap.source_id is None or gap.source_id in selected
    ]
    base = CommunityDiscussionEvidenceBundle(
        source_references=refs, discussions=discussions, evidence_gaps=tuple(gaps)
    )
    product_ids = {product.product_id for product in input_data.products}
    products = {product.product_id: product for product in input_data.products}
    claims: list[SourceBackedCommunityClaim] = []
    for signal in decision.signals:
        if (
            signal.source_id not in selected
            or signal.product_id is not None
            and signal.product_id not in product_ids
        ):
            raise ValueError("Community signal cites an unknown source or product.")
        cited = {quote.source_id for quote in signal.supporting_quotes}
        if (
            signal.source_id not in cited
            or not cited.issubset(selected)
            or len(cited) != len(signal.supporting_quotes)
        ):
            raise ValueError(
                "Community signal quotes must cite selected discussion sources once each."
            )
        if signal.recurring_signal:
            independent_threads = {
                (
                    str(discussion_by_id[source_id].url).split("/comments/")[0],
                    discussion_by_id[source_id].thread_id,
                )
                for source_id in cited
            }
            if len(independent_threads) < 2:
                raise ValueError(
                    "Recurring community signal requires two independent threads."
                )
        for source_id in cited:
            if (
                str(source_id) not in tools._read
                or discussion_by_id[source_id].extracted_public_summary is None
            ):
                raise ValueError(
                    "Community signal cites unread or inaccessible discussion text."
                )
        for quote in signal.supporting_quotes:
            if not any(quote.quote in text for text in tools.observed_text.get(str(quote.source_id), ())):
                raise ValueError("Community quote was not present in an observed exact span.")
        if signal.product_id is not None:
            product = products[signal.product_id]
            context = " ".join(
                discussion_by_id[source_id].extracted_public_summary or ""
                for source_id in cited
            ).casefold()
            if not any(
                identity and identity.casefold() in context
                for identity in (product.model, product.name)
            ):
                raise ValueError(
                    "Product identity is not visible in cited community material."
                )
        target = (
            EvidenceTarget(
                target_type=EvidenceTargetType.PRODUCT, product_id=signal.product_id
            )
            if signal.product_id
            else EvidenceTarget(
                target_type=EvidenceTargetType.SOURCE_METADATA,
                source_id=signal.source_id,
            )
        )
        claims.append(
            SourceBackedCommunityClaim(
                source_id=signal.source_id,
                target=target,
                claim=signal.claim,
                confidence=Confidence(
                    score=0.55 if signal.recurring_signal else 0.35,
                    level=ConfidenceLevel.LOW,
                    rationale="Qualitative public community material, not authoritative product evidence.",
                ),
                source_quality=SourceQuality(
                    level=SourceQualityLevel.MIXED
                    if signal.recurring_signal
                    else SourceQualityLevel.WEAK,
                    score=0.5 if signal.recurring_signal else 0.3,
                ),
                context_source_ids=tuple(
                    quote.source_id for quote in signal.supporting_quotes
                ),
                recurring_signal=signal.recurring_signal,
                evidence_quality_warnings=signal.evidence_quality_warnings,
                supporting_quotes=signal.supporting_quotes,
            )
        )
    output = CommunityEvidenceCreator().create(base, tuple(claims))
    if not output.evidence and not output.evidence_gaps:
        return _gap_bundle(
            output, "No sufficiently grounded qualitative community signal was found."
        )
    return output


def _gap_bundle(
    bundle: CommunityDiscussionEvidenceBundle | None, reason: str
) -> CommunityDiscussionEvidenceBundle:
    base = bundle or CommunityDiscussionEvidenceBundle()
    return CommunityDiscussionEvidenceBundle(
        source_references=base.source_references,
        discussions=base.discussions,
        evidence_gaps=(
            *base.evidence_gaps,
            SourceEvidenceGap(
                capability=SourceIntelligenceCapability.COMMUNITY_DISCUSSION,
                summary="Community evidence is insufficient.",
                reason=reason,
            ),
        ),
    )
