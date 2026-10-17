from typing import Literal

from pydantic import Field

from app.schemas.base import CartCartBaseModel
from app.schemas.ids import SourceId
from app.schemas.search_sources import SourceEvidence, SourceQuality, VideoTranscriptSupport


class CandidateSourceCoverage(CartCartBaseModel):
    candidate_name: str
    source_ids: tuple[SourceId, ...]
    buying_questions: tuple[str, ...] = ()
    support_kind: Literal["page", "accepted_speech", "source_note"]


class CandidateCoverageNote(CartCartBaseModel):
    candidate_names: tuple[str, ...]
    buying_question: str
    finding: str
    quote: str
    evidence_id: SourceId
    perspective: str | None = None


class DecisionSourcePacket(CartCartBaseModel):
    source_id: SourceId
    equivalent_source_ids: tuple[SourceId, ...] = ()
    url: str
    title: str
    content_kind: Literal["page", "accepted_speech", "source_note", "search_lead", "metadata_only"]
    excerpts: tuple[str, ...] = ()
    source_notes: tuple[str, ...] = ()
    candidate_names: tuple[str, ...] = ()
    buying_questions: tuple[str, ...] = ()
    coverage_notes: tuple[CandidateCoverageNote, ...] = ()
    findings: tuple[str, ...] = ()
    perspective: str | None = None
    evidence_ids: tuple[SourceId, ...] = ()
    transcript_support: tuple[VideoTranscriptSupport, ...] = ()
    evidence: tuple[SourceEvidence, ...] = ()
    source_quality: SourceQuality | None = None
    original_content_size: dict[str, int] = Field(default_factory=dict)
    material_cautions: tuple[str, ...] = ()
    content_sha256: str
    unreviewed_content: bool = False


class SourceDecisionProjection(CartCartBaseModel):
    projection_id: str
    selected_source_ids: tuple[SourceId, ...]
    deferred_source_ids: tuple[SourceId, ...]
    candidate_coverage: tuple[CandidateSourceCoverage, ...] = ()
    sources: tuple[DecisionSourcePacket, ...] = ()
    measurements: dict[str, int | str | bool | dict[str, int]] = Field(default_factory=dict)
