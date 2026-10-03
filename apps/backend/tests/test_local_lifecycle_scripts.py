"""Exercise local shell lifecycle behavior without providers or application calls."""

import os
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[3]
HELPER = ROOT / "scripts/local/lifecycle-common.sh"


def shell(code: str, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", 'set -euo pipefail; source "$HELPER"; ' + code],
        cwd=tmp_path,
        env={**os.environ, "HELPER": str(HELPER)},
        capture_output=True,
        text=True,
        timeout=5,
    )


def test_env_file_is_reloaded_and_overrides_existing_exports(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("CARTCART_AGENT_WORKFLOW_MODE=fixture\n")
    first = shell(
        "unset CARTCART_AGENT_WORKFLOW_MODE; source_env_file .env; "
        'echo "$CARTCART_AGENT_WORKFLOW_MODE"',
        tmp_path,
    )
    (tmp_path / ".env").write_text("CARTCART_AGENT_WORKFLOW_MODE=live\n")
    second = shell(
        "unset CARTCART_AGENT_WORKFLOW_MODE; source_env_file .env; "
        'echo "$CARTCART_AGENT_WORKFLOW_MODE"',
        tmp_path,
    )
    override = shell(
        "export CARTCART_AGENT_WORKFLOW_MODE=fixture; source_env_file .env; "
        'echo "$CARTCART_AGENT_WORKFLOW_MODE"',
        tmp_path,
    )
    assert first.stdout == "fixture\n"
    assert second.stdout == "live\n"
    assert override.stdout == "live\n"
    assert first.returncode == second.returncode == override.returncode == 0


def test_explicit_shell_override_option_preserves_inline_environment(
    tmp_path: Path,
) -> None:
    (tmp_path / ".env").write_text("CARTCART_AGENT_WORKFLOW_MODE=live\n")
    result = shell(
        "export CARTCART_AGENT_WORKFLOW_MODE=fixture; "
        'parse_env_options --use-shell-env; source_env_file .env "$USE_SHELL_ENV"; '
        'echo "$CARTCART_AGENT_WORKFLOW_MODE"',
        tmp_path,
    )
    assert result.returncode == 0
    assert result.stdout == "fixture\n"


@pytest.mark.parametrize("operation", ["start", "stop"])
def test_permission_failure_preserves_managed_pid(
    tmp_path: Path, operation: str
) -> None:
    pid_file = tmp_path / "service.pid"
    pid_file.write_text("12345\n")
    call = (
        "start_managed_service backend service.pid service.log http://localhost/healthz true"
        if operation == "start"
        else "stop_managed_service backend service.pid"
    )
    result = shell(
        'kill() { echo "kill: Operation not permitted" >&2; return 1; }; ' + call,
        tmp_path,
    )
    assert result.returncode != 0
    assert pid_file.read_text() == "12345\n"
    assert "permission" in result.stderr.lower()


@pytest.mark.parametrize("pid", ["0", "-1", "garbage"])
def test_invalid_pid_cannot_signal_a_process_group(tmp_path: Path, pid: str) -> None:
    (tmp_path / "service.pid").write_text(pid + "\n")
    result = shell(
        "kill() { touch signal-attempted; return 0; }; "
        "stop_managed_service backend service.pid",
        tmp_path,
    )
    assert result.returncode != 0
    assert not (tmp_path / "signal-attempted").exists()
    assert (tmp_path / "service.pid").read_text() == pid + "\n"


def test_stale_pid_is_removed_without_signalling(tmp_path: Path) -> None:
    (tmp_path / "service.pid").write_text("12345\n")
    result = shell(
        'kill() { echo "kill: No such process" >&2; return 1; }; '
        "stop_managed_service backend service.pid",
        tmp_path,
    )
    assert result.returncode == 0
    assert not (tmp_path / "service.pid").exists()


def test_start_waits_for_http_readiness(tmp_path: Path) -> None:
    result = shell(
        "kill() { return 0; }; sleep() { :; }; nohup() { :; }; "
        "curl() { local n=0; [[ ! -f probes ]] || n=$(cat probes); "
        'n=$((n+1)); echo "$n" > probes; ((n >= 4)); }; '
        "start_managed_service backend service.pid service.log "
        "http://localhost/healthz true",
        tmp_path,
    )
    assert result.returncode == 0
    assert int((tmp_path / "probes").read_text()) >= 4
    assert "ready" in result.stdout


def test_occupied_port_is_not_reported_as_new_service(tmp_path: Path) -> None:
    result = shell(
        "curl() { return 0; }; nohup() { touch launched; }; "
        "start_managed_service backend service.pid service.log "
        "http://localhost/healthz true",
        tmp_path,
    )
    assert result.returncode != 0
    assert not (tmp_path / "launched").exists()
    assert not (tmp_path / "service.pid").exists()
    assert "already" in result.stderr.lower()


def test_startup_failure_does_not_print_raw_logs(tmp_path: Path) -> None:
    (tmp_path / "service.log").write_text("private-log-token\n")
    result = shell(
        "curl() { return 7; }; sleep() { :; }; nohup() { :; }; "
        'kill() { echo "kill: No such process" >&2; return 1; }; '
        "start_managed_service backend service.pid service.log "
        "http://localhost/healthz true",
        tmp_path,
    )
    assert result.returncode != 0
    assert not (tmp_path / "service.pid").exists()
    assert "private-log-token" not in result.stderr + result.stdout


def test_startup_timeout_preserves_pid_for_cleanup(tmp_path: Path) -> None:
    result = shell(
        "curl() { return 7; }; sleep() { :; }; nohup() { :; }; "
        "kill() { return 0; }; "
        "start_managed_service backend service.pid service.log "
        "http://localhost/healthz true",
        tmp_path,
    )
    assert result.returncode != 0
    assert (tmp_path / "service.pid").exists()
    assert "did not become ready" in result.stderr


@pytest.mark.parametrize(
    ("script", "variable", "command"),
    [
        ("reset-db.sh", "CARTCART_DATABASE_PATH", "rm"),
        ("cleanup-artifacts.sh", "CARTCART_ARTIFACT_DIR", "find"),
    ],
)
def test_destructive_wrappers_respect_explicit_test_path_without_deleting(
    tmp_path: Path, script: str, variable: str, command: str
) -> None:
    target = tmp_path / "explicit-test-target"
    target.mkdir()
    executable = tmp_path / command
    executable.write_text('#!/bin/bash\nprintf "%s\\n" "$@" >> "$ARGUMENT_LOG"\n')
    executable.chmod(0o755)
    if command == "find":
        for name in [
            "raw-sources",
            "extracted-content",
            "screenshots",
            "agent-outputs",
            "traces",
            "evals",
        ]:
            (target / name).mkdir()
    result = subprocess.run(
        ["bash", str(ROOT / "scripts/local" / script), "--yes", "--use-shell-env"],
        cwd=tmp_path,
        env={
            **os.environ,
            variable: str(target),
            "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"],
            "ARGUMENT_LOG": str(tmp_path / "arguments"),
        },
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 0
    assert str(target) in (tmp_path / "arguments").read_text()
    assert target.is_dir()


def test_all_local_shell_scripts_have_valid_syntax() -> None:
    for path in sorted((ROOT / "scripts/local").glob("*.sh")):
        result = subprocess.run(
            ["bash", "-n", str(path)], capture_output=True, text=True
        )
        assert result.returncode == 0, f"{path.name}: {result.stderr}"
