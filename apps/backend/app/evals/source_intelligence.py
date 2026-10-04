"""Synthetic, offline source services/specialists and downstream contract probes."""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator
from pydantic_evals import Case, Dataset

from app.agents.contracts import (
    AmazonProductIntelligenceAgentInput,
    ComparisonDecisionAgentInput,
    IKEAStoreIntelligenceAgentInput,
    ProductAnalysisAgentInput,
    RedditCommunityIntelligenceAgentInput,
    VerificationAgentInput,
    VerificationReport,
    YouTubeReviewIntelligenceAgentInput,
)
from app.agents.amazon_product_intelligence_service import (
    AmazonProductIntelligenceService,
)
from app.agents.ikea_store_intelligence_service import IKEAStoreIntelligenceService
from app.agents.live_amazon_product_intelligence import (
    AmazonProductIntelligenceAgent,
    MockAmazonProductModelRunner,
)
from app.agents.live_comparison_decision import (
    LiveComparisonDecisionAgent,
    MockComparisonDecisionModelRunner,
)
from app.agents.live_generic_product_analyst import (
    LiveGenericProductAnalystAgent,
    MockGenericProductAnalystModelRunner,
)
from app.agents.live_ikea_store_intelligence import (
    IKEAStoreIntelligenceAgent,
    MockIKEAStoreModelRunner,
)
from app.agents.live_reddit_community_intelligence import (
    RedditCommunityIntelligenceAgent,
    MockRedditCommunityModelRunner,
)
from app.agents.live_verifier_critic import (
    LiveVerifierCriticAgent,
    MockVerifierCriticModelRunner,
)
from app.agents.live_youtube_review_intelligence import (
    YouTubeReviewIntelligenceAgent,
    MockYouTubeReviewModelRunner,
)
from app.agents.reddit_community_intelligence_service import (
    RedditCommunityIntelligenceService,
)
from app.agents.youtube_review_intelligence_service import (
    YouTubeReviewIntelligenceService,
)
from app.core.settings import Settings
from app.evals.schemas import EvalMetadata, LocalEvalCase
from app.evals.trust_recommendation import TrustRecommendationRule
from app.providers import (
    AmazonProductIntelligenceProviderResult,
    CommunityDiscussionProviderResult,
    IKEAStoreIntelligenceProviderResult,
    ProviderCapabilityFlags,
    ProviderRunStatus,
    TranscriptProviderResult,
    VideoSearchProviderResult,
)
from app.schemas.analysis import CategoryAnalysis, RecommendationBundle
from app.schemas.base import CartCartBaseModel, VersionedSchema
from app.schemas.search_sources import (
    AmazonProductEvidenceBundle,
    CommunityDiscussionEvidenceBundle,
    EvidenceType,
    IKEAStoreEvidenceBundle,
    SourceEvidence,
    SourceEvidenceGap,
    VideoReviewEvidenceBundle,
)
from app.services.amazon_evidence_creation import (
    AmazonProductEvidenceCreator,
    AmazonProductEvidenceInput,
)
from app.services.ikea_evidence_creation import (
    IKEAStoreEvidenceCreator,
    IKEAStoreEvidenceInput,
)
from app.services.listing_trust import ListingTrustRuleContext, assess_listing_trust
from app.schemas.timestamps import Timestamp

CORPUS_PATH = Path(__file__).parent / "fixtures" / "source_intelligence.json"
STAGES = ("youtube", "reddit", "amazon", "ikea")
Bundle = (
    VideoReviewEvidenceBundle
    | CommunityDiscussionEvidenceBundle
    | AmazonProductEvidenceBundle
    | IKEAStoreEvidenceBundle
)
Request = (
    YouTubeReviewIntelligenceAgentInput
    | RedditCommunityIntelligenceAgentInput
    | AmazonProductIntelligenceAgentInput
    | IKEAStoreIntelligenceAgentInput
)
Fault = Literal[
    "timeout",
    "invalid",
    "invented_quote",
    "wrong_source",
    "erase_warnings",
    "wrong_price",
]


class SourceFixture(VersionedSchema):
    stage: Literal["youtube", "reddit", "amazon", "ikea"]
    mode: Literal["service", "specialist"] = "specialist"
    youtube: YouTubeReviewIntelligenceAgentInput | None = None
    reddit: RedditCommunityIntelligenceAgentInput | None = None
    amazon: AmazonProductIntelligenceAgentInput | None = None
    ikea: IKEAStoreIntelligenceAgentInput | None = None
    video_result: VideoSearchProviderResult | None = None
    transcripts: tuple[TranscriptProviderResult, ...] = ()
    community_result: CommunityDiscussionProviderResult | None = None
    amazon_facts: tuple[AmazonProductEvidenceInput, ...] = ()
    ikea_facts: tuple[IKEAStoreEvidenceInput, ...] = ()
    provider_status: ProviderRunStatus = ProviderRunStatus.SUCCEEDED
    provider_notes: tuple[str, ...] = ()
    provider_gaps: tuple[SourceEvidenceGap, ...] = ()
    observed_at: Timestamp
    selection_limit: int = Field(default=2, ge=1, le=3)
    model_fault: Fault | None = None
    # Scripted tool strategy, never an expected answer or injected model output.
    read_focus: str | None = Field(default=None, min_length=1, max_length=200)
    # Optional claim is a proposed shopper rationale, not an expected answer.
    recommendation_claim: str | None = Field(default=None, min_length=1, max_length=500)
    offer_evidence: tuple[SourceEvidence, ...] = ()

    @model_validator(mode="after")
    def _references(self) -> "SourceFixture":
        if tuple(getattr(self, s) is not None for s in STAGES) != tuple(
            self.stage == s for s in STAGES
        ):
            raise ValueError("Exactly one selected source request is required.")
        if self.mode == "service" and self.model_fault:
            raise ValueError("Model faults require the specialist path.")
        if self.read_focus and (self.mode != "specialist" or self.stage not in {"youtube", "reddit"}):
            raise ValueError("Focused reads require a transcript/discussion specialist.")
        if (
            self.model_fault == "erase_warnings"
            and self.stage != "amazon"
            or self.model_fault == "wrong_price"
            and self.stage != "ikea"
            or self.model_fault == "invented_quote"
            and self.stage not in {"youtube", "reddit"}
        ):
            raise ValueError("Model fault does not apply to this source contract.")
        if self.stage != "youtube" and (self.transcripts or self.video_result):
            raise ValueError("Video fixtures belong only to YouTube.")
        if self.stage != "reddit" and self.community_result:
            raise ValueError("Community fixture belongs only to Reddit.")
        if self.stage != "amazon" and self.amazon_facts:
            raise ValueError("Amazon facts belong only to Amazon.")
        if self.stage != "ikea" and (self.ikea_facts or self.provider_gaps):
            raise ValueError("Store facts/gaps belong only to IKEA.")
        request = self.request
        products = {p.product_id for p in request.products}
        listings = {v.listing_id: v for v in request.listings}
        for p in request.products:
            if set(p.listing_ids) != {
                v.listing_id for v in request.listings if v.product_id == p.product_id
            }:
                raise ValueError("Product listing membership must be exact.")
        if self.recommendation_claim and (len(products) != 1 or len(listings) != 1):
            raise ValueError("Downstream probes require one candidate and one offer.")
        if bool(self.offer_evidence) != bool(self.recommendation_claim):
            raise ValueError("Downstream probes require separate offer evidence.")
        if len({e.evidence_id for e in self.offer_evidence}) != len(
            self.offer_evidence
        ) or any(
            e.target.listing_id not in listings
            or e.source_id not in listings[e.target.listing_id].source_ids
            for e in self.offer_evidence
        ):
            raise ValueError(
                "Offer evidence needs unique IDs and its own listing/source."
            )
        videos = {s.video.video_id for s in request.source_snapshots if s.video}
        if self.video_result and self.video_result.bundle:
            videos.update(v.video_id for v in self.video_result.bundle.videos)
        if len({r.video.video_id for r in self.transcripts}) != len(
            self.transcripts
        ) or any(r.video.video_id not in videos for r in self.transcripts):
            raise ValueError("Transcript recordings need unique known videos.")
        for fact in self.amazon_facts:
            if (
                fact.product_id not in products
                or fact.listing_id not in listings
                or listings[fact.listing_id].product_id != fact.product_id
            ):
                raise ValueError("Amazon fact targets an unknown or mismatched offer.")
        if any(f.product_id not in products for f in self.ikea_facts):
            raise ValueError("IKEA fact targets an unknown product.")
        if self.provider_status != ProviderRunStatus.SUCCEEDED and (
            self.amazon_facts or self.ikea_facts
        ):
            raise ValueError("Unavailable providers cannot contain product facts.")
        facts = (*self.amazon_facts, *self.ikea_facts)
        if len({f.source_reference.source_id for f in facts}) != len(facts):
            raise ValueError("Provider facts require unique source identities.")
        return self

    @property
    def request(self) -> Request:
        value = getattr(self, self.stage)
        assert value is not None
        return value


class SourceRule(TrustRecommendationRule):
    field: str = Field(
        pattern=r"^(youtube|reddit|amazon|ikea|analysis|recommendation|verification|model_calls)(\.(\w+|\*))*$"
    )


class SourceExpectation(CartCartBaseModel):
    fields: tuple[SourceRule, ...] = Field(min_length=1)


class SourceOutput(VersionedSchema):
    youtube: VideoReviewEvidenceBundle | None = None
    reddit: CommunityDiscussionEvidenceBundle | None = None
    amazon: AmazonProductEvidenceBundle | None = None
    ikea: IKEAStoreEvidenceBundle | None = None
    analysis: CategoryAnalysis | None = None
    recommendation: RecommendationBundle | None = None
    verification: VerificationReport | None = None
    model_calls: int = Field(ge=0)

    @property
    def bundle(self) -> Bundle:
        values = [getattr(self, s) for s in STAGES if getattr(self, s) is not None]
        if len(values) != 1:
            raise ValueError("Exactly one source bundle must be returned.")
        return values[0]


SourceResult = SourceOutput | SourceExpectation


class SourceCorpus(VersionedSchema):
    provenance: Literal["synthetic"]
    cases: tuple[LocalEvalCase[SourceFixture, SourceExpectation], ...] = Field(
        min_length=1
    )


def _fixed(raw: object, model: object) -> None:
    if isinstance(model, BaseModel) and isinstance(raw, dict):
        if isinstance(model, VersionedSchema) and model.schema_version != 1:
            raise ValueError("Unsupported fixture version.")
        for name in type(model).model_fields:
            value = getattr(model, name)
            if (
                (
                    name.endswith("_id")
                    and name != "comment_id"
                    or name
                    in {
                        "captured_at",
                        "created_at",
                        "assessed_at",
                        "observed_at",
                        "checked_at",
                        "published_at",
                        "posted_at",
                    }
                )
                and value is not None
                and raw.get(name) is None
            ):
                raise ValueError(f"Fixture {name} must be fixed explicitly.")
            if name in raw:
                _fixed(raw[name], value)
    elif isinstance(model, (tuple, list)) and isinstance(raw, list):
        for r, v in zip(raw, model, strict=True):
            _fixed(r, v)


def source_intelligence_cases(
    path: Path = CORPUS_PATH,
) -> tuple[LocalEvalCase[SourceFixture, SourceExpectation], ...]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    corpus = SourceCorpus.model_validate(raw)
    _fixed(raw, corpus)
    if len({c.name for c in corpus.cases}) != len(corpus.cases):
        raise ValueError("Duplicate case name.")
    for c in corpus.cases:
        rules = c.expected_output.fields
        roots = {c.inputs.stage, "model_calls"}
        if c.inputs.recommendation_claim:
            roots.update(("analysis", "recommendation", "verification"))
        if any(r.field.split(".")[0] not in roots for r in rules) or not any(
            r.field.startswith(c.inputs.stage + ".") for r in rules
        ):
            raise ValueError("Criteria must cover the selected source's behavior.")
        keys = [(r.field, r.operator, str(r.value)) for r in rules]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate expectation rule.")
    return corpus.cases


def source_intelligence_dataset() -> Dataset[SourceFixture, SourceResult, EvalMetadata]:
    from app.evals.source_intelligence_scoring import SourceIntelligenceEvaluator

    return Dataset(
        name="cartcart-source-intelligence",
        cases=[
            Case[SourceFixture, SourceResult, EvalMetadata](
                name=c.name,
                inputs=c.inputs,
                expected_output=c.expected_output,
                metadata=c.metadata,
            )
            for c in source_intelligence_cases()
        ],
        evaluators=[SourceIntelligenceEvaluator()],
    )


@dataclass
class _Providers:
    fixture: SourceFixture

    @property
    def capabilities(self) -> ProviderCapabilityFlags:
        return ProviderCapabilityFlags(
            provider_name="synthetic-source-eval",
            enabled=self.fixture.provider_status != ProviderRunStatus.DISABLED,
            supports_video_search=True,
            supports_transcripts=True,
            permits_transcript_text=True,
            transcript_access_strategy="user_provided",
            supports_community_discussion_retrieval=True,
            supports_amazon_product_intelligence=True,
            supports_amazon_listing_identity=True,
            supports_amazon_review_signals=True,
            supports_regional_ship_to_evidence=True,
            supports_ikea_regional_store_lookup=True,
            supports_ikea_product_pages=True,
            supports_ikea_store_delivery_context=True,
        )

    async def search_videos(
        self, query: str, options: Any = None
    ) -> VideoSearchProviderResult:
        del options
        assert self.fixture.youtube is not None
        if (
            query not in self.fixture.youtube.video_queries
            or self.fixture.video_result is None
        ):
            raise ValueError("Unrecorded video query; no network fallback.")
        return self.fixture.video_result.model_copy(deep=True)

    async def fetch_transcript(
        self, video: Any, options: Any = None
    ) -> TranscriptProviderResult:
        del options
        for result in self.fixture.transcripts:
            if result.video.video_id == video.video_id:
                return result.model_copy(deep=True)
        raise ValueError("Unrecorded transcript; no network fallback.")

    async def search_discussions(
        self, query: str, products: Any = (), options: Any = None
    ) -> CommunityDiscussionProviderResult:
        del options
        assert self.fixture.reddit is not None
        if (
            query not in self.fixture.reddit.community_queries
            or self.fixture.community_result is None
        ):
            raise ValueError("Unrecorded community query; no network fallback.")
        return self.fixture.community_result.model_copy(deep=True)

    async def fetch_product_evidence(
        self, product: Any, listings: Any = (), options: Any = None
    ) -> AmazonProductIntelligenceProviderResult:
        if (
            product.product_id
            not in {p.product_id for p in self.fixture.request.products}
            or options.region_code != self.fixture.request.target_region_code
        ):
            raise ValueError("Unrecorded Amazon candidate/region.")
        facts = tuple(
            f for f in self.fixture.amazon_facts if f.product_id == product.product_id
        )
        if listings and any(
            f.listing_id not in {v.listing_id for v in listings} for f in facts
        ):
            raise ValueError("Amazon read changed the supplied listing.")
        return AmazonProductIntelligenceProviderResult(
            status=self.fixture.provider_status,
            capabilities=self.capabilities,
            bundle=AmazonProductEvidenceCreator().create(facts)
            if self.fixture.provider_status == ProviderRunStatus.SUCCEEDED
            else None,
            notes=self.fixture.provider_notes,
        )

    async def fetch_store_evidence(
        self, product: Any, options: Any = None
    ) -> IKEAStoreIntelligenceProviderResult:
        if (
            product.product_id
            not in {p.product_id for p in self.fixture.request.products}
            or options.region_code != self.fixture.request.target_region_code
        ):
            raise ValueError("Unrecorded IKEA candidate/region.")
        facts = tuple(
            f for f in self.fixture.ikea_facts if f.product_id == product.product_id
        )
        return IKEAStoreIntelligenceProviderResult(
            status=self.fixture.provider_status,
            capabilities=self.capabilities,
            bundle=IKEAStoreEvidenceCreator().create(
                facts, evidence_gaps=self.fixture.provider_gaps
            )
            if self.fixture.provider_status == ProviderRunStatus.SUCCEEDED
            else None,
            notes=self.fixture.provider_notes,
        )


@dataclass
class _FaultRunner:
    delegate: Any
    fault: Fault | None

    async def run(self, *args: Any, **kwargs: Any) -> Any:
        if self.fault == "timeout":
            raise TimeoutError("Synthetic model timeout.")
        result = await self.delegate.run(*args, **kwargs)
        if not self.fault:
            return result
        data = result.final_output.model_dump(mode="json")
        if self.fault == "invalid":
            data = {"unexpected": True}
        elif self.fault == "invented_quote":
            if data.get("claims"):
                data["claims"][0]["quote"] = (
                    "The screen has a guaranteed 240Hz OLED panel."
                )
            elif data.get("signals"):
                data["signals"][0]["supporting_quotes"][0]["quote"] = (
                    "Invented authoritative community statement."
                )
        elif self.fault == "wrong_source":
            key = (
                "selected_videos"
                if "selected_videos" in data
                else "selected_sources"
                if "selected_sources" in data
                else "selected_discussions"
            )
            if data.get(key):
                data[key][0]["source_id"] = "00000000-0000-4000-8000-000000099999"
        elif self.fault == "erase_warnings":
            for source in data.get("selected_sources", []):
                source["selected_evidence_ids"] = []
        elif self.fault == "wrong_price":
            for source in data.get("selected_sources", []):
                source["price"] = {"amount": "1", "currency": "USD"}
        return type("SyntheticResult", (), {"final_output": data})()


class _FocusedTools:
    def __init__(self, tools: Any, focus: str):
        self.tools, self.focus = tools, focus

    def __getattr__(self, name: str) -> Any:
        return getattr(self.tools, name)

    async def read(self, source_id: str) -> Any:
        return await self.tools.read(source_id, focus=self.focus)


@dataclass
class _FocusedRunner:
    delegate: Any
    focus: str | None

    async def run(self, *args: Any, **kwargs: Any) -> Any:
        if self.focus:
            kwargs["tools"] = _FocusedTools(kwargs["tools"], self.focus)
        return await self.delegate.run(*args, **kwargs)


class _PagedTranscriptTools:
    def __init__(self, tools: Any):
        self.tools = tools

    def __getattr__(self, name: str) -> Any:
        return getattr(self.tools, name)

    async def transcript(self, video_id: str) -> Any:
        page = await self.tools.transcript(video_id)
        observed = list(page.get("segments", ()))
        while page.get("next_segment") is not None:
            page = await self.tools.transcript(
                video_id, start_segment=page["next_segment"],
                start_char=page["next_start_char"],
            )
            observed.extend(page.get("segments", ()))
        relevant = [segment for segment in observed if re.search(
            r"\b(?:pro|con|concern):", segment.get("text") or "", re.I
        )]
        return {**page, "segments": (relevant or observed)[:3]}


@dataclass
class _PagedTranscriptRunner:
    delegate: Any

    async def run(self, *args: Any, **kwargs: Any) -> Any:
        kwargs["tools"] = _PagedTranscriptTools(kwargs["tools"])
        return await self.delegate.run(*args, **kwargs)


def _analysis_evidence(bundle: Bundle) -> tuple[SourceEvidence, ...]:
    """Eval-only bridge: preserve identities/targets/claims; metadata stays metadata.

    Production owners consume typed bundles directly. This bridge probes the
    separate analyst/decision/verifier contracts, not workflow persistence.
    """
    videos = (
        {v.video_id: v for v in bundle.videos}
        if isinstance(bundle, VideoReviewEvidenceBundle)
        else {}
    )
    return tuple(
        SourceEvidence(
            evidence_id=e.evidence_id,
            source_id=e.source_id,
            target=e.target,
            evidence_type=EvidenceType.OTHER
            if getattr(e, "metadata_only", False)
            else EvidenceType.VIDEO_CLAIM
            if videos
            else EvidenceType.COMMUNITY_CLAIM
            if isinstance(bundle, CommunityDiscussionEvidenceBundle)
            else {
                "product_page_fact": EvidenceType.MARKETPLACE_PRODUCT_FACT,
                "official_product_fact": EvidenceType.OFFICIAL_STORE_FACT,
                "listing_identity": EvidenceType.LISTING_IDENTITY,
                "seller_fulfillment": EvidenceType.SELLER_TRUST,
                "review_summary": EvidenceType.REVIEW_SUMMARY,
                "review_quality_warning": EvidenceType.WARNING,
                "marketplace_warning": EvidenceType.WARNING,
                "regional_availability": EvidenceType.REGION_AVAILABILITY,
                "price": EvidenceType.PRICE,
                "regional_price": EvidenceType.PRICE,
                "store_delivery_context": EvidenceType.REGION_AVAILABILITY,
            }.get(getattr(e, "fact_type", None), EvidenceType.OTHER),
            claim=e.claim,
            confidence=e.confidence,
            source_quality=e.source_quality,
            timestamp_references=getattr(e, "timestamp_references", ()),
            video=videos.get(getattr(e, "video_id", None)),
        )
        for e in bundle.evidence
    )


@dataclass
class OfflineSourceIntelligenceTask:
    settings: Settings

    async def __call__(self, inputs: SourceFixture) -> SourceOutput:
        f = inputs.model_copy(deep=True)
        providers = _Providers(f)
        calls = 0
        bundle: Bundle
        if f.stage == "youtube":
            assert f.youtube is not None
            if f.mode == "service":
                bundle = await YouTubeReviewIntelligenceService(
                    video_search_provider=providers,
                    transcript_provider=providers,
                    max_review_videos=f.selection_limit,
                ).run(f.youtube)
            else:
                bundle = await YouTubeReviewIntelligenceAgent(
                    settings=self.settings,
                    video_search_provider=providers,
                    transcript_provider=providers,
                    model_runner=_FaultRunner(
                        _PagedTranscriptRunner(MockYouTubeReviewModelRunner()), f.model_fault
                    ),
                ).run(f.youtube)
                calls += 1
        elif f.stage == "reddit":
            assert f.reddit is not None
            if f.mode == "service":
                bundle = await RedditCommunityIntelligenceService(
                    community_provider=providers,
                    max_discussions=f.selection_limit,
                    now=lambda: f.observed_at,
                ).run(f.reddit)
            else:
                bundle = await RedditCommunityIntelligenceAgent(
                    settings=self.settings,
                    community_provider=providers,
                    model_runner=_FaultRunner(
                        _FocusedRunner(MockRedditCommunityModelRunner(), f.read_focus), f.model_fault
                    ),
                ).run(f.reddit)
                calls += 1
        elif f.stage == "amazon":
            assert f.amazon is not None
            if f.mode == "service":
                bundle = await AmazonProductIntelligenceService(
                    amazon_provider=providers
                ).run(f.amazon)
            else:
                bundle = await AmazonProductIntelligenceAgent(
                    settings=self.settings,
                    amazon_provider=providers,
                    model_runner=_FaultRunner(
                        MockAmazonProductModelRunner(), f.model_fault
                    ),
                ).run(f.amazon)
                calls += 1
        else:
            assert f.ikea is not None
            if f.mode == "service":
                bundle = await IKEAStoreIntelligenceService(
                    ikea_provider=providers
                ).run(f.ikea)
            else:
                bundle = await IKEAStoreIntelligenceAgent(
                    settings=self.settings,
                    ikea_provider=providers,
                    model_runner=_FaultRunner(
                        MockIKEAStoreModelRunner(), f.model_fault
                    ),
                ).run(f.ikea)
                calls += 1
        result = SourceOutput(**{f.stage: bundle}, model_calls=calls)
        if f.recommendation_claim:
            evidence = (*_analysis_evidence(bundle), *f.offer_evidence)
            r = f.request
            analysis = await LiveGenericProductAnalystAgent(
                settings=self.settings,
                model_runner=MockGenericProductAnalystModelRunner(),
            ).run(
                ProductAnalysisAgentInput(
                    run_id=r.run_id,
                    brief=r.brief,
                    product=r.products[0],
                    listings=r.listings,
                    evidence=evidence,
                )
            )
            request = ComparisonDecisionAgentInput(
                run_id=r.run_id,
                brief=r.brief,
                products=r.products,
                listings=r.listings,
                evidence=evidence,
                category_analyses=(analysis,),
                trust_assessments=tuple(
                    assess_listing_trust(
                        v,
                        ListingTrustRuleContext(
                            evidence_ids=tuple(e.evidence_id for e in f.offer_evidence),
                            source_ids=tuple(e.source_id for e in f.offer_evidence),
                        ),
                    )
                    for v in r.listings
                ),
            )
            recommendation = await LiveComparisonDecisionAgent(
                settings=self.settings, model_runner=MockComparisonDecisionModelRunner()
            ).run(request)
            cited_copy = {
                ids: " ".join(e.claim for e in bundle.evidence if e.evidence_id in ids)
                for ids in (
                    recommendation.evidence_ids,
                    *(
                        row.evidence_ids
                        for row in recommendation.comparison_matrix.rows
                    ),
                    *(item.evidence_ids for item in recommendation.rejected_items),
                )
            }
            quoted = cited_copy[recommendation.evidence_ids]
            no_buy_reason = (
                f"{quoted} These concerns and limited evidence do not support a strong buy. "
                "Next, corroborate the concerns before buying."
                if recommendation.no_strong_buy
                else None
            )
            cautions = tuple(
                dict.fromkeys(
                    (
                        *(
                            "These concerns and limited evidence do not support a strong buy."
                            if warning
                            == "No candidate clears the fit, budget, evidence, and listing-trust bar."
                            else warning
                            for warning in recommendation.warnings
                        ),
                        *(
                            warning.replace(
                                "availability or shipping elsewhere",
                                "availability or delivery elsewhere",
                            )
                            for e in bundle.evidence
                            for warning in getattr(e, "evidence_quality_warnings", ())
                        ),
                        *(
                            video.bias_notes.replace("review claims", "source claims")
                            for video in getattr(bundle, "videos", ())
                            if video.bias_notes
                        ),
                    )
                )
            )
            draft = recommendation.model_copy(
                deep=True,
                update={
                    "final_rationale": f.recommendation_claim,
                    "no_strong_buy_reason": no_buy_reason,
                    "mode_results": tuple(
                        m.model_copy(update={"rationale": f.recommendation_claim})
                        for m in recommendation.mode_results
                    ),
                    "comparison_matrix": recommendation.comparison_matrix.model_copy(
                        update={
                            "rows": tuple(
                                row.model_copy(
                                    update={"summary": cited_copy[row.evidence_ids]}
                                )
                                for row in recommendation.comparison_matrix.rows
                            )
                        }
                    ),
                    "rejected_items": tuple(
                        item.model_copy(
                            update={
                                "reason": f"{cited_copy[item.evidence_ids]} "
                                "These concerns do not support a strong buy."
                            }
                        )
                        for item in recommendation.rejected_items
                    ),
                    "warnings": tuple(f"{quoted} {warning}" for warning in cautions),
                },
            )
            report = await LiveVerifierCriticAgent(
                settings=self.settings, model_runner=MockVerifierCriticModelRunner()
            ).run(
                VerificationAgentInput(
                    **request.model_dump(
                        exclude={"schema_version", "requested_result_mode"}
                    ),
                    recommendation_bundle=draft,
                )
            )
            result.analysis, result.recommendation, result.verification = (
                analysis,
                draft,
                report,
            )
            result.model_calls += 3
        return result


def offline_source_intelligence_task() -> OfflineSourceIntelligenceTask:
    settings = Settings(
        _env_file=None,
        environment="test",
        live_agents_enabled=False,
        openai_api_key=None,
        openai_model="synthetic-source-eval",
        openai_run_profiles={},
        openai_agent_overrides={},
        openai_agent_tracing_enabled=False,
    )  # type: ignore[call-arg]
    return OfflineSourceIntelligenceTask(settings=settings)
