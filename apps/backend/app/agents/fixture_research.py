"""Typed, network-free research replay for fixture shopping runs.

These adapters replay explicit source decisions and entities. Unknown provider
results are insufficient evidence; they never become products by heuristic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import AnyHttpUrl

from app.agents.contracts import (
    DiscoveryAgentInput,
    DiscoveryAgentOutcome,
    DiscoveryAgentOutput,
    DiscoveryNextAction,
    DiscoverySourceDecision,
    DiscoverySourceKind,
    ExtractionAgentInput,
    ExtractionAgentOutput,
    ExtractionEvidenceGap,
    ExtractionUserAddedMatch,
)
from app.providers.contracts import ExtractionProviderOptions, SearchProviderOptions
from app.schemas.search_sources import (
    SearchQuery,
    SearchResult,
    SourceSnapshot,
    SourceType,
)

if TYPE_CHECKING:
    from app.orchestration.fixtures import MonitorFixtureRunOutput


def _fixture_kind(source_type: SourceType) -> DiscoverySourceKind:
    return {
        SourceType.PROFESSIONAL_REVIEW: DiscoverySourceKind.PROFESSIONAL_REVIEW,
        SourceType.OFFICIAL_BRAND_PAGE: DiscoverySourceKind.OFFICIAL_BRAND_PAGE,
        SourceType.RETAILER_LISTING: DiscoverySourceKind.RETAILER_LISTING,
    }.get(source_type, DiscoverySourceKind.UNCERTAIN)


@dataclass(frozen=True)
class FixtureDiscoveryAgent:
    replay: MonitorFixtureRunOutput | None = None

    async def run(self, input_data: DiscoveryAgentInput) -> DiscoveryAgentOutput:
        known = (
            {item.source_id for item in self.replay.search_results}
            if self.replay is not None
            else set()
        )
        results = input_data.seed_results[:12]
        decisions = tuple(
            DiscoverySourceDecision(
                source_id=item.source_id,
                classification=(
                    _fixture_kind(item.source_type)
                    if item.source_id in known
                    else DiscoverySourceKind.UNCERTAIN
                ),
                confidence=1.0 if item.source_id in known else 0.0,
                reasons=(
                    "Explicit fixture replay classification."
                    if item.source_id in known
                    else "No semantic fixture decision is available for this result.",
                ),
                intended_treatment=(
                    "Inspect the replayed source."
                    if item.source_id in known
                    else "Inspect only to record the fixture limitation."
                ),
                next_action=DiscoveryNextAction.FETCH,
            )
            for item in results
        )
        return DiscoveryAgentOutput(
            search_results=input_data.seed_results,
            source_decisions=decisions,
            selected_source_ids=tuple(item.source_id for item in results),
            outcome=(
                DiscoveryAgentOutcome.SELECTED
                if results
                else DiscoveryAgentOutcome.INSUFFICIENT_CANDIDATES
            ),
            notes=()
            if known
            else ("No category-compatible fixture agent replay is available.",),
        )


@dataclass(frozen=True)
class FixtureExtractionAgent:
    replay: MonitorFixtureRunOutput | None = None

    async def run(self, input_data: ExtractionAgentInput) -> ExtractionAgentOutput:
        if self.replay is None:
            return ExtractionAgentOutput(
                evidence_gaps=tuple(
                    ExtractionEvidenceGap(
                        source_id=source_id,
                        summary="No fixture interpretation is available for this source.",
                    )
                    for source_id in input_data.snapshot_ids
                )
            )
        source_ids = set(input_data.snapshot_ids)
        listings = tuple(
            item
            for item in self.replay.listings
            if source_ids.intersection(item.source_ids)
        )
        product_ids = {item.product_id for item in listings}
        product_ids.update(
            item.target.product_id
            for item in self.replay.source_evidence
            if item.source_id in source_ids and item.target.product_id is not None
        )
        products = tuple(
            item for item in self.replay.products if item.product_id in product_ids
        )
        evidence = tuple(
            item for item in self.replay.source_evidence if item.source_id in source_ids
        )
        return ExtractionAgentOutput(
            products=products,
            listings=listings,
            source_evidence=evidence,
            user_added_matches=tuple(
                ExtractionUserAddedMatch(
                    candidate_id=user_added.candidate_id,
                    product_id=listing.product_id,
                    listing_id=listing.listing_id,
                    source_id=input_data.snapshot_ids[0],
                    confidence="confirmed",
                    rationale="Exact named product in the fixture replay.",
                )
                for user_added in input_data.user_added_products
                if user_added.url is None and user_added.input_text is not None
                for listing in listings
                for product in products
                if listing.product_id == product.product_id
                and user_added.input_text.strip().casefold() == product.name.casefold()
            ),
        )


@dataclass
class FixtureSearchReplayProvider:
    results: tuple[SearchResult, ...]
    provider_name: str = "fixture-search"
    served: bool = False

    async def search(
        self,
        query: SearchQuery,
        options: SearchProviderOptions | None = None,
    ) -> tuple[SearchResult, ...]:
        del query, options
        if self.served:
            return ()
        self.served = True
        return self.results


@dataclass(frozen=True)
class FixtureSnapshotReplayProvider:
    replay: MonitorFixtureRunOutput
    provider_name: str = "fixture-extraction"

    async def extract(
        self,
        url: AnyHttpUrl,
        options: ExtractionProviderOptions | None = None,
    ) -> SourceSnapshot:
        del options
        for snapshot in self.replay.source_snapshots:
            if str(snapshot.url) == str(url):
                return snapshot.model_copy(
                    update={
                        "provider": snapshot.provider.model_copy(
                            update={"provider_name": self.provider_name}
                        )
                    }
                )
        raise ValueError("URL is not in the approved fixture snapshot replay.")
