"""Bounded SDK manager delegating source research to real specialist agents."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from agents import Agent, MaxTurnsExceeded, ModelSettings, RunConfig
from pydantic import Field

from app.agents.context_management import (
    BoundedRunner,
    ContextBudgetExceeded,
    context_budget_failure,
    active_budget,
    context_events,
    managed_source_context,
    source_bundle_context,
)
from app.agents.contracts import (
    AmazonProductIntelligenceAgentInput,
    IKEAStoreIntelligenceAgentInput,
    RedditCommunityIntelligenceAgentInput,
    YouTubeReviewIntelligenceAgentInput,
)
from app.agents.live_amazon_product_intelligence import (
    AmazonProductIntelligenceAgent,
    AmazonProductModelOutput,
    _model_input as amazon_input,
    _validated_bundle as validate_amazon,
)
from app.agents.live_ikea_store_intelligence import (
    IKEAStoreIntelligenceAgent,
    IKEAStoreModelOutput,
    _validated_bundle as validate_ikea,
)
from app.agents.live_reddit_community_intelligence import (
    RedditCommunityIntelligenceAgent,
    RedditCommunityModelOutput,
    _model_input as reddit_input,
    _validated_bundle as validate_reddit,
)
from app.agents.live_youtube_review_intelligence import (
    YouTubeReviewIntelligenceAgent,
    YouTubeReviewModelOutput,
    _model_input as youtube_input,
    _validated_bundle as validate_youtube,
)
from app.agents.openai_config import (
    OpenAIAgentConfigurationError,
    OpenAIAgentRuntimeMode,
    apply_openai_agent_run_profile,
    build_openai_agent_run_configuration,
)
from app.agents.research_tools import HostedCitationStore
from app.agents.source_hosted_search import (
    process_source_specialist_output,
    source_tool_activity,
)
from app.core.settings import Settings
from app.providers import (
    AmazonProductIntelligenceProvider,
    CommunityDiscussionProvider,
    IKEAStoreIntelligenceProvider,
    TranscriptProvider,
    VideoSearchProvider,
)
from app.schemas.base import CartCartBaseModel
from app.schemas.ids import RunId
from app.schemas.intake import ShoppingBrief
from app.schemas.products import CanonicalProduct, ProductListing
from app.schemas.regions import RegionCode
from app.schemas.search_sources import (
    AmazonProductEvidenceBundle,
    CommunityDiscussionEvidenceBundle,
    IKEAStoreEvidenceBundle,
    SourceEvidenceGap,
    SourceIntelligenceCapability,
    SourceSnapshot,
    VideoReviewEvidenceBundle,
)


_NAMES = {
    SourceIntelligenceCapability.VIDEO_REVIEW: "YouTubeReviewIntelligenceAgent",
    SourceIntelligenceCapability.COMMUNITY_DISCUSSION: "RedditCommunityIntelligenceAgent",
    SourceIntelligenceCapability.AMAZON_PRODUCT_LISTING_REVIEW: "AmazonProductIntelligenceAgent",
    SourceIntelligenceCapability.IKEA_REGIONAL_OFFICIAL_STORE: "IKEAStoreIntelligenceAgent",
}
_MAX_MANAGER_USAGE_TOKENS = 30_000
_MAX_PARENT_TURNS = 15
_MAX_SPECIALIST_TURNS = 12
_MAX_PARENT_SECONDS = 90


class SkippedSource(CartCartBaseModel):
    capability: SourceIntelligenceCapability
    reason: str = Field(min_length=1, max_length=500)


class SourceManagerDecision(CartCartBaseModel):
    skipped_sources: tuple[SkippedSource, ...] = Field(
        default_factory=tuple, max_length=4
    )
    summary: str = Field(min_length=1, max_length=700)


class SourceManagerModelRunner(Protocol):
    async def run(
        self,
        agent: Agent[Any],
        model_input: str,
        *,
        run_config: RunConfig,
        max_turns: int,
    ) -> Any: ...


@dataclass
class OpenAIAgentsSDKSourceManagerRunner:
    async def run(
        self,
        agent: Agent[Any],
        model_input: str,
        *,
        run_config: RunConfig,
        max_turns: int,
    ) -> Any:
        return await BoundedRunner.run(
            agent, model_input, run_config=run_config, max_turns=max_turns
        )


@dataclass(frozen=True)
class SourceManagerInput:
    run_id: RunId
    brief: ShoppingBrief
    products: tuple[CanonicalProduct, ...]
    listings: tuple[ProductListing, ...]
    source_snapshots: tuple[SourceSnapshot, ...]
    query_hints: tuple[str, ...]
    region_code: RegionCode
    allowed_capabilities: tuple[SourceIntelligenceCapability, ...]


@dataclass(frozen=True)
class SourceManagerResult:
    video_bundles: tuple[VideoReviewEvidenceBundle, ...] = ()
    community_bundles: tuple[CommunityDiscussionEvidenceBundle, ...] = ()
    amazon_bundles: tuple[AmazonProductEvidenceBundle, ...] = ()
    ikea_bundles: tuple[IKEAStoreEvidenceBundle, ...] = ()
    notes: tuple[str, ...] = ()
    activity: tuple[dict[str, Any], ...] = ()
    model_name: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


@dataclass
class SourceIntelligenceManagerAgent:
    settings: Settings
    video_provider: VideoSearchProvider | None = None
    transcript_provider: TranscriptProvider | None = None
    community_provider: CommunityDiscussionProvider | None = None
    amazon_provider: AmazonProductIntelligenceProvider | None = None
    ikea_provider: IKEAStoreIntelligenceProvider | None = None
    citation_store_factory: Callable[[RunId], HostedCitationStore] | None = None
    model_runner: SourceManagerModelRunner = field(
        default_factory=OpenAIAgentsSDKSourceManagerRunner
    )

    @managed_source_context
    async def run(self, input_data: SourceManagerInput) -> SourceManagerResult:
        budget = active_budget()
        context_start = len(budget.events) if budget else 0
        spent_start = budget.spent if budget else 0
        config = build_openai_agent_run_configuration(
            self.settings,
            agent_name="SourceIntelligenceManagerAgent",
            run_id=str(input_data.run_id),
        )
        if (
            config.mode == OpenAIAgentRuntimeMode.LIVE
            and self.citation_store_factory is None
        ):
            raise OpenAIAgentConfigurationError(
                "Live source specialists require run-scoped hosted citation persistence."
            )
        if len(input_data.products) > 3 or len(input_data.allowed_capabilities) > 4:
            raise ValueError("Source manager candidate or capability budget exceeded.")
        if len(set(input_data.allowed_capabilities)) != len(
            input_data.allowed_capabilities
        ):
            raise ValueError("Source manager capabilities must be unique.")

        captured: dict[SourceIntelligenceCapability, Any] = {}
        attempted: set[SourceIntelligenceCapability] = set()
        failures: list[str] = []
        activity: list[dict[str, Any]] = []
        nested_models: dict[SourceIntelligenceCapability, str] = {}
        source_states: dict[SourceIntelligenceCapability, Any] = {}
        citation_store = (
            self.citation_store_factory(input_data.run_id)
            if config.mode == OpenAIAgentRuntimeMode.LIVE
            and self.citation_store_factory is not None
            else None
        )
        tools = []
        for capability in input_data.allowed_capabilities:
            specialist, specialist_input = self._specialist(
                capability, input_data, citation_store
            )
            sdk_agent, source_tools, nested_config = specialist.prepare_delegated_run(
                specialist_input
            )
            nested_models[capability] = nested_config.model
            source_states[capability] = source_tools
            model_input = self._specialist_input(
                capability, specialist_input, source_tools
            )

            def build_input(
                options: Any,
                *,
                base: str = model_input,
                cap: SourceIntelligenceCapability = capability,
            ) -> str:
                if cap in attempted or len(attempted) >= 4:
                    raise ValueError(
                        "Source specialist may be called only once per run."
                    )
                attempted.add(cap)
                params = (
                    options.get("params", {})
                    if isinstance(options, dict)
                    else getattr(options, "params", {})
                )
                reason = params.get("input", "") if isinstance(params, dict) else ""
                context = json.loads(base)
                context["delegation_reason"] = str(reason)[:400]
                return json.dumps(context, sort_keys=True)

            async def extract(
                raw: Any,
                *,
                cap: SourceIntelligenceCapability = capability,
                supplied: Any = specialist_input,
                state: Any = source_tools,
                model: str = nested_config.model,
                limit: int = min(nested_config.max_turns, _MAX_SPECIALIST_TURNS),
                name: str = sdk_agent.name,
                source_agent: Any = specialist,
            ) -> str:
                if cap in captured:
                    raise ValueError("Duplicate source specialist invocation.")
                try:
                    output_models: dict[
                        SourceIntelligenceCapability, type[CartCartBaseModel]
                    ] = {
                        SourceIntelligenceCapability.VIDEO_REVIEW: YouTubeReviewModelOutput,
                        SourceIntelligenceCapability.COMMUNITY_DISCUSSION: RedditCommunityModelOutput,
                        SourceIntelligenceCapability.AMAZON_PRODUCT_LISTING_REVIEW: AmazonProductModelOutput,
                        SourceIntelligenceCapability.IKEA_REGIONAL_OFFICIAL_STORE: IKEAStoreModelOutput,
                    }
                    output_model = output_models[cap].model_validate(raw.final_output)
                    (
                        output_model,
                        hosted_activity,
                    ) = await process_source_specialist_output(
                        raw=raw,
                        decision=output_model,
                        input_data=supplied,
                        agent_name=name,
                        citation_store=source_agent.citation_store,
                        require_sdk_metadata=True,
                    )
                    activity.extend(hosted_activity)
                    output = self._validate(cap, supplied, state, output_model)
                    captured[cap] = output
                    status = "validated"
                    result: dict[str, Any] = {"bundle": source_bundle_context(output)}
                except ContextBudgetExceeded:
                    raise
                except Exception as exc:
                    budget_failure = context_budget_failure(exc)
                    if budget_failure is not None:
                        raise budget_failure from exc
                    if isinstance(exc, OpenAIAgentConfigurationError):
                        activity.append(
                            {
                                "tool_name": "web_search",
                                "status": "configuration_or_persistence_failed",
                                "input": {"agent": name},
                                "output": {"reason": str(exc)},
                            }
                        )
                    captured[cap] = self._gap_bundle(
                        cap,
                        "Nested agent output failed validation or source retrieval.",
                    )
                    failures.append(
                        f"{cap.value}: specialist evidence unavailable or invalid."
                    )
                    status = "evidence_gap"
                    result = {
                        "evidence_gap": "Nested source evidence was unavailable or invalid."
                    }
                nested_events = tuple(
                    item
                    for item in context_events(context_start)
                    if item["input"].get("agent") == name
                )
                nested_usage = {
                    field: sum(item["output"][key] for item in nested_events)
                    if nested_events
                    and all(
                        item["output"].get(key) is not None for item in nested_events
                    )
                    else None
                    for field, key in (
                        ("input_tokens", "actual_input_tokens"),
                        ("output_tokens", "actual_output_tokens"),
                    )
                }
                nested_input, nested_output = (
                    nested_usage["input_tokens"],
                    nested_usage["output_tokens"],
                )
                nested_usage["total_tokens"] = (
                    nested_input + nested_output
                    if nested_input is not None and nested_output is not None
                    else None
                )
                activity.append(
                    {
                        "tool_name": "agent_as_tool",
                        "status": status,
                        "input": {
                            "parent_agent": "SourceIntelligenceManagerAgent",
                            "agent": name,
                            "model": model,
                            "max_turns": limit,
                            "capability": cap.value,
                        },
                        "output": {
                            "source_evidence": [
                                {
                                    "source_id": str(item.source_id),
                                    "evidence_id": str(item.evidence_id),
                                }
                                for item in getattr(captured[cap], "evidence", ())
                            ],
                            "source_ids": [
                                str(ref.source_id)
                                for ref in getattr(
                                    captured[cap], "source_references", ()
                                )
                            ],
                            **nested_usage,
                            "trace_id": getattr(raw, "trace_id", None),
                        },
                    }
                )
                activity.extend(source_tool_activity(state.workbench_activity, name))
                return json.dumps(result, sort_keys=True)

            tools.append(
                sdk_agent.as_tool(
                    tool_name=f"consult_{capability.value}",
                    tool_description=f"Delegate bounded {capability.value} evidence research to {sdk_agent.name}; call only when relevant to the supplied products and region.",
                    custom_output_extractor=extract,
                    input_builder=build_input,
                    is_enabled=lambda context, _agent, cap=capability: (
                        cap not in attempted
                        and getattr(context.usage, "total_tokens", 0)
                        < _MAX_MANAGER_USAGE_TOKENS
                    ),
                    max_turns=min(nested_config.max_turns, _MAX_SPECIALIST_TURNS),
                    failure_error_function=None,
                )
            )

        parent = Agent(
            name="SourceIntelligenceManagerAgent",
            model=config.model,
            model_settings=ModelSettings(max_tokens=1500, include_usage=True),
            instructions=(
                "You organize optional shopping-source evidence after products have been deduplicated. "
                "Choose only relevant source specialists from the supplied tools; each may be called at most once. "
                "YouTube covers review videos, Reddit qualitative owner discussions, Amazon marketplace offers, and IKEA official regional items. "
                "Do not call a source just because it is available. Consider the product type and region, especially for IKEA. "
                "Use returned cited bundles only; never invent source, evidence, product, seller, price, or availability facts. "
                "After delegating, give a concise summary and a reason for every available source you skipped. "
                "The backend, not your summary, decides which validated evidence is persisted and passed downstream."
            ),
            tools=tools,
            output_type=SourceManagerDecision,
        )
        apply_openai_agent_run_profile(parent, config)
        run_config = RunConfig(
            tracing_disabled=not config.tracing_enabled,
            trace_include_sensitive_data=config.trace_include_sensitive_data,
            workflow_name=config.trace_workflow_name,
            trace_metadata=config.trace_metadata,
        )
        notes = []
        raw = None
        completed = False
        try:
            raw = await asyncio.wait_for(
                self.model_runner.run(
                    parent,
                    json.dumps(
                        {
                            "brief": input_data.brief.model_dump(mode="json"),
                            "region": input_data.region_code,
                            "products": [
                                p.model_dump(mode="json") for p in input_data.products
                            ],
                            "available_specialists": [
                                cap.value for cap in input_data.allowed_capabilities
                            ],
                            "limits": {
                                "specialist_calls": len(tools),
                                "parent_turns": min(
                                    config.max_turns, _MAX_PARENT_TURNS
                                ),
                                "shared_usage_tokens": _MAX_MANAGER_USAGE_TOKENS,
                            },
                        },
                        sort_keys=True,
                    ),
                    run_config=run_config,
                    max_turns=min(config.max_turns, _MAX_PARENT_TURNS),
                ),
                timeout=min(config.timeout_seconds, _MAX_PARENT_SECONDS),
            )
            usage = getattr(getattr(raw, "context_wrapper", None), "usage", None)
            total_tokens = (
                budget.spent - spent_start
                if budget is not None and context_events(context_start)
                else getattr(usage, "total_tokens", 0) or 0
            )
            if total_tokens > _MAX_MANAGER_USAGE_TOKENS:
                raise ContextBudgetExceeded("Source manager exceeded its token budget.")
            decision = SourceManagerDecision.model_validate(
                getattr(raw, "final_output", raw)
            )
            skipped = {
                item.capability: item.reason for item in decision.skipped_sources
            }
            if len(skipped) != len(decision.skipped_sources):
                raise ValueError("Manager skip reasons must be unique by source.")
            if any(
                cap not in input_data.allowed_capabilities or cap in attempted
                for cap in skipped
            ):
                raise ValueError(
                    "Manager skipped-source output contradicts tool activity."
                )
            if set(skipped) != set(input_data.allowed_capabilities) - attempted:
                raise ValueError("Manager must explain every skipped source.")
            notes.append(decision.summary)
            for cap in input_data.allowed_capabilities:
                if cap not in attempted:
                    notes.append(f"{cap.value} skipped: {skipped[cap]}")
            completed = True
        except ContextBudgetExceeded:
            raise
        except Exception as exc:
            budget_failure = context_budget_failure(exc)
            if budget_failure is not None:
                raise budget_failure from exc
            if isinstance(exc, MaxTurnsExceeded):
                last_agent = getattr(
                    getattr(getattr(exc, "run_data", None), "last_agent", None),
                    "name",
                    "unknown",
                )
                notes.append(
                    f"Source agent turn limit exhausted ({exc}); last SDK agent: "
                    f"{last_agent}. No unvalidated source evidence was accepted."
                )
            else:
                notes.append(
                    f"Source manager model failed ({type(exc).__name__}); no unvalidated source evidence was accepted."
                )
            for cap in input_data.allowed_capabilities:
                if cap not in captured:
                    if cap in attempted:
                        activity.append(
                            {
                                "tool_name": "agent_as_tool",
                                "status": "model_or_provider_failed",
                                "input": {
                                    "parent_agent": "SourceIntelligenceManagerAgent",
                                    "agent": _NAMES[cap],
                                    "model": nested_models[cap],
                                    "capability": cap.value,
                                },
                                "output": {"source_evidence": []},
                            }
                        )
                        activity.extend(
                            source_tool_activity(
                                source_states[cap].workbench_activity, _NAMES[cap]
                            )
                        )
                    captured[cap] = self._gap_bundle(
                        cap,
                        "Specialist model or provider failed."
                        if cap in attempted
                        else "Source manager failed before delegating this source.",
                    )
        activity.insert(
            0,
            {
                "tool_name": "openai_agents_manager",
                "status": "completed" if completed else "model_or_validation_failure",
                "input": {
                    "agent": parent.name,
                    "model": config.model,
                    "max_turns": min(config.max_turns, _MAX_PARENT_TURNS),
                    "available_tools": [t.name for t in tools],
                },
                "output": {
                    "called_specialists": [
                        _NAMES[cap]
                        for cap in input_data.allowed_capabilities
                        if cap in attempted
                    ]
                },
            },
        )
        usage = getattr(getattr(raw, "context_wrapper", None), "usage", None)
        events = context_events(context_start)
        actual_usage = {
            field: sum(item["output"][key] for item in events)
            if events and all(item["output"].get(key) is not None for item in events)
            else None
            if events
            else getattr(usage, field, None)
            for field, key in (
                ("input_tokens", "actual_input_tokens"),
                ("output_tokens", "actual_output_tokens"),
            )
        }
        actual_input, actual_output = (
            actual_usage["input_tokens"],
            actual_usage["output_tokens"],
        )
        actual_usage["total_tokens"] = (
            actual_input + actual_output
            if actual_input is not None and actual_output is not None
            else None
        )
        notes.extend(failures)
        return SourceManagerResult(
            video_bundles=tuple(
                v
                for k, v in captured.items()
                if k == SourceIntelligenceCapability.VIDEO_REVIEW and v is not None
            ),
            community_bundles=tuple(
                v
                for k, v in captured.items()
                if k == SourceIntelligenceCapability.COMMUNITY_DISCUSSION
                and v is not None
            ),
            amazon_bundles=tuple(
                v
                for k, v in captured.items()
                if k == SourceIntelligenceCapability.AMAZON_PRODUCT_LISTING_REVIEW
                and v is not None
            ),
            ikea_bundles=tuple(
                v
                for k, v in captured.items()
                if k == SourceIntelligenceCapability.IKEA_REGIONAL_OFFICIAL_STORE
                and v is not None
            ),
            notes=tuple(notes),
            activity=tuple(activity),
            model_name=config.model,
            input_tokens=actual_usage["input_tokens"],
            output_tokens=actual_usage["output_tokens"],
            total_tokens=actual_usage["total_tokens"],
        )

    def _specialist(
        self,
        capability: SourceIntelligenceCapability,
        data: SourceManagerInput,
        citation_store: HostedCitationStore | None = None,
    ) -> tuple[Any, Any]:
        common: dict[str, Any] = dict(
            run_id=data.run_id,
            brief=data.brief,
            products=data.products,
            listings=data.listings,
            source_snapshots=data.source_snapshots,
        )
        if capability == SourceIntelligenceCapability.VIDEO_REVIEW:
            return YouTubeReviewIntelligenceAgent(
                self.settings,
                self.video_provider,
                self.transcript_provider,
                citation_store=citation_store,
            ), YouTubeReviewIntelligenceAgentInput(
                **common,
                video_queries=data.query_hints,
                target_region_code=data.region_code,
            )
        if capability == SourceIntelligenceCapability.COMMUNITY_DISCUSSION:
            return RedditCommunityIntelligenceAgent(
                self.settings, self.community_provider, citation_store=citation_store
            ), RedditCommunityIntelligenceAgentInput(
                **common,
                community_queries=data.query_hints,
                target_region_code=data.region_code,
            )
        if capability == SourceIntelligenceCapability.AMAZON_PRODUCT_LISTING_REVIEW:
            return AmazonProductIntelligenceAgent(
                self.settings, self.amazon_provider, citation_store=citation_store
            ), AmazonProductIntelligenceAgentInput(
                **common,
                product_queries=data.query_hints,
                target_region_code=data.region_code,
            )
        if capability == SourceIntelligenceCapability.IKEA_REGIONAL_OFFICIAL_STORE:
            return IKEAStoreIntelligenceAgent(
                self.settings, self.ikea_provider, citation_store=citation_store
            ), IKEAStoreIntelligenceAgentInput(
                **common,
                product_queries=data.query_hints,
                target_region_code=data.region_code,
            )
        raise ValueError("Unapproved source specialist capability.")

    @staticmethod
    def _specialist_input(
        capability: SourceIntelligenceCapability, supplied: Any, tools: Any
    ) -> str:
        if capability == SourceIntelligenceCapability.VIDEO_REVIEW:
            return youtube_input(supplied, tools)
        if capability == SourceIntelligenceCapability.COMMUNITY_DISCUSSION:
            return reddit_input(supplied, tools)
        if capability == SourceIntelligenceCapability.AMAZON_PRODUCT_LISTING_REVIEW:
            return amazon_input(supplied, tools)
        return json.dumps(
            {
                "brief": supplied.brief.model_dump(mode="json"),
                "region": tools.region,
                "products": tools.product_summaries(),
                "product_queries": supplied.product_queries,
                "official_snapshots": tools.snapshot_summaries(),
                "limits": {"searches": tools.max_searches, "reads": tools.max_reads},
            },
            sort_keys=True,
        )

    @staticmethod
    def _validate(
        capability: SourceIntelligenceCapability, supplied: Any, tools: Any, output: Any
    ) -> Any:
        if capability == SourceIntelligenceCapability.VIDEO_REVIEW:
            return validate_youtube(
                supplied, tools, YouTubeReviewModelOutput.model_validate(output)
            )
        if capability == SourceIntelligenceCapability.COMMUNITY_DISCUSSION:
            return validate_reddit(
                supplied, tools, RedditCommunityModelOutput.model_validate(output)
            )
        if capability == SourceIntelligenceCapability.AMAZON_PRODUCT_LISTING_REVIEW:
            return validate_amazon(
                tools, AmazonProductModelOutput.model_validate(output)
            )
        return validate_ikea(tools, IKEAStoreModelOutput.model_validate(output))

    @staticmethod
    def _gap_bundle(capability: SourceIntelligenceCapability, reason: str) -> Any:
        gap = SourceEvidenceGap(
            capability=capability, summary="Source evidence unavailable.", reason=reason
        )
        if capability == SourceIntelligenceCapability.COMMUNITY_DISCUSSION:
            return CommunityDiscussionEvidenceBundle(evidence_gaps=(gap,))
        if capability == SourceIntelligenceCapability.AMAZON_PRODUCT_LISTING_REVIEW:
            return AmazonProductEvidenceBundle(evidence_gaps=(gap,))
        if capability == SourceIntelligenceCapability.IKEA_REGIONAL_OFFICIAL_STORE:
            return IKEAStoreEvidenceBundle(evidence_gaps=(gap,))
        return VideoReviewEvidenceBundle(transcript_gap_notes=(reason,))
