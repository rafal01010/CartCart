import re
from dataclasses import dataclass
from enum import StrEnum

from app.schemas.confidence import Confidence, ConfidenceLevel
from app.schemas.products import CanonicalProduct, ProductListing
from app.schemas.search_sources import (
    ConflictSeverity,
    EvidenceConflict,
    EvidenceTarget,
    EvidenceTargetType,
    EvidenceType,
    ExtractionStatus,
    SourceEvidence,
    SourceQualityLevel,
    SourceSnapshot,
)


class SourceEvidenceCreationError(ValueError):
    """Raised when extracted claims cannot be linked to their source."""


@dataclass(frozen=True)
class SourceEvidenceInput:
    snapshot: SourceSnapshot
    product: CanonicalProduct | None = None
    listing: ProductListing | None = None


@dataclass(frozen=True)
class SourceEvidenceCreationResult:
    evidence: tuple[SourceEvidence, ...]
    conflicts: tuple[EvidenceConflict, ...]


class _TargetKind(StrEnum):
    PRODUCT = "product"
    LISTING = "listing"


@dataclass(frozen=True)
class _FactRule:
    fact_key: str
    labels: tuple[str, ...]
    evidence_type: EvidenceType
    target_kind: _TargetKind


@dataclass(frozen=True)
class _CreatedFact:
    fact_key: str
    normalized_value: str
    evidence: SourceEvidence


_FACT_RULES = (
    _FactRule(
        fact_key="brand",
        labels=("brand", "manufacturer"),
        evidence_type=EvidenceType.PRODUCT_SPEC,
        target_kind=_TargetKind.PRODUCT,
    ),
    _FactRule(
        fact_key="model",
        labels=("model", "model number"),
        evidence_type=EvidenceType.PRODUCT_SPEC,
        target_kind=_TargetKind.PRODUCT,
    ),
    _FactRule(
        fact_key="warranty",
        labels=("warranty", "limited warranty"),
        evidence_type=EvidenceType.WARRANTY,
        target_kind=_TargetKind.PRODUCT,
    ),
    _FactRule(
        fact_key="review verdict",
        labels=("review verdict", "review signal", "verdict"),
        evidence_type=EvidenceType.REVIEW_CLAIM,
        target_kind=_TargetKind.PRODUCT,
    ),
    _FactRule(
        fact_key="price",
        labels=("price", "sale price", "current price"),
        evidence_type=EvidenceType.PRICE,
        target_kind=_TargetKind.LISTING,
    ),
    _FactRule(
        fact_key="seller",
        labels=("sold by", "seller", "store", "retailer"),
        evidence_type=EvidenceType.LISTING_IDENTITY,
        target_kind=_TargetKind.LISTING,
    ),
    _FactRule(
        fact_key="region",
        labels=("region", "available in", "ships to", "country"),
        evidence_type=EvidenceType.REGION_AVAILABILITY,
        target_kind=_TargetKind.LISTING,
    ),
    _FactRule(
        fact_key="availability",
        labels=("availability", "stock status"),
        evidence_type=EvidenceType.AVAILABILITY,
        target_kind=_TargetKind.LISTING,
    ),
)
_MANUFACTURER_WARRANTY = re.compile(
    r"(?i)\b(?:the\s+)?manufacturer\s+"
    r"(?:lists|states|provides|offers)\s+"
    r"(?P<value>[^.!?\n]{1,180}\bwarranty)\s*[.!?]"
)


class SourceEvidenceCreator:
    """Create deterministic evidence and conflicts from extracted page facts."""

    def create(
        self,
        inputs: tuple[SourceEvidenceInput, ...],
    ) -> SourceEvidenceCreationResult:
        created: list[_CreatedFact] = []
        for item in inputs:
            self._validate_input(item)
            created.extend(self._create_facts(item))

        evidence = tuple(fact.evidence for fact in created)
        return SourceEvidenceCreationResult(
            evidence=evidence,
            conflicts=_find_conflicts(created),
        )

    def _validate_input(self, item: SourceEvidenceInput) -> None:
        snapshot = item.snapshot
        if snapshot.extracted_content is None or snapshot.extraction_status not in {
            ExtractionStatus.SUCCEEDED,
            ExtractionStatus.PARTIAL,
        }:
            raise SourceEvidenceCreationError(
                "source evidence creation requires usable extracted content."
            )
        if item.product is None and item.listing is None:
            raise SourceEvidenceCreationError(
                "source evidence creation requires a product or listing target."
            )
        if item.product is not None and snapshot.source_id not in item.product.source_ids:
            raise SourceEvidenceCreationError(
                "product claims require the snapshot source ID on the product."
            )
        if item.listing is not None and snapshot.source_id not in item.listing.source_ids:
            raise SourceEvidenceCreationError(
                "listing claims require the snapshot source ID on the listing."
            )
        if (
            item.product is not None
            and item.listing is not None
            and item.product.product_id != item.listing.product_id
        ):
            raise SourceEvidenceCreationError(
                "product and listing evidence targets must identify the same product."
            )

    def _create_facts(self, item: SourceEvidenceInput) -> tuple[_CreatedFact, ...]:
        content = item.snapshot.extracted_content
        assert content is not None
        created: list[_CreatedFact] = []
        seen: set[tuple[str, str, EvidenceTargetType]] = set()

        for rule in _FACT_RULES:
            target = _target_for_rule(item, rule)
            if target is None:
                continue
            for label, value, claim in _labeled_facts(content.text, rule.labels):
                normalized_value = _normalize_value(value)
                dedupe_key = (rule.fact_key, normalized_value, target.target_type)
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                created.append(
                    _created_fact(
                        item.snapshot,
                        target,
                        rule.evidence_type,
                        rule.fact_key,
                        normalized_value,
                        f"{label}: {claim}",
                    )
                )

        if item.product is not None:
            target = EvidenceTarget(
                target_type=EvidenceTargetType.PRODUCT,
                product_id=item.product.product_id,
            )
            for match in _MANUFACTURER_WARRANTY.finditer(content.text):
                value = match.group("value").strip()
                normalized_value = _normalize_value(value)
                dedupe_key = (
                    "warranty",
                    normalized_value,
                    EvidenceTargetType.PRODUCT,
                )
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                created.append(
                    _created_fact(
                        item.snapshot,
                        target,
                        EvidenceType.WARRANTY,
                        "warranty",
                        normalized_value,
                        " ".join(match.group(0).split()),
                    )
                )

        return tuple(created)


def _target_for_rule(
    item: SourceEvidenceInput,
    rule: _FactRule,
) -> EvidenceTarget | None:
    if rule.target_kind == _TargetKind.PRODUCT and item.product is not None:
        return EvidenceTarget(
            target_type=EvidenceTargetType.PRODUCT,
            product_id=item.product.product_id,
        )
    if rule.target_kind == _TargetKind.LISTING and item.listing is not None:
        return EvidenceTarget(
            target_type=EvidenceTargetType.LISTING,
            listing_id=item.listing.listing_id,
        )
    return None


def _labeled_facts(
    text: str,
    labels: tuple[str, ...],
) -> tuple[tuple[str, str, str], ...]:
    label_pattern = "|".join(
        sorted((re.escape(label) for label in labels), key=len, reverse=True)
    )
    pattern = re.compile(
        rf"(?im)(?:^|\n)\s*(?P<label>{label_pattern})\s*:\s*"
        r"(?P<value>[^\n]{1,500})"
    )
    facts: list[tuple[str, str, str]] = []
    for match in pattern.finditer(text):
        value = match.group("value").strip()
        claim_value = value.rstrip().rstrip(".;")
        if claim_value:
            facts.append((match.group("label"), claim_value, claim_value))
    return tuple(facts)


def _created_fact(
    snapshot: SourceSnapshot,
    target: EvidenceTarget,
    evidence_type: EvidenceType,
    fact_key: str,
    normalized_value: str,
    claim: str,
) -> _CreatedFact:
    return _CreatedFact(
        fact_key=fact_key,
        normalized_value=normalized_value,
        evidence=SourceEvidence(
            source_id=snapshot.source_id,
            target=target,
            evidence_type=evidence_type,
            claim=claim,
            confidence=_confidence(snapshot),
            source_quality=snapshot.quality,
        ),
    )


def _confidence(snapshot: SourceSnapshot) -> Confidence:
    score_by_quality = {
        SourceQualityLevel.STRONG: 0.9,
        SourceQualityLevel.ADEQUATE: 0.78,
        SourceQualityLevel.MIXED: 0.62,
        SourceQualityLevel.WEAK: 0.4,
        SourceQualityLevel.UNKNOWN: 0.5,
    }
    score = score_by_quality[snapshot.quality.level]
    if snapshot.extraction_status == ExtractionStatus.PARTIAL:
        score = max(0.0, score - 0.1)
    level = (
        ConfidenceLevel.HIGH
        if score >= 0.75
        else ConfidenceLevel.MEDIUM
        if score >= 0.55
        else ConfidenceLevel.LOW
    )
    return Confidence(
        score=score,
        level=level,
        rationale="Deterministic fact extracted from source snapshot text.",
    )


def _normalize_value(value: str) -> str:
    return " ".join(value.casefold().strip().rstrip(".;").split())


def _find_conflicts(facts: list[_CreatedFact]) -> tuple[EvidenceConflict, ...]:
    groups: dict[tuple[object, ...], list[_CreatedFact]] = {}
    for fact in facts:
        target = fact.evidence.target
        key = (
            target.target_type,
            target.product_id,
            target.listing_id,
            fact.evidence.evidence_type,
            fact.fact_key,
        )
        groups.setdefault(key, []).append(fact)

    conflicts: list[EvidenceConflict] = []
    for group in groups.values():
        values = {fact.normalized_value for fact in group}
        if len(values) < 2:
            continue
        severity = _conflict_severity(group[0].evidence.evidence_type)
        claim_summary = " | ".join(
            f'"{fact.evidence.claim[:220]}"' for fact in group
        )
        summary = f"Conflicting {group[0].fact_key} evidence: {claim_summary}"
        conflicts.append(
            EvidenceConflict(
                evidence_ids=tuple(fact.evidence.evidence_id for fact in group),
                summary=summary[:1000],
                severity=severity,
                affects_decision=severity
                in {ConflictSeverity.HIGH, ConflictSeverity.MATERIAL},
            )
        )
    return tuple(conflicts)


def _conflict_severity(evidence_type: EvidenceType) -> ConflictSeverity:
    if evidence_type == EvidenceType.WARRANTY:
        return ConflictSeverity.MATERIAL
    if evidence_type in {
        EvidenceType.PRODUCT_SPEC,
        EvidenceType.AVAILABILITY,
        EvidenceType.REGION_AVAILABILITY,
        EvidenceType.LISTING_IDENTITY,
    }:
        return ConflictSeverity.HIGH
    return ConflictSeverity.MEDIUM
