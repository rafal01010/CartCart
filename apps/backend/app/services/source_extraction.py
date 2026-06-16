from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from trafilatura import bare_extraction

from app.schemas.search_sources import (
    ExtractedPageContent,
    ExtractionStatus,
    SourceSnapshot,
    SourceType,
)


class StaticPageExtractionError(RuntimeError):
    """Raised when a stored source artifact cannot be read safely."""


class ExtractionDecisionAction(StrEnum):
    RUN_STATIC = "run_static"
    ACCEPT_STATIC = "accept_static"
    TRY_DYNAMIC = "try_dynamic"
    STOP = "stop"


class ExtractionDecisionReason(StrEnum):
    STATIC_NOT_ATTEMPTED = "static_not_attempted"
    STATIC_SUFFICIENT = "static_sufficient"
    STATIC_FAILED = "static_failed"
    STATIC_PARTIAL = "static_partial"
    STATIC_TOO_SPARSE = "static_too_sparse"
    SOURCE_EXCLUDED = "source_excluded"
    SOURCE_NOT_HTML_PAGE = "source_not_html_page"


@dataclass(frozen=True)
class ExtractionDecision:
    action: ExtractionDecisionAction
    reason: ExtractionDecisionReason
    dynamic_fallback_optional: bool = True
    uses_dynamic_fallback: bool = False


class DynamicExtractionPolicy:
    """Choose an extraction path without invoking a browser or provider."""

    _NON_PAGE_SOURCE_TYPES = frozenset({SourceType.SEARCH_RESULT, SourceType.VIDEO})

    def __init__(
        self,
        *,
        dynamic_fallback_enabled: bool = False,
        minimum_static_word_count: int = 50,
    ) -> None:
        if minimum_static_word_count <= 0:
            raise ValueError("Minimum static word count must be greater than zero.")
        self._dynamic_fallback_enabled = dynamic_fallback_enabled
        self._minimum_static_word_count = minimum_static_word_count

    def decide(self, snapshot: SourceSnapshot) -> ExtractionDecision:
        if snapshot.extraction_status == ExtractionStatus.EXCLUDED:
            return ExtractionDecision(
                action=ExtractionDecisionAction.STOP,
                reason=ExtractionDecisionReason.SOURCE_EXCLUDED,
            )
        if snapshot.source_type in self._NON_PAGE_SOURCE_TYPES:
            return ExtractionDecision(
                action=ExtractionDecisionAction.STOP,
                reason=ExtractionDecisionReason.SOURCE_NOT_HTML_PAGE,
            )
        if snapshot.extraction_status == ExtractionStatus.NOT_ATTEMPTED:
            return ExtractionDecision(
                action=ExtractionDecisionAction.RUN_STATIC,
                reason=ExtractionDecisionReason.STATIC_NOT_ATTEMPTED,
            )

        fallback_reason = self._dynamic_fallback_reason(snapshot)
        if fallback_reason is None:
            return ExtractionDecision(
                action=ExtractionDecisionAction.ACCEPT_STATIC,
                reason=ExtractionDecisionReason.STATIC_SUFFICIENT,
            )
        if self._dynamic_fallback_enabled:
            return ExtractionDecision(
                action=ExtractionDecisionAction.TRY_DYNAMIC,
                reason=fallback_reason,
                uses_dynamic_fallback=True,
            )
        return ExtractionDecision(
            action=ExtractionDecisionAction.STOP,
            reason=fallback_reason,
        )

    def _dynamic_fallback_reason(
        self,
        snapshot: SourceSnapshot,
    ) -> ExtractionDecisionReason | None:
        if snapshot.extraction_status == ExtractionStatus.FAILED:
            return ExtractionDecisionReason.STATIC_FAILED
        if snapshot.extraction_status == ExtractionStatus.PARTIAL:
            return ExtractionDecisionReason.STATIC_PARTIAL
        if snapshot.extracted_content is None:
            return ExtractionDecisionReason.STATIC_FAILED
        if snapshot.extracted_content.word_count < self._minimum_static_word_count:
            return ExtractionDecisionReason.STATIC_TOO_SPARSE
        return None


class StaticPageTextExtractor:
    extractor_name = "trafilatura"

    def __init__(self, *, snapshot_dir: Path) -> None:
        self._snapshot_dir = snapshot_dir.resolve()

    def extract(self, snapshot: SourceSnapshot) -> SourceSnapshot:
        artifact_path = self._artifact_path(snapshot)
        try:
            html = artifact_path.read_bytes()
        except OSError as exc:
            raise StaticPageExtractionError(
                "Stored source artifact could not be read."
            ) from exc

        document = bare_extraction(
            html,
            url=str(snapshot.url),
            with_metadata=True,
            include_comments=False,
            include_tables=True,
            favor_precision=True,
        )
        extracted = snapshot.model_copy(deep=True)
        if document is None:
            extracted.extraction_status = ExtractionStatus.FAILED
            extracted.extracted_content = None
            return extracted

        data = document.as_dict()
        text = _clean_optional_text(data.get("text"))
        if text is None:
            extracted.extraction_status = ExtractionStatus.FAILED
            extracted.extracted_content = None
            return extracted

        title = _clean_optional_text(data.get("title"))
        if title is not None:
            extracted.title = title[:300]
        extracted.extracted_content = ExtractedPageContent(
            text=text,
            extractor=self.extractor_name,
            author=_bounded_optional_text(data.get("author"), 500),
            description=_bounded_optional_text(data.get("description"), 2000),
            site_name=_bounded_optional_text(data.get("sitename"), 300),
            published_date=_bounded_optional_text(data.get("date"), 35),
            language=_bounded_optional_text(data.get("language"), 35),
            word_count=len(text.split()),
        )
        extracted.extraction_status = ExtractionStatus.SUCCEEDED
        return extracted

    def _artifact_path(self, snapshot: SourceSnapshot) -> Path:
        if snapshot.raw_artifact is None:
            raise StaticPageExtractionError(
                "Static extraction requires a stored source artifact."
            )

        artifact_path = (self._snapshot_dir / snapshot.raw_artifact.path).resolve()
        if not artifact_path.is_relative_to(self._snapshot_dir):
            raise StaticPageExtractionError(
                "Stored source artifact path is outside the snapshot directory."
            )
        return artifact_path


def _clean_optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _bounded_optional_text(value: object, max_length: int) -> str | None:
    cleaned = _clean_optional_text(value)
    return cleaned[:max_length] if cleaned is not None else None
