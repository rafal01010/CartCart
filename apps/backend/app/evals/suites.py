"""Fixed offline regression subsets and quick-before-full suite orchestration."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic_evals import Dataset

from app.evals.discovery_extraction import (
    discovery_extraction_dataset,
    offline_discovery_extraction_task,
)
from app.evals.fixtures import EvalFixtureSearchProvider, EvalSearchInput
from app.evals.intake_planning import (
    intake_planning_dataset,
    offline_intake_planning_task,
)
from app.evals.runner import run_local_evaluation
from app.evals.scaffolding import SMOKE_FIXTURE_PATH, smoke_dataset
from app.evals.schemas import EvalMetadata
from app.evals.source_intelligence import (
    offline_source_intelligence_task,
    source_intelligence_dataset,
)
from app.evals.trust_recommendation import (
    offline_trust_recommendation_task,
    trust_recommendation_dataset,
)
from app.schemas.base import VersionedSchema

# Authored selection, never filtered by whether a case currently passes. Keep
# known failures: CI must catch these regressions rather than quietly skip them.
QUICK_CASES: dict[str, tuple[str, ...]] = {
    "scaffolding": ("scaffolding/fixture-search",),
    "intake-planning": (
        "guide/monitor-sequence",
        "guide/comparison-control",
        "intake/inferred-monitor-fields",
        "planning/unknown-category-fallback",
    ),
    "discovery-extraction": (
        "discovery/generic-shortlist",
        "quality/misleading-domain",
        "extraction/punctuated-price-fidelity",
        "dedupe/same-model-distinct-offers",
        "dedupe/uncertain-missing-specs",
    ),
    "trust-recommendation": (
        "guardrail/off-topic",
        "guardrail/unsafe-firearm",
        "trust/implausibly-cheap-offer",
        "recommendation/hard-cap",
        "recommendation/preferred-stretch",
        "recommendation/manual-only-no-buy",
        "recommendation/conflict-disclosure",
        "verification/unsupported-specification",
    ),
    "source-intelligence": (
        "youtube/transcript-bias",
        "youtube/invented-quote",
        "reddit/quoted-recurrence",
        "reddit/inaccessible",
        "amazon/marketplace-seller-region",
        "amazon/retained-hard-risk",
        "ikea/official-ph-read",
        "ikea/invented-price",
        "downstream/amazon-unsupported",
    ),
}

Task = Callable[[Any], Awaitable[Any]]
DatasetFactory = Callable[[], Dataset[Any, Any, EvalMetadata]]
TaskFactory = Callable[[], Task]
EvaluationRunner = Callable[
    [Dataset[Any, Any, EvalMetadata], Task, Path], tuple[Path, bool]
]


async def _fixture_search(inputs: EvalSearchInput) -> tuple[str, ...]:
    provider = EvalFixtureSearchProvider.from_file(SMOKE_FIXTURE_PATH)
    results = await provider.search(inputs.query, inputs.options)
    return tuple(str(result.url) for result in results)


@dataclass(frozen=True)
class Lane:
    name: str
    dataset: DatasetFactory
    task: TaskFactory


LANES = (
    Lane("scaffolding", smoke_dataset, lambda: _fixture_search),
    Lane(
        "intake-planning",
        intake_planning_dataset,
        lambda: offline_intake_planning_task().__call__,
    ),
    Lane(
        "discovery-extraction",
        discovery_extraction_dataset,
        lambda: offline_discovery_extraction_task().__call__,
    ),
    Lane(
        "trust-recommendation",
        trust_recommendation_dataset,
        lambda: offline_trust_recommendation_task().__call__,
    ),
    Lane(
        "source-intelligence",
        source_intelligence_dataset,
        lambda: offline_source_intelligence_task().__call__,
    ),
)


class LaneReport(VersionedSchema):
    lane: str
    phase: Literal["quick", "full"]
    case_names: tuple[str, ...]
    report_path: Path
    passed: bool


class SuiteReport(VersionedSchema):
    suite: Literal["quick", "full"]
    execution_mode: Literal["fixture"] = "fixture"
    recorded_at: datetime
    passed: bool
    lanes: tuple[LaneReport, ...]


def select_dataset(lane: Lane, phase: Literal["quick", "full"]) -> Dataset:
    """Preserve lane evaluators and case expectations; reject stale selections."""
    dataset = lane.dataset()
    if any(case.name is None for case in dataset.cases):
        raise ValueError(f"Unnamed case in {lane.name}.")
    if phase == "full":
        return dataset
    selected = QUICK_CASES[lane.name]
    by_name = {case.name: case for case in dataset.cases}
    if len(by_name) != len(dataset.cases) or len(selected) != len(set(selected)):
        raise ValueError(f"Duplicate case names in {lane.name}.")
    missing = set(selected) - by_name.keys()
    if missing or not selected:
        raise ValueError(f"Invalid quick selection for {lane.name}: {sorted(missing)}")
    dataset.cases = [by_name[name] for name in selected]
    dataset.name += "-quick"
    return dataset


def run_suite(
    suite: Literal["quick", "full"],
    output_dir: Path,
    runner: EvaluationRunner = run_local_evaluation,
) -> tuple[Path, bool]:
    """Full includes quick first, then all lanes for complete failure diagnostics."""
    reports: list[LaneReport] = []
    phases: tuple[Literal["quick", "full"], ...] = (
        ("quick",) if suite == "quick" else ("quick", "full")
    )
    for phase in phases:
        for lane in LANES:
            dataset = select_dataset(lane, phase)
            path, passed = runner(dataset, lane.task(), output_dir)
            reports.append(
                LaneReport(
                    lane=lane.name,
                    phase=phase,
                    case_names=tuple(
                        case.name for case in dataset.cases if case.name is not None
                    ),
                    report_path=path,
                    passed=passed,
                )
            )
    recorded_at = datetime.now(timezone.utc)
    passed = bool(reports) and all(report.passed for report in reports)
    saved = SuiteReport(
        suite=suite, recorded_at=recorded_at, passed=passed, lanes=tuple(reports)
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"suite-{suite}-{recorded_at.strftime('%Y%m%dT%H%M%S%fZ')}.json"
    with path.open("x", encoding="utf-8") as file:
        file.write(saved.model_dump_json(indent=2) + "\n")
    return path, passed
