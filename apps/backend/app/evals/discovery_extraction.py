"""Offline discovery, source-quality, extraction and conservative dedupe evals."""

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Literal

from pydantic import AnyHttpUrl, BaseModel, Field, JsonValue, model_validator
from pydantic_evals import Case, Dataset

from app.agents.contracts import (
    DiscoveryAgentInput,
    DiscoveryAgentOutput,
    ExtractionAgentInput,
    ExtractionAgentOutput,
)
from app.agents.extraction_tools import SnapshotInterpretationTools, SnapshotReadResult
from app.agents.live_discovery import LiveDiscoveryAgent, MockDiscoveryModelRunner
from app.agents.live_extraction import LiveExtractionAgent, MockExtractionModelRunner
from app.core.settings import Settings
from app.evals.schemas import EvalMetadata, LocalEvalCase
from app.providers.source_quality import (
    SourceQualityAssessment,
    SourceQualityMetadata,
    score_source_quality,
)
from app.schemas.base import CartCartBaseModel, VersionedSchema
from app.schemas.ids import ListingId
from app.schemas.products import (
    CanonicalProduct,
    ProductListing,
    ProductListingExtraction,
)
from app.services.product_deduplication import (
    DeterministicProductDeduplicator,
    FuzzyProductMatchDecision,
)
from app.services.product_listing_extraction import ProductListingExtractor

CORPUS_PATH = Path(__file__).parent / "fixtures" / "discovery_extraction.json"


class QualityInput(CartCartBaseModel):
    url: AnyHttpUrl
    metadata: SourceQualityMetadata


class ExtractionInput(CartCartBaseModel):
    request: ExtractionAgentInput
    # Synthetic model responses are fixtures, separate from acceptance criteria.
    model_output: ExtractionAgentOutput | None = None
    normalization: bool = False

    @model_validator(mode="after")
    def validate_lane(self) -> "ExtractionInput":
        if self.normalization == (self.model_output is not None):
            raise ValueError(
                "Choose deterministic normalization or a recorded mock response."
            )
        snapshots = self.request.workbench_snapshots
        ids = [s.source_id for s in snapshots]
        if len(ids) != len(set(ids)) or set(ids) != set(self.request.snapshot_ids):
            raise ValueError(
                "Assigned snapshot IDs must exactly match unique fixture snapshots."
            )
        if len(self.request.snapshot_ids) != len(set(self.request.snapshot_ids)):
            raise ValueError("Assigned snapshot IDs must be unique.")
        if not set(
            (
                *self.request.editorial_snapshot_ids,
                *self.request.collection_snapshot_ids,
            )
        ).issubset(ids):
            raise ValueError("Editorial/collection sources must be assigned snapshots.")
        if self.model_output is not None:
            output = self.model_output
            cited = (
                {s for p in output.products for s in p.source_ids}
                | {
                    s
                    for listing in output.listings
                    for s in (*listing.source_ids, *listing.seller.source_ids)
                }
                | {e.source_id for e in output.source_evidence}
                | {g.source_id for g in output.evidence_gaps}
                | {m.source_id for m in output.product_mentions}
            )
            if not cited.issubset(ids):
                raise ValueError("Recorded model fixture cites an unassigned snapshot.")
        if self.normalization and len(snapshots) != 1:
            raise ValueError("Normalization takes one listing snapshot.")
        return self


class DiscoveryExtractionInput(VersionedSchema):
    stage: Literal["discovery", "quality", "extraction", "dedupe"]
    discovery: DiscoveryAgentInput | None = None
    quality: QualityInput | None = None
    extraction: ExtractionInput | None = None
    extractions: tuple[ProductListingExtraction, ...] = ()

    @model_validator(mode="after")
    def exclusive_stage(self) -> "DiscoveryExtractionInput":
        present = (
            self.discovery is not None,
            self.quality is not None,
            self.extraction is not None,
            bool(self.extractions),
        )
        if present != tuple(
            self.stage == stage
            for stage in ("discovery", "quality", "extraction", "dedupe")
        ):
            raise ValueError("Provide only the selected stage's inputs.")
        if self.discovery is not None:
            ids = [r.source_id for r in self.discovery.seed_results]
            if len(ids) != len(set(ids)):
                raise ValueError("Duplicate discovery source IDs.")
        if self.extractions:
            ids = [e.listing.listing_id for e in self.extractions]
            if len(ids) != len(set(ids)):
                raise ValueError("Dedupe fixtures must use distinct listing IDs.")
        return self


class FieldRule(CartCartBaseModel):
    field: str = Field(
        pattern=r"^(discovery|quality|extraction|groups|fuzzy_decisions)(\.(\w+|\*))*$"
    )
    operator: Literal["equals", "set_equals", "contains_text", "count"] = "equals"
    value: JsonValue
    requirement: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def valid_operand(self) -> "FieldRule":
        if self.operator == "set_equals" and (
            not isinstance(self.value, list)
            or any(isinstance(v, (dict, list)) for v in self.value)
        ):
            raise ValueError("set_equals requires a list of scalar values.")
        if self.operator == "contains_text" and (
            not isinstance(self.value, str) or not self.value.strip()
        ):
            raise ValueError("contains_text requires nonempty text.")
        if self.operator == "count" and (type(self.value) is not int or self.value < 0):
            raise ValueError("count requires a nonnegative integer.")
        return self


class DiscoveryExtractionExpectation(CartCartBaseModel):
    fields: tuple[FieldRule, ...] = Field(min_length=1)
    # Partition by listing identity, independent of canonical ID or output order.
    groups: tuple[tuple[ListingId, ...], ...] = ()

    @model_validator(mode="after")
    def unique_criteria(self) -> "DiscoveryExtractionExpectation":
        keys = [(r.field, r.operator) for r in self.fields]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate field rules.")
        ids = [i for group in self.groups for i in group]
        if any(not group for group in self.groups) or len(ids) != len(set(ids)):
            raise ValueError("Expected groups must be a disjoint nonempty partition.")
        return self


class ProductGroup(CartCartBaseModel):
    product: CanonicalProduct
    listings: tuple[ProductListing, ...]
    match_kinds: tuple[str, ...] = ()


class DiscoveryExtractionOutput(CartCartBaseModel):
    discovery: DiscoveryAgentOutput | None = None
    quality: SourceQualityAssessment | None = None
    extraction: ExtractionAgentOutput | None = None
    groups: tuple[ProductGroup, ...] = ()
    fuzzy_decisions: tuple[FuzzyProductMatchDecision, ...] = ()


DiscoveryExtractionResult = DiscoveryExtractionOutput | DiscoveryExtractionExpectation


class DiscoveryExtractionCorpus(VersionedSchema):
    provenance: Literal["synthetic"]
    cases: tuple[
        LocalEvalCase[DiscoveryExtractionInput, DiscoveryExtractionExpectation], ...
    ] = Field(min_length=1)


def _validate_fixture(raw: object, validated: object) -> None:
    """Reject unsupported versions and identity/time generated by schema defaults."""
    if isinstance(validated, BaseModel):
        assert isinstance(raw, dict)
        if isinstance(validated, VersionedSchema) and validated.schema_version != 1:
            raise ValueError("Unsupported discovery/extraction corpus version.")
        for name in type(validated).model_fields:
            value = getattr(validated, name)
            if (
                name
                in {
                    "source_id",
                    "product_id",
                    "listing_id",
                    "evidence_id",
                    "run_id",
                    "captured_at",
                    "created_at",
                }
                and value is not None
                and name not in raw
            ):
                raise ValueError(f"Fixtures require explicit {name}.")
            if name in raw and value is not None:
                _validate_fixture(raw[name], value)
    elif isinstance(validated, (tuple, list)):
        assert isinstance(raw, list)
        for original, value in zip(raw, validated, strict=True):
            _validate_fixture(original, value)


def discovery_extraction_cases(
    path: Path = CORPUS_PATH,
) -> tuple[
    LocalEvalCase[DiscoveryExtractionInput, DiscoveryExtractionExpectation], ...
]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    corpus = DiscoveryExtractionCorpus.model_validate(raw)
    _validate_fixture(raw, corpus)
    names = [c.name for c in corpus.cases]
    if len(names) != len(set(names)):
        raise ValueError("Case names must be unique.")

    for case in corpus.cases:
        stage = case.inputs.stage
        roots = {"dedupe": {"groups", "fuzzy_decisions"}}.get(stage, {stage})
        if any(
            rule.field.split(".")[0] not in roots
            for rule in case.expected_output.fields
        ):
            raise ValueError(f"{case.name}: criteria must address the selected stage.")
        if stage == "dedupe":
            if set(i for g in case.expected_output.groups for i in g) != {
                e.listing.listing_id for e in case.inputs.extractions
            }:
                raise ValueError("Expected groups must partition every input listing.")
        elif case.expected_output.groups:
            raise ValueError("Only dedupe cases accept expected groups.")
    return corpus.cases


def discovery_extraction_dataset() -> Dataset[
    DiscoveryExtractionInput, DiscoveryExtractionResult, EvalMetadata
]:
    from app.evals.discovery_extraction_scoring import DiscoveryExtractionEvaluator

    return Dataset(
        name="cartcart-discovery-extraction",
        cases=[
            Case[DiscoveryExtractionInput, DiscoveryExtractionResult, EvalMetadata](
                name=c.name,
                inputs=c.inputs,
                expected_output=c.expected_output,
                metadata=c.metadata,
            )
            for c in discovery_extraction_cases()
        ],
        evaluators=[DiscoveryExtractionEvaluator()],
    )


class FixtureSnapshotTools(SnapshotInterpretationTools):
    """In-memory read adapter; no database or provider fallback."""

    def __init__(self, request: ExtractionAgentInput) -> None:
        self._snapshots = {s.source_id: s for s in request.workbench_snapshots}
        self._allowed = set(request.snapshot_ids)
        self._remaining = 24
        self._max_text_chars = 4000
        self._activity = []
        self.observed_text = {}

    async def read(self, snapshot_id: str, *, start_char: int = 0,
                   focus: str | None = None) -> SnapshotReadResult:
        from app.schemas.ids import SourceId
        from app.agents.source_spans import source_span

        try:
            parsed = SourceId(snapshot_id)
        except (TypeError, ValueError):
            return SnapshotReadResult(
                status="invalid_request", gap="Invalid snapshot ID."
            )
        if parsed not in self._allowed or self._remaining <= 0:
            return SnapshotReadResult(
                status="gap", gap="Snapshot unavailable or read budget exhausted."
            )
        self._remaining -= 1
        snapshot = self._snapshots[parsed]
        text = snapshot.extracted_content.text if snapshot.extracted_content else None
        try:
            span = source_span(text, start=start_char, focus=focus,
                               limit=self._max_text_chars) if text else None
        except ValueError as exc:
            return SnapshotReadResult(status="invalid_request", gap=str(exc))
        bounded = span.text if span else None
        if bounded:
            self.observed_text.setdefault(parsed, []).append(bounded)
        self._activity.append(
            {"tool_name": "read_source_snapshot", "status": "fixture"}
        )
        return SnapshotReadResult(
            status="succeeded" if text else "gap",
            snapshot_id=parsed,
            title=snapshot.title,
            url=str(snapshot.url),
            provider_source_type=snapshot.source_type.value,
            extraction_status=snapshot.extraction_status,
            text=bounded,
            start_char=span.start if span else 0,
            total_characters=span.total_characters if span else 0,
            content_sha256=span.content_sha256 if span else None,
            text_truncated=text is not None and len(text) > len(bounded or ""),
            gap=None if text else "No readable fixture content.",
        )


@dataclass
class DiscoveryExtractionTask:
    settings: Settings
    discovery: LiveDiscoveryAgent
    deduplicator: DeterministicProductDeduplicator = field(
        default_factory=DeterministicProductDeduplicator
    )
    normalizer: ProductListingExtractor = field(default_factory=ProductListingExtractor)

    async def __call__(
        self, inputs: DiscoveryExtractionInput
    ) -> DiscoveryExtractionOutput:
        inputs = inputs.model_copy(deep=True)
        if inputs.discovery is not None:
            return DiscoveryExtractionOutput(
                discovery=await self.discovery.run(inputs.discovery)
            )
        if inputs.quality is not None:
            return DiscoveryExtractionOutput(
                quality=score_source_quality(
                    str(inputs.quality.url), inputs.quality.metadata
                )
            )
        if inputs.extraction is not None:
            fixture = inputs.extraction
            if fixture.normalization:
                result = self.normalizer.extract_source_snapshot(
                    fixture.request.workbench_snapshots[0]
                )
                return DiscoveryExtractionOutput(
                    extraction=ExtractionAgentOutput(
                        products=(result.product,), listings=(result.listing,)
                    )
                )
            assert fixture.model_output is not None
            agent = LiveExtractionAgent(
                settings=self.settings,
                snapshot_tools_factory=FixtureSnapshotTools,
                model_runner=MockExtractionModelRunner(output=fixture.model_output),
            )
            return DiscoveryExtractionOutput(
                extraction=await agent.run(fixture.request)
            )
        result = self.deduplicator.group(inputs.extractions)
        return DiscoveryExtractionOutput(
            groups=tuple(
                ProductGroup(
                    product=g.product,
                    listings=g.listings,
                    match_kinds=tuple(e.kind.value for e in g.match_evidence),
                )
                for g in result.groups
            ),
            fuzzy_decisions=result.fuzzy_decisions,
        )


def offline_discovery_extraction_task() -> DiscoveryExtractionTask:
    settings = Settings(
        _env_file=None,
        environment="test",
        live_agents_enabled=False,
        openai_api_key=None,
        openai_model="eval-mock-model",
        openai_run_profiles={},
        openai_agent_overrides={},
        openai_agent_tracing_enabled=False,
    )  # type: ignore[call-arg]
    return DiscoveryExtractionTask(
        settings=settings,
        discovery=LiveDiscoveryAgent(
            settings=settings, model_runner=MockDiscoveryModelRunner()
        ),
    )
