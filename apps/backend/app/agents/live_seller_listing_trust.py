import asyncio
import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Protocol

from agents import Agent, ModelSettings, RunConfig
from pydantic import Field, ValidationError

from app.agents.token_policy import scaled_tokens
from app.agents.context_management import BoundedRunner, ContextBudgetExceeded
from app.agents.contracts import SellerListingTrustAgentInput
from app.agents.hosted_web_search import build_hosted_web_search_tool
from app.agents.openai_config import (
    OpenAIAgentConfigurationError,
    OpenAIAgentRuntimeMode,
    apply_openai_agent_run_profile,
    build_openai_agent_run_configuration,
)
from app.agents.research_tools import HostedCitationStore, PersistedHostedCitation
from app.agents.trust_hosted_search import (
    persist_trust_search_leads,
    trust_search_policy,
)
from app.core.settings import Settings
from app.schemas.analysis import (
    ListingTrustAssessment,
    ListingTrustLevel,
    ListingTrustSignal,
    ListingTrustSignalKind,
    ListingTrustSignalPolarity,
)
from app.schemas.base import CartCartBaseModel
from app.schemas.ids import RunId, SourceId
from app.schemas.regions import RegionCode
from app.services.listing_trust import ListingTrustRuleContext, assess_listing_trust


_ADVISORY_CONCERN_KINDS = frozenset(
    {
        ListingTrustSignalKind.SUSPICIOUS_PRICE,
        ListingTrustSignalKind.CONTRADICTORY_LISTING_DATA,
    }
)


class TrustWebLead(CartCartBaseModel):
    url: str = Field(min_length=1, max_length=2048)
    question: Literal["seller_identity", "return_warranty", "listing_claim"]


class SellerListingTrustModelOutput(CartCartBaseModel):
    assessment: ListingTrustAssessment
    web_leads: tuple[TrustWebLead, ...] = Field(default_factory=tuple, max_length=8)


class SellerListingTrustModelRunner(Protocol):
    async def run(
        self,
        agent: Agent[Any],
        model_input: str,
        *,
        run_config: RunConfig,
        max_turns: int,
    ) -> Any:
        """Run the SDK seller/listing trust agent and return its raw run result."""


@dataclass
class OpenAIAgentsSDKSellerListingTrustModelRunner:
    async def run(
        self,
        agent: Agent[Any],
        model_input: str,
        *,
        run_config: RunConfig,
        max_turns: int,
    ) -> Any:
        return await BoundedRunner.run(
            agent,
            model_input,
            run_config=run_config,
            max_turns=max_turns,
        )


@dataclass
class MockSellerListingTrustModelRunner:
    output: ListingTrustAssessment | dict[str, Any] | None = None
    error: BaseException | None = None
    calls: int = 0

    async def run(
        self,
        agent: Agent[Any],
        model_input: str,
        *,
        run_config: RunConfig,
        max_turns: int,
    ) -> Any:
        del agent, run_config, max_turns
        self.calls += 1
        if self.error is not None:
            raise self.error
        output = self.output or _mock_assessment_from_model_input(model_input)
        return _MockRunResult(final_output=output)


@dataclass
class LiveSellerListingTrustAgent:
    settings: Settings
    citation_store_factory: Callable[[RunId], HostedCitationStore] | None = None
    model_runner: SellerListingTrustModelRunner = field(
        default_factory=OpenAIAgentsSDKSellerListingTrustModelRunner,
    )
    _workbench_activity: tuple[dict[str, Any], ...] = field(
        default=(),
        init=False,
        repr=False,
    )

    async def run(
        self,
        input_data: SellerListingTrustAgentInput,
    ) -> ListingTrustAssessment:
        rule_based = _rule_based_assessment(input_data)
        configuration = build_openai_agent_run_configuration(
            self.settings,
            agent_name="SellerListingTrustAgent",
            run_id=str(input_data.run_id),
        )
        hosted_tool = None
        citation_store = None
        region_code = input_data.target_region_code or _listing_region(input_data)
        if (
            configuration.mode == OpenAIAgentRuntimeMode.LIVE
            and region_code is not None
            and self.citation_store_factory is not None
        ):
            citation_store = self.citation_store_factory(input_data.run_id)
            if citation_store.run_id != input_data.run_id:
                raise OpenAIAgentConfigurationError(
                    "Seller/listing citation store belongs to another run."
                )
            hosted_tool = build_hosted_web_search_tool(
                agent_name="SellerListingTrustAgent",
                region_code=region_code,
                source_policy=trust_search_policy(input_data.listing),
            )
        agent = _build_seller_listing_trust_agent(
            configuration.model, hosted_tool=hosted_tool
        )
        apply_openai_agent_run_profile(agent, configuration)
        run_config = RunConfig(
            tracing_disabled=not configuration.tracing_enabled,
            trace_include_sensitive_data=configuration.trace_include_sensitive_data,
            workflow_name=configuration.trace_workflow_name,
            trace_metadata=configuration.trace_metadata,
        )

        hosted_activity: tuple[dict[str, Any], ...] = ()
        try:
            raw_result = await asyncio.wait_for(
                self.model_runner.run(
                    agent,
                    _model_input(input_data, rule_based),
                    run_config=run_config,
                    max_turns=configuration.max_turns,
                ),
                timeout=configuration.timeout_seconds,
            )
            final_output = getattr(raw_result, "final_output", raw_result)
            if isinstance(final_output, SellerListingTrustModelOutput):
                model_output = final_output
            elif isinstance(final_output, dict) and "assessment" in final_output:
                model_output = SellerListingTrustModelOutput.model_validate(
                    final_output
                )
            else:
                model_output = SellerListingTrustModelOutput(
                    assessment=ListingTrustAssessment.model_validate(final_output)
                )
            assessment = _coerce_listing_trust_result(
                model_output.assessment,
                input_data,
                rule_based,
            )
            persisted: dict[str, PersistedHostedCitation] = {}
            gap = None
            if citation_store is not None:
                assert region_code is not None
                try:
                    persisted, hosted_activity, gap = await persist_trust_search_leads(
                        raw=raw_result,
                        selected_urls=tuple(
                            lead.url for lead in model_output.web_leads
                        ),
                        listing=input_data.listing,
                        run_id=input_data.run_id,
                        region_code=region_code,
                        citation_store=citation_store,
                        source_policy=trust_search_policy(input_data.listing),
                        require_sdk_metadata=True,
                    )
                except ContextBudgetExceeded:
                    raise
                except Exception:
                    gap = "An optional seller source could not be retained. The supplied seller assessment remains available."

            assessment = _attach_web_leads(
                assessment, model_output.web_leads, persisted
            )
            if gap:
                hosted_activity = (
                    *hosted_activity,
                    {
                        "tool_name": "web_search_gap",
                        "status": "gap",
                        "input": {"agent": "SellerListingTrustAgent"},
                        "output": {"reason": gap},
                    },
                )
        except OpenAIAgentConfigurationError:
            raise
        except TimeoutError:
            assessment = rule_based
            self._set_activity(
                "timeout_rule_based_fallback",
                input_data,
                assessment,
                hosted_activity,
                hosted_tool is not None,
            )
            return assessment
        except (ValidationError, ValueError, TypeError):
            assessment = rule_based
            self._set_activity(
                "schema_invalid_rule_based_fallback",
                input_data,
                assessment,
                hosted_activity,
                hosted_tool is not None,
            )
            return assessment
        except ContextBudgetExceeded:
            raise
        except Exception:
            assessment = rule_based
            self._set_activity(
                "error_rule_based_fallback",
                input_data,
                assessment,
                hosted_activity,
                hosted_tool is not None,
            )
            return assessment

        status = "model_listing_trust_completed"
        self._set_activity(
            status, input_data, assessment, hosted_activity, hosted_tool is not None
        )
        return assessment

    @property
    def workbench_activity(self) -> tuple[dict[str, Any], ...]:
        return self._workbench_activity

    def _set_activity(
        self,
        status: str,
        input_data: SellerListingTrustAgentInput,
        assessment: ListingTrustAssessment,
        hosted_activity: tuple[dict[str, Any], ...] = (),
        hosted_enabled: bool = False,
    ) -> None:
        rule_based = _rule_based_assessment(input_data)
        self._workbench_activity = (
            {
                "tool_name": "openai_agents_structured_output",
                "status": status,
                "input": {
                    "agent": "SellerListingTrustAgent",
                    "allowed_tools": ["hosted_web_search"] if hosted_enabled else [],
                    "listing_id": str(input_data.listing.listing_id),
                    "seller_name": input_data.listing.seller.seller_name,
                    "evidence_count": len(input_data.evidence),
                    "rule_based_level": rule_based.level.value,
                    "advisory_concern_signal_kinds": [
                        signal.kind.value
                        for signal in _advisory_concern_signals(rule_based)
                    ],
                },
                "output": assessment.model_dump(mode="json"),
            },
            *hosted_activity,
        )


@dataclass
class _MockRunResult:
    final_output: Any


def _build_seller_listing_trust_agent(
    model: str, *, hosted_tool: Any | None = None
) -> Agent[Any]:
    return Agent(
        name="CartCartSellerListingTrustAgent",
        model=model,
        model_settings=ModelSettings(
            max_tokens=scaled_tokens(800),
            include_usage=True,
            tool_choice="auto",
        ),
        instructions=(
            "Assess the supplied seller and listing independently of product quality and return an assessment. "
            "Rule scores, source reputation, review counts and price-plausibility flags are advisory context. "
            "You may improve or worsen the rule assessment when the supplied information supports your judgment. "
            "An official store is acceptable seller context without a mandatory background check, reviews or policy checklist. "
            "Missing reviews, price, stock or warranty are unknowns, not adverse findings. Multiple reviews without meaningful "
            "adverse findings can be positive context. Weigh actual seller concerns, their scope and sources. "
            "Do not invent seller facts, prices, reviews or source links. Keep supplied IDs. "
            "If an optional search tool is supplied, use it only for a useful seller or listing question, never as a prerequisite. "
            "Write a concise summary for an ordinary shopper."
        ),
        tools=[hosted_tool] if hosted_tool else [],
        output_type=SellerListingTrustModelOutput,
    )


def _model_input(
    input_data: SellerListingTrustAgentInput,
    rule_based: ListingTrustAssessment,
) -> str:
    return json.dumps(
        {
            "run_id": str(input_data.run_id),
            "listing": input_data.listing.model_dump(mode="json"),
            "target_region_code": input_data.target_region_code
            or _listing_region(input_data),
            "evidence": [
                evidence.model_dump(mode="json") for evidence in input_data.evidence
            ],
            "rule_based_assessment": rule_based.model_dump(mode="json"),
            "advisory_concern_signal_kinds": [
                signal.kind.value for signal in _advisory_concern_signals(rule_based)
            ],
        },
        sort_keys=True,
    )


def _listing_region(input_data: SellerListingTrustAgentInput) -> RegionCode | None:
    regions = {item.region_code for item in input_data.listing.region_availability}
    return next(iter(regions)) if len(regions) == 1 else None


def _attach_web_leads(
    assessment: ListingTrustAssessment,
    web_leads: tuple[TrustWebLead, ...],
    persisted: dict[str, Any],
) -> ListingTrustAssessment:
    kinds = {
        "seller_identity": ListingTrustSignalKind.SELLER_IDENTITY,
        "return_warranty": ListingTrustSignalKind.RETURN_WARRANTY_CLARITY,
        "listing_claim": ListingTrustSignalKind.MISSING_METADATA,
    }
    summaries = {
        "seller_identity": "A page related to this seller was found, but its details are unverified.",
        "return_warranty": "A page about returns or warranty was found, but its terms are unverified.",
        "listing_claim": "A page related to this listing was found, but its claims are unverified.",
    }
    signals = []
    for lead in web_leads:
        citation = persisted.get(lead.url)
        if citation is None:
            continue
        signals.append(
            ListingTrustSignal(
                kind=kinds[lead.question],
                polarity=ListingTrustSignalPolarity.NEUTRAL,
                strength=0.2,
                summary=summaries[lead.question],
                evidence_ids=(citation.evidence_id,),
                source_ids=(citation.snapshot_id,),
            )
        )
    if not signals:
        return assessment
    return assessment.model_copy(
        update={
            "trust_signals": (*assessment.trust_signals, *signals),
            "evidence_ids": _dedupe_source_ids(
                (*assessment.evidence_ids, *(item.evidence_ids[0] for item in signals))
            ),
            "source_ids": _dedupe_source_ids(
                (*assessment.source_ids, *(item.source_ids[0] for item in signals))
            ),
            "summary": (
                assessment.summary
                + " Related pages need checking before they affect seller trust."
            )[:1000],
        }
    )


def _coerce_listing_trust_result(
    value: Any,
    input_data: SellerListingTrustAgentInput,
    rule_based: ListingTrustAssessment,
) -> ListingTrustAssessment:
    assessment = (
        value
        if isinstance(value, ListingTrustAssessment)
        else ListingTrustAssessment.model_validate(value)
    )
    _validate_listing_trust_policy(assessment, input_data, rule_based)
    return _normalize_listing_trust_assessment(assessment, input_data, rule_based)


def _validate_listing_trust_policy(
    assessment: ListingTrustAssessment,
    input_data: SellerListingTrustAgentInput,
    rule_based: ListingTrustAssessment,
) -> None:
    if assessment.listing_id != input_data.listing.listing_id:
        raise ValueError("listing trust output used an unknown listing ID.")


def _normalize_listing_trust_assessment(
    assessment: ListingTrustAssessment,
    input_data: SellerListingTrustAgentInput,
    rule_based: ListingTrustAssessment,
) -> ListingTrustAssessment:
    known_evidence = _known_evidence_ids(input_data, rule_based)
    known_sources = _known_source_ids(input_data, rule_based)
    return assessment.model_copy(
        update={
            "evidence_ids": _dedupe_source_ids(
                value
                for value in (
                    *assessment.evidence_ids,
                    *_fallback_evidence_ids(input_data, rule_based),
                )
                if value in known_evidence
            ),
            "source_ids": _dedupe_source_ids(
                value
                for value in (
                    *assessment.source_ids,
                    *_fallback_source_ids(input_data, rule_based),
                )
                if value in known_sources
            ),
            "trust_signals": tuple(
                signal.model_copy(
                    update={
                        "evidence_ids": tuple(
                            value
                            for value in signal.evidence_ids
                            if value in known_evidence
                        ),
                        "source_ids": tuple(
                            value
                            for value in signal.source_ids
                            if value in known_sources
                        ),
                    }
                )
                for signal in assessment.trust_signals
            ),
        }
    )


def _mock_assessment_from_model_input(model_input: str) -> ListingTrustAssessment:
    payload = json.loads(model_input)
    input_data = SellerListingTrustAgentInput.model_validate(
        {
            "run_id": payload["run_id"],
            "listing": payload["listing"],
            "evidence": payload["evidence"],
            "rule_based_assessment": payload["rule_based_assessment"],
        }
    )
    rule_based = _rule_based_assessment(input_data)
    if rule_based.level in {
        ListingTrustLevel.SUSPICIOUS,
        ListingTrustLevel.WEAK,
        ListingTrustLevel.UNKNOWN,
    }:
        return rule_based
    return rule_based.model_copy(
        update={
            "summary": (
                "The supplied seller, source, return, warranty, and review "
                "signals are enough to treat this listing as reasonably trusted."
            ),
        }
    )


def _rule_based_assessment(
    input_data: SellerListingTrustAgentInput,
) -> ListingTrustAssessment:
    if input_data.rule_based_assessment is not None:
        return input_data.rule_based_assessment
    return assess_listing_trust(
        input_data.listing,
        ListingTrustRuleContext(
            evidence_ids=_input_evidence_ids(input_data),
            source_ids=input_data.listing.source_ids,
        ),
    )


def _known_evidence_ids(
    input_data: SellerListingTrustAgentInput,
    rule_based: ListingTrustAssessment,
) -> set[SourceId]:
    return set(_fallback_evidence_ids(input_data, rule_based))


def _known_source_ids(
    input_data: SellerListingTrustAgentInput,
    rule_based: ListingTrustAssessment,
) -> set[SourceId]:
    return set(_fallback_source_ids(input_data, rule_based))


def _fallback_evidence_ids(
    input_data: SellerListingTrustAgentInput, rule_based: ListingTrustAssessment
) -> tuple[SourceId, ...]:
    return _dedupe_source_ids(
        (*_input_evidence_ids(input_data), *rule_based.evidence_ids)
    )


def _fallback_source_ids(
    input_data: SellerListingTrustAgentInput,
    rule_based: ListingTrustAssessment,
) -> tuple[SourceId, ...]:
    source_ids: list[SourceId] = [
        *(evidence.source_id for evidence in input_data.evidence),
        *input_data.listing.source_ids,
        *input_data.listing.seller.source_ids,
        *rule_based.source_ids,
    ]
    return _dedupe_source_ids(source_ids)


def _input_evidence_ids(
    input_data: SellerListingTrustAgentInput,
) -> tuple[SourceId, ...]:
    return tuple(evidence.evidence_id for evidence in input_data.evidence)


def _advisory_concern_signals(
    assessment: ListingTrustAssessment,
) -> tuple[ListingTrustSignal, ...]:
    return tuple(
        signal
        for signal in assessment.trust_signals
        if signal.kind in _ADVISORY_CONCERN_KINDS
    )


def _dedupe_source_ids(source_ids: Iterable[SourceId]) -> tuple[SourceId, ...]:
    return tuple(dict.fromkeys(source_ids))
