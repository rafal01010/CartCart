"""Local offline eval CLI with separately scoped regression suites."""

import argparse
from pathlib import Path

from app.evals.fixtures import EvalFixtureSearchProvider, EvalSearchInput
from app.evals.discovery_extraction import (
    discovery_extraction_dataset,
    offline_discovery_extraction_task,
)
from app.evals.intake_planning import (
    intake_planning_dataset,
    offline_intake_planning_task,
)
from app.evals.trust_recommendation import (
    offline_trust_recommendation_task,
    trust_recommendation_dataset,
)
from app.evals.runner import DEFAULT_OUTPUT_DIR, run_local_evaluation
from app.evals.source_intelligence import (
    offline_source_intelligence_task,
    source_intelligence_dataset,
)
from app.evals.scaffolding import SMOKE_FIXTURE_PATH, smoke_dataset
from app.evals.suites import run_suite


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--suite",
        choices=(
            "quick",
            "full",
            "scaffolding",
            "intake-planning",
            "discovery-extraction",
            "trust-recommendation",
            "source-intelligence",
        ),
        default="scaffolding",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)
    output_dir = args.output_dir.expanduser().resolve()
    if args.suite in ("quick", "full"):
        path, passed = run_suite(args.suite, output_dir, run_local_evaluation)
        print(
            f"Offline {args.suite} eval {'passed' if passed else 'failed'}. Local suite report: {path}"
        )
        return 0 if passed else 1
    if args.suite == "source-intelligence":
        source_task = offline_source_intelligence_task()
        path, passed = run_local_evaluation(
            source_intelligence_dataset(), source_task.__call__, output_dir
        )
        print(
            f"Offline reusable source intelligence eval {'passed' if passed else 'failed'}. Local report: {path}"
        )
        return 0 if passed else 1
    if args.suite == "trust-recommendation":
        trust_task = offline_trust_recommendation_task()
        path, passed = run_local_evaluation(
            trust_recommendation_dataset(), trust_task.__call__, output_dir
        )
        print(
            f"Offline trust/guardrail/recommendation eval {'passed' if passed else 'failed'}. Local report: {path}"
        )
        return 0 if passed else 1
    if args.suite == "discovery-extraction":
        discovery_task = offline_discovery_extraction_task()
        path, passed = run_local_evaluation(
            discovery_extraction_dataset(), discovery_task.__call__, output_dir
        )
        print(
            f"Offline discovery/extraction/dedupe eval {'passed' if passed else 'failed'}. Local report: {path}"
        )
        return 0 if passed else 1
    if args.suite == "intake-planning":
        task = offline_intake_planning_task()
        path, passed = run_local_evaluation(
            intake_planning_dataset(), task.__call__, output_dir
        )
        print(
            f"Offline mocked intake/planning eval {'passed' if passed else 'failed'}. Local report: {path}"
        )
        return 0 if passed else 1
    provider = EvalFixtureSearchProvider.from_file(SMOKE_FIXTURE_PATH)

    async def fixture_search(inputs: EvalSearchInput) -> tuple[str, ...]:
        results = await provider.search(inputs.query, inputs.options)
        return tuple(str(result.url) for result in results)

    path, passed = run_local_evaluation(smoke_dataset(), fixture_search, output_dir)
    print(f"Scaffolding eval {'passed' if passed else 'failed'}. Local report: {path}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
