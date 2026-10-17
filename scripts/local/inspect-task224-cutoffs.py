import ast
import asyncio
import importlib.metadata
import json
import sys
from collections import defaultdict
from pathlib import Path

import httpx
from agents import AgentOutputSchema, ModelSettings
from agents.models.interface import ModelTracing
from agents.models.openai_responses import OpenAIResponsesModel
from openai import AsyncOpenAI
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps/backend"))


class ProbeOutput(BaseModel):
    answer: str


def calls_with_context(path):
    from app.agents.token_policy import scaled_tokens

    source = path.read_text()
    tree = ast.parse(source)
    constants = {
        target.id: node.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    result = []

    def cap_value(value):
        if isinstance(value, ast.Constant) and isinstance(value.value, int):
            return value.value
        if isinstance(value, ast.Name) and value.id in constants:
            return cap_value(constants[value.id])
        if (
            isinstance(value, ast.Call)
            and ast.unparse(value.func) == "scaled_tokens"
            and len(value.args) == 1
            and isinstance(value.args[0], ast.Constant)
        ):
            return scaled_tokens(value.args[0].value)
        return None

    def walk(node, scope=()):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            scope = (*scope, node.name)
        if isinstance(node, ast.Call):
            for keyword in node.keywords:
                if keyword.arg == "max_tokens":
                    expression = ast.unparse(keyword.value)
                    cap = cap_value(keyword.value)
                    result.append(
                        {
                            "line": node.lineno,
                            "context": ".".join(scope),
                            "expression": expression,
                            "cap": cap,
                        }
                    )
        for child in ast.iter_child_nodes(node):
            walk(child, scope)

    walk(tree)
    return result


def inventory():
    baseline = json.loads(
        (ROOT / "data/artifacts/task222/consumer-census.json").read_text()
    )
    current = defaultdict(list)
    paths = sorted({row["path"] for row in baseline["consumers"]})
    for path in paths:
        for row in calls_with_context(ROOT / path):
            current[(path, row["context"])].append(row)
    rows = []
    for before in baseline["consumers"]:
        key = (before["path"], before["context"])
        matches = current[key]
        index = next(
            (
                i
                for i, candidate in enumerate(matches)
                if candidate["expression"] == before["expression"]
            ),
            0,
        )
        assert matches, key
        after = matches.pop(index)
        rows.append(
            {
                "path": before["path"],
                "context": before["context"],
                "task222_cap": before["approved"],
                **after,
                "changed_since_task222": after["cap"] != before["approved"],
                "within_global_ceiling": after["cap"] is not None
                and after["cap"] <= 6667,
                "transport": "BoundedRunner/BudgetedProvider/BudgetedModel",
                "streaming": "BudgetedModel refuses streaming before a request",
            }
        )
    assert len(rows) == baseline["construction_count"] == 44
    assert not any(current.values()), current
    assert all(row["within_global_ceiling"] for row in rows)
    wrappers = []
    direct = []
    for path in sorted((ROOT / "apps/backend/app").rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            called = ast.unparse(node.func)
            if called in {"BoundedRunner.run", "Runner.run", "Runner.run_streamed"}:
                record = {
                    "path": str(path.relative_to(ROOT)),
                    "line": node.lineno,
                    "call": called,
                }
                (wrappers if called == "BoundedRunner.run" else direct).append(record)
    return rows, wrappers, direct


def module_controls(paths):
    result = []
    for path in sorted(paths):
        source = (ROOT / path).read_text()
        tree = ast.parse(source)
        result.append(
            {
                "path": path,
                "output_contracts": sorted(
                    {
                        ast.unparse(keyword.value)
                        for node in ast.walk(tree)
                        if isinstance(node, ast.Call)
                        for keyword in node.keywords
                        if keyword.arg == "output_type"
                    }
                ),
                "exception_handlers": [
                    {
                        "line": node.lineno,
                        "type": ast.unparse(node.type) if node.type else "BaseException",
                    }
                    for node in ast.walk(tree)
                    if isinstance(node, ast.ExceptHandler)
                ],
                "failure_and_fallback_labels": sorted(
                    {
                        node.value
                        for node in ast.walk(tree)
                        if isinstance(node, ast.Constant)
                        and isinstance(node.value, str)
                        and len(node.value) < 100
                        and any(
                            word in node.value
                            for word in ("fallback", "failed", "failure", "unavailable", "budget_limited")
                        )
                    }
                ),
            }
        )
    return result


def saved_failure_evidence():
    base = ROOT / "data/artifacts/task221/resume-20261016"
    evidence = []
    for name in ("phone-attempt1-inspection.json", "phone-attempt2-inspection.json"):
        document = json.loads((base / name).read_text())
        seen = set()

        def walk(value):
            if isinstance(value, dict):
                error = value.get("error_message")
                if isinstance(error, str) and error.startswith("Invalid JSON when parsing ") and error not in seen:
                    seen.add(error)
                    evidence.append(
                        {
                            "artifact": str((base / name).relative_to(ROOT)),
                            "shape": "eof" if "EOF while parsing" in error else "tool_shaped_text_with_prose",
                            "exception": "ModelBehaviorError",
                            "original_error": error,
                            "provider_response_envelope_available": False,
                            "reasoning_token_split_available": False,
                        }
                    )
                for item in value.values():
                    walk(item)
            elif isinstance(value, list):
                for item in value:
                    walk(item)

        walk(document)
    transport = json.loads((base / "phone-attempt2-transport.json").read_text())
    cutoff_calls = [
        {
            "agent": row.get("input", {}).get("agent"),
            "status": row.get("status"),
            "output_tokens": row.get("output", {}).get("actual_output_tokens"),
            "output_limit": row.get("output", {}).get("output_limit"),
            "actual_input_tokens": row.get("output", {}).get("actual_input_tokens"),
            "charged_tokens": row.get("output", {}).get("charged_tokens"),
        }
        for row in transport["new_context_calls"]
        if row.get("output", {}).get("actual_output_tokens") == row.get("output", {}).get("output_limit")
        and row.get("output", {}).get("output_limit") is not None
    ]
    return {"validation_failures": evidence, "retry_calls_at_output_cap": cutoff_calls}


async def sdk_probe(name, *, status, output, reasoning_tokens=None):
    seen = []
    payload = {
        "id": "resp_task224_offline",
        "object": "response",
        "created_at": 0,
        "status": status,
        "error": None,
        "incomplete_details": {"reason": "max_output_tokens"}
        if status == "incomplete"
        else None,
        "instructions": None,
        "max_output_tokens": 2000,
        "model": "gpt-6-luna",
        "output": output,
        "parallel_tool_calls": True,
        "tool_choice": "auto",
        "tools": [],
        "usage": {
            "input_tokens": 23,
            "output_tokens": 2000,
            "total_tokens": 2023,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": reasoning_tokens or 0},
        },
    }
    if reasoning_tokens is None:
        payload["usage"].pop("output_tokens_details")

    def respond(request):
        seen.append(
            {
                "method": request.method,
                "url": str(request.url),
                "max_output_tokens": json.loads(request.content).get(
                    "max_output_tokens"
                ),
            }
        )
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        client = AsyncOpenAI(
            api_key="offline-task224", base_url="https://offline.invalid/v1", http_client=http
        )
        model = OpenAIResponsesModel(model="gpt-6-luna", openai_client=client)
        response = await model.get_response(
            "Return the required JSON.",
            "offline cutoff probe",
            ModelSettings(max_tokens=2000),
            [],
            AgentOutputSchema(ProbeOutput),
            [],
            ModelTracing.DISABLED,
        )
        text = "".join(
            part.text
            for item in response.output
            for part in (getattr(item, "content", None) or ())
            if getattr(part, "type", None) == "output_text"
        )
        try:
            AgentOutputSchema(ProbeOutput).validate_json(text)
            validation = "accepted"
        except Exception as exc:
            validation = type(exc).__name__
        return {
            "case": name,
            "mock_requests": seen,
            "external_requests": 0,
            "response_envelope_status": status,
            "response_envelope_incomplete_reason": payload["incomplete_details"],
            "sdk_retains_envelope_status": hasattr(response, "status"),
            "sdk_retains_incomplete_details": hasattr(response, "incomplete_details"),
            "sdk_output_types": [item.type for item in response.output],
            "sdk_message_statuses": [
                item.status for item in response.output if item.type == "message"
            ],
            "sdk_schema_validation": validation,
            "actual_local_usage": {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
                "total_tokens": response.usage.total_tokens,
                "reasoning_tokens": response.usage.output_tokens_details.reasoning_tokens,
            },
            "reasoning_detail_supplied_by_local_control": reasoning_tokens is not None,
            "sdk_default_is_not_provider_detail": reasoning_tokens is None,
            "reasoning_tokens_are_not_live_measurements": True,
        }


def message(text, status):
    return {
        "type": "message",
        "id": "msg_task224",
        "role": "assistant",
        "status": status,
        "content": [{"type": "output_text", "text": text, "annotations": []}],
    }


async def main():
    rows, wrappers, direct = inventory()
    probes = []
    for name, status, output, reasoning in (
        ("truncated_json", "incomplete", [message('{"answer":"cut off', "incomplete")], 1930),
        ("incomplete_envelope_with_completed_valid_message", "incomplete", [message('{"answer":"valid"}', "completed")], 1900),
        ("incomplete_reasoning_only", "incomplete", [{"type": "reasoning", "id": "rs_task224", "summary": [], "status": "incomplete"}], 2000),
        ("incomplete_empty_output", "incomplete", [], 2000),
        ("complete_valid_at_cap", "completed", [message('{"answer":"valid"}', "completed")], 1900),
        ("completed_envelope_in_progress_message", "completed", [message('{"answer":"valid"}', "in_progress")], 1900),
        ("completed_without_reasoning_detail", "completed", [message('{"answer":"valid"}', "completed")], None),
    ):
        probes.append(await sdk_probe(name, status=status, output=output, reasoning_tokens=reasoning))
    report = {
        "scope": "Task 224 focused retained-path cutoff audit. No Task 222/223 gate or paid call.",
        "proof_labels": {
            "consumer_inventory": "measured from current AST against the saved Task 222 census",
            "live_wrapper_coverage": "static AST call-site inventory, not a paid execution claim",
            "raw_sdk_controls": "measured through installed SDKs and local httpx.MockTransport",
            "saved_failure_evidence": "read from immutable saved evidence, provider envelope unavailable",
            "recovery_acceptance": "outside this script; requires focused Task 224 finalization tests",
        },
        "baseline_inventory": "data/artifacts/task222/consumer-census.json",
        "baseline_review": "docs/TASK_222_TOKEN_ALLOWANCE_REVIEW.md",
        "sdk_versions": {name: importlib.metadata.version(name) for name in ("openai", "openai-agents")},
        "construction_count": len(rows),
        "file_count": len({row["path"] for row in rows}),
        "consumers": rows,
        "module_controls": module_controls({row["path"] for row in rows}),
        "saved_failure_evidence": saved_failure_evidence(),
        "bounded_live_runner_wrappers": wrappers,
        "direct_sdk_runner_sites": direct,
        "unbounded_site_assessment": "context_management.py is the shared bounded dispatch. workbench.py is _WorkbenchOwnerHandoffRunner with explicit offline fixture models, not a retained live provider bypass.",
        "unsupported_transport_recommendation": "BudgetedProvider must explicitly reject OpenAIChatCompletionsModel and unsupported OpenAIResponsesModel subclasses before a request because their incomplete envelope or finish_reason is lost. Exact OpenAIResponsesModel uses the bounded envelope adapter. Generic injected local Model controls remain supported for offline behavior tests.",
        "raw_sdk_controls": probes,
        "limits_of_proof": [
            "Actual installed OpenAI SDK performs HTTP parsing and Agents SDK response conversion against local MockTransport payloads.",
            "Payloads are deliberate offline controls. They prove conversion and validation behavior, not live provider output quality or the saved response envelope, which was not retained.",
            "The saved retry reports output 2000 at its 2000 cap plus EOF. Its reasoning split and original provider envelope are unavailable.",
            "No sampled output-cap increase can guarantee a live result. Every retained role still needs explicit cutoff rejection.",
        ],
    }
    target = ROOT / "data/artifacts/task224/output-cutoff-audit.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, default=str) + "\n")
    print(json.dumps({"artifact": str(target.relative_to(ROOT)), "consumers": len(rows), "files": report["file_count"], "sdk_controls": len(probes), "external_requests": 0}))


if __name__ == "__main__":
    asyncio.run(main())
