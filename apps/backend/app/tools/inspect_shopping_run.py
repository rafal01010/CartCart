"""Read a saved run's runtime and agent activity without starting research."""

import argparse
import json
import sqlite3
from uuid import UUID

from app.core.settings import Settings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-id", type=UUID, help="Defaults to the most recent saved run."
    )
    args = parser.parse_args()
    path = Settings().resolved_database_path
    if not path.exists():
        parser.error("No local shopping database exists.")
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        run = connection.execute(
            "SELECT * FROM shopping_runs WHERE run_id = ?"
            if args.run_id
            else "SELECT * FROM shopping_runs ORDER BY created_at DESC LIMIT 1",
            (str(args.run_id),) if args.run_id else (),
        ).fetchone()
        if run is None:
            parser.error("No matching saved shopping run exists.")
        agents = []
        for row in connection.execute(
            "SELECT record FROM agent_run_records WHERE run_id = ? ORDER BY started_at",
            (run["run_id"],),
        ):
            record = json.loads(row["record"])
            agents.append(
                {
                    key: record.get(key)
                    for key in (
                        "agent_name",
                        "stage",
                        "status",
                        "runtime_mode",
                        "model_name",
                        "fallback_outcome",
                    )
                }
                | {
                    "tools": [
                        {
                            "name": item.get("tool_name"),
                            "status": item.get("status"),
                            **(
                                {
                                    "source_agent": item.get("input", {}).get(
                                        "source_agent"
                                    ),
                                    "target_agent": item.get("output", {}).get(
                                        "target_agent"
                                    ),
                                }
                                if item.get("tool_name") == "sdk_handoff"
                                else {}
                            ),
                            **(
                                {
                                    key: item.get("output", {}).get(key)
                                    for key in (
                                        "last_agent",
                                        "failure_type",
                                        "failure_code",
                                    )
                                }
                                if item.get("tool_name") == "general_owner"
                                else {}
                            ),
                            **(
                                {
                                    "failure_type": item.get("input", {}).get(
                                        "failure_type"
                                    )
                                }
                                if item.get("tool_name")
                                == "openai_agents_structured_output"
                                else {}
                            ),
                        }
                        for item in record.get("tool_activity", ())
                    ]
                }
            )
        print(
            json.dumps(
                {
                    "run_id": run["run_id"],
                    "session_id": run["session_id"],
                    "status": run["status"],
                    "current_stage": run["current_stage"],
                    "agents": agents,
                },
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
