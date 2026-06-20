import argparse
import asyncio
import json
import sys
from typing import Any

from app.agents.workbench import (
    AgentWorkbenchError,
    AgentWorkbenchMode,
    AgentWorkbenchRunRequest,
    AgentWorkbenchRunner,
)
from app.core.settings import Settings, get_settings


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run one allowlisted CartCart agent workbench scenario.",
    )
    parser.add_argument("--agent", required=True, help="Allowlisted agent name.")
    parser.add_argument("--scenario", required=True, help="Registered scenario name.")
    parser.add_argument(
        "--mode",
        choices=[mode.value for mode in AgentWorkbenchMode],
        default=AgentWorkbenchMode.FIXTURE.value,
        help="Run mode. Live mode requires explicit live-agent configuration.",
    )
    parser.add_argument(
        "--input-json",
        help="Optional complete JSON input override validated against the agent input schema.",
    )

    args = parser.parse_args()
    try:
        input_override = _parse_input_override(args.input_json)
        request = AgentWorkbenchRunRequest(
            agent_name=args.agent,
            scenario_name=args.scenario,
            mode=AgentWorkbenchMode(args.mode),
            input=input_override,
        )
        result = asyncio.run(_run(request, get_settings()))
    except AgentWorkbenchError as exc:
        _write_json(
            {
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                }
            },
            stream=sys.stderr,
        )
        return 2
    except ValueError as exc:
        _write_json(
            {
                "error": {
                    "code": "agent_workbench_invalid_cli_input",
                    "message": str(exc),
                }
            },
            stream=sys.stderr,
        )
        return 2

    _write_json(result.model_dump(mode="json", exclude_none=True))
    return 0


async def _run(
    request: AgentWorkbenchRunRequest,
    settings: Settings,
) -> Any:
    return await AgentWorkbenchRunner(settings).run(request)


def _parse_input_override(input_json: str | None) -> dict[str, Any] | None:
    if input_json is None:
        return None
    try:
        value = json.loads(input_json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"--input-json must be valid JSON: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise ValueError("--input-json must decode to a JSON object.")
    return value


def _write_json(payload: Any, *, stream: Any = sys.stdout) -> None:
    stream.write(json.dumps(payload, indent=2, sort_keys=True))
    stream.write("\n")


if __name__ == "__main__":
    raise SystemExit(main())
