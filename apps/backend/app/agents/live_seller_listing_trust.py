import asyncio
import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Protocol

from agents import Agent, ModelSettings, RunConfig, Runner
from pydantic import ValidationError

from app.agents.contracts import SellerListingTrustAgentInput
from app.agents.openai_config import build_openai_agent_run_configuration
from app.core.settings import Settings
from app.schemas.analysis import (
    ListingTrustAssessment,
    ListingTrustLevel,
    ListingTrustSignal,
    ListingTrustSignalKind,
)
from app.schemas.confidence import Confidence, ConfidenceLevel
from app.schemas.ids import SourceId, new_id
from app.services.listing_trust import ListingTrustRuleContext, assess_listing_trust


_HARD_SUSPICIOUS_SIGNAL_KINDS = frozenset(
    {
        ListingTrustSignalKind.SUSPICIOUS_PRICE,
        ListingTrustSignalKind.CONTRADICTORY_LISTING_DATA,
    }
)


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
        return await Runner.run(
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
        agent = _build_seller_listing_trust_agent(configuration.model)
        run_config = RunConfig(
            model=configuration.model,
            model_settings=ModelSettings(
                temperature=0,
                max_tokens=800,
                include_usage=True,
            ),
            tracing_disabled=not configuration.tracing_enabled,
            trace_include_sensitive_data=configuration.trace_include_sensitive_data,
            workflow_name=configuration.trace_workflow_name,
            trace_metadata=configuration.trace_metadata,
        )

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
            assessment = _coerce_listing_trust_result(
                getattr(raw_result, "final_output", raw_result),
                input_data,
                rule_based,
            )
        except TimeoutError:
            assessment = rule_based
            self._set_activity("timeout_rule_based_fallback", input_data, assessment)
            return assessment
        except (ValidationError, ValueError, TypeError):
            assessment = rule_based
            self._set_activity(
                "schema_invalid_rule_based_fallback",
                input_data,
                assessment,
            )
            return assessment
        except Exception:
            assessment = rule_based
            self._set_activity("error_rule_based_fallback", input_data, assessment)
            return assessment

        status = (
            "hard_suspicious_flag_preserved"
            if _has_hard_suspicious_flags(rule_based)
            and assessment.level == ListingTrustLevel.SUSPICIOUS
            else "model_listing_trust_completed"
        )
        self._set_activity(status, input_data, assessment)
        return assessment

    @property
    def workbench_activity(self) -> tuple[dict[str, Any], ...]:
        return self._workbench_activity

    def _set_activity(
        self,
        status: str,
        input_data: SellerListingTrustAgentInput,
        assessment: ListingTrustAssessment,
    ) -> None:
        rule_based = _rule_based_assessment(input_data)
        self._workbench_activity = (
            {
                "tool_name": "openai_agents_structured_output",
                "status": status,
                "input": {
                    "agent": "SellerListingTrustAgent",
                    "allowed_tools": [],
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
        )


@dataclass
class _MockRunResult:
    final_output: Any


def _build_seller_listing_trust_agent(model: str) -> Agent[Any]:
    return Agent(
        name="CartCartSellerListingTrustAgent",
        model=model,
        model_settings=ModelSettings(
            temperature=0,
            max_tokens=800,
            include_usage=True,
        ),
        instructions=(
            "Review one supplied product listing for buyer-safety trust and "
            "return only a structured ListingTrustAssessment. Assess listing "
            "and seller trust independently of product quality or product fit. "
            "Use only the supplied listing, source evidence, and deterministic "
            "rule-based assessment. Do not browse, call tools, fetch seller "
            "pages, or invent seller, price, return, warranty, review, source, "
            "or evidence facts. Preserve supplied listing_id, evidence_ids, "
            "source_ids, and deterministic trust signals. If deterministic "
            "rules mark suspicious price or contradictory listing data, do not "
            "silently downgrade or override those hard suspicious flags; keep a "
            "clear red flag and explanation. Use unknown or weak trust when "
            "evidence is insufficient, and reserve reasonable or strong trust "
            "for established seller/source evidence with clear policy signals. "
            "Do not recommend products or expose agents, providers, prompts, "
            "traces, policies, or schemas to shoppers."
        ),
        tools=[],
        output_type=ListingTrustAssessment,
    )


def _model_input(
    input_data: SellerListingTrustAgentInput,
    rule_based: ListingTrustAssessment,
) -> str:
    return json.dumps(
        {
            "run_id": str(input_data.run_id),
            "listing": input_data.listing.model_dump(mode="json"),
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
    trust_signals = _merge_signals(
        assessment.trust_signals,
        rule_based.trust_signals,
    )
    red_flags = _merge_strings(assessment.red_flags, rule_based.red_flags)
    positive_signals = _merge_strings(
        assessment.positive_signals,
        rule_based.positive_signals,
    )
    update: dict[str, Any] = {
        "evidence_ids": evidence_ids,
        "source_ids": source_ids,
        "trust_signals": trust_signals,
        "red_flags": red_flags,
        "positive_signals": positive_signals,
    }

    if _has_hard_suspicious_flags(rule_based):
        update.update(
            {
                "level": ListingTrustLevel.SUSPICIOUS,
                "confidence": _preserved_hard_flag_confidence(
                    assessment.confidence,
                    rule_based.confidence,
                ),
                "summary": _hard_flag_summary(assessment, rule_based),
            }
        )
    elif _more_severe(rule_based.level, assessment.level):
        update.update(
            {
                "level": rule_based.level,
                "summary": _merge_summary(assessment.summary, rule_based.summary),
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
            evidence_ids=_input_evidence_ids(input_data) or input_data.listing.source_ids,
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


def _merge_signals(
    primary: Iterable[ListingTrustSignal],
    fallback: Iterable[ListingTrustSignal],
) -> tuple[ListingTrustSignal, ...]:
    merged: list[ListingTrustSignal] = []
    seen: set[tuple[ListingTrustSignalKind, str]] = set()
    for signal in (*tuple(primary), *tuple(fallback)):
        key = (signal.kind, signal.summary)
        if key in seen:
            continue
        merged.append(signal)
        seen.add(key)
    return tuple(merged)


def _merge_strings(primary: Iterable[str], fallback: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys((*tuple(primary), *tuple(fallback))))


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


def _hard_flag_summary(
    assessment: ListingTrustAssessment,
    rule_based: ListingTrustAssessment,
) -> str:
    return _merge_summary(
        "Suspicious deterministic listing signals remain blocking.",
        _merge_summary(assessment.summary, rule_based.summary),
    )


def _merge_summary(primary: str, fallback: str) -> str:
    if primary == fallback:
        return primary
    return f"{primary} {fallback}"
