import ast
import json
import subprocess
import sys
from types import ModuleType
from dataclasses import asdict
from pathlib import Path

import pytest
from agents import ModelSettings
from agents.models.interface import ModelTracing

from test_task222_budget_matrix import _LocalTransportModel, _Step, _native
from test_task222_source_sdk import _message

from app.agents.context_management import ContextLimits
from app.agents.catalog import DEFAULT_AGENT_CATALOG
from app.agents.openai_config import build_openai_agent_run_configuration
from app.agents.token_policy import (
    OWNER_START_TOKENS,
    SOURCE_START_TOKENS,
    scaled_tokens,
)
from app.core.settings import Settings


ROOT = Path(__file__).resolve().parents[3]
ARTIFACTS = ROOT / "data/artifacts/task222"


@pytest.mark.asyncio
async def test_committed_task221_transport_reproduces_captured_source_closure():
    historical = subprocess.check_output([
        "git", "show", "94d50d7:apps/backend/app/agents/context_management.py"
    ], cwd=ROOT).decode()
    module_name = "app.agents.task222_before_control"
    baseline = ModuleType(module_name)
    sys.modules[module_name] = baseline
    try:
        exec(compile(historical, module_name, "exec"), baseline.__dict__)
        root = baseline.ContextBudget(spent=49104)
        source = baseline.ContextBudget(limits=baseline.ContextLimits(total_tokens=30000), spent=7659)
        inspection = json.loads((ROOT / "data/artifacts/task221/phone3-inspection.json").read_text())
        model = _LocalTransportModel(_Step(_message({"selected_videos": [], "evidence_gaps": ["No retrieval attempted."]})))
        with baseline.context_scope(root):
            baseline._agent.set("YouTubeReviewIntelligenceAgent")
            baseline._allowances.set((source,))
            await baseline.BudgetedModel(model, root, "explicitly-local-before-control").get_response(
                "Return retrieved source evidence and accurate gaps.",
                json.dumps({"brief": inspection["brief"], "captured_search_candidates": 8}),
                ModelSettings(max_tokens=3000), [_native()], None, [], ModelTracing.DISABLED,
                previous_response_id=None, conversation_id=None, prompt=None,
            )
        event = root.events[0]
        assert event["output"]["owner_remaining_tokens"] == 22341
        assert event["output"]["shared_remaining_tokens"] == 100896
        assert event["output"]["spending_finalizing"] is True
        assert model.calls[0]["tools"] == []
        (ARTIFACTS / "committed-before-reproduction.json").write_text(json.dumps({
            "proof_kind": "historical committed transport with local scripted model",
            "commit": "94d50d7", "external_calls": 0,
            "captured_phone_brief": inspection["brief"],
            "event": event, "outgoing_tools": model.calls[0]["tools"],
        }, indent=2))
    finally:
        sys.modules.pop(module_name, None)


def test_all_retained_consumers_and_safe_configuration_parity():
    census = json.loads((ARTIFACTS / "consumer-census.json").read_text())
    expected_limits = {
        "input_tokens": 25334,
        "total_tokens": 200000,
        "decision_reserve": 32000,
        "verification_reserve": 32000,
        "hosted_reserve": 10667,
        "output_tokens": 6667,
    }
    assert asdict(ContextLimits()) == expected_limits
    assert OWNER_START_TOKENS == 120000
    assert SOURCE_START_TOKENS == 40000
    expected_caps = {
        300: 400,
        500: 667,
        800: 1067,
        900: 1200,
        1100: 1467,
        1200: 1600,
        1500: 2000,
        1700: 2267,
        1800: 2400,
        2500: 3334,
        3000: 4000,
        4000: 5334,
        5000: 6667,
    }
    sites = []
    for path in sorted((ROOT / "apps/backend/app/agents").glob("live_*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.keyword) or node.arg != "max_tokens":
                continue
            value = node.value
            assert isinstance(value, ast.Call) and isinstance(value.func, ast.Name)
            assert value.func.id == "scaled_tokens"
            baseline = value.args[0].value
            assert scaled_tokens(baseline) == expected_caps[baseline]
            sites.append(
                {
                    "file": str(path.relative_to(ROOT)),
                    "line": node.lineno,
                    "before": baseline,
                    "after": expected_caps[baseline],
                }
            )
    assert len(sites) == 44
    assert len({site["file"] for site in sites}) == 24
    assert census

    baseline = json.loads(
        (ROOT / "data/artifacts/task221/configuration-parity.json").read_text()
    )
    settings = Settings(_env_file=ROOT / "apps/backend/.env")
    assert settings.agent_workflow_mode == baseline["workflow_mode"]
    agent_fields = (
        "mode",
        "model",
        "run_profile",
        "timeout_seconds",
        "max_turns",
        "reasoning_effort",
    )
    agents = {
        name: {
            key: getattr(
                build_openai_agent_run_configuration(settings, agent_name=name), key
            )
            for key in agent_fields
        }
        for name in baseline["agents"]
    }
    assert agents == baseline["agents"]
    providers = {key: getattr(settings, key) for key in baseline["providers"]}
    assert providers == baseline["providers"]
    captions = {
        key: getattr(settings, key) for key in baseline["caption_configuration"]
    }
    assert json.loads(json.dumps(captions)) == baseline["caption_configuration"]
    profiles = {
        str(name): profile.model_dump(mode="json")
        for name, profile in settings.openai_run_profiles.items()
    }
    assert {name: profiles[name] for name in baseline["profiles"]} == baseline[
        "profiles"
    ]
    overrides = {
        name: profile.model_dump(mode="json")
        for name, profile in settings.openai_agent_overrides.items()
    }
    assert {name: overrides[name] for name in baseline["agent_overrides"]} == baseline[
        "agent_overrides"
    ]

    unchanged = []
    for name in (
        "apps/backend/app/core/settings.py",
        "apps/backend/app/agents/openai_config.py",
        "apps/backend/app/agents/catalog.py",
        "apps/backend/app/providers/youtube_transcript.py",
        "apps/backend/pyproject.toml",
        "apps/backend/uv.lock",
    ):
        committed = subprocess.check_output(["git", "show", "HEAD:" + name], cwd=ROOT)
        assert (ROOT / name).read_bytes() == committed
        unchanged.append(name)
    assert agents["VerifierCriticAgent"]["timeout_seconds"] == 180
    all_agents = {
        name: {key: getattr(build_openai_agent_run_configuration(settings, agent_name=name), key)
               for key in agent_fields}
        for name in DEFAULT_AGENT_CATALOG.entries
    }
    orchestration_path = "apps/backend/app/orchestration/shopping_runs.py"
    previous_tree = ast.parse(subprocess.check_output(["git", "show", "HEAD:" + orchestration_path], cwd=ROOT).decode())
    current_tree = ast.parse((ROOT / orchestration_path).read_text())
    for method in ("run", "resume", "_run_general_owner", "_run_comparison_decision"):
        previous = next(node for node in ast.walk(previous_tree)
                        if isinstance(node, ast.AsyncFunctionDef) and node.name == method
                        and any(isinstance(child, ast.Name) and child.id == "context" for child in ast.walk(node)))
        current = next(node for node in ast.walk(current_tree)
                       if isinstance(node, ast.AsyncFunctionDef) and node.name == method
                       and any(isinstance(child, ast.Name) and child.id == "context" for child in ast.walk(node)))
        assert ast.dump(current, include_attributes=False) == ast.dump(previous, include_attributes=False)
    (ARTIFACTS / "configuration-after.json").write_text(
        json.dumps(
            {
                "proof_kind": "offline configuration inspection, no provider calls",
                "context_limits": expected_limits,
                "owner_start": OWNER_START_TOKENS,
                "source_start": SOURCE_START_TOKENS,
                "effective_output_sites": sites,
                "agents": agents,
        "all_catalog_configurations": all_agents,
                "providers": providers,
                "caption_configuration": captions,
                "profiles": profiles,
                "agent_overrides": overrides,
                "unchanged_files_against_HEAD": unchanged,
                "removed_normal_stages": baseline["removed_normal_stages"],
        "unchanged_orchestration_methods": ["run", "resume", "_run_general_owner", "_run_comparison_decision"],
                "non_token_parity_passed": True,
        "workflow_mode": settings.agent_workflow_mode,
            },
            indent=2,
        )
    )
