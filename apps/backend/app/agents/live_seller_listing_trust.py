import asyncio
import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Protocol

from agents import Agent, ModelSettings, RunConfig
from pydantic import Field, ValidationError

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
from app.schemas.confidence import Confidence, ConfidenceLevel
from app.schemas.ids import RunId, SourceId, new_id
from app.schemas.regions import RegionCode
from app.services.listing_trust import ListingTrustRuleContext, assess_listing_trust


_HARD_SUSPICIOUS_SIGNAL_KINDS = frozenset(
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
        if configuration.mode == OpenAIAgentRuntimeMode.LIVE:
            if region_code is None:
                raise OpenAIAgentConfigurationError(
                    "Seller/listing hosted search requires a buyer region."
                )
            if self.citation_store_factory is None:
                raise OpenAIAgentConfigurationError(
                    "Live SellerListingTrustAgent requires run-scoped citation persistence."
                )
            citation_store = self.citation_store_factory(input_data.run_id)
            if citation_store.run_id != input_data.run_id:
                raise OpenAIAgentConfigurationError(
                    "Seller/listing citation store belongs to another run."
                )
            hosted_tool = build_hosted_web_search_tool(
                agent_name="SellerListingTrustAgent",
                model=configuration.model,
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
                persisted, hosted_activity, gap = await persist_trust_search_leads(
                    raw=raw_result,
                    selected_urls=tuple(lead.url for lead in model_output.web_leads),
                    listing=input_data.listing,
                    run_id=input_data.run_id,
                    region_code=region_code,
                    citation_store=citation_store,
                    source_policy=trust_search_policy(input_data.listing),
                    require_sdk_metadata=True,
                )
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

        status = (
            "hard_suspicious_flag_preserved"
            if _has_hard_suspicious_flags(rule_based)
            and assessment.level == ListingTrustLevel.SUSPICIOUS
            else "model_listing_trust_completed"
        )
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
                    "hard_suspicious_signal_kinds": [
                        signal.kind.value
                        for signal in _hard_suspicious_signals(rule_based)
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
            max_tokens=800,
            include_usage=True,
            tool_choice="auto",
        ),
        instructions=(
            "Review one supplied product listing for buyer-safety trust and "
            "return a structured assessment and optional cited web_leads. Assess listing "
            "and seller trust independently of product quality or product fit. "
            "Use the supplied listing, source evidence, and deterministic "
            "rule-based assessment. When supplied trust evidence is weak, you may "
            "use web_search to inspect the exact seller, listing, or return/warranty "
            "question for the supplied buyer region; skip it when evidence suffices. "
            "Search only the supplied listing or seller sites. Put useful exact "
            "cited URLs and their question in web_leads. A search snippet, "
            "marketplace rating, or uncited assertion cannot establish a trusted "
            "seller or a verified return/warranty policy. Never infer product "
            "quality from seller reputation. Do not invent seller, price, return, "
            "warranty, review, source, or evidence facts. Preserve supplied listing_id, evidence_ids, "
            "source_ids, and deterministic trust signals. If deterministic "
            "rules mark suspicious price or contradictory listing data, do not "
            "silently downgrade or override those hard suspicious flags; keep a "
            "clear red flag and explanation. Use unknown or weak trust when "
            "evidence is insufficient, and reserve reasonable or strong trust "
            "for established seller/source evidence with clear policy signals. "
            "Do not recommend products or expose agents, providers, prompts, "
            "traces, policies, or schemas to shoppers."
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
            "hard_suspicious_signal_kinds": [
                signal.kind.value for signal in _hard_suspicious_signals(rule_based)
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

    known_evidence_ids = _known_evidence_ids(input_data, rule_based)
    unknown_evidence_ids = set(assessment.evidence_ids) - known_evidence_ids
    if unknown_evidence_ids:
        raise ValueError("listing trust output used unknown evidence IDs.")

    known_source_ids = _known_source_ids(input_data, rule_based)
    unknown_source_ids = set(assessment.source_ids) - known_source_ids
    if unknown_source_ids:
        raise ValueError("listing trust output used unknown source IDs.")

    for signal in assessment.trust_signals:
        if set(signal.evidence_ids) - known_evidence_ids:
            raise ValueError("listing trust signal used unknown evidence IDs.")
        if set(signal.source_ids) - known_source_ids:
            raise ValueError("listing trust signal used unknown source IDs.")

    if _has_hard_suspicious_flags(rule_based):
        if not _model_output_explains_hard_flags(assessment, rule_based):
            raise ValueError(
                "hard deterministic suspicious flags require explicit explanation."
            )


def _normalize_listing_trust_assessment(
    assessment: ListingTrustAssessment,
    input_data: SellerListingTrustAgentInput,
    rule_based: ListingTrustAssessment,
) -> ListingTrustAssessment:
    evidence_ids = _dedupe_source_ids(
        (*assessment.evidence_ids, *_fallback_evidence_ids(input_data, rule_based))
    )
    source_ids = _dedupe_source_ids(
        (*assessment.source_ids, *_fallback_source_ids(input_data, rule_based))
    )
    trust_signals = rule_based.trust_signals
    red_flags = rule_based.red_flags
    positive_signals = rule_based.positive_signals
    update: dict[str, Any] = {
        "evidence_ids": evidence_ids,
        "source_ids": source_ids,
        "trust_signals": trust_signals,
        "red_flags": red_flags,
        "positive_signals": positive_signals,
        "summary": rule_based.summary,
    }

    if _has_hard_suspicious_flags(rule_based):
        update.update(
            {
                "level": ListingTrustLevel.SUSPICIOUS,
                "confidence": _preserved_hard_flag_confidence(
                    assessment.confidence,
                    rule_based.confidence,
                ),
            }
        )
    elif _more_severe(rule_based.level, assessment.level):
        update.update(
            {
                "level": rule_based.level,
                "confidence": _lower_confidence(
                    assessment.confidence,
                    rule_based.confidence,
                ),
            }
        )

    return assessment.model_copy(update=update)


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
            evidence_ids=_input_evidence_ids(input_data)
            or input_data.listing.source_ids,
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
    input_data: SellerListingTrustAgentInput,
    rule_based: ListingTrustAssessment,
) -> tuple[SourceId, ...]:
    evidence_ids = _input_evidence_ids(input_data)
    if evidence_ids:
        return _dedupe_source_ids((*evidence_ids, *rule_based.evidence_ids))
    if rule_based.evidence_ids:
        return rule_based.evidence_ids
    return input_data.listing.source_ids or (new_id(),)


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


def _hard_suspicious_signals(
    assessment: ListingTrustAssessment,
) -> tuple[ListingTrustSignal, ...]:
    return tuple(
        signal
        for signal in assessment.trust_signals
        if signal.kind in _HARD_SUSPICIOUS_SIGNAL_KINDS
    )


def _has_hard_suspicious_flags(assessment: ListingTrustAssessment) -> bool:
    return bool(_hard_suspicious_signals(assessment))


def _model_output_explains_hard_flags(
    assessment: ListingTrustAssessment,
    rule_based: ListingTrustAssessment,
) -> bool:
    combined_text = " ".join(
        (
            assessment.summary,
            *assessment.red_flags,
            *assessment.positive_signals,
            *(
                signal.summary
                for signal in assessment.trust_signals
                if signal.kind in _HARD_SUSPICIOUS_SIGNAL_KINDS
            ),
        )
    ).casefold()
    if not combined_text.strip():
        return False

    for signal in _hard_suspicious_signals(rule_based):
        if signal.kind == ListingTrustSignalKind.SUSPICIOUS_PRICE:
            if not any(
                marker in combined_text
                for marker in ("price", "too low", "discount", "cheap")
            ):
                return False
        if signal.kind == ListingTrustSignalKind.CONTRADICTORY_LISTING_DATA:
            if not any(
                marker in combined_text
                for marker in ("contradict", "mismatch", "conflict", "differs")
            ):
                return False
    return True


def _dedupe_source_ids(source_ids: Iterable[SourceId]) -> tuple[SourceId, ...]:
    return tuple(dict.fromkeys(source_ids))


def _more_severe(left: ListingTrustLevel, right: ListingTrustLevel) -> bool:
    return _severity_rank(left) > _severity_rank(right)


def _severity_rank(level: ListingTrustLevel) -> int:
    return {
        ListingTrustLevel.STRONG: 0,
        ListingTrustLevel.REASONABLE: 1,
        ListingTrustLevel.MIXED: 2,
        ListingTrustLevel.UNKNOWN: 3,
        ListingTrustLevel.WEAK: 4,
        ListingTrustLevel.SUSPICIOUS: 5,
    }[level]


def _preserved_hard_flag_confidence(
    model_confidence: Confidence,
    rule_confidence: Confidence,
) -> Confidence:
    score = max(model_confidence.score, rule_confidence.score, 0.75)
    return Confidence(
        score=score,
        level=ConfidenceLevel.HIGH if score >= 0.75 else ConfidenceLevel.MEDIUM,
        rationale=(
            "Hard deterministic suspicious listing signals were preserved after "
            "model review."
        ),
    )


def _lower_confidence(
    model_confidence: Confidence,
    rule_confidence: Confidence,
) -> Confidence:
    score = min(model_confidence.score, rule_confidence.score)
    level = (
        ConfidenceLevel.LOW
        if score < 0.5
        else ConfidenceLevel.MEDIUM
        if score < 0.75
        else ConfidenceLevel.HIGH
    )
    return Confidence(
        score=score,
        level=level,
        rationale=rule_confidence.rationale or model_confidence.rationale,
    )
