"""Bounded official-region retrieval for the IKEA source specialist."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from agents import FunctionTool, function_tool
from pydantic import AnyHttpUrl

from app.agents.contracts import IKEAStoreIntelligenceAgentInput
from app.agents.ikea_store_intelligence_service import _target_region_code
from app.agents.research_history import tracked_tools
from app.agents.source_spans import source_span
from app.core.ikea_regions import IKEA_REGION_PATHS
from app.providers import (
    IKEAStoreIntelligenceProvider,
    IKEAStoreIntelligenceProviderOptions,
    ProviderRunStatus,
)
from app.providers.ikea import IKEARegionalStoreDiscoveryProvider
from app.schemas.search_sources import (
    ExtractionStatus,
    SourceQuality,
    SourceQualityLevel,
)
from app.schemas.source_references import SourceReference


def _official_url(url: str, region: str | None) -> str | None:
    configured = IKEA_REGION_PATHS.get(region or "")
    if configured is None:
        return None
    domain, prefix = configured
    parsed = urlsplit(url)
    host = (parsed.hostname or "").casefold()
    path = parsed.path.casefold()
    expected_prefix = prefix.casefold().rstrip("/")
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or host not in {domain, f"www.{domain}"}
        or not path.startswith(expected_prefix + "/")
        or "/p/" not in path
    ):
        return None
    return urlunsplit(("https", domain, parsed.path, "", ""))


@dataclass(frozen=True)
class _OfficialRecord:
    product_id: str
    reference: SourceReference
    text: str
    quality: SourceQuality


@dataclass
class IKEARegionalStoreTools:
    input_data: IKEAStoreIntelligenceAgentInput
    ikea_provider: IKEAStoreIntelligenceProvider
    max_searches: int = 3
    max_reads: int = 5
    _records: dict[str, _OfficialRecord] = field(default_factory=dict, init=False)
    _searched: set[str] = field(default_factory=set, init=False)
    _read: set[str] = field(default_factory=set, init=False)
    _search_cache: dict[str, dict[str, Any]] = field(default_factory=dict, init=False)
    _last_status: str | None = field(default=None, init=False)
    _activity: list[dict[str, Any]] = field(default_factory=list, init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

    @property
    def region(self) -> str | None:
        value = _target_region_code(self.input_data)
        return str(value) if value else None

    @property
    def workbench_activity(self) -> tuple[dict[str, Any], ...]:
        return tuple(self._activity)

    def product_summaries(self) -> list[dict[str, str]]:
        return [
            {
                "product_id": str(item.product_id),
                "name": item.name,
                "brand": item.brand or "",
                "model": item.model or "",
            }
            for item in self.input_data.products
        ]

    def snapshot_summaries(self) -> list[dict[str, str]]:
        return [
            {
                "source_id": str(item.source_id),
                "url": neutral,
                "title": item.title or "",
            }
            for item in self.input_data.source_snapshots[:20]
            if item.extraction_status
            not in {ExtractionStatus.FAILED, ExtractionStatus.EXCLUDED}
            if (neutral := _official_url(str(item.url), self.region)) is not None
        ]

    def sdk_tools(self) -> tuple[FunctionTool, ...]:
        @function_tool
        async def search_ikea_products(product_id: str) -> str:
            """Search approved official IKEA product results for a supplied product ID and region."""
            return json.dumps(await self.search(product_id))

        @function_tool
        async def read_ikea_product(
            source_id: str, start_char: int = 0, focus: str | None = None
        ) -> str:
            """Read one previously returned official regional product result or snapshot."""
            return json.dumps(
                await self.read(source_id, start_char=start_char, focus=focus)
            )

        return tracked_tools(
            (search_ikea_products, read_ikea_product), include_controls=True
        )

    async def search(self, product_id: str) -> dict[str, Any]:
        product = next(
            (p for p in self.input_data.products if str(p.product_id) == product_id),
            None,
        )
        if product is None:
            return {
                "status": "unknown_product",
                "sources": [],
                "gap": "Product ID was not supplied.",
            }
        if self.region not in IKEA_REGION_PATHS:
            return {
                "status": "unsupported_region",
                "sources": [],
                "gap": "No approved official IKEA path exists for the requested region.",
            }
        async with self._lock:
            if product_id in self._searched:
                return self._search_cache.get(
                    product_id,
                    {
                        "status": "in_progress",
                        "sources": [],
                        "gap": "IKEA search is already running.",
                    },
                )
            if len(self._searched) >= self.max_searches:
                return {
                    "status": "budget_exhausted",
                    "sources": [],
                    "gap": "IKEA search limit reached.",
                }
            self._searched.add(product_id)
        status = "succeeded"
        try:
            if isinstance(self.ikea_provider, IKEARegionalStoreDiscoveryProvider):
                hits = await self.ikea_provider.search_product_candidates(
                    product, region_code=self.region
                )
                for hit in hits:
                    neutral = _official_url(str(hit.url), self.region)
                    if neutral is None:
                        continue
                    self._records[str(hit.source_id)] = _OfficialRecord(
                        product_id=product_id,
                        reference=SourceReference(
                            source_id=hit.source_id,
                            url=AnyHttpUrl(neutral),
                            title=hit.title,
                        ),
                        text=". ".join(filter(None, (hit.title, hit.snippet))),
                        quality=hit.quality,
                    )
            else:
                result = await self.ikea_provider.fetch_store_evidence(
                    product,
                    IKEAStoreIntelligenceProviderOptions(region_code=self.region),
                )
                status = result.status.value
                if result.status == ProviderRunStatus.SUCCEEDED and result.bundle:
                    contexts = {c.source_id: c for c in result.bundle.store_contexts}
                    for ref in result.bundle.source_references:
                        context = contexts.get(ref.source_id)
                        neutral = _official_url(str(ref.url), self.region)
                        if (
                            context is None
                            or neutral is None
                            or _official_url(str(context.official_url), self.region)
                            != neutral
                        ):
                            continue
                        fragments = [
                            ref.title or "",
                            context.product_name or "",
                            context.product_code or "",
                            context.store_name or "",
                            context.delivery_area or "",
                        ]
                        if context.price:
                            fragments.append(
                                f"{context.price.currency} {context.price.amount}"
                            )
                        if context.availability.value != "unknown":
                            fragments.append(
                                context.availability.value.replace("_", " ")
                            )
                        fragments.extend(
                            e.claim
                            for e in result.bundle.evidence
                            if e.source_id == ref.source_id
                        )
                        self._records[str(ref.source_id)] = _OfficialRecord(
                            product_id=product_id,
                            reference=SourceReference(
                                source_id=ref.source_id,
                                url=AnyHttpUrl(neutral),
                                title=ref.title,
                            ),
                            text=". ".join(filter(None, fragments)),
                            quality=next(
                                (
                                    e.source_quality
                                    for e in result.bundle.evidence
                                    if e.source_id == ref.source_id
                                ),
                                SourceQuality(level=SourceQualityLevel.UNKNOWN),
                            ),
                        )
        except Exception:
            status = "provider_error"
        for snapshot in self.input_data.source_snapshots[:20]:
            neutral = _official_url(str(snapshot.url), self.region)
            if neutral and snapshot.extraction_status not in {
                ExtractionStatus.FAILED,
                ExtractionStatus.EXCLUDED,
            }:
                self._records.setdefault(
                    str(snapshot.source_id),
                    _OfficialRecord(
                        product_id=product_id,
                        reference=SourceReference(
                            source_id=snapshot.source_id,
                            url=AnyHttpUrl(neutral),
                            title=snapshot.title,
                        ),
                        text=(
                            snapshot.extracted_content.text
                            if snapshot.extracted_content
                            else snapshot.title or ""
                        ),
                        quality=snapshot.quality,
                    ),
                )
        sources = [
            {
                "source_id": source_id,
                "url": str(record.reference.url),
                "title": record.reference.title,
            }
            for source_id, record in self._records.items()
            if record.product_id == product_id
        ][:8]
        response = {
            "status": status,
            "sources": sources,
            "gap": None
            if sources
            else "No approved official regional IKEA product result was available.",
        }
        self._last_status = status
        self._search_cache[product_id] = response
        self._activity.append(
            {
                "tool_name": "search_ikea_products",
                "status": status,
                "input": {"product_id": product_id, "region": self.region},
                "output": {"source_count": len(sources)},
            }
        )
        return response

    async def read(
        self, source_id: str, *, start_char: int = 0, focus: str | None = None
    ) -> dict[str, Any]:
        record = self._records.get(source_id)
        if record is None:
            return {
                "status": "unknown_source",
                "gap": "Source ID was not returned by approved regional search.",
            }
        try:
            span = source_span(record.text, start=start_char, focus=focus, limit=2000)
        except ValueError as exc:
            return {"status": "invalid_request", "gap": str(exc)}
        async with self._lock:
            if source_id not in self._read and len(self._read) >= self.max_reads:
                return {"status": "budget_exhausted", "gap": "IKEA read limit reached."}
            self._read.add(source_id)
        response = {
            "status": "ok",
            "product_id": record.product_id,
            "region": self.region,
            "source_reference": record.reference.model_dump(
                mode="json", exclude_none=True
            ),
            "text": span.text,
            "start_char": span.start,
            "total_characters": span.total_characters,
            "content_sha256": span.content_sha256,
            "text_truncated": span.start > 0
            or span.start + len(span.text) < span.total_characters,
            "unreviewed_content": span.start > 0
            or span.start + len(span.text) < span.total_characters,
        }
        self._activity.append(
            {
                "tool_name": "read_ikea_product",
                "status": "ok",
                "input": {"source_id": source_id},
                "output": {"text_length": len(record.text)},
            }
        )
        return response
