import asyncio
import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Protocol

from agents import Agent, ModelSettings, RunConfig
from pydantic import ValidationError

from app.agents.context_management import BoundedRunner, ContextBudgetExceeded
from app.agents.catalog import (
    AgentCatalog,
    ProductAnalysisRoute,
    build_default_agent_catalog,
)
from app.agents.contracts import ProductAnalysisAgentInput
from app.agents.model_input_projection import evidence_model_fields, restore_evidence
from app.agents.openai_config import (
    apply_openai_agent_run_profile,
    build_openai_agent_run_configuration,
)
from app.agents.research_guidance import SHOPPER_ADVICE_GUIDANCE
from app.core.settings import Settings
from app.schemas.analysis import CategoryAnalysis
from app.schemas.confidence import Confidence, ConfidenceLevel
from app.schemas.ids import ListingId, SourceId
from app.schemas.products import ProductListing
from app.schemas.search_sources import SourceQualityLevel


SMARTPHONE_SPECIALIST_AGENT_NAME = "SmartphoneSpecialistAgent"


class SmartphoneSpecialistModelRunner(Protocol):
    async def run(
        self,
        agent: Agent[Any],
        model_input: str,
        *,
        run_config: RunConfig,
        max_turns: int,
    ) -> Any:
        """Run the SDK smartphone specialist and return its raw run result."""


@dataclass
class OpenAIAgentsSDKSmartphoneSpecialistModelRunner:
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
class MockSmartphoneSpecialistModelRunner:
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
class LiveSmartphoneSpecialistAgent:
    settings: Settings
    catalog: AgentCatalog = field(default_factory=build_default_agent_catalog)
    model_runner: SmartphoneSpecialistModelRunner = field(
        default_factory=OpenAIAgentsSDKSmartphoneSpecialistModelRunner,
    )
    _workbench_activity: tuple[dict[str, Any], ...] = field(
        default=(),
        init=False,
        repr=False,
    )

    async def run(self, input_data: ProductAnalysisAgentInput) -> CategoryAnalysis:
        route = _route_for_input(input_data, self.catalog)
        if not _is_smartphone_route(route, self.catalog):
            analysis, status = _fallback_for_non_phone(input_data, route, self.catalog)
            self._set_activity(status, input_data, route, analysis)
            return analysis

        configuration = build_openai_agent_run_configuration(
            self.settings,
            agent_name=SMARTPHONE_SPECIALIST_AGENT_NAME,
            run_id=str(input_data.run_id),
        )
        agent = _build_smartphone_specialist_agent(configuration.model)
        apply_openai_agent_run_profile(agent, configuration)
        run_config = RunConfig(
            model_settings=ModelSettings(
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
        except ContextBudgetExceeded:
            raise
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
            "model_smartphone_analysis_completed",
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
                    "agent": SMARTPHONE_SPECIALIST_AGENT_NAME,
                    "allowed_tools": [],
                    "category": _analysis_category(input_data),
                    "declared_route": route.model_dump(mode="json"),
                    "listing_count": len(input_data.listings),
                    "evidence_count": len(input_data.evidence),
                    "weak_or_sparse_evidence": _has_weak_or_sparse_evidence(input_data),
                },
                "output": analysis.model_dump(mode="json"),
            },
        )


@dataclass
class _MockRunResult:
    final_output: Any


def _build_smartphone_specialist_agent(model: str) -> Agent[Any]:
    return Agent(
        name="CartCartSmartphoneSpecialistAgent",
        model=model,
        model_settings=ModelSettings(
            max_tokens=1200,
            include_usage=True,
        ),
        instructions=(
            "Analyze exactly one smartphone candidate for fit against the "
            "shopper's brief and return only a structured CategoryAnalysis. "
            "This specialist is only for smartphone, phone, or mobile-phone "
            "products routed through the technology domain. Use only supplied "
            "product, listing, and available evidence. Source associations are optional. "
            "Give useful qualified judgment without inventing specs, prices, "
            "seller facts, product IDs, listing IDs, evidence IDs, or source IDs. "
            "Cover smartphone-specific fit: camera quality, battery life and "
            "charging, OS/security update support, day-to-day performance, "
            "storage or memory caveats when relevant, region/model variant "
            "differences such as supported network bands when relevant. "
            "Record confidence and evidence gaps only as internal metadata. "
            "Do not invent certainty. Do not analyze non-phone "
            "products as phones, rank final recommendations, browse, call tools, "
            "or expose agents, providers, prompts, traces, policies, or schemas "
            "to shoppers. "
            + SHOPPER_ADVICE_GUIDANCE
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
            **evidence_model_fields(input_data.evidence),
            "declared_route": route.model_dump(mode="json"),
            "required_smartphone_coverage": (
                "camera",
                "battery",
                "update support",
                "performance",
                "region/model caveats",
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
    return analysis


def _normalize_category_analysis(
    analysis: CategoryAnalysis,
    input_data: ProductAnalysisAgentInput,
) -> CategoryAnalysis:
    if analysis.product_id != input_data.product.product_id:
        raise ValueError("smartphone analysis output used an unknown product ID.")

    listing_ids = analysis.listing_ids or _input_listing_ids(input_data)
    unknown_listing_ids = set(listing_ids) - set(_input_listing_ids(input_data))
    if unknown_listing_ids:
        raise ValueError("smartphone analysis output used unknown listing IDs.")

    known_evidence_ids = {item.evidence_id for item in input_data.evidence}
    evidence_ids = tuple(
        item for item in analysis.evidence_ids if item in known_evidence_ids
    )
    known_source_ids = _known_source_ids(input_data)
    source_ids = _dedupe_source_ids(
        (
            *(item for item in analysis.source_ids if item in known_source_ids),
            *_source_ids_for_evidence_ids(input_data, evidence_ids),
        )
    )
    return analysis.model_copy(
        update={
            "listing_ids": listing_ids,
            "evidence_ids": evidence_ids,
            "source_ids": source_ids,
        }
    )


def _fallback_for_non_phone(
    input_data: ProductAnalysisAgentInput,
    route: ProductAnalysisRoute,
    catalog: AgentCatalog,
) -> tuple[CategoryAnalysis, str]:
    if _is_technology_route(route, catalog):
        return (
            _technology_domain_fallback_analysis(input_data, catalog),
            "technology_domain_fallback_non_phone",
        )
    return _generic_fallback_analysis(input_data), "generic_fallback_non_phone"


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
    score = 0.45 if weak_or_sparse else 0.6

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
            "Listing seller context is incomplete.",
        )

    return CategoryAnalysis(
        product_id=input_data.product.product_id,
        listing_ids=listing_ids,
        category=category,
        fit_summary=f"Consider {product_name} for {category}.",
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
        fit_summary=f"Consider {product_name} for {category}.",
        warnings=warnings,
        confidence=_confidence(
            score,
            "Confidence is based only on supplied evidence and generic fit rules.",
        ),
        evidence_ids=evidence_ids,
        source_ids=source_ids,
    )


def _smartphone_specific_analysis(
    input_data: ProductAnalysisAgentInput,
) -> CategoryAnalysis:
    weak_or_sparse = _has_weak_or_sparse_evidence(input_data)
    category = _analysis_category(input_data)
    product_name = input_data.product.name
    score = 0.48 if weak_or_sparse else 0.68
    warnings: tuple[str, ...] = ()
    if weak_or_sparse:
        warnings = (
            "Only limited smartphone evidence was supplied, so missing camera, "
            "battery, update, performance, or regional model claims should stay unknown.",
        )

    return CategoryAnalysis(
        product_id=input_data.product.product_id,
        listing_ids=_input_listing_ids(input_data),
        category=category,
        fit_summary=f"Consider {product_name} for {category}.",
        warnings=warnings,
        confidence=_confidence(
            score,
            "Confidence is based only on supplied smartphone evidence and specialist fit rules.",
        ),
        evidence_ids=_fallback_evidence_ids(input_data),
        source_ids=_fallback_source_ids(input_data),
    )


def _mock_analysis_from_model_input(model_input: str) -> CategoryAnalysis:
    payload = json.loads(model_input)
    input_data = ProductAnalysisAgentInput.model_validate(
        {
            "run_id": payload["run_id"],
            "brief": payload["brief"],
            "product": payload["product"],
            "listings": payload["listings"],
            "evidence": restore_evidence(payload),
        }
    )
    return _smartphone_specific_analysis(input_data)


def _route_for_input(
    input_data: ProductAnalysisAgentInput,
    catalog: AgentCatalog,
) -> ProductAnalysisRoute:
    return catalog.route_product_analysis(_analysis_category(input_data))


def _is_smartphone_route(route: ProductAnalysisRoute, catalog: AgentCatalog) -> bool:
    return route.agent_path == (
        catalog.technology_domain_agent_name,
        SMARTPHONE_SPECIALIST_AGENT_NAME,
    )


def _is_technology_route(route: ProductAnalysisRoute, catalog: AgentCatalog) -> bool:
    return bool(route.agent_path) and route.agent_path[0] == (
        catalog.technology_domain_agent_name
    )


def _is_smartphone_text(text: str, catalog: AgentCatalog) -> bool:
    return _is_smartphone_route(catalog.route_product_analysis(text), catalog)


def _input_listing_ids(input_data: ProductAnalysisAgentInput) -> tuple[ListingId, ...]:
    return tuple(listing.listing_id for listing in input_data.listings)


def _fallback_evidence_ids(
    input_data: ProductAnalysisAgentInput,
) -> tuple[SourceId, ...]:
    return tuple(dict.fromkeys(item.evidence_id for item in input_data.evidence))


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
        if candidate:
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


def _listing_has_marketplace_or_unknown_seller(listing: ProductListing) -> bool:
    return listing.seller.is_marketplace_seller is not False


def _confidence(score: float, rationale: str) -> Confidence:
    if score < 0.5:
        level = ConfidenceLevel.LOW
    elif score < 0.75:
        level = ConfidenceLevel.MEDIUM
    else:
        level = ConfidenceLevel.HIGH
    return Confidence(score=score, level=level, rationale=rationale)
