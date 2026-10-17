"""Bounded SDK manager delegating source research to real specialist agents."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from agents import Agent, MaxTurnsExceeded, ModelSettings, RunConfig
from pydantic import Field

from app.agents.token_policy import SOURCE_START_TOKENS, scaled_tokens
from app.agents.source_consultation import (
    SourceConsultationCheckpoint,
    SourceConsultationOutcome,
    safe_failure,
)
from app.agents.context_management import (
    BoundedRunner,
    ContextBudgetExceeded,
    context_budget_failure,
    active_budget,
    context_events,
    managed_source_context,
    funded_scope_limit,
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
from app.agents.research_history import tracked_tools
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
_MAX_MANAGER_USAGE_TOKENS = SOURCE_START_TOKENS
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
    reuse_key: str | None = None
    owner_request: dict[str, str | None] | None = None


@dataclass(frozen=True)
class SourceManagerResult:
    outcome: SourceConsultationOutcome = field(
        default_factory=SourceConsultationOutcome
    )
    prior_usage: tuple[dict[str, Any], ...] = ()
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

        checkpoint = (
            SourceConsultationCheckpoint(
                self.settings.resolved_artifact_dir,
                str(input_data.run_id),
                self._compatibility(input_data),
            )
            if input_data.reuse_key is not None
            else None
        )
        saved = checkpoint.load() if checkpoint is not None else None
        bundle_models = {
            SourceIntelligenceCapability.VIDEO_REVIEW: VideoReviewEvidenceBundle,
            SourceIntelligenceCapability.COMMUNITY_DISCUSSION: CommunityDiscussionEvidenceBundle,
            SourceIntelligenceCapability.AMAZON_PRODUCT_LISTING_REVIEW: AmazonProductEvidenceBundle,
            SourceIntelligenceCapability.IKEA_REGIONAL_OFFICIAL_STORE: IKEAStoreEvidenceBundle,
        }
        captured: dict[SourceIntelligenceCapability, Any] = {
            SourceIntelligenceCapability(key): bundle_models[
                SourceIntelligenceCapability(key)
            ].model_validate(value)
            for key, value in (saved or {}).get("validated_bundles", {}).items()
        }
        validated = {
            cap for cap, bundle in captured.items() if self._substantive(bundle)
        }
        accepted = set(captured)
        prior_usage = tuple((saved or {}).get("attempt_usage", ()))
        prior_diagnostics = tuple((saved or {}).get("diagnostics", ()))
        diagnostics: list[dict[str, str]] = []
        outcome = SourceConsultationOutcome()
        attempt_finalized = False
        reused_completion = bool(saved) and set(
            input_data.allowed_capabilities
        ).issubset(validated)
        attempted: set[SourceIntelligenceCapability] = set()
        delivered: set[SourceIntelligenceCapability] = set()
        failures: list[str] = []
        activity: list[dict[str, Any]] = []
        nested_models: dict[SourceIntelligenceCapability, str] = {}
        source_states: dict[SourceIntelligenceCapability, Any] = {}
        activity_offsets: dict[SourceIntelligenceCapability, int] = {}
        citation_store = (
            self.citation_store_factory(input_data.run_id)
            if config.mode == OpenAIAgentRuntimeMode.LIVE
            and self.citation_store_factory is not None
            else None
        )

        def save_progress() -> None:
            if checkpoint is None:
                return
            saved_outcome = outcome
            if outcome.status == "interrupted" and any(
                self._substantive(bundle) for bundle in captured.values()
            ):
                saved_outcome = outcome.model_copy(update={"status": "partial"})
            checkpoint.save(
                {
                    "input": self._saved_input(input_data),
                    "outcome": saved_outcome.model_dump(mode="json"),
                    "notes": list(notes),
                    "attempted_capabilities": sorted(
                        set((saved or {}).get("attempted_capabilities", ()))
                        | {cap.value for cap in attempted}
                    ),
                    "validated_bundles": {
                        cap.value: bundle.model_dump(mode="json")
                        for cap, bundle in captured.items()
                        if cap in accepted
                    },
                    "tool_states": {
                        **(saved or {}).get("tool_states", {}),
                        **{
                            cap.value: state.dump_state()
                            for cap, state in source_states.items()
                            if callable(getattr(state, "dump_state", None))
                        },
                    },
                    "diagnostics": [*prior_diagnostics, *diagnostics],
                    "attempt_usage": [
                        *prior_usage,
                        *(
                            []
                            if reused_completion
                            else [
                                {
                                    "charged_tokens": budget.spent - spent_start
                                    if budget is not None
                                    else None,
                                    "input_tokens": self._recorded_usage(
                                        context_start, "actual_input_tokens"
                                    ),
                                    "output_tokens": self._recorded_usage(
                                        context_start, "actual_output_tokens"
                                    ),
                                    "finalized": attempt_finalized,
                                    "usage_complete": attempt_finalized
                                    and self._recorded_usage(
                                        context_start, "actual_input_tokens"
                                    )
                                    is not None
                                    and self._recorded_usage(
                                        context_start, "actual_output_tokens"
                                    )
                                    is not None,
                                    "unknown_in_flight_possible": not attempt_finalized,
                                    "recorded_charge_is_lower_bound": not attempt_finalized,
                                    "accounting": "ordinary admitted attempt; prior work is not charged again",
                                }
                            ]
                        ),
                    ],
                    "accounting": "Each explicitly admitted invocation uses its ordinary attempt budget. Saved provider operations remain consumed.",
                }
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
            saved_state = (saved or {}).get("tool_states", {}).get(capability.value)
            if saved_state is not None and callable(
                getattr(source_tools, "restore_state", None)
            ):
                source_tools.restore_state(saved_state)
            activity_offsets[capability] = len(source_tools.workbench_activity)
            if hasattr(source_tools, "checkpoint"):
                source_tools.checkpoint = save_progress
            if capability in validated:
                continue
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
                        "Source specialist may be called only once per admitted consultation attempt."
                    )
                attempted.add(cap)
                save_progress()
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
                if cap in delivered:
                    raise ValueError("Duplicate source specialist invocation.")
                delivered.add(cap)
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
                    accepted.add(cap)
                    if self._substantive(output):
                        validated.add(cap)
                    save_progress()
                    status = "validated"
                    result: dict[str, Any] = {"bundle": source_bundle_context(output)}
                except asyncio.CancelledError as exc:
                    diagnostics.append(safe_failure(exc, phase="specialist_output"))
                    save_progress()
                    raise
                except ContextBudgetExceeded as exc:
                    diagnostics.append(safe_failure(exc, phase="specialist_output"))
                    save_progress()
                    raise
                except Exception as exc:
                    budget_failure = context_budget_failure(exc)
                    if budget_failure is not None:
                        raise budget_failure from exc
                    diagnostics.append(safe_failure(exc, phase="specialist_output"))
                    if isinstance(exc, OpenAIAgentConfigurationError):
                        activity.append(
                            {
                                "tool_name": "web_search",
                                "status": "configuration_or_persistence_failed",
                                "input": {"agent": name},
                                "output": safe_failure(exc, phase="specialist_output"),
                            }
                        )
                    captured[cap] = self._retained_or_gap(
                        cap,
                        state,
                        "Nested agent output failed validation or source retrieval.",
                    )
                    save_progress()
                    failures.append(
                        f"{cap.value}: specialist evidence unavailable or invalid."
                    )
                    status = "evidence_gap"
                    result = {
                        "evidence_gap": "Nested source evidence was unavailable or invalid.",
                        "failure": diagnostics[-1],
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
                            "diagnostics": list(diagnostics),
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
                        < funded_scope_limit("source", SOURCE_START_TOKENS)
                    ),
                    max_turns=min(nested_config.max_turns, _MAX_SPECIALIST_TURNS),
                    failure_error_function=None,
                )
            )

        parent = Agent(
            name="SourceIntelligenceManagerAgent",
            model=config.model,
            model_settings=ModelSettings(
                max_tokens=scaled_tokens(1500), include_usage=True
            ),
            instructions=(
                "You organize optional shopping-source evidence after products have been deduplicated. "
                "Choose only relevant source specialists from the supplied tools; each may be called at most once. "
                "YouTube covers review videos, Reddit qualitative owner discussions, Amazon marketplace offers, and IKEA official regional items. "
                "Do not call a source just because it is available. Consider the product type and region, especially for IKEA. "
                "Use returned cited bundles only; never invent source, evidence, product, seller, price, or availability facts. "
                "After delegating, give a concise summary and a reason for every available source you skipped. "
                "The backend, not your summary, decides which validated evidence is persisted and passed downstream."
            ),
            tools=list(tracked_tools(tuple(tools), include_controls=True)),
            output_type=SourceManagerDecision,
        )
        apply_openai_agent_run_profile(parent, config)
        run_config = RunConfig(
            tracing_disabled=not config.tracing_enabled,
            trace_include_sensitive_data=config.trace_include_sensitive_data,
            workflow_name=config.trace_workflow_name,
            trace_metadata=config.trace_metadata,
        )
        notes = list((saved or {}).get("notes", ()))
        raw = None
        completed = False
        reused_completion = bool(saved) and set(
            input_data.allowed_capabilities
        ).issubset(validated)
        try:
            if reused_completion:
                raw = None
                completed = True
            else:
                outcome = SourceConsultationOutcome(status="interrupted")
                save_progress()
                raw = await asyncio.wait_for(
                    self.model_runner.run(
                        parent,
                        json.dumps(
                            {
                                "brief": input_data.brief.model_dump(mode="json"),
                                "region": input_data.region_code,
                                "products": [
                                    p.model_dump(mode="json")
                                    for p in input_data.products
                                ],
                                "available_specialists": [
                                    cap.value
                                    for cap in input_data.allowed_capabilities
                                    if cap not in validated
                                ],
                                "completed_specialists": [
                                    cap.value for cap in validated
                                ],
                                "limits": {
                                    "specialist_calls": len(tools),
                                    "parent_turns": min(
                                        config.max_turns, _MAX_PARENT_TURNS
                                    ),
                                    "starting_usage_tokens": _MAX_MANAGER_USAGE_TOKENS,
                                    "funded_usage_tokens": funded_scope_limit(
                                        "source", SOURCE_START_TOKENS
                                    ),
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
                if not context_events(
                    context_start
                ) and total_tokens > funded_scope_limit("source", SOURCE_START_TOKENS):
                    raise ContextBudgetExceeded(
                        "Source manager exceeded its token budget."
                    )
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
                if (
                    set(skipped)
                    != set(input_data.allowed_capabilities) - attempted - validated
                ):
                    raise ValueError("Manager must explain every skipped source.")
                notes.append(decision.summary)
                for cap in input_data.allowed_capabilities:
                    if cap not in attempted and cap not in validated:
                        notes.append(f"{cap.value} skipped: {skipped[cap]}")
                completed = True
        except asyncio.CancelledError as exc:
            attempt_finalized = True
            diagnostics.append(safe_failure(exc, phase="source_manager"))
            outcome = self._outcome(
                captured,
                attempted,
                diagnostics,
                source_states,
                activity_offsets=activity_offsets,
                interrupted=True,
            )
            save_progress()
            raise
        except ContextBudgetExceeded as exc:
            attempt_finalized = True
            diagnostics.append(safe_failure(exc, phase="source_manager"))
            outcome = self._outcome(
                captured,
                attempted,
                diagnostics,
                source_states,
                activity_offsets=activity_offsets,
            )
            save_progress()
            raise
        except Exception as exc:
            diagnostics.append(safe_failure(exc, phase="source_manager"))
            budget_failure = context_budget_failure(exc)
            if budget_failure is not None:
                attempt_finalized = True
                outcome = self._outcome(
                    captured,
                    attempted,
                    diagnostics,
                    source_states,
                    activity_offsets=activity_offsets,
                )
                save_progress()
                raise budget_failure from exc
            if isinstance(exc, MaxTurnsExceeded):
                last_agent = getattr(
                    getattr(getattr(exc, "run_data", None), "last_agent", None),
                    "name",
                    "unknown",
                )
                notes.append(
                    "Source agent turn limit exhausted; last SDK agent: "
                    f"{last_agent}. No unvalidated source evidence was accepted."
                )
            else:
                notes.append(
                    f"Source manager model failed ({type(exc).__name__}); no unvalidated source evidence was accepted."
                )
            for cap in input_data.allowed_capabilities:
                if cap not in delivered and cap not in validated:
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
                                "output": {
                                    "source_evidence": [],
                                    **safe_failure(exc, phase="source_specialist"),
                                },
                            }
                        )
                        activity.extend(
                            source_tool_activity(
                                source_states[cap].workbench_activity, _NAMES[cap]
                            )
                        )
                    captured[cap] = self._retained_or_gap(
                        cap,
                        source_states[cap],
                        "Specialist model or provider failed."
                        if cap in attempted
                        else "Source manager failed before delegating this source.",
                    )
        if reused_completion:
            notes.append("Completed from retained validated evidence without repeating source retrieval or SDK work.")
        outcome = (
            SourceConsultationOutcome(status="succeeded")
            if reused_completion
            else self._outcome(
                captured,
                attempted,
                diagnostics,
                source_states,
                activity_offsets=activity_offsets,
            )
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
                    "outcome": outcome.model_dump(mode="json"),
                    "prior_attempt_usage": list(prior_usage),
                    "prior_attempt_diagnostics": list(prior_diagnostics),
                    "reused_completion": reused_completion,
                    "called_specialists": [
                        _NAMES[cap]
                        for cap in input_data.allowed_capabilities
                        if cap in attempted
                    ],
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
        attempt_finalized = True
        save_progress()
        return SourceManagerResult(
            outcome=outcome,
            prior_usage=prior_usage,
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
    def _recorded_usage(start: int, key: str) -> int | None:
        events = context_events(start)
        return (
            sum(item["output"][key] for item in events)
            if events and all(item["output"].get(key) is not None for item in events)
            else None
        )

    def _compatibility(self, data: SourceManagerInput) -> dict[str, Any]:
        return {
            "reuse_key": data.reuse_key,
            "owner_request": data.owner_request,
            "brief": data.brief.model_dump(mode="json"),
            "region": data.region_code,
            "products": [
                product.model_dump(mode="json", exclude={"product_id"})
                for product in data.products
            ],
            "listings": [item.model_dump(mode="json") for item in data.listings],
            "snapshots": [
                item.model_dump(mode="json") for item in data.source_snapshots
            ],
            "capabilities": [cap.value for cap in data.allowed_capabilities],
            "providers": {
                "video": str(self.settings.video_search_provider),
                "video_enabled": self.settings.video_search_provider_enabled,
                "transcript": str(self.settings.transcript_provider),
                "transcript_enabled": self.settings.transcript_provider_enabled,
                "search": str(self.settings.search_provider),
                "search_enabled": self.settings.search_provider_enabled,
                "amazon": str(self.settings.amazon_product_intelligence_provider),
                "amazon_enabled": self.settings.amazon_product_intelligence_provider_enabled,
                "ikea": str(self.settings.ikea_store_intelligence_provider),
                "ikea_enabled": self.settings.ikea_store_intelligence_provider_enabled,
            },
            "caption_bounds": {
                key: getattr(self.settings, key)
                for key in (
                    "youtube_transcript_languages",
                    "youtube_transcript_timeout_seconds",
                    "youtube_transcript_output_limit_bytes",
                    "youtube_transcript_temp_storage_limit_bytes",
                    "youtube_transcript_max_segments",
                )
            },
        }

    @staticmethod
    def _saved_input(data: SourceManagerInput) -> dict[str, Any]:
        return {
            "run_id": str(data.run_id),
            "brief": data.brief.model_dump(mode="json"),
            "products": [item.model_dump(mode="json") for item in data.products],
            "listings": [item.model_dump(mode="json") for item in data.listings],
            "source_snapshots": [
                item.model_dump(mode="json") for item in data.source_snapshots
            ],
            "query_hints": list(data.query_hints),
            "region_code": data.region_code,
            "allowed_capabilities": [cap.value for cap in data.allowed_capabilities],
            "reuse_key": data.reuse_key,
            "owner_request": data.owner_request,
        }

    def load_retry_input(self, run_id: RunId, reuse_key: str) -> SourceManagerInput:
        directory = (
            self.settings.resolved_artifact_dir / "source-consultations" / str(run_id)
        )
        for path in sorted(
            directory.glob("*.json"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        ):
            payload = json.loads(path.read_text()).get("input", {})
            if (
                payload.get("run_id") != str(run_id)
                or payload.get("reuse_key") != reuse_key
            ):
                continue
            data = SourceManagerInput(
                run_id=run_id,
                brief=ShoppingBrief.model_validate(payload["brief"]),
                products=tuple(
                    CanonicalProduct.model_validate(item)
                    for item in payload["products"]
                ),
                listings=tuple(
                    ProductListing.model_validate(item) for item in payload["listings"]
                ),
                source_snapshots=tuple(
                    SourceSnapshot.model_validate(item)
                    for item in payload["source_snapshots"]
                ),
                query_hints=tuple(payload["query_hints"]),
                region_code=payload["region_code"],
                allowed_capabilities=tuple(
                    SourceIntelligenceCapability(item)
                    for item in payload["allowed_capabilities"]
                ),
                reuse_key=reuse_key,
                owner_request=payload.get("owner_request"),
            )
            expected = SourceConsultationCheckpoint(
                self.settings.resolved_artifact_dir,
                str(run_id),
                self._compatibility(data),
            )
            if expected.path != path:
                continue
            expected.load()
            return data
        raise ValueError(
            "No compatible saved source consultation is available for this run."
        )

    def pending_retry_input(self, run_id: RunId) -> SourceManagerInput:
        directory = (
            self.settings.resolved_artifact_dir / "source-consultations" / str(run_id)
        )
        for path in sorted(
            directory.glob("*.json"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        ):
            saved = json.loads(path.read_text())
            if saved.get("run_id") != str(run_id):
                continue
            if saved.get("outcome", {}).get("status") == "succeeded":
                continue
            pending = saved.get("outcome", {}).get("status") in {
                "technical_failure",
                "interrupted",
                "partial",
            } or any(
                retrieval.get("status")
                in {"started", "cancelled", "interrupted", "technical_failure"}
                for state in saved.get("tool_states", {}).values()
                for retrieval in state.get("retrievals", {}).values()
            )
            key = saved.get("input", {}).get("reuse_key")
            if pending and isinstance(key, str):
                try:
                    return self.load_retry_input(run_id, key)
                except ValueError:
                    continue
        raise ValueError(
            "No compatible unfinished source consultation is available for this run."
        )

    @staticmethod
    def _substantive(bundle: Any) -> bool:
        return any(
            not getattr(evidence, "metadata_only", False)
            for evidence in bundle.evidence
        )

    @staticmethod
    def _outcome(
        captured: dict[SourceIntelligenceCapability, Any],
        attempted: set[SourceIntelligenceCapability],
        diagnostics: list[dict[str, str]],
        states: dict[SourceIntelligenceCapability, Any] | None = None,
        *,
        activity_offsets: dict[SourceIntelligenceCapability, int] | None = None,
        interrupted: bool = False,
    ) -> SourceConsultationOutcome:
        substantive = any(
            SourceIntelligenceManagerAgent._substantive(bundle)
            for bundle in captured.values()
        )
        retrievals = []
        provider_events = []
        for cap, state in (states or {}).items():
            events = list(state.workbench_activity)
            current = events[(activity_offsets or {}).get(cap, 0) :]
            current_video_ids = {
                event.get("input", {}).get("video_id")
                for event in current
                if event.get("tool_name") == "caption_retrieval"
            }
            retrievals.extend(
                item
                for video_id, item in getattr(state, "retrievals", {}).items()
                if not substantive or video_id in current_video_ids
            )
            if cap == SourceIntelligenceCapability.VIDEO_REVIEW:
                latest_searches = {}
                for event in events:
                    if event.get("tool_name") == "search_videos":
                        latest_searches[event.get("input", {}).get("query")] = event
                current_queries = {
                    event.get("input", {}).get("query")
                    for event in current
                    if event.get("tool_name") == "search_videos"
                }
                provider_events.extend(
                    event
                    for query, event in latest_searches.items()
                    if not substantive
                    or query in current_queries
                    or event.get("status") == "started"
                )
            else:
                provider_events.extend(current if substantive else events)
        provider_failed = any(
            event.get("status") in {"provider_error", "technical_failure"}
            for event in provider_events
        )
        provider_interrupted = any(
            event.get("status") in {"started", "cancelled", "interrupted"}
            for event in provider_events
        )
        provider_diagnostics = []
        for event in provider_events:
            if event.get("status") not in {
                "provider_error",
                "technical_failure",
                "cancelled",
            }:
                continue
            output = event.get("output", {})
            diagnostic = output.get("diagnostic", output)
            if diagnostic.get("error_type"):
                provider_diagnostics.append(
                    {
                        "error_type": diagnostic["error_type"],
                        "safe_detail": diagnostic.get(
                            "safe_detail", "Source retrieval did not complete."
                        ),
                        "phase": diagnostic.get("phase", "source_retrieval"),
                    }
                )
        diagnostics = [
            *diagnostics,
            *provider_diagnostics,
            *(
                {
                    "error_type": item["error_type"],
                    "safe_detail": item.get(
                        "safe_detail", "Caption retrieval did not complete."
                    ),
                    "phase": "caption_retrieval",
                }
                for item in retrievals
                if item.get("error_type")
                and item.get("status")
                in {"technical_failure", "cancelled", "interrupted"}
            ),
        ]
        interrupted = (
            interrupted
            or provider_interrupted
            or any(
                item.get("status") in {"cancelled", "interrupted", "started"}
                for item in retrievals
            )
        )
        actual_gap = any(
            item.get("status") == "provider_gap" for item in retrievals
        ) or any(event.get("status") == "unavailable" for event in provider_events)
        if not retrievals:
            actual_gap = actual_gap or any(
                any(
                    video.transcript_availability.value in {"unavailable", "restricted"}
                    for video in getattr(bundle, "videos", ())
                )
                for cap, bundle in captured.items()
                if cap in attempted
            )
        latest = diagnostics[-1] if diagnostics else None
        if interrupted:
            status = "partial" if substantive else "interrupted"
        elif (
            diagnostics
            or provider_failed
            or any(item.get("status") == "technical_failure" for item in retrievals)
        ):
            status = "partial" if substantive else "technical_failure"
        elif substantive:
            status = "succeeded"
        elif actual_gap:
            status = "provider_gap"
        else:
            status = "no_attempt"
        return SourceConsultationOutcome(
            status=status,
            failure_type=latest["error_type"] if latest else None,
            diagnostic=latest["safe_detail"]
            if latest
            else (
                "Source retrieval did not complete; provider unavailability was not established."
                if status == "technical_failure"
                else None
            ),
            diagnostics=tuple(diagnostics),
        )

    @staticmethod
    def _retained_or_gap(
        capability: SourceIntelligenceCapability, state: Any, reason: str
    ) -> Any:
        if (
            capability == SourceIntelligenceCapability.VIDEO_REVIEW
            and state.bundle is not None
        ):
            bundle = state.bundle
            return bundle.model_copy(
                update={
                    "evidence": tuple(
                        item for item in bundle.evidence if item.metadata_only
                    ),
                    "transcript_gap_notes": (*bundle.transcript_gap_notes, reason),
                }
            )
        return SourceIntelligenceManagerAgent._gap_bundle(capability, reason)

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
