"""Typed, run-scoped helpers shared by live shopping decision owners."""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Callable

from agents import FunctionTool, function_tool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.context_management import source_bundle_context
from app.agents.catalog import ApprovedSDKTool, DEFAULT_AGENT_CATALOG
from app.schemas.analysis import ListingTrustAssessment, ListingTrustLevel
from app.agents.live_source_intelligence_manager import (
    SourceIntelligenceManagerAgent,
    SourceManagerInput,
)
from app.agents.research_tools import (
    _neutral_url,
    _safe_public_result_url,
    _source_policy_allows,
)
from app.db.repositories.products import ProductRepository
from app.db.repositories.results import ResultRepository
from app.db.repositories.search_sources import SearchSourceRepository
from app.schemas.ids import ListingId, RunId, SourceId
from app.schemas.intake import ShoppingBrief
from app.schemas.products import CanonicalProduct, ProductListing
from app.schemas.regions import RegionCode
from app.schemas.search_sources import SourceIntelligenceCapability
from app.providers.contracts import SourceAllowAvoidPolicy
from app.services.listing_trust import assess_listing_trust, price_plausibility_contexts


def assess_run_listings(
    products: tuple[CanonicalProduct, ...],
    listings: tuple[ProductListing, ...],
    persisted: tuple[ListingTrustAssessment, ...] = (),
) -> dict[ListingId, ListingTrustAssessment]:
    groups = tuple(
        tuple(item for item in listings if item.product_id == product.product_id)
        for product in products
    )
    contexts = price_plausibility_contexts(groups)
    results = {
        listing.listing_id: assess_listing_trust(
            listing, contexts.get(listing.listing_id)
        )
        for listing in listings
    }
    blocked_ids = {
        item.listing_id
        for item in persisted
        if item.level == ListingTrustLevel.SUSPICIOUS
    }
    for assessment in persisted:
        if (
            assessment.listing_id in results
            and assessment.listing_id not in blocked_ids
            and results[assessment.listing_id].level != ListingTrustLevel.SUSPICIOUS
        ):
            results[assessment.listing_id] = assessment
    for assessment in persisted:
        if (
            assessment.listing_id in results
            and assessment.level == ListingTrustLevel.SUSPICIOUS
        ):
            results[assessment.listing_id] = assessment
    return results


@dataclass
class OwnerResearchContext:
    agent_name: str
    run_id: RunId
    brief: ShoppingBrief
    region_code: RegionCode | None
    session_factory: async_sessionmaker[AsyncSession] | None = None
    shared_session: AsyncSession | None = None
    source_manager: SourceIntelligenceManagerAgent | None = None
    source_policy: SourceAllowAvoidPolicy = field(
        default_factory=SourceAllowAvoidPolicy
    )
    allowed_quote_ids: Callable[[], frozenset[SourceId]] | None = None
    allowed_source_ids: Callable[[], frozenset[SourceId]] | None = None
    activity: list[dict[str, Any]] = field(default_factory=list)
    _read_count: int = 0
    _compare_count: int = 0
    _candidate_compare_count: int = 0
    _trust_count: int = 0
    _source_count: int = 0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def __post_init__(self) -> None:
        if self.session_factory is None and self.shared_session is None:
            raise ValueError("Owner helpers require run-scoped persistence.")
        approved = DEFAULT_AGENT_CATALOG.require(self.agent_name).approved_sdk_tools
        required = {
            ApprovedSDKTool.READ_RUN_EVIDENCE,
            ApprovedSDKTool.COMPARE_EVIDENCE,
            ApprovedSDKTool.COMPARE_CANDIDATES,
            ApprovedSDKTool.CHECK_LISTING_TRUST,
            ApprovedSDKTool.CONSULT_SOURCE_INTELLIGENCE,
        }
        if not required.issubset(approved):
            raise ValueError("Owner is not approved for research helpers.")

    @asynccontextmanager
    async def _session(self) -> AsyncIterator[AsyncSession]:
        if self.shared_session is not None:
            yield self.shared_session
        else:
            assert self.session_factory is not None
            async with self.session_factory() as session:
                yield session

    def _record(self, name: str, status: str, **output: Any) -> None:
        self.activity.append(
            {
                "tool_name": name,
                "status": status,
                "input": {"agent": self.agent_name, "run_id": str(self.run_id)},
                "output": output,
            }
        )

    def sdk_tools(self) -> tuple[FunctionTool, ...]:
        @function_tool
        async def read_run_evidence(source_id: str) -> str:
            """Read a persisted source and its bounded evidence from this shopping run.

            Args:
                source_id: Persisted search-result ID from this run.
            """
            return json.dumps(await self.read_source(source_id))

        @function_tool
        async def compare_evidence(source_ids: list[str]) -> str:
            """Compare up to four persisted sources without generating new claims.

            Args:
                source_ids: Search-result IDs from this shopping run.
            """
            return json.dumps(await self.compare(source_ids))

        @function_tool
        async def compare_candidates(product_ids: list[str]) -> str:
            """Compare up to three persisted run products and checked listing risk.

            Args:
                product_ids: Persisted product IDs from this shopping run.
            """
            return json.dumps(await self.compare_candidates(product_ids))

        @function_tool
        async def check_listing_trust(listing_id: str) -> str:
            """Check deterministic seller/listing risk for a persisted run listing.

            Args:
                listing_id: Persisted listing ID from this shopping run.
            """
            return json.dumps(await self.check_trust(listing_id))

        @function_tool
        async def consult_source_intelligence(
            capability: SourceIntelligenceCapability,
            product_id: str | None = None,
            product_name: str | None = None,
            evidence_id: str | None = None,
        ) -> str:
            """Ask one source specialist about a persisted product or a cited candidate.

            Args:
                capability: One of video_review, community_discussion, amazon_product_listing_review, ikea_regional_official_store.
                product_id: Persisted product ID from this shopping run, if available.
                product_name: Candidate name appearing in an exact recorded page quote.
                evidence_id: Evidence ID returned by record_source_quote for that candidate.
            """
            return json.dumps(
                await self.consult_source(
                    capability,
                    product_id=product_id,
                    product_name=product_name,
                    evidence_id=evidence_id,
                )
            )

        return (
            read_run_evidence,
            compare_evidence,
            compare_candidates,
            check_listing_trust,
            consult_source_intelligence,
        )

    async def read_source(self, source_id: str) -> dict[str, Any]:
        try:
            parsed = SourceId(source_id)
        except (TypeError, ValueError):
            self._record("read_run_evidence", "invalid_request")
            return {"status": "invalid_request", "gap": "Invalid source ID."}
        async with self._lock:
            if self._read_count >= 8:
                self._record("read_run_evidence", "budget_exhausted")
                return {
                    "status": "budget_exhausted",
                    "gap": "Source read limit reached.",
                }
            self._read_count += 1
            async with self._session() as session:
                repo = SearchSourceRepository(session)
                source = await repo.get_search_result_for_run(self.run_id, parsed)
                snapshot = (
                    await repo.get_snapshot_for_search_result(self.run_id, parsed)
                    if source is not None
                    else None
                )
                evidence = await repo.list_source_evidence(self.run_id)
                products = await ProductRepository(
                    session
                ).list_canonical_products_for_run(self.run_id)
        if source is None:
            self._record("read_run_evidence", "unknown_source")
            return {"status": "unknown_source", "gap": "Source is not in this run."}
        if not _safe_public_result_url(str(source.url)) or not _source_policy_allows(
            str(source.url), source.source_type, self.source_policy
        ):
            self._record("read_run_evidence", "source_rejected")
            return {"status": "gap", "gap": "Source URL is outside approved policy."}
        seen_by_owner = (
            self.allowed_source_ids is not None and parsed in self.allowed_source_ids()
        )
        attached_product = any(
            self._product_in_scope(product)
            and (
                parsed in product.source_ids
                or (snapshot is not None and snapshot.source_id in product.source_ids)
            )
            for product in products
        )
        if not seen_by_owner and not attached_product:
            self._record("read_run_evidence", "outside_owner_scope")
            return {
                "status": "gap",
                "gap": "Source is not assigned to this owner or a matching run product.",
            }
        result = {
            "status": "succeeded",
            "source_id": str(parsed),
            "title": source.title,
            "url": _neutral_url(str(source.url)),
            "source_type": source.source_type.value,
            "source_quality": source.quality.level.value,
            "snapshot_id": str(snapshot.source_id) if snapshot else None,
            "extraction_status": snapshot.extraction_status.value if snapshot else None,
            "text": (
                snapshot.extracted_content.text[:2000]
                if snapshot and snapshot.extracted_content
                else None
            ),
            "evidence": [
                {"evidence_id": str(item.evidence_id), "quote": item.claim[:400]}
                for item in evidence
                if snapshot and item.source_id == snapshot.source_id
            ][:8],
        }
        self._record("read_run_evidence", "succeeded", source_ids=[source_id])
        return result

    def _product_in_scope(self, product: CanonicalProduct) -> bool:
        if self.agent_name == "GeneralShoppingAgent":
            return True
        route = DEFAULT_AGENT_CATALOG.route_product_analysis(
            product.category or product.name
        ).agent_path
        if self.agent_name == "TechnologyDomainAnalystAgent":
            return route[0] == self.agent_name
        return route[-1] == self.agent_name

    async def compare(self, source_ids: list[str]) -> dict[str, Any]:
        if not 2 <= len(source_ids) <= 4 or len(set(source_ids)) != len(source_ids):
            self._record("compare_evidence", "invalid_request")
            return {
                "status": "invalid_request",
                "gap": "Supply 2 to 4 distinct source IDs.",
            }
        async with self._lock:
            if self._compare_count >= 3:
                self._record("compare_evidence", "budget_exhausted")
                return {
                    "status": "budget_exhausted",
                    "gap": "Comparison limit reached.",
                }
            self._compare_count += 1
        items = [await self.read_source(source_id) for source_id in source_ids]
        status = (
            "succeeded" if all(i["status"] == "succeeded" for i in items) else "gap"
        )
        self._record("compare_evidence", status, source_ids=source_ids)
        return {"status": status, "sources": items}

    async def check_trust(self, listing_id: str) -> dict[str, Any]:
        from app.schemas.ids import ListingId

        try:
            parsed = ListingId(listing_id)
        except (TypeError, ValueError):
            self._record("check_listing_trust", "invalid_request")
            return {"status": "invalid_request", "gap": "Invalid listing ID."}
        async with self._lock:
            if self._trust_count >= 3:
                self._record("check_listing_trust", "budget_exhausted")
                return {
                    "status": "budget_exhausted",
                    "gap": "Trust check limit reached.",
                }
            self._trust_count += 1
            async with self._session() as session:
                repo = ProductRepository(session)
                products = await repo.list_canonical_products_for_run(self.run_id)
                listings = await repo.list_product_listings_for_run(self.run_id)
                persisted_trust = await ResultRepository(
                    session
                ).list_listing_trust_assessments(self.run_id)
        listing = next((item for item in listings if item.listing_id == parsed), None)
        product = next(
            (
                item
                for item in products
                if listing and item.product_id == listing.product_id
            ),
            None,
        )
        if listing is None or product is None or not self._product_in_scope(product):
            self._record("check_listing_trust", "unknown_listing")
            return {"status": "unknown_listing", "gap": "Listing is not in this run."}
        assessment = assess_run_listings(products, listings, persisted_trust)[
            listing.listing_id
        ]
        self._record(
            "check_listing_trust",
            "succeeded",
            listing_id=listing_id,
            level=assessment.level.value,
        )
        return {
            "status": "succeeded",
            "listing_id": listing_id,
            "level": assessment.level.value,
            "red_flags": list(assessment.red_flags),
            "source_ids": [str(item) for item in assessment.source_ids],
            "gap": "Seller trust beyond supplied listing signals remains unverified.",
        }

    async def compare_candidates(self, product_ids: list[str]) -> dict[str, Any]:
        from app.schemas.ids import ProductId

        if not 2 <= len(product_ids) <= 3 or len(set(product_ids)) != len(product_ids):
            self._record("compare_candidates", "invalid_request")
            return {
                "status": "invalid_request",
                "gap": "Supply 2 or 3 distinct product IDs.",
            }
        try:
            parsed_ids = tuple(ProductId(item) for item in product_ids)
        except (TypeError, ValueError):
            self._record("compare_candidates", "invalid_request")
            return {"status": "invalid_request", "gap": "Invalid product ID."}
        async with self._lock:
            if self._candidate_compare_count >= 2:
                self._record("compare_candidates", "budget_exhausted")
                return {
                    "status": "budget_exhausted",
                    "gap": "Candidate comparison limit reached.",
                }
            self._candidate_compare_count += 1
            async with self._session() as session:
                repo = ProductRepository(session)
                products = await repo.list_canonical_products_for_run(self.run_id)
                listings = await repo.list_product_listings_for_run(self.run_id)
                persisted_trust = await ResultRepository(
                    session
                ).list_listing_trust_assessments(self.run_id)
        selected = [
            next((p for p in products if p.product_id == pid), None)
            for pid in parsed_ids
        ]
        if any(item is None or not self._product_in_scope(item) for item in selected):
            self._record("compare_candidates", "unknown_product")
            return {"status": "unknown_product", "gap": "Product is not in this run."}
        rows = []
        trust_by_listing = assess_run_listings(products, listings, persisted_trust)
        for product in selected:
            assert product is not None
            options = []
            for listing in listings:
                if listing.product_id != product.product_id:
                    continue
                trust = trust_by_listing[listing.listing_id]
                options.append(
                    {
                        "listing_id": str(listing.listing_id),
                        "price": listing.price.model_dump(mode="json")
                        if listing.price
                        else None,
                        "trust_level": trust.level.value,
                        "blocked": trust.level == ListingTrustLevel.SUSPICIOUS,
                        "source_ids": [str(item) for item in listing.source_ids[:4]],
                    }
                )
            rows.append(
                {
                    "product_id": str(product.product_id),
                    "name": product.name,
                    "category": product.category,
                    "source_ids": [str(item) for item in product.source_ids[:4]],
                    "listings": options[:4],
                }
            )
        self._record("compare_candidates", "succeeded", product_ids=product_ids)
        return {
            "status": "succeeded",
            "products": rows,
            "gap": "This is a comparison of recorded facts, not a verified best-buy ranking.",
        }

    async def consult_source(
        self,
        capability: SourceIntelligenceCapability,
        *,
        product_id: str | None = None,
        product_name: str | None = None,
        evidence_id: str | None = None,
    ) -> dict[str, Any]:
        from app.schemas.ids import ProductId

        try:
            parsed = ProductId(product_id) if product_id is not None else None
            parsed_evidence = SourceId(evidence_id) if evidence_id is not None else None
            capability = SourceIntelligenceCapability(capability)
        except (TypeError, ValueError):
            self._record("consult_source_intelligence", "invalid_request")
            return {
                "status": "invalid_request",
                "gap": "Invalid product or capability.",
            }
        if (parsed is None) == (parsed_evidence is None):
            self._record("consult_source_intelligence", "invalid_request")
            return {
                "status": "invalid_request",
                "gap": "Supply one persisted product ID or one recorded candidate quote.",
            }
        async with self._lock:
            if self._source_count >= 1:
                self._record("consult_source_intelligence", "budget_exhausted")
                return {
                    "status": "budget_exhausted",
                    "gap": "Source-agent limit reached.",
                }
            if self.source_manager is None or self.region_code is None:
                self._record("consult_source_intelligence", "unavailable")
                return {
                    "status": "gap",
                    "gap": "Source intelligence is unavailable for this run/region.",
                }
            async with self._session() as session:
                products_repo = ProductRepository(session)
                products = await products_repo.list_canonical_products_for_run(
                    self.run_id
                )
                listings = await products_repo.list_product_listings_for_run(
                    self.run_id
                )
                source_repo = SearchSourceRepository(session)
                all_snapshots = await source_repo.list_source_snapshots(self.run_id)
                evidence = await source_repo.list_source_evidence(self.run_id)
            product = (
                next((item for item in products if item.product_id == parsed), None)
                if parsed is not None
                else None
            )
            if parsed is not None and (
                product is None or not self._product_in_scope(product)
            ):
                self._record("consult_source_intelligence", "unknown_product")
                return {
                    "status": "unknown_product",
                    "gap": "Product is not in this run.",
                }
            if parsed_evidence is not None:
                quote = next(
                    (item for item in evidence if item.evidence_id == parsed_evidence),
                    None,
                )
                candidate_name = (product_name or "").strip()
                if (
                    quote is None
                    or self.allowed_quote_ids is None
                    or parsed_evidence not in self.allowed_quote_ids()
                    or not 2 <= len(candidate_name) <= 200
                    or candidate_name.casefold() not in quote.claim.casefold()
                ):
                    self._record("consult_source_intelligence", "unverified_candidate")
                    return {
                        "status": "gap",
                        "gap": "Candidate must match a page quote recorded in this owner run.",
                    }
                snapshot = next(
                    (
                        item
                        for item in all_snapshots
                        if item.source_id == quote.source_id
                    ),
                    None,
                )
                if snapshot is None:
                    self._record("consult_source_intelligence", "unknown_source")
                    return {"status": "gap", "gap": "Quoted page is not in this run."}
                if not _safe_public_result_url(
                    str(snapshot.url)
                ) or not _source_policy_allows(
                    str(snapshot.url), snapshot.source_type, self.source_policy
                ):
                    self._record("consult_source_intelligence", "source_rejected")
                    return {
                        "status": "gap",
                        "gap": "Quoted page is outside approved source policy.",
                    }
                product = CanonicalProduct(
                    name=candidate_name,
                    category=self.brief.category,
                    source_ids=(snapshot.source_id,),
                )
            assert product is not None
            self._source_count += 1
            snapshots = tuple(
                item
                for item in all_snapshots
                if item.source_id in product.source_ids
                and _safe_public_result_url(str(item.url))
                and _source_policy_allows(
                    str(item.url), item.source_type, self.source_policy
                )
            )[:4]
            try:
                result = await self.source_manager.run(
                    SourceManagerInput(
                        run_id=self.run_id,
                        brief=self.brief,
                        products=(product,),
                        listings=tuple(
                            item for item in listings if item.product_id == parsed
                        )[:3],
                        source_snapshots=snapshots,
                        query_hints=(product.name,),
                        region_code=self.region_code,
                        allowed_capabilities=(capability,),
                    )
                )
            except Exception as exc:
                self._record(
                    "consult_source_intelligence",
                    "failed",
                    error_type=type(exc).__name__,
                )
                return {
                    "status": "gap",
                    "gap": "Source specialist failed; its claims were not accepted.",
                }
        bundles = {
            SourceIntelligenceCapability.VIDEO_REVIEW: result.video_bundles,
            SourceIntelligenceCapability.COMMUNITY_DISCUSSION: result.community_bundles,
            SourceIntelligenceCapability.AMAZON_PRODUCT_LISTING_REVIEW: result.amazon_bundles,
            SourceIntelligenceCapability.IKEA_REGIONAL_OFFICIAL_STORE: result.ikea_bundles,
        }[capability]
        self.activity.extend(result.activity)
        self._record(
            "consult_source_intelligence",
            "succeeded" if bundles else "gap",
            capability=capability.value,
            product_id=str(product.product_id),
            model=result.model_name,
            total_tokens=result.total_tokens,
        )
        payload = [source_bundle_context(item) for item in bundles]
        if len(json.dumps(payload)) > 12000:
            return {
                "status": "gap",
                "gap": "Source bundle exceeded the owner tool's bounded response size.",
            }
        return {
            "status": "succeeded" if bundles else "gap",
            "capability": capability.value,
            "bundles": payload,
            "notes": list(result.notes),
            "gap": "Source bundles are context; candidate claims still need recorded page quotes.",
        }
