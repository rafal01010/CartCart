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


class TechnologyDomainAnalystModelRunner(Protocol):
    async def run(
        self,
        agent: Agent[Any],
        model_input: str,
        *,
        run_config: RunConfig,
        max_turns: int,
    ) -> Any:
        """Run the SDK technology-domain analyst and return its raw run result."""


@dataclass
class OpenAIAgentsSDKTechnologyDomainAnalystModelRunner:
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
class MockTechnologyDomainAnalystModelRunner:
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
class LiveTechnologyDomainAnalystAgent:
    settings: Settings
    catalog: AgentCatalog = field(default_factory=build_default_agent_catalog)
    model_runner: TechnologyDomainAnalystModelRunner = field(
        default_factory=OpenAIAgentsSDKTechnologyDomainAnalystModelRunner,
    )
    _workbench_activity: tuple[dict[str, Any], ...] = field(
        default=(),
        init=False,
        repr=False,
    )

    async def run(self, input_data: ProductAnalysisAgentInput) -> CategoryAnalysis:
        route = _route_for_input(input_data, self.catalog)
        if _is_generic_route(route, self.catalog):
            analysis = _generic_fallback_analysis(input_data)
            self._set_activity(
                "generic_fallback_non_technology",
                input_data,
                route,
                analysis,
            )
            return analysis

        configuration = build_openai_agent_run_configuration(
            self.settings,
            agent_name="TechnologyDomainAnalystAgent",
            run_id=str(input_data.run_id),
        )
        agent = _build_technology_domain_analyst_agent(configuration.model)
        run_config = RunConfig(
            model=configuration.model,
            model_settings=ModelSettings(
                temperature=0,
                max_tokens=1100,
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
            analysis = _generic_fallback_analysis(input_data)
            self._set_activity("timeout_generic_fallback", input_data, route, analysis)
            return analysis
        except (ValidationError, ValueError, TypeError):
            analysis = _generic_fallback_analysis(input_data)
            self._set_activity(
                "schema_invalid_generic_fallback",
                input_data,
                route,
                analysis,
            )
            return analysis
        except Exception:
            analysis = _generic_fallback_analysis(input_data)
            self._set_activity("error_generic_fallback", input_data, route, analysis)
            return analysis

        self._set_activity(
            "model_technology_analysis_completed",
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
                    "agent": "TechnologyDomainAnalystAgent",
                    "allowed_tools": [],
                    "category": _analysis_category(input_data),
                    "declared_route": route.model_dump(mode="json"),
                    "specialist_agent_name": _specialist_agent_name(route),
                    "listing_count": len(input_data.listings),
                    "evidence_count": len(input_data.evidence),
                    "weak_or_sparse_evidence": _has_weak_or_sparse_evidence(
                        input_data
                    ),
                },
                "output": {
                    "declared_route": route.model_dump(mode="json"),
                    "analysis": analysis.model_dump(mode="json"),
                },
            },
        )


@dataclass
class _MockRunResult:
    final_output: Any


def _build_technology_domain_analyst_agent(model: str) -> Agent[Any]:
    return Agent(
        name="CartCartTechnologyDomainAnalystAgent",
        model=model,
        model_settings=ModelSettings(
            temperature=0,
            max_tokens=1100,
            include_usage=True,
        ),
        instructions=(
            "Analyze one technology product for fit against the shopper's brief "
            "and return only a structured CategoryAnalysis. Use the supplied "
            "declared route only as routing context: when the route includes an "
            "MVP specialist, keep this as broad technology-domain fallback "
            "analysis and do not expose internal agent names to shoppers. For "
            "technology categories without an MVP specialist, cover shared "
            "technology concerns such as compatibility, specs, durability, "
            "connectivity, power or battery needs, software/update/support "
            "caveats, accessories, warranty, regional model differences, and "
            "evidence gaps. Use only supplied product, listing, and evidence "
            "records. Cite supplied evidence_ids and source_ids for factual "
            "claims, and do not invent specs, prices, sellers, IDs, or source "
            "claims. If evidence is weak or sparse, return lower confidence and "
            "plain limitations. Do not rank final recommendations, browse, call "
            "tools, invent specialists, route non-technology products into "
            "technology specialists, or expose agents, providers, prompts, "
            "traces, policies, or schemas to shoppers."
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
                "product_category_routes": catalog.product_category_routes,
                "technology_category_keywords": catalog.technology_category_keywords,
            },
            "declared_route": route.model_dump(mode="json"),
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
        raise ValueError("technology analysis output used an unknown product ID.")

    listing_ids = analysis.listing_ids or _input_listing_ids(input_data)
    unknown_listing_ids = set(listing_ids) - set(_input_listing_ids(input_data))
    if unknown_listing_ids:
        raise ValueError("technology analysis output used unknown listing IDs.")

    known_evidence_ids = {item.evidence_id for item in input_data.evidence}
    unknown_evidence_ids = set(analysis.evidence_ids) - known_evidence_ids
    if unknown_evidence_ids:
        raise ValueError("technology analysis output used unknown evidence IDs.")

    known_source_ids = _known_source_ids(input_data)
    unknown_source_ids = set(analysis.source_ids) - known_source_ids
    if unknown_source_ids:
        raise ValueError("technology analysis output used unknown source IDs.")

    cited_source_ids = _source_ids_for_evidence_ids(input_data, analysis.evidence_ids)
    source_ids = _dedupe_source_ids((*analysis.source_ids, *cited_source_ids))
    if input_data.evidence and not source_ids:
        raise ValueError("technology analysis output did not preserve source IDs.")

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
        raise ValueError("technology analysis output must include fit strengths.")
    if not analysis.weaknesses:
        raise ValueError("technology analysis output must include tradeoffs or gaps.")

    if _is_generic_route(_route_for_input(input_data, catalog), catalog):
        raise ValueError("technology analysis received a non-technology input.")
    if not _is_technology_text(analysis.category, catalog):
        raise ValueError("technology analysis output used a non-technology category.")

    texts = (
        analysis.category,
        analysis.fit_summary,
        *analysis.strengths,
        *analysis.weaknesses,
        *analysis.warnings,
    )
    if any(_contains_forbidden_text(text) for text in texts):
        raise ValueError("technology analysis output included forbidden text.")

    if _has_weak_or_sparse_evidence(input_data):
        if analysis.confidence.score > 0.6:
            raise ValueError("weak evidence requires restrained confidence.")
        if not _mentions_evidence_limitation(analysis):
            raise ValueError("weak evidence requires explicit limitations.")


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
    score = 0.45 if weak_or_sparse else 0.62

    fit_summary = (
        f"Broad technology fit analysis for {product_name} based on supplied "
        "product, listing, and source evidence. It screens practical tech "
        "tradeoffs but is not a final recommendation."
    )
    strengths = _fallback_strengths(input_data)
    if _specialist_agent_name(route) is not None:
        strengths = (
            *strengths,
            "The product category has a narrower technology review path available "
            "for deeper category-specific checks.",
        )
    weaknesses = (
        f"Important {category} details still need checking for real-world fit, "
        "compatibility, durability, support, and regional model differences.",
        "Software, firmware, warranty, accessory, and connectivity caveats may "
        "matter but should stay unknown unless source evidence confirms them.",
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
        fit_summary=fit_summary,
        strengths=strengths,
        weaknesses=weaknesses,
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
    catalog = build_default_agent_catalog()
    return _technology_domain_fallback_analysis(input_data, catalog)


def _route_for_input(
    input_data: ProductAnalysisAgentInput,
    catalog: AgentCatalog,
) -> ProductAnalysisRoute:
    return catalog.route_product_analysis(_analysis_category(input_data))


def _is_generic_route(route: ProductAnalysisRoute, catalog: AgentCatalog) -> bool:
    return route.agent_path == (catalog.generic_fallback_agent_name,)


def _specialist_agent_name(route: ProductAnalysisRoute) -> str | None:
    if len(route.agent_path) < 2:
        return None
    return route.agent_path[1]


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


def _is_technology_text(text: str, catalog: AgentCatalog) -> bool:
    return not _is_generic_route(catalog.route_product_analysis(text), catalog)


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
