"""Typed, run-scoped helpers shared by live shopping decision owners."""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any, Callable

from agents import FunctionTool, function_tool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.context_management import context_budget_failure, source_bundle_context
from app.agents.source_spans import source_span
from app.agents.research_history import (
    bounded_cautions,
    material_cautions,
    tracked_tools,
)
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
from app.db.session import shared_tool_session
from app.schemas.ids import ListingId, RunId, SourceId, new_id
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
class OwnerResearchState:
    completed_consultations: dict[str, dict[str, Any]] = field(default_factory=dict)
    bundles: dict[str, tuple[RunId, str, dict[str, Any]]] = field(default_factory=dict)
    bundle_versions: dict[tuple[str, str], tuple[RunId, dict[str, Any]]] = field(
        default_factory=dict
    )
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


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
    research_state: OwnerResearchState = field(default_factory=OwnerResearchState)
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
            async with shared_tool_session(self.shared_session) as session:
                yield session
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
        async def read_run_evidence(
            source_id: str,
            start_char: int = 0,
            focus: str | None = None,
            evidence_offset: int = 0,
        ) -> str:
            """Read a persisted source and its bounded evidence from this shopping run.

            Args:
                source_id: Persisted search-result ID from this run.
                start_char: Character offset of the bounded page view.
                focus: Optional exact term to locate anywhere in the page.
                evidence_offset: Offset into this source's persisted evidence records.
            """
            return json.dumps(
                await self.read_source(
                    source_id,
                    start_char=start_char,
                    focus=focus,
                    evidence_offset=evidence_offset,
                ),
                ensure_ascii=False,
            )

        @function_tool
        async def compare_evidence(source_ids: list[str]) -> str:
            """Compare up to four persisted sources without generating new claims.

            Args:
                source_ids: Search-result IDs from this shopping run.
            """
            return json.dumps(await self.compare(source_ids), ensure_ascii=False)

        @function_tool
        async def compare_candidates(product_ids: list[str]) -> str:
            """Compare up to three persisted run products and checked listing risk.

            Args:
                product_ids: Persisted product IDs from this shopping run.
            """
            return json.dumps(
                await self.compare_candidates(product_ids), ensure_ascii=False
            )

        @function_tool
        async def check_listing_trust(listing_id: str) -> str:
            """Check deterministic seller/listing risk for a persisted run listing.

            Args:
                listing_id: Persisted listing ID from this shopping run.
            """
            return json.dumps(await self.check_trust(listing_id), ensure_ascii=False)

        @function_tool(failure_error_function=None)
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
                ),
                ensure_ascii=False,
            )

        @function_tool
        async def read_source_bundle(
            bundle_id: str,
            start_char: int = 0,
            focus: str | None = None,
            content_sha256: str | None = None,
        ) -> str:
            """Read a bounded original source bundle consulted during this shopping run.

            Args:
                bundle_id: Bundle ID or consultation_id returned by consult_source_intelligence.
                start_char: Character offset into the serialized original.
                focus: Optional exact term to locate original support or cautions.
                content_sha256: Exact original version fingerprint when supplied.
            """
            return json.dumps(
                self.read_bundle(
                    bundle_id,
                    start_char=start_char,
                    focus=focus,
                    content_sha256=content_sha256,
                ),
                ensure_ascii=False,
            )

        return tracked_tools(
            (
                read_run_evidence,
                compare_evidence,
                compare_candidates,
                check_listing_trust,
                consult_source_intelligence,
                read_source_bundle,
            ),
            include_controls=False,
        )

    async def read_source(
        self,
        source_id: str,
        *,
        start_char: int = 0,
        focus: str | None = None,
        evidence_offset: int = 0,
    ) -> dict[str, Any]:
        if evidence_offset < 0:
            return {
                "status": "invalid_request",
                "gap": "Evidence offset must be nonnegative.",
            }
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
        text = (
            snapshot.extracted_content.text
            if snapshot and snapshot.extracted_content
            else ""
        )
        try:
            span = source_span(text, start=start_char, focus=focus, limit=2000)
        except ValueError as exc:
            return {"status": "invalid_request", "gap": str(exc)}
        source_evidence = [
            item
            for item in evidence
            if snapshot and item.source_id == snapshot.source_id
        ]
        result = {
            "status": "succeeded",
            "source_id": str(parsed),
            "title": source.title,
            "url": _neutral_url(str(source.url)),
            "source_type": source.source_type.value,
            "source_quality": source.quality.level.value,
            "snapshot_id": str(snapshot.source_id) if snapshot else None,
            "extraction_status": snapshot.extraction_status.value if snapshot else None,
            "text": span.text or None,
            "start_char": span.start,
            "total_characters": span.total_characters,
            "content_sha256": span.content_sha256,
            "text_truncated": len(span.text) < span.total_characters,
            "unreviewed_content": not text or len(span.text) < span.total_characters,
            "gap": None
            if text
            else "Page original is unavailable or has no extracted text. Page claims and safety remain unreviewed.",
            **bounded_cautions(text),
            "evidence": [
                {
                    "evidence_id": str(item.evidence_id),
                    "quote": item.claim,
                    "source_id": str(item.source_id),
                }
                for item in source_evidence[evidence_offset : evidence_offset + 4]
            ],
            "evidence_total": len(source_evidence),
            "next_evidence_offset": evidence_offset + 4
            if evidence_offset + 4 < len(source_evidence)
            else None,
            "deferred_evidence_ids": [
                str(item.evidence_id) for item in source_evidence[evidence_offset + 4 :]
            ],
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
        async with self.research_state.lock:
            return await self._consult_source(
                capability,
                product_id=product_id,
                product_name=product_name,
                evidence_id=evidence_id,
            )

    async def _consult_source(
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
            snapshots = tuple(
                item
                for item in all_snapshots
                if item.source_id in product.source_ids
                and _safe_public_result_url(str(item.url))
                and _source_policy_allows(
                    str(item.url), item.source_type, self.source_policy
                )
            )[:4]
            cache_key = sha256(
                json.dumps(
                    {
                        "run_id": str(self.run_id),
                        "brief": self.brief.model_dump(mode="json"),
                        "region": self.region_code,
                        "capability": capability.value,
                        "product": product.model_dump(mode="json")
                        if parsed is not None
                        else {
                            "name": product.name,
                            "category": product.category,
                            "source_ids": [str(item) for item in product.source_ids],
                        },
                        "listings": [
                            item.model_dump(mode="json")
                            for item in listings
                            if item.product_id == parsed
                        ],
                        "snapshots": [
                            item.model_dump(mode="json") for item in snapshots
                        ],
                        "policy": self.source_policy.model_dump(mode="json"),
                    },
                    sort_keys=True,
                ).encode()
            ).hexdigest()
            cached = self.research_state.completed_consultations.get(cache_key)
            if cached is not None:
                self._record(
                    "consult_source_intelligence",
                    "cached_completion",
                    capability=capability.value,
                )
                return cached
            if self._source_count >= 1:
                return {
                    "status": "budget_exhausted",
                    "gap": "Source-agent limit reached.",
                }
            self._source_count += 1
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
                budget_failure = context_budget_failure(exc)
                if budget_failure is not None:
                    raise budget_failure from exc
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
        payload: list[dict[str, Any]] = []
        deferred_bundle_ids: list[str] = []
        bundle_references: list[dict[str, str]] = []
        for item in bundles:
            original = item.model_dump(mode="json")
            bundle_id = str(original["bundle_id"])
            original_text = json.dumps(
                original, ensure_ascii=False, separators=(",", ":")
            )
            fingerprint = sha256(original_text.encode()).hexdigest()
            self.research_state.bundles[bundle_id] = (
                self.run_id,
                fingerprint,
                original,
            )
            self.research_state.bundle_versions[(bundle_id, fingerprint)] = (
                self.run_id,
                original,
            )
            bundle_references.append(
                {"bundle_id": bundle_id, "content_sha256": fingerprint}
            )
            if len(payload) < 2:
                payload.append(
                    _bounded_owner_bundle(
                        source_bundle_context(item),
                        fingerprint,
                        max_chars=5000,
                        caution_details=_original_cautions(
                            original, scope="original_bundle"
                        ),
                    )
                )
            else:
                deferred_bundle_ids.append(bundle_id)
        consultation_id = str(new_id())
        original_consultation = {
            "consultation_id": consultation_id,
            "capability": capability.value,
            "product_id": str(product.product_id),
            "region_code": self.region_code,
            "bundles": bundle_references,
            "notes": list(result.notes),
        }
        original_text = json.dumps(
            original_consultation, ensure_ascii=False, separators=(",", ":")
        )
        consultation_hash = sha256(original_text.encode()).hexdigest()
        self.research_state.bundles[consultation_id] = (
            self.run_id,
            consultation_hash,
            original_consultation,
        )
        self.research_state.bundle_versions[(consultation_id, consultation_hash)] = (
            self.run_id,
            original_consultation,
        )
        response = {
            "status": "succeeded" if bundles else "gap",
            "capability": capability.value,
            "consultation_id": consultation_id,
            "consultation_sha256": consultation_hash,
            "reload_tool": "read_source_bundle",
            "bundles": payload,
            "notes": list(result.notes),
            "deferred_bundle_ids": deferred_bundle_ids[:8],
            "deferred_bundle_count": len(deferred_bundle_ids),
            "unreviewed_content": bool(deferred_bundle_ids)
            or any(item.get("unreviewed_content") for item in payload),
            "gap": "Source bundles are context; candidate claims still need recorded page quotes. Consultation notes and every bundle/version remain retrievable by consultation_id.",
        }
        response.update(
            _original_cautions(
                {"notes": list(result.notes)}, scope="consultation_notes"
            )
        )
        response["unreviewed_content"] = response["unreviewed_content"] or response.get(
            "unreviewed_cautions", False
        )
        _cap_consultation_response(response)
        if bundles:
            self.research_state.completed_consultations[cache_key] = response
        return response

    def read_bundle(
        self,
        bundle_id: str,
        *,
        start_char: int = 0,
        focus: str | None = None,
        content_sha256: str | None = None,
    ) -> dict[str, Any]:
        try:
            parsed = str(SourceId(bundle_id))
        except (TypeError, ValueError):
            return {"status": "invalid_request", "gap": "Invalid bundle ID."}
        original = self.research_state.bundles.get(parsed)
        if content_sha256 is not None:
            version = self.research_state.bundle_versions.get((parsed, content_sha256))
            original = (version[0], content_sha256, version[1]) if version else None
        if original is None or original[0] != self.run_id:
            return {
                "status": "unknown_source",
                "gap": "Original bundle is not in this run.",
            }
        text = json.dumps(original[2], ensure_ascii=False, separators=(",", ":"))
        try:
            span = source_span(text, start=start_char, focus=focus, limit=4000)
        except ValueError as exc:
            return {"status": "invalid_request", "gap": str(exc)}
        return {
            "status": "succeeded",
            "bundle_id": parsed,
            "text": span.text,
            "start_char": span.start,
            "total_characters": span.total_characters,
            "content_sha256": span.content_sha256,
            "unreviewed_content": len(span.text) < len(text),
            **_original_cautions(
                original[2],
                scope="consultation_notes"
                if "consultation_id" in original[2]
                else "original_bundle",
            ),
        }


_CAUTION_FIELDS = (
    "material_cautions",
    "deferred_caution_count",
    "cautions_truncated",
    "caution_focus_terms",
    "unreviewed_cautions",
    "caution_scope",
)


def _original_cautions(payload: dict[str, Any], *, scope: str) -> dict[str, Any]:
    texts: list[str] = []
    forced: list[str] = []

    def collect(value: Any, warning: bool = False) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                collect(
                    item,
                    warning
                    or any(
                        term in key
                        for term in ("warning", "caution", "gap", "red_flag")
                    ),
                )
        elif isinstance(value, list):
            for item in value:
                collect(item, warning)
        elif isinstance(value, str):
            texts.append(value)
            if warning and not material_cautions(value):
                forced.append(value)

    collect(payload)
    metadata = bounded_cautions("\n".join(texts), extra_passages=forced)
    if metadata["material_cautions"]:
        metadata["caution_scope"] = scope
    return metadata


def _bounded_owner_bundle(
    payload: dict[str, Any],
    fingerprint: str,
    *,
    max_chars: int = 5000,
    caution_details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if caution_details is None:
        if "caution_scope" in payload:
            caution_details = {
                key: payload[key] for key in _CAUTION_FIELDS if key in payload
            }
        else:
            caution_details = _original_cautions(payload, scope="original_bundle")
    complete = {**payload, "content_sha256": fingerprint, **caution_details}
    if len(json.dumps(complete, ensure_ascii=False)) <= max_chars:
        return complete
    for string_limit, row_limit in ((600, 3), (300, 2), (150, 1), (80, 1)):
        deferred: list[str] = []

        def project(value: Any, path: str) -> Any:
            if isinstance(value, str) and len(value) > string_limit:
                deferred.append(path)
                return value[:string_limit]
            if isinstance(value, dict):
                return {
                    key: project(item, f"{path}.{key}")
                    for key, item in value.items()
                    if item is not None
                }
            if isinstance(value, list):
                if len(value) > row_limit:
                    deferred.append(path)
                return [
                    project(item, f"{path}[{index}]")
                    for index, item in enumerate(value[:row_limit])
                ]
            return value

        result = project(payload, "bundle")
        result.update(
            {
                "content_sha256": fingerprint,
                "unreviewed_content": True,
                "deferred_fields": sorted(set(deferred)),
                "reload_tool": "read_source_bundle",
                **caution_details,
                "gap": "Omitted original details remain unreviewed. Read the bundle before making claims about them.",
            }
        )
        if len(json.dumps(result, ensure_ascii=False)) <= max_chars:
            return result
    return {
        "bundle_id": payload["bundle_id"],
        "content_sha256": fingerprint,
        "evidence": project(payload.get("evidence", [])[:1], "bundle.evidence"),
        **caution_details,
        "unreviewed_content": True,
        "reload_tool": "read_source_bundle",
        "gap": "The full bundle and remaining claims/cautions require bounded rereads before use.",
    }


def _cap_consultation_response(
    response: dict[str, Any], *, max_chars: int = 11000
) -> None:
    def size() -> int:
        return len(json.dumps(response, ensure_ascii=False))

    if size() <= max_chars:
        return
    notes = response["notes"]
    response["notes"] = [note[:400] for note in notes[:4]]
    response.update(
        {
            "deferred_note_count": max(0, len(notes) - 4),
            "notes_truncated": any(len(note) > 400 for note in notes[:4]),
            "unreviewed_content": True,
        }
    )
    while size() > max_chars and len(response["bundles"]) > 1:
        omitted = response["bundles"].pop()
        response["deferred_bundle_ids"] = [
            omitted["bundle_id"],
            *response["deferred_bundle_ids"],
        ][:8]
        response["deferred_bundle_count"] += 1
    if size() > max_chars and response["bundles"]:
        first = response["bundles"][0]
        response["bundles"] = [
            _bounded_owner_bundle(first, first["content_sha256"], max_chars=3000)
        ]
    if size() > max_chars:
        response["notes"] = [note[:200] for note in notes[:2]]
        response["deferred_note_count"] = max(0, len(notes) - 2)
        response["notes_truncated"] = any(len(note) > 200 for note in notes[:2])
    if size() > max_chars:
        response["bundles"] = [
            {
                "bundle_id": item["bundle_id"],
                "content_sha256": item["content_sha256"],
                **{key: item[key] for key in _CAUTION_FIELDS if key in item},
                "unreviewed_content": True,
                "gap": "Read the canonical bundle for claims and full cautions.",
            }
            for item in response["bundles"]
        ]
