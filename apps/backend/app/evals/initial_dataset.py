"""Initial shopping corpus and expectations; scoring is deliberately separate."""

from pathlib import Path
from typing import Literal

from pydantic import AnyHttpUrl, Field, model_validator
from pydantic_evals import Dataset

from app.evals.schemas import EvalMetadata, LocalEvalCase
from app.schemas.base import CartCartBaseModel, VersionedSchema
from app.schemas.ids import ProductId, SourceId
from app.schemas.intake import BudgetMode, CreateSessionRequest, ShoppingBrief
from app.schemas.products import CanonicalProduct, ProductListing, UserAddedProduct
from app.schemas.regions import RegionCode
from app.schemas.search_sources import EvidenceTarget, SourceQualityLevel, SourceType
from app.schemas.timestamps import Timestamp

CORPUS_DIR = Path(__file__).parent / "fixtures" / "initial"


class FixtureExcerpt(CartCartBaseModel):
    evidence_id: SourceId
    text: str = Field(min_length=1, max_length=2000)
    target: EvidenceTarget
    timestamp_seconds: int | None = Field(default=None, ge=0)


class ShoppingSourceFixture(CartCartBaseModel):
    """Synthetic source input, not a provider response or verified agent output."""

    source_id: SourceId
    url: AnyHttpUrl
    source_type: SourceType
    quality: SourceQualityLevel
    region_code: RegionCode | None = None
    title: str = Field(min_length=1, max_length=300)
    captured_at: Timestamp
    context: tuple[str, ...] = Field(default_factory=tuple)
    excerpts: tuple[FixtureExcerpt, ...] = Field(default_factory=tuple)
    evidence_gaps: tuple[str, ...] = Field(default_factory=tuple)


class ShoppingScenarioInput(VersionedSchema):
    request: CreateSessionRequest
    # Absent during intake/guardrail cases; later-stage cases start from a brief.
    brief: ShoppingBrief | None = None
    shopper_answers: tuple[str, ...] = Field(default_factory=tuple)
    products: tuple[CanonicalProduct, ...] = Field(default_factory=tuple)
    listings: tuple[ProductListing, ...] = Field(default_factory=tuple)
    sources: tuple[ShoppingSourceFixture, ...] = Field(default_factory=tuple)
    user_added_products: tuple[UserAddedProduct, ...] = Field(default_factory=tuple)
    prior_result_product_ids: tuple[ProductId, ...] = Field(default_factory=tuple)
    refinement_request: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def consistent_references(self) -> "ShoppingScenarioInput":
        product_ids = {item.product_id for item in self.products}
        listing_ids = {item.listing_id for item in self.listings}
        source_ids = {item.source_id for item in self.sources}
        evidence_ids = [
            excerpt.evidence_id
            for source in self.sources
            for excerpt in source.excerpts
        ]
        for label, ids, count in (
            ("product", product_ids, len(self.products)),
            ("listing", listing_ids, len(self.listings)),
            ("source", source_ids, len(self.sources)),
            ("evidence", set(evidence_ids), len(evidence_ids)),
        ):
            if len(ids) != count:
                raise ValueError(f"Duplicate {label} IDs in shopping fixture.")
        for product in self.products:
            if not set(product.source_ids).issubset(source_ids):
                raise ValueError("Product references an unknown source.")
            if not set(product.listing_ids).issubset(listing_ids):
                raise ValueError("Product references an unknown listing.")
        for listing in self.listings:
            if listing.product_id not in product_ids:
                raise ValueError("Listing references an unknown product.")
            if not set(listing.source_ids).issubset(source_ids):
                raise ValueError("Listing references an unknown source.")
        for candidate in self.user_added_products:
            if candidate.product and candidate.product.product_id not in product_ids:
                raise ValueError("User-added candidate references an unknown product.")
            if candidate.listing and candidate.listing.listing_id not in listing_ids:
                raise ValueError("User-added candidate references an unknown listing.")
        for source in self.sources:
            for excerpt in source.excerpts:
                target = excerpt.target
                if (
                    target.product_id is not None
                    and target.product_id not in product_ids
                ):
                    raise ValueError("Excerpt references an unknown product.")
                if (
                    target.listing_id is not None
                    and target.listing_id not in listing_ids
                ):
                    raise ValueError("Excerpt references an unknown listing.")
                if target.source_id is not None and target.source_id not in source_ids:
                    raise ValueError("Excerpt references an unknown source.")
        if not set(self.prior_result_product_ids).issubset(product_ids):
            raise ValueError("Prior result references an unknown product.")
        return self


class ShoppingCriterion(CartCartBaseModel):
    field: str = Field(min_length=1, max_length=200)
    requirement: str = Field(min_length=1, max_length=1000)
    source_ids: tuple[SourceId, ...] = Field(default_factory=tuple)
    evidence_ids: tuple[SourceId, ...] = Field(default_factory=tuple)


class ShoppingExpectation(CartCartBaseModel):
    """Independent expectation specification, not a canned model response."""

    category: str | None = None
    region_code: RegionCode | None = None
    budget_mode: BudgetMode | None = None
    guardrail_decision: Literal["allow", "off_topic", "unsafe"] | None = None
    analysis_path: tuple[str, ...] = Field(default_factory=tuple)
    criteria: tuple[ShoppingCriterion, ...] = Field(min_length=1)


class ShoppingCaseManifest(VersionedSchema):
    cases: tuple[LocalEvalCase[str, ShoppingExpectation], ...] = Field(
        min_length=15, max_length=25
    )


class ShoppingFixtureCorpus(VersionedSchema):
    provenance: Literal["synthetic"]
    fixtures: dict[str, ShoppingScenarioInput]


def initial_cases(
    corpus_dir: Path = CORPUS_DIR,
) -> tuple[LocalEvalCase[ShoppingScenarioInput, ShoppingExpectation], ...]:
    """Load fresh validated inputs without settings, network, or agent execution."""
    manifest = ShoppingCaseManifest.model_validate_json(
        (corpus_dir / "cases.json").read_text(encoding="utf-8")
    )
    corpus = ShoppingFixtureCorpus.model_validate_json(
        (corpus_dir / "inputs.json").read_text(encoding="utf-8")
    )
    if any(
        version != 1
        for version in (
            manifest.schema_version,
            corpus.schema_version,
            *(case.schema_version for case in manifest.cases),
            *(inputs.schema_version for inputs in corpus.fixtures.values()),
        )
    ):
        raise ValueError("Unsupported corpus version; expected schema_version 1.")
    names = [case.name for case in manifest.cases]
    fixture_names = [case.inputs for case in manifest.cases]
    if len(set(names)) != len(names):
        raise ValueError("Shopping case names must be unique.")
    if set(fixture_names) != set(corpus.fixtures):
        raise ValueError("Shopping cases and fixtures must match exactly.")
    cases = []
    for case in manifest.cases:
        inputs = corpus.fixtures[case.inputs].model_copy(deep=True)
        source_ids = {source.source_id for source in inputs.sources}
        evidence_sources = {
            excerpt.evidence_id: source.source_id
            for source in inputs.sources
            for excerpt in source.excerpts
        }
        for criterion in case.expected_output.criteria:
            if not set(criterion.source_ids).issubset(source_ids):
                raise ValueError(f"{case.name}: expectation cites an unknown source.")
            if not set(criterion.evidence_ids).issubset(evidence_sources):
                raise ValueError(f"{case.name}: expectation cites unknown evidence.")
            if any(
                evidence_sources[evidence_id] not in criterion.source_ids
                for evidence_id in criterion.evidence_ids
            ):
                raise ValueError(f"{case.name}: evidence must cite its owning source.")
        cases.append(
            LocalEvalCase[ShoppingScenarioInput, ShoppingExpectation](
                name=case.name,
                inputs=inputs,
                expected_output=case.expected_output,
                metadata=case.metadata,
            )
        )
    return tuple(cases)


def initial_dataset() -> Dataset[
    ShoppingScenarioInput, ShoppingExpectation, EvalMetadata
]:
    """Expose corpus as Pydantic cases; task adapters/evaluators are not registered."""
    return Dataset(
        name="cartcart-initial-shopping",
        cases=[case.to_case() for case in initial_cases()],
    )
