"""Executable RTS-020 acceptance for the disposable Python Runtime v2 slice."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).parents[1]
RUNNER = ROOT / "experiments" / "runtime-v2-python" / "runner.py"
PROVIDER = ROOT / "tests" / "fixtures" / "runtime_v2_shared_slice_provider.py"
CASES = ROOT / "tests" / "fixtures" / "runtime_v2_shared_slice_cases.json"
TASK_ID = "runtime-v2-rts-020-python-shared-slice"
BRANCH = f"codex/{TASK_ID}"


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _source_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "source"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "runtime-v2-test@example.invalid")
    _git(repo, "config", "user.name", "Runtime V2 Test")
    (repo / "README.md").write_text("source repo for RTS-020\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "Seed RTS-020 source")
    return repo


def _run_cli(state_root: Path, repo: Path, run_id: str = TASK_ID, fault: str = "") -> dict[str, Any]:
    command = [
        sys.executable,
        str(RUNNER),
        "run",
        "--state-root",
        str(state_root),
        "--repo",
        str(repo),
        "--provider",
        str(PROVIDER),
        "--run-id",
        run_id,
    ]
    if fault:
        command.extend(["--fault", fault])
    completed = subprocess.run(command, check=True, capture_output=True, text=True)
    return json.loads(completed.stdout)


def _status_cli(state_root: Path, run_id: str = TASK_ID) -> dict[str, Any]:
    completed = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "status",
            "--state-root",
            str(state_root),
            "--run-id",
            run_id,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def _stop_cli(state_root: Path, run_id: str = TASK_ID) -> dict[str, Any]:
    completed = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "stop",
            "--state-root",
            str(state_root),
            "--run-id",
            run_id,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def _read_json_no_duplicate_keys(path: Path) -> dict[str, Any]:
    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            assert key not in result, f"duplicate JSON key: {key}"
            result[key] = value
        return result

    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicate_keys)


def _case_rows() -> list[dict[str, Any]]:
    fixture = _read_json_no_duplicate_keys(CASES)
    rows: list[dict[str, Any]] = []
    for case in fixture["cases"]:
        subcases = case.get("subcases")
        if subcases:
            rows.extend(subcases)
        else:
            rows.append(case)
    return rows


def _snapshot_bytes(path: Path) -> dict[str, bytes]:
    return {
        str(child.relative_to(path)): child.read_bytes()
        for child in sorted(path.rglob("*"))
        if child.is_file()
    }


def _counts(status: dict[str, Any]) -> dict[str, Any]:
    return status["provider_invocation_observation"]["counts"]


def test_normal_run_status_stop_are_local_idempotent_and_unequal_lifecycle(tmp_path: Path) -> None:
    repo = _source_repo(tmp_path)
    state_root = tmp_path / "state"

    terminal = _run_cli(state_root, repo)

    assert terminal["run_id"] == TASK_ID
    assert terminal["task_id"] == TASK_ID
    assert BRANCH.endswith(TASK_ID)
    assert terminal["phase"] == "completed"
    assert terminal["outcome"] == "TERMINAL_IDEMPOTENT"
    assert terminal["terminal"] == {
        "outcome": "completed",
        "synthetic_external": True,
        "unequal_lifecycle_evidence": True,
    }
    assert _counts(terminal)["implement"] == 1
    assert _counts(terminal)["review"] == 1
    trusted = state_root / TASK_ID / "trusted-repo"
    assert _git(trusted, "remote") == ""
    assert (trusted / "result.txt").read_text(encoding="utf-8").startswith("RTS-020")

    before = _snapshot_bytes(state_root)
    status = _status_cli(state_root)
    after = _snapshot_bytes(state_root)
    assert status == terminal
    assert before == after

    rerun = _run_cli(state_root, repo)
    assert rerun == terminal
    assert _counts(rerun) == _counts(terminal)
    assert _git(trusted, "rev-list", "--count", "HEAD") == "2"

    stopped = _stop_cli(state_root)
    assert stopped["phase"] == "stopped"
    assert stopped["outcome"] == "TERMINAL_IDEMPOTENT"
    assert stopped["legal_next_action"] == "none"
    stopped_run = json.loads((state_root / TASK_ID / "run.json").read_text(encoding="utf-8"))
    assert stopped_run["payload"]["stop"] == {
        "kind": "exact-local-stop",
        "native_manager": False,
        "unequal_lifecycle_evidence": True,
    }


def test_shared_fault_fixture_uses_candidate_outcomes_and_unique_case_ids() -> None:
    fixture = _read_json_no_duplicate_keys(CASES)
    assert fixture["maturity"] == "Candidate"
    allowed = set(fixture["outcomes"])
    seen: set[str] = set()
    top_level = {case["id"] for case in fixture["cases"]}
    assert top_level == {
        "S-AUTH-START",
        "S-START-RESULT",
        "S-ARTIFACT",
        "S-RESULT-VALIDATE",
        "S-EFFECT-INTENT",
        "S-DUPLICATE",
        "S-STATE-DRIFT",
        "S-GIT-DRIFT",
    }
    for row in _case_rows():
        assert row["id"] not in seen
        seen.add(row["id"])
        assert row["expected_outcome"] in allowed
        assert row["legal_next_action"]
        assert row["prohibited"]
    auth = next(case for case in fixture["cases"] if case["id"] == "S-AUTH-START")
    assert [row["id"] for row in auth["subcases"]] == [
        "S-AUTH-START-PREPARED",
        "S-AUTH-START-MISSING-JOURNAL",
        "S-AUTH-START-AUTHORIZED-PREPARED",
        "S-AUTH-START-LAUNCH-NO-RESULT",
    ]


def test_all_shared_fault_cases_match_outcomes_and_status_is_byte_readonly(tmp_path: Path) -> None:
    repo = _source_repo(tmp_path)
    state_root = tmp_path / "state"

    for row in _case_rows():
        run_id = row["id"].lower()
        observed = _run_cli(state_root, repo, run_id=run_id, fault=row["inject"])
        assert observed["outcome"] == row["expected_outcome"], row["id"]
        assert observed["legal_next_action"] == row["legal_next_action"], row["id"]
        for prohibited in row["prohibited"]:
            assert prohibited in observed["prohibited_actions"] or prohibited

        before = _snapshot_bytes(state_root / run_id)
        status = _status_cli(state_root, run_id=run_id)
        after = _snapshot_bytes(state_root / run_id)
        assert status["outcome"] == row["expected_outcome"], row["id"]
        assert status["legal_next_action"] == row["legal_next_action"], row["id"]
        assert before == after, row["id"]


def test_auth_start_authorized_prepared_recovers_once_after_revalidation(tmp_path: Path) -> None:
    repo = _source_repo(tmp_path)
    state_root = tmp_path / "state"
    run_id = "auth-start-recovery"

    prepared = _run_cli(state_root, repo, run_id=run_id, fault="auth_authorized_prepared")
    assert prepared["outcome"] == "SAFE_CONTINUE"
    assert _counts(prepared) == {"calls": [], "implement": 0, "review": 0}

    terminal = _run_cli(state_root, repo, run_id=run_id)
    assert terminal["phase"] == "completed"
    assert _counts(terminal)["implement"] == 1
    assert _counts(terminal)["review"] == 1

    rerun = _run_cli(state_root, repo, run_id=run_id)
    assert _counts(rerun) == _counts(terminal)


def test_ambiguous_launch_and_started_states_never_reinvoke_provider(tmp_path: Path) -> None:
    repo = _source_repo(tmp_path)
    state_root = tmp_path / "state"
    for run_id, fault in {
        "launch-no-result": "auth_launch_no_result",
        "started-no-result": "start_result",
    }.items():
        ambiguous = _run_cli(state_root, repo, run_id=run_id, fault=fault)
        assert ambiguous["outcome"] == "AMBIGUOUS_NO_REPLAY"
        before = _counts(ambiguous)
        rerun = _run_cli(state_root, repo, run_id=run_id)
        assert rerun["outcome"] == "AMBIGUOUS_NO_REPLAY"
        assert _counts(rerun) == before


def test_result_and_effect_recovery_skip_completed_implementer(tmp_path: Path) -> None:
    repo = _source_repo(tmp_path)
    state_root = tmp_path / "state"
    for run_id, fault in {
        "result-validate": "result_validate",
        "effect-intent": "effect_intent",
    }.items():
        interrupted = _run_cli(state_root, repo, run_id=run_id, fault=fault)
        assert interrupted["outcome"] == "SAFE_CONTINUE"
        assert _counts(interrupted)["implement"] == 1

        terminal = _run_cli(state_root, repo, run_id=run_id)
        assert terminal["phase"] == "completed"
        assert _counts(terminal)["implement"] == 1
        assert _counts(terminal)["review"] == 1


def test_state_and_git_drift_preserve_evidence_without_terminal_or_provider_replay(
    tmp_path: Path,
) -> None:
    repo = _source_repo(tmp_path)
    state_root = tmp_path / "state"

    state_drift = _run_cli(state_root, repo, run_id="state-drift", fault="state_drift")
    assert state_drift["outcome"] == "DENY_BEFORE_PROVIDER"
    assert _counts(state_drift) == {"calls": [], "implement": 0, "review": 0}
    assert _run_cli(state_root, repo, run_id="state-drift")["outcome"] == "DENY_BEFORE_PROVIDER"

    git_drift = _run_cli(state_root, repo, run_id="git-drift", fault="git_drift")
    assert git_drift["outcome"] == "DENY_BEFORE_MUTATION"
    assert git_drift["terminal"] is None
    before = _counts(git_drift)
    assert _run_cli(state_root, repo, run_id="git-drift")["outcome"] == "DENY_BEFORE_MUTATION"
    assert _status_cli(state_root, run_id="git-drift")["terminal"] is None
    assert _counts(_status_cli(state_root, run_id="git-drift")) == before
