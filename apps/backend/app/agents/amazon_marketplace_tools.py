"""Bounded, neutral marketplace evidence tools for the Amazon specialist."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from agents import FunctionTool, function_tool

from app.agents.contracts import AmazonProductIntelligenceAgentInput
from app.agents.amazon_product_intelligence_service import (
    _merge_amazon_bundles,
    _target_region_code,
)
from app.providers import (
    AmazonProductIntelligenceProvider,
    AmazonProductIntelligenceProviderOptions,
    ProviderRunStatus,
)
from app.providers.amazon import (
    AmazonSearchCandidate,
    SerpApiAmazonProductIntelligenceProvider,
    _amazon_domain,
    _asin_from_url,
)
from app.schemas.ids import new_id
from app.schemas.search_sources import (
    AmazonEvidenceFactType,
    AmazonProductEvidenceBundle,
    ExtractionStatus,
)
from app.services.amazon_evidence_creation import _is_amazon_party


def _neutral_amazon_url(url: str, domain: str, asin: str | None) -> bool:
    parsed = urlsplit(url)
    return (
        parsed.scheme == "https"
        and parsed.username is None
        and parsed.password is None
        and not parsed.query
        and not parsed.fragment
        and _amazon_domain(parsed.hostname) == domain
        and (asin is None or _asin_from_url(url) == asin)
    )


@dataclass
class AmazonMarketplaceTools:
    input_data: AmazonProductIntelligenceAgentInput
    amazon_provider: AmazonProductIntelligenceProvider
    max_searches: int = 3
    max_reads: int = 5
    _bundles: dict[str, AmazonProductEvidenceBundle] = field(
        default_factory=dict, init=False
    )
    _searched: set[str] = field(default_factory=set, init=False)
    _read: set[str] = field(default_factory=set, init=False)
    _candidates: dict[str, tuple[str, AmazonSearchCandidate]] = field(
        default_factory=dict, init=False
    )
    _candidate_sources: dict[str, str] = field(default_factory=dict, init=False)
    _search_cache: dict[str, dict[str, Any]] = field(default_factory=dict, init=False)
    _last_status: str | None = field(default=None, init=False)
    _activity: list[dict[str, Any]] = field(default_factory=list, init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

    @property
    def workbench_activity(self) -> tuple[dict[str, Any], ...]:
        return tuple(self._activity)

    def product_summaries(self) -> list[dict[str, Any]]:
        return [
            {
                "product_id": str(product.product_id),
                "name": product.name,
                "brand": product.brand,
                "model": product.model,
                "amazon_listing_urls": [
                    str(item.url)
                    for item in self.input_data.listings
                    if item.product_id == product.product_id
                    and _amazon_domain(urlsplit(str(item.url)).hostname)
                    and _asin_from_url(str(item.url))
                ][:5],
            }
            for product in self.input_data.products
        ]

    def snapshot_summaries(self) -> list[dict[str, Any]]:
        return [
            {
                "source_id": str(item.source_id),
                "url": str(item.url),
                "title": item.title,
            }
            for item in self.input_data.source_snapshots
            if item.extraction_status
            not in {ExtractionStatus.FAILED, ExtractionStatus.EXCLUDED}
            and _amazon_domain(urlsplit(str(item.url)).hostname)
            and _asin_from_url(str(item.url))
        ][:10]

    def sdk_tools(self) -> tuple[FunctionTool, ...]:
        @function_tool
        async def search_amazon_products(product_id: str) -> str:
            """Retrieve approved Amazon/SerpAPI evidence for a supplied product ID."""
            return json.dumps(await self.search(product_id))

        @function_tool
        async def read_amazon_product(source_id: str) -> str:
            """Read a neutral marketplace source returned by approved search."""
            return json.dumps(await self.read(source_id))

        return search_amazon_products, read_amazon_product

    async def search(self, product_id: str) -> dict[str, Any]:
        product = next(
            (
                item
                for item in self.input_data.products
                if str(item.product_id) == product_id
            ),
            None,
        )
        if product is None:
            return {"status": "unknown_product", "gap": "Product ID was not supplied."}
        async with self._lock:
            if product_id in self._searched:
                return self._search_cache[product_id]
            if len(self._searched) >= self.max_searches:
                return {
                    "status": "budget_exhausted",
                    "gap": "Amazon search limit reached.",
                }
            self._searched.add(product_id)
        listings = tuple(
            item
            for item in self.input_data.listings
            if item.product_id == product.product_id
            and _amazon_domain(urlsplit(str(item.url)).hostname)
            and _asin_from_url(str(item.url))
        )[:5]
        try:
            if isinstance(
                self.amazon_provider, SerpApiAmazonProductIntelligenceProvider
            ):
                candidates = await self.amazon_provider.search_product_candidates(
                    product, region_code=_target_region_code(self.input_data)
                )
                sources = []
                for candidate in candidates:
                    candidate_id = str(new_id())
                    self._candidates[candidate_id] = (product_id, candidate)
                    sources.append(
                        {
                            "source_id": candidate_id,
                            "candidate_only": True,
                            "asin": candidate.asin,
                            "title": candidate.title,
                            "domain": candidate.marketplace_domain,
                        }
                    )
                response = {"status": "succeeded", "sources": sources, "gaps": []}
            else:
                result = await self.amazon_provider.fetch_product_evidence(
                    product,
                    listings=listings,
                    options=AmazonProductIntelligenceProviderOptions(
                        region_code=_target_region_code(self.input_data)
                    ),
                )
                if result.status == ProviderRunStatus.SUCCEEDED and result.bundle:
                    self._bundles[product_id] = self._sanitize(result.bundle)
                response = self._search_result(product_id, status=result.status.value)
        except Exception:
            response = {"status": "provider_error", "sources": [], "gaps": []}
        self._last_status = response["status"]
        self._search_cache[product_id] = response
        self._activity.append(
            {
                "tool_name": "search_amazon_products",
                "status": response["status"],
                "input": {
                    "product_id": product_id,
                    "listing_ids": [str(item.listing_id) for item in listings],
                },
                "output": {"source_count": len(response["sources"])},
            }
        )
        return response

    def _search_result(
        self, product_id: str, status: str = "succeeded"
    ) -> dict[str, Any]:
        bundle = self._bundles.get(product_id)
        return {
            "status": status,
            "sources": [
                {
                    "source_id": str(item.source_id),
                    "asin": item.asin,
                    "title": item.product_title,
                    "domain": item.marketplace_domain,
                    "variant": item.variant_label,
                }
                for item in bundle.listing_contexts
            ]
            if bundle
            else [],
            "gaps": [item.model_dump(mode="json") for item in bundle.evidence_gaps]
            if bundle
            else [],
        }

    def _sanitize(
        self, bundle: AmazonProductEvidenceBundle
    ) -> AmazonProductEvidenceBundle:
        refs = {item.source_id: item for item in bundle.source_references}
        contexts = tuple(
            item
            for item in bundle.listing_contexts
            if item.source_id in refs
            and _amazon_domain(item.marketplace_domain) == item.marketplace_domain
            and _neutral_amazon_url(
                str(item.listing_url), item.marketplace_domain, item.asin
            )
            and str(refs[item.source_id].url) == str(item.listing_url)
            and (
                not item.seller_name
                or _is_amazon_party(item.seller_name)
                or any(
                    evidence.source_id == item.source_id
                    and evidence.fact_type == AmazonEvidenceFactType.MARKETPLACE_WARNING
                    for evidence in bundle.evidence
                )
            )
        )
        ids = {item.source_id for item in contexts}
        return AmazonProductEvidenceBundle(
            source_references=tuple(
                item for item in bundle.source_references if item.source_id in ids
            ),
            listing_contexts=contexts,
            evidence=tuple(item for item in bundle.evidence if item.source_id in ids),
            evidence_gaps=tuple(
                item
                for item in bundle.evidence_gaps
                if item.source_id is None or item.source_id in ids
            ),
        )

    async def read(self, source_id: str) -> dict[str, Any]:
        if source_id in self._candidates:
            actual_source_id = self._candidate_sources.get(source_id)
            if actual_source_id is None:
                async with self._lock:
                    actual_source_id = self._candidate_sources.get(source_id)
                    if actual_source_id is None:
                        if len(self._read) >= self.max_reads:
                            return {
                                "status": "budget_exhausted",
                                "gap": "Amazon read limit reached.",
                            }
                        product_id, candidate = self._candidates[source_id]
                        product = next(
                            item
                            for item in self.input_data.products
                            if str(item.product_id) == product_id
                        )
                        listing = next(
                            (
                                item
                                for item in self.input_data.listings
                                if item.product_id == product.product_id
                                and _amazon_domain(urlsplit(str(item.url)).hostname)
                                == candidate.marketplace_domain
                                and _asin_from_url(str(item.url)) == candidate.asin
                            ),
                            None,
                        )
                        try:
                            provider = self.amazon_provider
                            assert isinstance(
                                provider, SerpApiAmazonProductIntelligenceProvider
                            )
                            result = await provider.fetch_selected_product_evidence(
                                product,
                                asin=candidate.asin,
                                marketplace_domain=candidate.marketplace_domain,
                                region_code=_target_region_code(self.input_data),
                                listing=listing,
                            )
                            if (
                                result.status != ProviderRunStatus.SUCCEEDED
                                or result.bundle is None
                            ):
                                return {
                                    "status": result.status.value,
                                    "gap": "Selected Amazon product was unavailable.",
                                }
                            selected_bundle = self._sanitize(result.bundle)
                            if not selected_bundle.source_references:
                                return {
                                    "status": "invalid_source",
                                    "gap": "Selected Amazon source failed neutral-link or hard-risk checks.",
                                }
                            existing = self._bundles.get(product_id)
                            self._bundles[product_id] = _merge_amazon_bundles(
                                (existing, selected_bundle)
                                if existing
                                else (selected_bundle,),
                                (),
                            )
                            actual_source_id = str(
                                selected_bundle.source_references[0].source_id
                            )
                            self._candidate_sources[source_id] = actual_source_id
                        except Exception:
                            return {
                                "status": "provider_error",
                                "gap": "Selected Amazon product read failed.",
                            }
            source_id = actual_source_id
        found = next(
            (
                (product_id, bundle, context)
                for product_id, bundle in self._bundles.items()
                for context in bundle.listing_contexts
                if str(context.source_id) == source_id
            ),
            None,
        )
        if found is None:
            snapshot = next(
                (
                    item
                    for item in self.input_data.source_snapshots
                    if str(item.source_id) == source_id
                    and item.extraction_status
                    not in {ExtractionStatus.FAILED, ExtractionStatus.EXCLUDED}
                    and _amazon_domain(urlsplit(str(item.url)).hostname)
                    and _asin_from_url(str(item.url))
                ),
                None,
            )
            if snapshot is None:
                return {
                    "status": "unknown_source",
                    "gap": "Source ID was not returned by approved marketplace search or supplied as a permitted snapshot.",
                }
            if source_id not in self._read and len(self._read) >= self.max_reads:
                return {
                    "status": "budget_exhausted",
                    "gap": "Amazon read limit reached.",
                }
            self._read.add(source_id)
            response = {
                "status": "persisted_source",
                "source_id": source_id,
                "url": str(snapshot.url),
                "title": snapshot.title,
                "extracted_excerpt": (
                    snapshot.extracted_content.text[:2000]
                    if snapshot.extracted_content
                    else None
                ),
                "note": "Candidate context only; product/listing facts require approved provider evidence.",
            }
            self._activity.append(
                {
                    "tool_name": "read_amazon_product",
                    "status": "persisted_source",
                    "input": {"source_id": source_id},
                    "output": {"candidate_context": True},
                }
            )
            return response
        if source_id not in self._read and len(self._read) >= self.max_reads:
            return {"status": "budget_exhausted", "gap": "Amazon read limit reached."}
        product_id, bundle, context = found
        self._read.add(source_id)
        response = {
            "status": "ok",
            "product_id": product_id,
            "source_reference": next(
                item.model_dump(mode="json")
                for item in bundle.source_references
                if item.source_id == context.source_id
            ),
            "listing_context": context.model_dump(mode="json"),
            "provider_evidence": [
                item.model_dump(mode="json")
                for item in bundle.evidence
                if item.source_id == context.source_id
            ],
            "provider_gaps": [
                item.model_dump(mode="json")
                for item in bundle.evidence_gaps
                if item.source_id in {None, context.source_id}
            ],
        }
        self._activity.append(
            {
                "tool_name": "read_amazon_product",
                "status": "ok",
                "input": {"source_id": source_id},
                "output": {"evidence_count": len(response["provider_evidence"])},
            }
        )
        return response
