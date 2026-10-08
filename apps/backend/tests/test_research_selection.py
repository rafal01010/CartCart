import json
import tempfile
from pathlib import Path

import pytest

from app.agents.research_selection import ResearchSelection, equivalent_url
from app.agents.research_tools import (
    AgentResearchTools,
    FetchSourceRequest,
    ResearchToolLimits,
    SearchSourcesRequest,
    ToolSource,
)
from app.db.repositories.search_sources import SearchSourceRepository
from app.schemas.intake import FieldSource, RegionPreference, ShoppingBrief
from app.schemas.ids import new_id
from app.schemas.regions import Region
from app.schemas.search_sources import (
    ExtractedPageContent,
    ExtractionStatus,
    ProviderMetadata,
    SearchIntent,
    SearchQuery,
    SearchResult,
    SourceSnapshot,
    SourceType,
)
from test_agent_research_tools import RecordingSearchProvider, _database


def _lead(
    url: str,
    title: str,
    snippet: str,
    role: SourceType = SourceType.SEARCH_RESULT,
    date: str | None = None,
) -> SearchResult:
    return SearchResult(
        url=url,
        title=title,
        snippet=snippet,
        source_type=role,
        query=SearchQuery(query="Aster lamp", intent=SearchIntent.DISCOVERY),
        provider=ProviderMetadata(
            provider_name="fixture-search", raw={"published_date": date} if date else {}
        ),
    )


def _brief() -> ShoppingBrief:
    return ShoppingBrief(
        original_query="Aster lamp for reading in PH",
        region=RegionPreference(
            region=Region(country_code="PH"), source=FieldSource.USER_PROVIDED
        ),
    )


def test_noisy_batch_selects_lower_rank_independent_and_contrary_sources() -> None:
    plan = ResearchSelection(_brief())
    need = plan.need("Aster lamp", SearchIntent.DISCOVERY)
    leads = [
        _lead("https://noise.example/car", "Car insurance", "Compare annual policies"),
        _lead(
            "https://store.example/aster?utm_source=one",
            "Aster lamp PH",
            "Aster lamp warm reading light",
            SourceType.PRODUCT_PAGE,
        ),
        _lead(
            "https://store.example/aster?utm_source=two",
            "Aster lamp PH",
            "Aster lamp warm reading light",
            SourceType.PRODUCT_PAGE,
        ),
        _lead(
            "https://store.example/aster-duplicate",
            "Aster lamp PH",
            "Aster lamp warm reading light",
            SourceType.PRODUCT_PAGE,
        ),
        _lead(
            "https://seller.example/import",
            "Aster lamp import",
            "Aster lamp has no local warranty. Seller identity is unverified.",
            SourceType.RETAILER_LISTING,
        ),
        _lead(
            "https://independent.example/aster",
            "Aster lamp independent review",
            "Aster lamp reading comfort was measured independently.",
            SourceType.PROFESSIONAL_REVIEW,
        ),
    ]
    chosen = plan.select(leads, need, limit=4)
    assert sorted(lead.title for lead in chosen) == [
        "Aster lamp PH",
        "Aster lamp import",
        "Aster lamp independent review",
    ]
    assert plan.decisions[leads[0].source_id].reason == "no_buyer_or_need_match"
    assert (
        plan.decisions[leads[4].source_id].reason == "material_caution_or_contrary_lead"
    )
    assert plan.covered is False


def test_cross_batch_novelty_keeps_variant_and_new_warning() -> None:
    plan = ResearchSelection(_brief())
    first = _lead(
        "https://store.example/aster?variant=ph&utm_source=x",
        "Aster PH lamp",
        "Aster lamp warm reading light",
        SourceType.PRODUCT_PAGE,
    )
    need = plan.need("Aster lamp", SearchIntent.OFFICIAL_SOURCE)
    assert plan.select([first], need, limit=4) == (first,)
    same = _lead(
        "https://store.example/aster?utm_source=y&variant=ph",
        "Aster PH lamp",
        "Aster lamp warm reading light",
        SourceType.PRODUCT_PAGE,
    )
    conflict = _lead(
        "https://store.example/aster?variant=us",
        "Aster US lamp",
        "Aster US variant is imported and has no local warranty.",
        SourceType.PRODUCT_PAGE,
    )
    caution = _lead(
        "https://store.example/aster?variant=ph&utm_source=z",
        "Aster PH lamp",
        "Aster lamp now has an unverified seller warning.",
        SourceType.PRODUCT_PAGE,
    )
    chosen = plan.select([same, conflict, caution], need, limit=4)
    assert {str(lead.url) for lead in chosen} == {str(conflict.url), str(caution.url)}
    assert plan.decisions[same.source_id].reason == "equivalent_url_already_admitted"
    assert equivalent_url(str(first.url)) == "https://store.example/aster?variant=ph"
    assert equivalent_url(str(conflict.url)) == "https://store.example/aster?variant=us"


def test_region_and_known_freshness_break_ties_and_missing_support_widens() -> None:
    plan = ResearchSelection(_brief())
    need = plan.need("Aster lamp", SearchIntent.REVIEW)
    old = _lead(
        "https://old.example/aster",
        "Aster lamp review",
        "Aster lamp reading measurements.",
        SourceType.PROFESSIONAL_REVIEW,
        "2020-01-01",
    )
    recent = _lead(
        "https://recent.example/aster",
        "Aster lamp review",
        "Aster lamp reading comfort testing.",
        SourceType.PROFESSIONAL_REVIEW,
        "2026-01-01",
    )
    local = _lead(
        "https://local.example/ph/aster",
        "Aster lamp review",
        "Aster lamp reading fit analysis.",
        SourceType.PROFESSIONAL_REVIEW,
        "2021-01-01",
    )
    assert plan.select([old, recent, local], need, limit=1) == (local,)
    assert plan.widen(need.need_id, limit=1) == (recent,)
    assert plan.widen(need.need_id, limit=1) == (old,)
    assert plan.widen(need.need_id, limit=1) == ()


def test_same_site_marketing_review_does_not_close_independent_coverage() -> None:
    plan = ResearchSelection(_brief())
    need = plan.need("Aster lamp", SearchIntent.DISCOVERY)
    official = _lead(
        "https://brand.example/aster",
        "Aster lamp official",
        "Aster lamp reading light",
        SourceType.OFFICIAL_BRAND_PAGE,
    )
    marketing = _lead(
        "https://brand.example/aster-review",
        "Aster lamp review",
        "Aster lamp review measurements",
        SourceType.PROFESSIONAL_REVIEW,
    )
    independent = _lead(
        "https://independent.example/aster",
        "Aster lamp test",
        "Aster lamp independent analysis",
        SourceType.PROFESSIONAL_REVIEW,
    )
    plan.select([official, marketing, independent], need, limit=4)
    plan.record_support(official, "Aster lamp provides warm light.", new_id())
    plan.record_support(
        marketing, "Aster lamp is promoted in the brand review.", new_id()
    )
    assert plan.covered is False
    plan.record_support(
        independent, "Aster lamp has measured comfortable light.", new_id()
    )
    assert plan.covered is True


@pytest.mark.parametrize(
    "claim",
    ["Aster lamp includes local warranty.", "Aster lamp has no local warranty."],
)
def test_product_attribute_quotes_cannot_close_a_warranty_need(claim: str) -> None:
    plan = ResearchSelection(_brief())
    need = plan.need("Aster lamp local warranty", SearchIntent.DISCOVERY)
    official = _lead(
        "https://brand.example/aster",
        "Aster lamp local warranty",
        "Aster lamp details",
        SourceType.OFFICIAL_BRAND_PAGE,
    )
    review = _lead(
        "https://independent.example/aster",
        "Aster lamp local warranty",
        "Aster lamp details",
        SourceType.PROFESSIONAL_REVIEW,
    )
    plan.select([official, review], need, limit=4)
    for source in (official, review):
        plan.record_support(source, "Aster lamp is white.", new_id())
    assert plan.covered is False and need.evidence_ids == set()
    assert plan.admit_fetch(review, need.need_id) is need
    plan.record_support(official, claim, new_id())
    assert len(need.evidence_ids) == 1 and plan.covered is False
    plan.record_support(review, claim, new_id())
    assert len(need.evidence_ids) == 2 and plan.covered is True


@pytest.mark.parametrize(
    "query, unrelated, support",
    [
        (
            "Aster lamp price",
            "Aster lamp price information.",
            "Aster lamp costs PHP 1000.",
        ),
        (
            "Aster lamp local stock",
            "Aster lamp has local stock information.",
            "Aster lamp is in local stock.",
        ),
        (
            "Aster lamp 512GB variant",
            "Aster lamp has a 256GB variant.",
            "Aster lamp has a 512GB storage variant.",
        ),
    ],
)
def test_critical_needs_require_substantive_exact_support(
    query: str, unrelated: str, support: str
) -> None:
    plan = ResearchSelection(_brief())
    need = plan.need(query, SearchIntent.DISCOVERY)
    official = _lead(
        "https://brand.example/aster",
        query,
        "Aster lamp details",
        SourceType.OFFICIAL_BRAND_PAGE,
    )
    review = _lead(
        "https://independent.example/aster",
        query,
        "Aster lamp details",
        SourceType.PROFESSIONAL_REVIEW,
    )
    plan.select([official, review], need, limit=4)
    for source in (official, review):
        plan.record_support(source, unrelated, new_id())
    assert plan.covered is False and need.evidence_ids == set()
    for source in (official, review):
        plan.record_support(source, support, new_id())
    assert len(need.evidence_ids) == 2 and plan.covered is True


@pytest.mark.parametrize(
    "question", ["Aster lamp price", "Aster lamp budget", "Aster lamp local warranty"]
)
def test_a_new_critical_question_cannot_reuse_supported_product_need(
    question: str,
) -> None:
    plan = ResearchSelection(_brief())
    product_need = plan.need("Aster lamp", SearchIntent.DISCOVERY)
    official = _lead(
        "https://brand.example/aster",
        "Aster lamp",
        "Aster lamp details",
        SourceType.OFFICIAL_BRAND_PAGE,
    )
    review = _lead(
        "https://independent.example/aster",
        "Aster lamp",
        "Aster lamp details",
        SourceType.PROFESSIONAL_REVIEW,
    )
    plan.select([official, review], product_need, limit=4)
    for source in (official, review):
        plan.record_support(source, "Aster lamp is white.", new_id())
    assert plan.covered is True
    critical_need = plan.need(question, SearchIntent.DISCOVERY)
    assert critical_need is not product_need and critical_need.query == question
    assert plan.covered is False
    assert (
        plan.need("  " + question.upper() + "  ", SearchIntent.DISCOVERY)
        is critical_need
    )
    plan.select([official, review], critical_need, limit=4)
    for source in (official, review):
        plan.record_support(source, "Aster lamp is white.", new_id())
    assert critical_need.evidence_ids == set() and plan.covered is False
    support = (
        "Aster lamp includes local warranty."
        if "warranty" in question
        else "Aster lamp costs PHP 1000."
    )
    plan.record_support(official, support, new_id())
    assert len(critical_need.evidence_ids) == 1 and plan.covered is True


def test_need_identity_preserves_qualifiers_and_intent() -> None:
    plan = ResearchSelection(_brief())
    local = plan.need("Aster lamp local warranty", SearchIntent.DISCOVERY)
    foreign = plan.need("Aster lamp overseas warranty", SearchIntent.DISCOVERY)
    review = plan.need("Aster lamp local warranty", SearchIntent.REVIEW)
    assert len({local.need_id, foreign.need_id, review.need_id}) == 3


class SelectionExtraction:
    provider_name = "fixture-extraction"

    def __init__(self, pages: dict[str, str]):
        self.pages = pages
        self.urls: list[str] = []

    async def extract(self, url, options):
        self.urls.append(str(url))
        text = self.pages[str(url)]
        return SourceSnapshot(
            url=url,
            source_type=options.source_type,
            extraction_status=ExtractionStatus.SUCCEEDED,
            provider=ProviderMetadata(provider_name=self.provider_name),
            extracted_content=ExtractedPageContent(
                text=text, extractor="fixture", word_count=len(text.split())
            ),
        )


async def measure_noisy_selection() -> dict[str, object]:
    lead_rows = (
        (
            "https://noise.example/car",
            "Car insurance",
            "Annual car policy information",
            SourceType.SEARCH_RESULT,
        ),
        (
            "https://brand.example/ph/aster",
            "Aster lamp",
            "Aster lamp has steady reading light.",
            SourceType.OFFICIAL_BRAND_PAGE,
        ),
        (
            "https://brand.example/ph/aster?utm_source=one",
            "Aster lamp",
            "Aster lamp has steady reading light.",
            SourceType.OFFICIAL_BRAND_PAGE,
        ),
        (
            "https://brand.example/ph/aster?utm_source=two",
            "Aster lamp",
            "Aster lamp has steady reading light.",
            SourceType.OFFICIAL_BRAND_PAGE,
        ),
        (
            "https://brand.example/aster-copy",
            "Aster lamp",
            "Aster lamp has steady reading light.",
            SourceType.OFFICIAL_BRAND_PAGE,
        ),
        (
            "https://noise.example/gardens",
            "Garden soil",
            "Soil nutrients for seedlings",
            SourceType.SEARCH_RESULT,
        ),
        (
            "https://noise.example/motors",
            "Car motors",
            "Motor replacement parts",
            SourceType.SEARCH_RESULT,
        ),
        (
            "https://independent.example/aster",
            "Aster lamp reading review",
            "Aster lamp has comfortable reading illumination.",
            SourceType.PROFESSIONAL_REVIEW,
        ),
        (
            "https://seller.example/aster",
            "Aster lamp imported offer",
            "Aster lamp seller is unverified and has no local warranty.",
            SourceType.RETAILER_LISTING,
        ),
        (
            "https://noise.example/tires",
            "Vehicle tires",
            "Tires for wet roads",
            SourceType.SEARCH_RESULT,
        ),
    )
    leads = tuple(_lead(*row) for row in lead_rows)
    report: dict[str, object] = {}
    for name, configure in (("before", False), ("after", True)):
        with tempfile.TemporaryDirectory(
            prefix="cartcart-selection-", dir="/private/tmp"
        ) as folder:
            engine, factory, run_id, _ = await _database(Path(folder))
            search = RecordingSearchProvider(leads)
            extraction = SelectionExtraction(
                {str(lead.url): lead.snippet or lead.title for lead in leads}
            )
            tools = AgentResearchTools(
                agent_name="GeneralShoppingAgent",
                run_id=run_id,
                session_factory=factory,
                search_provider=search,
                extraction_provider=extraction,
                required_region_code="PH",
                limits=ResearchToolLimits(max_fetch_calls=20),
            )
            if configure:
                tools.set_brief(_brief())
            try:
                result = await tools.search(SearchSourcesRequest(query="Aster lamp"))
                admitted = list(result.sources)
                histories = [result.tool_json()]
                if not configure:
                    offset = result.next_offset
                    while offset is not None:
                        raw = await tools.read_search_results(
                            search_result_id=str(result.search_result_id), offset=offset
                        )
                        histories.append(raw)
                        page = json.loads(raw)
                        admitted.extend(
                            ToolSource.model_validate(row) for row in page["sources"]
                        )
                        offset = page.get("next_offset")
                exact = {}
                for lead in admitted:
                    fetched = await tools.fetch(
                        FetchSourceRequest(source_id=lead.source_id)
                    )
                    assert fetched.text is not None
                    histories.append(fetched.model_dump_json())
                    if str(lead.url) in {
                        "https://brand.example/ph/aster",
                        "https://independent.example/aster",
                        "https://seller.example/aster",
                    }:
                        recorded = await tools.record_quote(
                            lead.source_id, fetched.text
                        )
                        assert recorded.quote == fetched.text
                        exact[str(lead.url)] = recorded.quote
                assert (
                    exact["https://brand.example/ph/aster"]
                    == "Aster lamp has steady reading light."
                )
                assert (
                    exact["https://independent.example/aster"]
                    == "Aster lamp has comfortable reading illumination."
                )
                assert (
                    exact["https://seller.example/aster"]
                    == "Aster lamp seller is unverified and has no local warranty."
                )
                report[name] = {
                    "admitted_lead_bytes": sum(
                        len(lead.model_dump_json(exclude_defaults=True).encode())
                        for lead in admitted
                    ),
                    "repeated_history_characters": sum(
                        len("".join(histories[: index + 1]))
                        for index in range(len(histories))
                    ),
                    "repeated_history_bytes": sum(
                        len("".join(histories[: index + 1]).encode("utf-8"))
                        for index in range(len(histories))
                    ),
                    "page_fetches": len(extraction.urls),
                    "expected_product_support": exact["https://brand.example/ph/aster"],
                    "expected_independent_support": exact[
                        "https://independent.example/aster"
                    ],
                    "expected_rejected_seller_warning": exact[
                        "https://seller.example/aster"
                    ],
                    "initial_source_urls": [str(lead.url) for lead in result.sources],
                    "selection_reasons": result.selection_reasons,
                }
            finally:
                await engine.dispose()
    return report


@pytest.mark.asyncio
async def test_noisy_selection_reduces_admission_and_fetches_with_literal_support() -> (
    None
):
    report = await measure_noisy_selection()
    before, after = report["before"], report["after"]
    assert isinstance(before, dict) and isinstance(after, dict)
    assert before["page_fetches"] == 10 and after["page_fetches"] == 3
    assert after["admitted_lead_bytes"] < before["admitted_lead_bytes"]
    assert after["repeated_history_characters"] < before["repeated_history_characters"]
    assert after["repeated_history_bytes"] < before["repeated_history_bytes"]
    assert (
        after["expected_independent_support"]
        == "Aster lamp has comfortable reading illumination."
    )
    assert (
        after["expected_rejected_seller_warning"]
        == "Aster lamp seller is unverified and has no local warranty."
    )


@pytest.mark.asyncio
async def test_durable_shortlist_widen_fetch_needs_and_stop_with_exact_support(
    tmp_path: Path,
) -> None:
    engine, factory, run_id, _ = await _database(tmp_path)
    official = _lead(
        "https://brand.example/ph/aster",
        "Aster lamp official",
        "Aster lamp reading light",
        SourceType.OFFICIAL_BRAND_PAGE,
    )
    review = _lead(
        "https://review.example/aster",
        "Aster lamp review",
        "Aster lamp reading measurements",
        SourceType.PROFESSIONAL_REVIEW,
    )
    noise = _lead(
        "https://noise.example/insurance", "Car insurance", "Policy information"
    )
    unsafe = _lead(
        "http://127.0.0.1/internal", "Aster lamp", "Aster lamp internal server"
    )
    extra = _lead(
        "https://more.example/aster",
        "Aster lamp additional review",
        "Aster lamp long term testing",
        SourceType.PROFESSIONAL_REVIEW,
    )
    search = RecordingSearchProvider((noise, official, review, unsafe, extra))
    official_quote = "Aster lamp provides steady warm light."
    review_quote = "Aster lamp has comfortable reading illumination."
    extraction = SelectionExtraction(
        {
            str(official.url): official_quote,
            str(review.url): review_quote,
            str(extra.url): "Aster lamp has additional tests.",
        }
    )
    tools = AgentResearchTools(
        agent_name="GeneralShoppingAgent",
        run_id=run_id,
        session_factory=factory,
        search_provider=search,
        extraction_provider=extraction,
        limits=ResearchToolLimits(max_initial_results=1),
        required_region_code="PH",
    )
    tools.set_brief(_brief())
    try:
        result = await tools.search(SearchSourcesRequest(query="Aster lamp"))
        assert result.status == "succeeded" and result.evidence_need_id is not None
        assert result.sources[0].source_id == official.source_id
        assert result.selection_reasons[str(unsafe.source_id)] == "unsafe_url"
        async with factory() as session:
            originals = await SearchSourceRepository(session).list_search_results(
                run_id
            )
        assert {str(item.url) for item in originals} == {
            str(item.url) for item in (noise, official, review, unsafe, extra)
        }
        assert (
            next(
                item for item in originals if item.source_id == unsafe.source_id
            ).provider.raw["research_selection"]["status"]
            == "rejected"
        )
        assert (
            json.loads(
                await tools.read_search_results(source_id=str(unsafe.source_id))
            )["status"]
            == "gap"
        )
        widened = json.loads(
            await tools.read_search_results(need_id=result.evidence_need_id)
        )
        assert len(widened["sources"]) == 1
        fetched = await tools.fetch(FetchSourceRequest(source_id=official.source_id))
        assert (
            fetched.text == official_quote
            and fetched.evidence_need_id == result.evidence_need_id
        )
        assert (
            await tools.record_quote(official.source_id, official_quote)
        ).status == "succeeded"
        after_support = json.loads(
            await tools.read_search_results(need_id=result.evidence_need_id)
        )
        assert (
            after_support["sources"][0]["provider_source_type"] == "professional_review"
        )
        fetched_review = await tools.fetch(
            FetchSourceRequest(source_id=review.source_id)
        )
        assert fetched_review.text == review_quote
        assert (
            await tools.record_quote(review.source_id, review_quote)
        ).status == "succeeded"
        stopped = await tools.search(
            SearchSourcesRequest(query="Aster lamp more reviews")
        )
        assert (
            stopped.gap
            == "Required research already has exact support. Continue to candidate validation and verification."
        )
        stopped_fetch = await tools.fetch(FetchSourceRequest(source_id=extra.source_id))
        assert stopped_fetch.status == "gap"
        assert (
            await tools.fetch(
                FetchSourceRequest(source_id=official.source_id, need_id="foreign-run")
            )
        ).status == "invalid_request"
        assert len(search.calls) == 1 and extraction.urls == [
            str(official.url),
            str(review.url),
        ]
        reread = await tools.fetch(FetchSourceRequest(source_id=official.source_id))
        assert reread.text == official_quote
        assert (
            tools.workbench_activity[0]["output"]["lead_bytes"]["admitted"]
            < tools.workbench_activity[0]["output"]["lead_bytes"]["original"]
        )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_late_seller_caution_stays_open_until_exact_quote_is_reviewed(
    tmp_path: Path,
) -> None:
    engine, factory, run_id, _ = await _database(tmp_path)
    official = _lead(
        "https://brand.example/aster",
        "Aster lamp official",
        "Aster lamp reading light",
        SourceType.OFFICIAL_BRAND_PAGE,
    )
    review = _lead(
        "https://review.example/aster",
        "Aster lamp review",
        "Aster lamp reading measurements",
        SourceType.PROFESSIONAL_REVIEW,
    )
    quote = "Aster lamp provides steady warm light."
    warning = "Aster imported variant has no local warranty."
    page = quote + " " + "Lighting measurements. " * 240 + warning
    provider = RecordingSearchProvider((official, review))
    extraction = SelectionExtraction({str(official.url): page, str(review.url): quote})
    tools = AgentResearchTools(
        agent_name="GeneralShoppingAgent",
        run_id=run_id,
        session_factory=factory,
        search_provider=provider,
        extraction_provider=extraction,
        required_region_code="PH",
    )
    tools.set_brief(_brief())
    try:
        await tools.search(SearchSourcesRequest(query="Aster lamp"))
        first = await tools.fetch(FetchSourceRequest(source_id=official.source_id))
        assert warning not in (first.text or "") and warning in first.material_cautions
        assert (
            await tools.record_quote(official.source_id, quote)
        ).status == "succeeded"
        await tools.fetch(FetchSourceRequest(source_id=review.source_id))
        assert (await tools.record_quote(review.source_id, quote)).status == "succeeded"
        assert tools._run_state.selection is not None
        assert tools._run_state.selection.covered is False
        assert (await tools.record_quote(official.source_id, warning)).status == "gap"
        late = await tools.fetch(
            FetchSourceRequest(source_id=official.source_id, focus="no local warranty")
        )
        assert warning in (late.text or "")
        assert (await tools.record_quote(official.source_id, warning)).quote == warning
        assert tools._run_state.selection.covered is True
        reread = await tools.fetch(FetchSourceRequest(source_id=official.source_id))
        assert warning in reread.material_cautions
        assert tools._run_state.selection.covered is True
    finally:
        await engine.dispose()
