import asyncio
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Protocol

from agents import Agent, ModelSettings, RunConfig, Runner
from pydantic import ValidationError

from app.agents.catalog import (
    AgentCatalog,
    ProductAnalysisRoute,
    build_default_agent_catalog,
)
from app.agents.contracts import ProductAnalysisAgentInput
from app.agents.openai_config import build_openai_agent_run_configuration
from app.core.settings import Settings
from app.schemas.analysis import CategoryAnalysis
from app.schemas.confidence import Confidence, ConfidenceLevel
from app.schemas.ids import ListingId, SourceId, new_id
from app.schemas.products import ProductListing
from app.schemas.search_sources import SourceQualityLevel


EARPHONES_HEADPHONES_SPECIALIST_AGENT_NAME = "EarphonesHeadphonesSpecialistAgent"


class EarphonesHeadphonesSpecialistModelRunner(Protocol):
    async def run(
        self,
        agent: Agent[Any],
        model_input: str,
        *,
        run_config: RunConfig,
        max_turns: int,
    ) -> Any:
        """Run the SDK earphones/headphones specialist and return its raw result."""


@dataclass
class OpenAIAgentsSDKEarphonesHeadphonesSpecialistModelRunner:
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
class MockEarphonesHeadphonesSpecialistModelRunner:
    output: CategoryAnalysis | dict[str, Any] | None = None
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
        output = self.output or _mock_analysis_from_model_input(model_input)
        return _MockRunResult(final_output=output)


@dataclass
class LiveEarphonesHeadphonesSpecialistAgent:
    settings: Settings
    catalog: AgentCatalog = field(default_factory=build_default_agent_catalog)
    model_runner: EarphonesHeadphonesSpecialistModelRunner = field(
        default_factory=OpenAIAgentsSDKEarphonesHeadphonesSpecialistModelRunner,
    )
    _workbench_activity: tuple[dict[str, Any], ...] = field(
        default=(),
        init=False,
        repr=False,
    )

    async def run(self, input_data: ProductAnalysisAgentInput) -> CategoryAnalysis:
        route = _route_for_input(input_data, self.catalog)
        if not _is_earphones_headphones_route(route, self.catalog):
            analysis, status = _fallback_for_non_audio(input_data, route, self.catalog)
            self._set_activity(status, input_data, route, analysis)
            return analysis

        configuration = build_openai_agent_run_configuration(
            self.settings,
            agent_name=EARPHONES_HEADPHONES_SPECIALIST_AGENT_NAME,
            run_id=str(input_data.run_id),
        )
        agent = _build_earphones_headphones_specialist_agent(configuration.model)
        run_config = RunConfig(
            model=configuration.model,
            model_settings=ModelSettings(
                temperature=0,
                max_tokens=1200,
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
                    _model_input(input_data, self.catalog, route),
                    run_config=run_config,
                    max_turns=configuration.max_turns,
                ),
                timeout=configuration.timeout_seconds,
            )
            analysis = _coerce_category_analysis_result(
                getattr(raw_result, "final_output", raw_result),
                input_data,
                self.catalog,
            )
        except TimeoutError:
            analysis = _technology_domain_fallback_analysis(input_data, self.catalog)
            self._set_activity(
                "timeout_technology_domain_fallback",
                input_data,
                route,
                analysis,
            )
            return analysis
        except (ValidationError, ValueError, TypeError):
            analysis = _technology_domain_fallback_analysis(input_data, self.catalog)
            self._set_activity(
                "schema_invalid_technology_domain_fallback",
                input_data,
                route,
                analysis,
            )
            return analysis
        except Exception:
            analysis = _technology_domain_fallback_analysis(input_data, self.catalog)
            self._set_activity(
                "error_technology_domain_fallback",
                input_data,
                route,
                analysis,
            )
            return analysis

        self._set_activity(
            "model_earphones_headphones_analysis_completed",
            input_data,
            route,
            analysis,
        )
        return analysis

    @property
    def workbench_activity(self) -> tuple[dict[str, Any], ...]:
        return self._workbench_activity

    def _set_activity(
        self,
        status: str,
        input_data: ProductAnalysisAgentInput,
        route: ProductAnalysisRoute,
        analysis: CategoryAnalysis,
    ) -> None:
        self._workbench_activity = (
            {
                "tool_name": "openai_agents_structured_output",
                "status": status,
                "input": {
                    "agent": EARPHONES_HEADPHONES_SPECIALIST_AGENT_NAME,
                    "allowed_tools": [],
                    "category": _analysis_category(input_data),
                    "declared_route": route.model_dump(mode="json"),
                    "listing_count": len(input_data.listings),
                    "evidence_count": len(input_data.evidence),
                    "weak_or_sparse_evidence": _has_weak_or_sparse_evidence(
                        input_data
                    ),
                },
                "output": analysis.model_dump(mode="json"),
            },
        )


@dataclass
class _MockRunResult:
    final_output: Any


def _build_earphones_headphones_specialist_agent(model: str) -> Agent[Any]:
    return Agent(
        name="CartCartEarphonesHeadphonesSpecialistAgent",
        model=model,
        model_settings=ModelSettings(
            temperature=0,
            max_tokens=1200,
            include_usage=True,
        ),
        instructions=(
            "Analyze exactly one earphones, earbuds, headset, or headphones "
            "candidate for fit against the shopper's brief and return only a "
            "structured CategoryAnalysis. This specialist is only for "
            "earphone/headphone-scoped products routed through the technology "
            "domain. Use only supplied product, listing, and evidence records. "
            "Cite supplied evidence_ids and source_ids for factual claims, and "
            "do not invent specs, prices, seller facts, product IDs, listing "
            "IDs, evidence IDs, or source IDs. Cover audio-wearable fit: active "
            "noise cancellation or isolation, comfort and fit, microphone and "
            "call quality, battery life and charging, Bluetooth codec/device "
            "compatibility, commute or use-case tradeoffs, listing caveats, and "
            "evidence gaps. If evidence is weak or sparse, return lower "
            "confidence and plain limitations. Do not analyze non-audio "
            "products as headphones, rank final recommendations, browse, call "
            "tools, or expose agents, providers, prompts, traces, policies, or "
            "schemas to shoppers."
        ),
        tools=[],
        output_type=CategoryAnalysis,
    )


def _model_input(
    input_data: ProductAnalysisAgentInput,
    catalog: AgentCatalog,
    route: ProductAnalysisRoute,
) -> str:
    return json.dumps(
        {
            "run_id": str(input_data.run_id),
            "brief": input_data.brief.model_dump(mode="json"),
            "product": input_data.product.model_dump(mode="json"),
            "listings": [
                listing.model_dump(mode="json") for listing in input_data.listings
            ],
            "evidence": [
                evidence.model_dump(mode="json") for evidence in input_data.evidence
            ],
            "allowed_routes": {
                "generic_fallback_agent_name": catalog.generic_fallback_agent_name,
                "technology_domain_agent_name": catalog.technology_domain_agent_name,
                "earphones_headphones_specialist_agent_name": (
                    EARPHONES_HEADPHONES_SPECIALIST_AGENT_NAME
                ),
                "product_category_routes": catalog.product_category_routes,
            },
            "declared_route": route.model_dump(mode="json"),
            "required_earphones_headphones_coverage": (
                "ANC",
                "comfort/fit",
                "microphone",
                "battery",
                "codec/device fit",
                "source IDs",
            ),
        },
        sort_keys=True,
    )


def _coerce_category_analysis_result(
    value: Any,
    input_data: ProductAnalysisAgentInput,
    catalog: AgentCatalog,
) -> CategoryAnalysis:
    analysis = (
        value
        if isinstance(value, CategoryAnalysis)
        else CategoryAnalysis.model_validate(value)
    )
    analysis = _normalize_category_analysis(analysis, input_data)
    _validate_analysis_policy(analysis, input_data, catalog)
    return analysis


def _normalize_category_analysis(
    analysis: CategoryAnalysis,
    input_data: ProductAnalysisAgentInput,
) -> CategoryAnalysis:
    if analysis.product_id != input_data.product.product_id:
        raise ValueError("headphone analysis output used an unknown product ID.")

    listing_ids = analysis.listing_ids or _input_listing_ids(input_data)
    unknown_listing_ids = set(listing_ids) - set(_input_listing_ids(input_data))
    if unknown_listing_ids:
        raise ValueError("headphone analysis output used unknown listing IDs.")

    known_evidence_ids = {item.evidence_id for item in input_data.evidence}
    unknown_evidence_ids = set(analysis.evidence_ids) - known_evidence_ids
    if unknown_evidence_ids:
        raise ValueError("headphone analysis output used unknown evidence IDs.")

    known_source_ids = _known_source_ids(input_data)
    unknown_source_ids = set(analysis.source_ids) - known_source_ids
    if unknown_source_ids:
        raise ValueError("headphone analysis output used unknown source IDs.")

    cited_source_ids = _source_ids_for_evidence_ids(input_data, analysis.evidence_ids)
    source_ids = _dedupe_source_ids((*analysis.source_ids, *cited_source_ids))
    if input_data.evidence and not source_ids:
        raise ValueError("headphone analysis output did not preserve source IDs.")

    return analysis.model_copy(
        update={
            "listing_ids": listing_ids,
            "source_ids": source_ids,
        }
    )


def _validate_analysis_policy(
    analysis: CategoryAnalysis,
    input_data: ProductAnalysisAgentInput,
    catalog: AgentCatalog,
) -> None:
    if not analysis.strengths:
        raise ValueError("headphone analysis output must include fit strengths.")
    if not analysis.weaknesses:
        raise ValueError("headphone analysis output must include tradeoffs or gaps.")

    route = _route_for_input(input_data, catalog)
    if not _is_earphones_headphones_route(route, catalog):
        raise ValueError("headphone analysis received a non-audio input.")
    if not _is_earphones_headphones_text(analysis.category, catalog):
        raise ValueError("headphone analysis output used a non-audio category.")

    texts = (
        analysis.category,
        analysis.fit_summary,
        *analysis.strengths,
        *analysis.weaknesses,
        *analysis.warnings,
    )
    if any(_contains_forbidden_text(text) for text in texts):
        raise ValueError("headphone analysis output included forbidden text.")
    if not _mentions_required_earphones_headphones_coverage(analysis):
        raise ValueError("headphone analysis omitted required audio-specific coverage.")

    if _has_weak_or_sparse_evidence(input_data):
        if analysis.confidence.score > 0.6:
            raise ValueError("weak evidence requires restrained confidence.")
        if not _mentions_evidence_limitation(analysis):
            raise ValueError("weak evidence requires explicit limitations.")


def _fallback_for_non_audio(
    input_data: ProductAnalysisAgentInput,
    route: ProductAnalysisRoute,
    catalog: AgentCatalog,
) -> tuple[CategoryAnalysis, str]:
    if _is_technology_route(route, catalog):
        return (
            _technology_domain_fallback_analysis(input_data, catalog),
            "technology_domain_fallback_non_audio",
        )
    return _generic_fallback_analysis(input_data), "generic_fallback_non_audio"


def _technology_domain_fallback_analysis(
    input_data: ProductAnalysisAgentInput,
    catalog: AgentCatalog,
) -> CategoryAnalysis:
    weak_or_sparse = _has_weak_or_sparse_evidence(input_data)
    category = _analysis_category(input_data)
    product_name = input_data.product.name
    listing_ids = _input_listing_ids(input_data)
    evidence_ids = _fallback_evidence_ids(input_data)
    source_ids = _fallback_source_ids(input_data)
    route = _route_for_input(input_data, catalog)
    score = 0.45 if weak_or_sparse else 0.6

    strengths = _fallback_strengths(input_data)
    if _is_earphones_headphones_route(route, catalog):
        strengths = (
            *strengths,
            "A technology-domain fallback is available when headphone-focused output is unavailable.",
        )

    warnings: tuple[str, ...] = ()
    if weak_or_sparse:
        warnings = (
            "Only limited source evidence was supplied, so confidence is low and "
            "missing technology claims should stay unknown.",
        )
    if any(
        _listing_has_marketplace_or_unknown_seller(listing)
        for listing in input_data.listings
    ):
        warnings = (
            *warnings,
            "Seller and listing trust still need a separate check before this "
            "could be treated as a safe purchase option.",
        )

    return CategoryAnalysis(
        product_id=input_data.product.product_id,
        listing_ids=listing_ids,
        category=category,
        fit_summary=(
            f"Broad technology fit analysis for {product_name} based on supplied "
            "product, listing, and source evidence. It screens practical tech "
            "tradeoffs but is not a final recommendation."
        ),
        strengths=strengths,
        weaknesses=(
            f"Important {category} details still need checking for real-world "
            "fit, compatibility, durability, support, and regional model differences.",
            "Specs, warranty, accessory, software, and connectivity caveats "
            "should stay unknown unless source evidence confirms them.",
        ),
        warnings=warnings,
        confidence=_confidence(
            score,
            "Confidence is based only on supplied evidence and broad technology fit rules.",
        ),
        evidence_ids=evidence_ids,
        source_ids=source_ids,
    )


def _generic_fallback_analysis(
    input_data: ProductAnalysisAgentInput,
) -> CategoryAnalysis:
    weak_or_sparse = _has_weak_or_sparse_evidence(input_data)
    category = _analysis_category(input_data)
    product_name = input_data.product.name
    listing_ids = _input_listing_ids(input_data)
    evidence_ids = _fallback_evidence_ids(input_data)
    source_ids = _fallback_source_ids(input_data)
    score = 0.42 if weak_or_sparse else 0.58

    warnings: tuple[str, ...] = ()
    if weak_or_sparse:
        warnings = (
            "Only limited source evidence was supplied, so confidence is low and "
            "missing claims should stay unknown.",
        )

    return CategoryAnalysis(
        product_id=input_data.product.product_id,
        listing_ids=listing_ids,
        category=category,
        fit_summary=(
            f"Generic fit analysis for {product_name} based on the supplied "
            "product, listing, and source evidence."
        ),
        strengths=_fallback_strengths(input_data),
        weaknesses=(
            f"Key {category} tradeoffs still need checking against the shopper's "
            "needs, listing details, warranty, returns, and region.",
            "Evidence gaps may remain around long-term owner experience and "
            "whether listing details fully match the product.",
        ),
        warnings=warnings,
        confidence=_confidence(
            score,
            "Confidence is based only on supplied evidence and generic fit rules.",
        ),
        evidence_ids=evidence_ids,
        source_ids=source_ids,
    )


def _earphones_headphones_specific_analysis(
    input_data: ProductAnalysisAgentInput,
) -> CategoryAnalysis:
    weak_or_sparse = _has_weak_or_sparse_evidence(input_data)
    category = _analysis_category(input_data)
    product_name = input_data.product.name
    score = 0.48 if weak_or_sparse else 0.68
    warnings: tuple[str, ...] = ()
    if weak_or_sparse:
        warnings = (
            "Only limited headphone evidence was supplied, so missing ANC, "
            "comfort, fit, microphone, battery, codec, or device compatibility "
            "claims should stay unknown.",
        )

    return CategoryAnalysis(
        product_id=input_data.product.product_id,
        listing_ids=_input_listing_ids(input_data),
        category=category,
        fit_summary=(
            f"Earphones/headphones-specific fit analysis for {product_name} "
            "based on supplied source evidence, covering ANC, comfort and fit, "
            "microphone calls, battery life, codecs, device compatibility, and "
            "commute tradeoffs."
        ),
        strengths=(
            "ANC and isolation evidence provide the main source-backed check for commute noise control.",
            "Comfort, fit, and battery evidence help screen whether the headphones can handle daily use.",
            "Microphone, codec, and device compatibility evidence help flag call quality and iPhone or Android fit.",
        ),
        weaknesses=(
            "Headphone tradeoffs remain around ANC strength, comfort and fit, microphone quality, battery life, codec support, and device compatibility if any source is incomplete.",
            "A separate seller and listing trust check is still needed before treating the listing as safe to buy.",
        ),
        warnings=warnings,
        confidence=_confidence(
            score,
            "Confidence is based only on supplied headphone evidence and specialist fit rules.",
        ),
        evidence_ids=_fallback_evidence_ids(input_data),
        source_ids=_fallback_source_ids(input_data),
    )


def _fallback_strengths(input_data: ProductAnalysisAgentInput) -> tuple[str, ...]:
    strengths = []
    if input_data.evidence:
        strengths.append(
            "Supplied evidence gives a source-backed starting point for screening fit."
        )
    if input_data.listings:
        strengths.append(
            "A concrete listing is available for later price, availability, and seller checks."
        )
    if input_data.brief.constraints or input_data.brief.preferences:
        strengths.append(
            "The shopper's stated needs can be compared against the candidate's known details."
        )
    return tuple(strengths) or (
        "The candidate can be screened against the shopper's request, but evidence is minimal.",
    )


def _mock_analysis_from_model_input(model_input: str) -> CategoryAnalysis:
    payload = json.loads(model_input)
    input_data = ProductAnalysisAgentInput.model_validate(
        {
            "run_id": payload["run_id"],
            "brief": payload["brief"],
            "product": payload["product"],
            "listings": payload["listings"],
            "evidence": payload["evidence"],
        }
    )
    return _earphones_headphones_specific_analysis(input_data)


def _route_for_input(
    input_data: ProductAnalysisAgentInput,
    catalog: AgentCatalog,
) -> ProductAnalysisRoute:
    return catalog.route_product_analysis(_analysis_category(input_data))


def _is_earphones_headphones_route(
    route: ProductAnalysisRoute,
    catalog: AgentCatalog,
) -> bool:
    return route.agent_path == (
        catalog.technology_domain_agent_name,
        EARPHONES_HEADPHONES_SPECIALIST_AGENT_NAME,
    )


def _is_technology_route(route: ProductAnalysisRoute, catalog: AgentCatalog) -> bool:
    return bool(route.agent_path) and route.agent_path[0] == (
        catalog.technology_domain_agent_name
    )


def _is_earphones_headphones_text(text: str, catalog: AgentCatalog) -> bool:
    return _is_earphones_headphones_route(
        catalog.route_product_analysis(text),
        catalog,
    )


def _input_listing_ids(input_data: ProductAnalysisAgentInput) -> tuple[ListingId, ...]:
    return tuple(listing.listing_id for listing in input_data.listings)


def _fallback_evidence_ids(
    input_data: ProductAnalysisAgentInput,
) -> tuple[SourceId, ...]:
    evidence_ids = tuple(item.evidence_id for item in input_data.evidence)
    if evidence_ids:
        return evidence_ids

    source_ids = _fallback_source_ids(input_data)
    if source_ids:
        return source_ids

    return (new_id(),)


def _fallback_source_ids(input_data: ProductAnalysisAgentInput) -> tuple[SourceId, ...]:
    source_ids = [
        *(item.source_id for item in input_data.evidence),
        *input_data.product.source_ids,
    ]
    for listing in input_data.listings:
        source_ids.extend(listing.source_ids)
        source_ids.extend(listing.seller.source_ids)
    return _dedupe_source_ids(source_ids)


def _known_source_ids(input_data: ProductAnalysisAgentInput) -> set[SourceId]:
    return set(_fallback_source_ids(input_data))


def _source_ids_for_evidence_ids(
    input_data: ProductAnalysisAgentInput,
    evidence_ids: tuple[SourceId, ...],
) -> tuple[SourceId, ...]:
    evidence_by_id = {item.evidence_id: item for item in input_data.evidence}
    return _dedupe_source_ids(
        evidence_by_id[evidence_id].source_id
        for evidence_id in evidence_ids
        if evidence_id in evidence_by_id
    )


def _dedupe_source_ids(source_ids: Iterable[SourceId]) -> tuple[SourceId, ...]:
    deduped: list[SourceId] = []
    seen: set[SourceId] = set()
    for source_id in source_ids:
        if source_id in seen:
            continue
        deduped.append(source_id)
        seen.add(source_id)
    return tuple(deduped)


def _analysis_category(input_data: ProductAnalysisAgentInput) -> str:
    for candidate in (
        input_data.brief.category,
        input_data.product.category,
        _category_from_query(input_data.brief.original_query),
    ):
        if candidate and not _contains_forbidden_text(candidate):
            return " ".join(candidate.strip().split())
    return "general product"


def _category_from_query(query: str) -> str:
    cleaned = " ".join(query.strip().split())
    return cleaned[:80] if cleaned else "general product"


def _has_weak_or_sparse_evidence(input_data: ProductAnalysisAgentInput) -> bool:
    if len(input_data.evidence) < 2:
        return True
    weak_levels = {
        SourceQualityLevel.WEAK,
        SourceQualityLevel.MIXED,
        SourceQualityLevel.UNKNOWN,
    }
    return any(
        evidence.source_quality.level in weak_levels or evidence.confidence.score < 0.5
        for evidence in input_data.evidence
    )


def _mentions_evidence_limitation(analysis: CategoryAnalysis) -> bool:
    combined = " ".join(
        (
            analysis.fit_summary,
            *analysis.weaknesses,
            *analysis.warnings,
            analysis.confidence.rationale or "",
        )
    ).casefold()
    markers = (
        "evidence",
        "gap",
        "limited",
        "sparse",
        "weak",
        "missing",
        "unknown",
        "uncertain",
    )
    return any(marker in combined for marker in markers)


def _mentions_required_earphones_headphones_coverage(
    analysis: CategoryAnalysis,
) -> bool:
    combined = " ".join(
        (
            analysis.fit_summary,
            *analysis.strengths,
            *analysis.weaknesses,
            *analysis.warnings,
        )
    ).casefold()
    required_groups = (
        (
            "anc",
            "active noise",
            "noise cancellation",
            "noise cancelling",
            "noise canceling",
            "isolation",
        ),
        ("comfort", "fit", "ear tip", "eartip", "clamp", "seal"),
        ("microphone", "mic", "call", "calls", "voice"),
        ("battery", "runtime", "charging", "charge", "hours"),
        (
            "codec",
            "bluetooth",
            "aac",
            "sbc",
            "ldac",
            "aptx",
            "device",
            "iphone",
            "android",
            "multipoint",
            "latency",
            "compatibility",
        ),
    )
    return all(any(marker in combined for marker in group) for group in required_groups)


def _listing_has_marketplace_or_unknown_seller(listing: ProductListing) -> bool:
    return listing.seller.is_marketplace_seller is not False


def _contains_forbidden_text(text: str | None) -> bool:
    if not text:
        return False
    normalized = text.casefold()
    patterns = (
        r"\bunsupported categor",
        r"\bunsupported product",
        r"\bnot supported\b",
        r"\bno specialist\b",
        r"\bspecialist-only\b",
        r"\bcannot (?:support|analyze|assess|route)\b",
        r"\bcan't (?:support|analyze|assess|route)\b",
        r"\brefuse(?:d|s)? (?:category|product|analysis)\b",
        r"\b[A-Za-z]+Agent\b",
        r"\binternal agent\b",
    )
    return any(re.search(pattern, text) is not None for pattern in patterns) or any(
        re.search(pattern, normalized) is not None for pattern in patterns[:-2]
    )


def _confidence(score: float, rationale: str) -> Confidence:
    if score < 0.5:
        level = ConfidenceLevel.LOW
    elif score < 0.75:
        level = ConfidenceLevel.MEDIUM
    else:
        level = ConfidenceLevel.HIGH
    return Confidence(score=score, level=level, rationale=rationale)
