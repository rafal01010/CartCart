"""Execute local deterministic tasks and retain the complete Pydantic report."""

from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from typing import Generic, Literal

from pydantic_evals import Dataset
from pydantic_evals.reporting import EvaluationReport

from app.evals.schemas import EvalMetadata, InputsT, OutputT
from app.schemas.base import VersionedSchema

DEFAULT_OUTPUT_DIR = (
    Path(__file__).resolve().parents[4] / "data" / "artifacts" / "evals"
)


class LocalEvalReport(VersionedSchema, Generic[InputsT, OutputT]):
    recorded_at: datetime
    execution_mode: Literal["fixture"] = "fixture"
    framework_version: str
    passed: bool
    report: EvaluationReport[InputsT, OutputT, EvalMetadata]


def report_passed(report: EvaluationReport[InputsT, OutputT, EvalMetadata]) -> bool:
    return bool(report.cases) and not (
        report.failures
        or report.report_evaluator_failures
        or any(
            case.evaluator_failures
            or not case.assertions
            or any(not assertion.value for assertion in case.assertions.values())
            for case in report.cases
        )
    )


def run_local_evaluation(
    dataset: Dataset[InputsT, OutputT, EvalMetadata],
    task: Callable[[InputsT], OutputT] | Callable[[InputsT], Awaitable[OutputT]],
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> tuple[Path, bool]:
    report = dataset.evaluate_sync(
        task, name=dataset.name, max_concurrency=1, progress=False
    )
    passed = report_passed(report)
    recorded_at = datetime.now(timezone.utc)
    saved = LocalEvalReport[InputsT, OutputT](
        recorded_at=recorded_at,
        framework_version=version("pydantic-evals"),
        passed=passed,
        report=report,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"eval-{recorded_at.strftime('%Y%m%dT%H%M%S%fZ')}.json"
    with path.open("x", encoding="utf-8") as file:
        file.write(saved.model_dump_json(indent=2) + "\n")
    return path, passed
