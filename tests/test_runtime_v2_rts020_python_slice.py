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


def _run_dir(state_root: Path, run_id: str) -> Path:
    return state_root / run_id


def _state_payload(run_dir: Path, name: str) -> dict[str, Any]:
    return json.loads((run_dir / name).read_text(encoding="utf-8"))["payload"]


def _atomic_state(path: Path, payload: dict[str, Any]) -> None:
    import hashlib
    import os

    checksum = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    envelope = {
        "format": "awf.runtime-v2-python-slice.v1",
        "payload": payload,
        "checksum": checksum,
    }
    temp = path.with_name(f"{path.name}.tmp-{os.getpid()}")
    temp.write_text(json.dumps(envelope, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def _assert_machine_assertions(state_root: Path, run_id: str, status: dict[str, Any], row: dict[str, Any]) -> None:
    counts = _counts(status)
    run_dir = _run_dir(state_root, run_id)
    trusted = run_dir / "trusted-repo"
    assertions = set(row["assertions"])

    if "no_provider" in assertions:
        assert counts == {"calls": [], "implement": 0, "review": 0}, row["id"]
    if "one_implement" in assertions:
        assert counts["implement"] == 1, row["id"]
    if "no_review" in assertions:
        assert counts["review"] == 0, row["id"]
    if "one_review" in assertions:
        assert counts["review"] == 1, row["id"]
    if "no_terminal" in assertions:
        assert status["terminal"] is None, row["id"]
    if "terminal_completed" in assertions:
        assert status["terminal"]["outcome"] == "completed", row["id"]
    if "no_trusted_repo" in assertions:
        assert not trusted.exists(), row["id"]
    if "trusted_repo_exists" in assertions:
        assert trusted.exists(), row["id"]
        assert _git(trusted, "remote") == ""
    if "trusted_commit_exists" in assertions:
        assert trusted.exists(), row["id"]
        assert int(_git(trusted, "rev-list", "--count", "HEAD")) >= 2, row["id"]
    if "trusted_head_drifted" in assertions:
        run_payload = _state_payload(run_dir, "run.json")
        assert _git(trusted, "rev-parse", "HEAD") != run_payload["trusted_commit"], row["id"]


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
        assert row["assertions"]
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
        _assert_machine_assertions(state_root, run_id, observed, row)

        before = _snapshot_bytes(state_root / run_id)
        status = _status_cli(state_root, run_id=run_id)
        after = _snapshot_bytes(state_root / run_id)
        assert status["outcome"] == row["expected_outcome"], row["id"]
        assert status["legal_next_action"] == row["legal_next_action"], row["id"]
        _assert_machine_assertions(state_root, run_id, status, row)
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


def test_provider_child_environment_is_credential_minimized(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setenv("RTS020_SENTINEL_SECRET", "must-not-reach-provider")
    repo = _source_repo(tmp_path)
    state_root = tmp_path / "state"

    terminal = _run_cli(state_root, repo)

    assert terminal["phase"] == "completed"
    assert _counts(terminal)["implement"] == 1
    assert _counts(terminal)["review"] == 1


def test_review_authorized_journal_states_do_not_replay_unsafely(tmp_path: Path) -> None:
    repo = _source_repo(tmp_path)
    state_root = tmp_path / "state"

    for run_id, fault in {
        "review-launch-no-result": "review_launch_no_result",
        "review-started-no-result": "review_started_no_result",
    }.items():
        ambiguous = _run_cli(state_root, repo, run_id=run_id, fault=fault)
        assert ambiguous["outcome"] == "AMBIGUOUS_NO_REPLAY"
        before = _counts(ambiguous)
        rerun = _run_cli(state_root, repo, run_id=run_id)
        assert rerun["outcome"] == "AMBIGUOUS_NO_REPLAY"
        assert _counts(rerun) == before

    recoverable = _run_cli(state_root, repo, run_id="review-result-recover", fault="review_result_recover")
    assert recoverable["outcome"] == "SAFE_CONTINUE"
    assert _counts(recoverable)["review"] == 1
    terminal = _run_cli(state_root, repo, run_id="review-result-recover")
    assert terminal["phase"] == "completed"
    assert _counts(terminal)["review"] == 1


def test_stop_denies_corrupt_or_identity_invalid_journals_without_writing(tmp_path: Path) -> None:
    repo = _source_repo(tmp_path)
    state_root = tmp_path / "state"

    invalid_id = "stop-invalid-journal"
    _run_cli(state_root, repo, run_id=invalid_id, fault="auth_authorized_prepared")
    invalid_dir = _run_dir(state_root, invalid_id)
    journal_path = invalid_dir / "invocations" / "implement-1.json"
    journal = _state_payload(invalid_dir, "invocations/implement-1.json")
    journal["role"] = "review"
    _atomic_state(journal_path, journal)
    before = _snapshot_bytes(invalid_dir)
    denied = _stop_cli(state_root, run_id=invalid_id)
    assert denied["outcome"] == "DENY_BEFORE_MUTATION"
    assert _snapshot_bytes(invalid_dir) == before

    corrupt_id = "stop-corrupt-journal"
    _run_cli(state_root, repo, run_id=corrupt_id, fault="auth_authorized_prepared")
    corrupt_dir = _run_dir(state_root, corrupt_id)
    (corrupt_dir / "invocations" / "implement-1.json").write_text("{", encoding="utf-8")
    before = _snapshot_bytes(corrupt_dir)
    denied = _stop_cli(state_root, run_id=corrupt_id)
    assert denied["outcome"] == "DENY_BEFORE_MUTATION"
    assert _snapshot_bytes(corrupt_dir) == before


def test_duplicate_key_state_and_artifact_inputs_fail_closed(tmp_path: Path) -> None:
    repo = _source_repo(tmp_path)
    state_root = tmp_path / "state"

    state_id = "duplicate-key-state"
    _run_cli(state_root, repo, run_id=state_id, fault="auth_authorized_prepared")
    state_dir = _run_dir(state_root, state_id)
    run_path = state_dir / "run.json"
    original = run_path.read_text(encoding="utf-8")
    run_path.write_text(original.replace('"payload":', '"payload": {}, "payload":', 1), encoding="utf-8")
    status = _status_cli(state_root, run_id=state_id)
    assert status["outcome"] == "DENY_BEFORE_PROVIDER"
    assert _counts(status) == {"calls": [], "implement": 0, "review": 0}

    artifact_id = "duplicate-key-artifact"
    interrupted = _run_cli(state_root, repo, run_id=artifact_id, fault="result_validate")
    assert interrupted["outcome"] == "SAFE_CONTINUE"
    artifact = _run_dir(state_root, artifact_id) / "artifacts" / "implementation-report.json"
    artifact.write_text(
        '{"artifact_type":"ImplementationReport","artifact_type":"Other","changed_files":["result.txt"]}',
        encoding="utf-8",
    )
    failed = _run_cli(state_root, repo, run_id=artifact_id)
    assert failed["outcome"] == "HANDLER_FAILURE_NO_ACK"
    assert _counts(failed)["implement"] == 1
    assert _counts(failed)["review"] == 0


def test_launch_argv_drift_and_presence_gaps_fail_closed_without_guessing(tmp_path: Path) -> None:
    repo = _source_repo(tmp_path)
    state_root = tmp_path / "state"

    argv_id = "launch-argv-drift"
    _run_cli(state_root, repo, run_id=argv_id, fault="auth_launch_no_result")
    argv_dir = _run_dir(state_root, argv_id)
    journal_path = argv_dir / "invocations" / "implement-1.json"
    journal = _state_payload(argv_dir, "invocations/implement-1.json")
    journal["launch_intent"]["argv"][-1] = "invalid-artifact"
    _atomic_state(journal_path, journal)
    denied = _status_cli(state_root, run_id=argv_id)
    assert denied["outcome"] == "DENY_BEFORE_PROVIDER"
    assert _counts(denied) == {"calls": [], "implement": 0, "review": 0}
    assert _run_cli(state_root, repo, run_id=argv_id)["outcome"] == "DENY_BEFORE_PROVIDER"

    missing_spec_id = "missing-spec"
    _run_cli(state_root, repo, run_id=missing_spec_id, fault="auth_authorized_prepared")
    missing_spec_dir = _run_dir(state_root, missing_spec_id)
    (missing_spec_dir / "runspec.json").unlink()
    before = _snapshot_bytes(missing_spec_dir)
    denied = _status_cli(state_root, run_id=missing_spec_id)
    assert denied["outcome"] == "DENY_BEFORE_PROVIDER"
    assert _snapshot_bytes(missing_spec_dir) == before
    assert _run_cli(state_root, repo, run_id=missing_spec_id)["outcome"] == "DENY_BEFORE_PROVIDER"

    missing_run_id = "missing-run"
    _run_cli(state_root, repo, run_id=missing_run_id, fault="auth_authorized_prepared")
    missing_run_dir = _run_dir(state_root, missing_run_id)
    (missing_run_dir / "run.json").unlink()
    before = _snapshot_bytes(missing_run_dir)
    denied = _status_cli(state_root, run_id=missing_run_id)
    assert denied["outcome"] == "DENY_BEFORE_PROVIDER"
    assert _snapshot_bytes(missing_run_dir) == before
    assert _run_cli(state_root, repo, run_id=missing_run_id)["outcome"] == "DENY_BEFORE_PROVIDER"


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
