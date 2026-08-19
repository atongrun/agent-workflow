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
IMPLEMENT_AUTH = [{"invocation_id": "implement-1", "role": "implement"}]
FULL_AUTH = [*IMPLEMENT_AUTH, {"invocation_id": "review-1", "role": "review"}]
PROHIBITED_ASSERTION_MAP = {
    "automatic provider replay": ["state_stable_on_rerun"],
    "broaden allowed paths": ["spec_allowed_delta_stable"],
    "change TaskCard verification contract": ["spec_allowed_delta_stable"],
    "different trusted commit": ["trusted_commit_exact"],
    "erase authorization": ["auth_implement_once"],
    "fall back to prepared recovery": ["journal_state_launch_intent"],
    "fresh replacement delivery": ["state_stable_on_rerun"],
    "guessed authorization": ["no_auth"],
    "guessed journal repair": ["implement_journal_absent"],
    "guessed repair": ["state_stable_on_status"],
    "handoff intent": ["no_handoff"],
    "handoff rewrite": ["handoff_exact"],
    "new Git commit": ["duplicate_rerun_stable"],
    "new authorization identity": ["auth_implement_once"],
    "provider replay": ["implement_count_stable_on_rerun", "duplicate_rerun_stable"],
    "provider replay after launch intent": ["state_stable_on_rerun"],
    "provider start": ["no_provider"],
    "remote Git write": ["trusted_remote_absent"],
    "second authorization identity": ["auth_implement_once"],
    "second prepared journal": ["exact_journal_ids"],
    "terminal completion": ["no_terminal"],
    "terminal guess": ["no_terminal"],
    "terminal promotion": ["no_terminal"],
    "terminal rewrite": ["duplicate_rerun_stable"],
    "treat prepared as launch intent": ["journal_implement_prepared_only"],
    "trusted import": ["no_trusted_repo"],
}


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


def _run_cli(
    state_root: Path, repo: Path, run_id: str = TASK_ID, fault: str = ""
) -> dict[str, Any]:
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


def _journal_ids(run_dir: Path) -> list[str]:
    invocations = run_dir / "invocations"
    if not invocations.exists():
        return []
    return sorted(path.stem for path in invocations.glob("*.json"))


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


def _assert_machine_assertions(
    state_root: Path, run_id: str, status: dict[str, Any], row: dict[str, Any]
) -> None:
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
    if "no_auth" in assertions:
        assert _state_payload(run_dir, "run.json")["authorizations"] == [], row["id"]
    if "auth_implement_once" in assertions:
        assert _state_payload(run_dir, "run.json")["authorizations"] == IMPLEMENT_AUTH, row["id"]
    if "auth_full_once" in assertions:
        assert _state_payload(run_dir, "run.json")["authorizations"] == FULL_AUTH, row["id"]
    if "no_handoff" in assertions:
        assert _state_payload(run_dir, "run.json")["handoff_intent"] is None, row["id"]
    if "no_trusted_repo" in assertions:
        assert not trusted.exists(), row["id"]
    if "journal_implement_prepared_only" in assertions:
        journals = sorted((run_dir / "invocations").glob("*.json"))
        assert [path.stem for path in journals] == ["implement-1"], row["id"]
        journal = _state_payload(run_dir, "invocations/implement-1.json")
        assert journal["state"] == "prepared", row["id"]
        assert journal["prepared_is_launch_intent"] is False, row["id"]
        assert journal["launch_intent"] is None, row["id"]
        assert journal["started"] is None, row["id"]
        assert journal["result"] is None, row["id"]
    if "implement_journal_absent" in assertions:
        assert not (run_dir / "invocations" / "implement-1.json").exists(), row["id"]
    if "journal_state_launch_intent" in assertions:
        journal = _state_payload(run_dir, "invocations/implement-1.json")
        assert journal["state"] == "launch_intent", row["id"]
        assert journal["launch_intent"] is not None, row["id"]
        assert journal["started"] is None, row["id"]
        assert journal["result"] is None, row["id"]
    if "journal_state_started" in assertions:
        journal = _state_payload(run_dir, "invocations/implement-1.json")
        assert journal["state"] == "started", row["id"]
        assert journal["launch_intent"] is not None, row["id"]
        assert journal["started"] is not None, row["id"]
        assert journal["result"] is None, row["id"]
    if "exact_journal_ids" in assertions:
        if "auth_full_once" in assertions:
            assert _journal_ids(run_dir) == ["implement-1", "review-1"], row["id"]
        elif "implement_journal_absent" in assertions:
            assert _journal_ids(run_dir) == [], row["id"]
        else:
            assert _journal_ids(run_dir) == ["implement-1"], row["id"]
    if "spec_allowed_delta_stable" in assertions:
        spec = _state_payload(run_dir, "runspec.json")
        assert spec["allowed_delta"] == ["result.txt"], row["id"]
        assert spec["task_id"] == TASK_ID, row["id"]
    if "trusted_repo_exists" in assertions:
        assert trusted.exists(), row["id"]
        assert _git(trusted, "remote") == ""
    if "trusted_remote_absent" in assertions:
        assert trusted.exists(), row["id"]
        assert _git(trusted, "remote") == "", row["id"]
    if "trusted_commit_exists" in assertions:
        assert trusted.exists(), row["id"]
        assert int(_git(trusted, "rev-list", "--count", "HEAD")) >= 2, row["id"]
    if "trusted_commit_exact" in assertions:
        run_payload = _state_payload(run_dir, "run.json")
        assert _git(trusted, "rev-parse", "HEAD") == run_payload["trusted_commit"], row["id"]
    if "handoff_exact" in assertions:
        run_payload = _state_payload(run_dir, "run.json")
        handoff = run_payload["handoff_intent"]
        assert handoff["trusted_commit"] == run_payload["trusted_commit"], row["id"]
        assert handoff["trusted_tree"] == run_payload["trusted_tree"], row["id"]
    if "trusted_head_drifted" in assertions:
        run_payload = _state_payload(run_dir, "run.json")
        assert _git(trusted, "rev-parse", "HEAD") != run_payload["trusted_commit"], row["id"]


def _assert_replay_assertions(
    state_root: Path,
    repo: Path,
    run_id: str,
    status: dict[str, Any],
    row: dict[str, Any],
) -> None:
    assertions = set(row["assertions"])
    if not assertions.intersection(
        {"state_stable_on_rerun", "implement_count_stable_on_rerun", "duplicate_rerun_stable"}
    ):
        return
    run_dir = _run_dir(state_root, run_id)
    before = _snapshot_bytes(run_dir)
    before_counts = _counts(status)
    before_commit = None
    trusted = run_dir / "trusted-repo"
    if trusted.exists():
        before_commit = _git(trusted, "rev-parse", "HEAD")
    rerun = _run_cli(state_root, repo, run_id=run_id, fault=row["inject"])
    if "state_stable_on_rerun" in assertions:
        assert _snapshot_bytes(run_dir) == before, row["id"]
    if "implement_count_stable_on_rerun" in assertions:
        assert _counts(rerun)["implement"] == before_counts["implement"], row["id"]
    if "duplicate_rerun_stable" in assertions:
        assert _counts(rerun) == before_counts, row["id"]
        assert _snapshot_bytes(run_dir) == before, row["id"]
        assert trusted.exists(), row["id"]
        assert _git(trusted, "rev-parse", "HEAD") == before_commit, row["id"]


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
        row_assertions = set(row["assertions"])
        for prohibited in row["prohibited"]:
            mapped = PROHIBITED_ASSERTION_MAP[prohibited]
            assert row_assertions.intersection(mapped), (row["id"], prohibited, mapped)
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
        _assert_replay_assertions(state_root, repo, run_id, status, row)


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


def test_duplicate_pre_start_keeps_exact_auth_journal_and_provider_state(tmp_path: Path) -> None:
    repo = _source_repo(tmp_path)
    state_root = tmp_path / "state"
    run_id = "duplicate-pre-start-exact"

    first = _run_cli(state_root, repo, run_id=run_id, fault="duplicate_pre_start")
    assert first["outcome"] == "SAFE_CONTINUE"
    run_dir = _run_dir(state_root, run_id)
    before = _snapshot_bytes(run_dir)
    before_counts = _counts(first)
    before_auth = _state_payload(run_dir, "run.json")["authorizations"]
    before_journal = _state_payload(run_dir, "invocations/implement-1.json")

    second = _run_cli(state_root, repo, run_id=run_id, fault="duplicate_pre_start")

    assert second == first
    assert _snapshot_bytes(run_dir) == before
    assert _counts(second) == before_counts == {"calls": [], "implement": 0, "review": 0}
    assert _state_payload(run_dir, "run.json")["authorizations"] == before_auth
    assert _state_payload(run_dir, "invocations/implement-1.json") == before_journal


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


def test_provider_child_environment_is_credential_minimized(
    tmp_path: Path, monkeypatch: Any
) -> None:
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

    recoverable = _run_cli(
        state_root, repo, run_id="review-result-recover", fault="review_result_recover"
    )
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
    run_path.write_text(
        original.replace('"payload":', '"payload": {}, "payload":', 1), encoding="utf-8"
    )
    status = _status_cli(state_root, run_id=state_id)
    assert status["outcome"] == "DENY_BEFORE_PROVIDER"
    assert _counts(status) == {"calls": [], "implement": 0, "review": 0}

    artifact_id = "duplicate-key-artifact"
    interrupted = _run_cli(state_root, repo, run_id=artifact_id, fault="result_validate")
    assert interrupted["outcome"] == "SAFE_CONTINUE"
    artifact = _run_dir(state_root, artifact_id) / "artifacts" / "implementation-report.json"
    artifact.write_text(
        '{"artifact_type":"ImplementationReport","artifact_type":"Other",'
        '"changed_files":["result.txt"]}',
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


def test_phase_evidence_drift_is_joined_before_status_or_continuation(tmp_path: Path) -> None:
    repo = _source_repo(tmp_path)
    state_root = tmp_path / "state"

    result_id = "implement-result-journal-drift"
    _run_cli(state_root, repo, run_id=result_id, fault="result_validate")
    result_dir = _run_dir(state_root, result_id)
    result_journal_path = result_dir / "invocations" / "implement-1.json"
    result_journal = _state_payload(result_dir, "invocations/implement-1.json")
    result_journal["role"] = "review"
    _atomic_state(result_journal_path, result_journal)
    before = _snapshot_bytes(result_dir)
    denied = _status_cli(state_root, run_id=result_id)
    assert denied["outcome"] == "DENY_BEFORE_PROVIDER"
    assert denied["terminal"] is None
    assert _snapshot_bytes(result_dir) == before
    assert _run_cli(state_root, repo, run_id=result_id)["outcome"] == "DENY_BEFORE_PROVIDER"

    committed_id = "implement-committed-artifact-drift"
    _run_cli(state_root, repo, run_id=committed_id, fault="effect_intent")
    committed_dir = _run_dir(state_root, committed_id)
    artifact = committed_dir / "artifacts" / "implementation-report.json"
    artifact_payload = json.loads(artifact.read_text(encoding="utf-8"))
    artifact_payload["summary"] = "checksum-valid run state but artifact bytes drifted"
    artifact.write_text(json.dumps(artifact_payload, sort_keys=True) + "\n", encoding="utf-8")
    before = _snapshot_bytes(committed_dir)
    denied = _status_cli(state_root, run_id=committed_id)
    assert denied["outcome"] == "DENY_BEFORE_PROVIDER"
    assert denied["terminal"] is None
    assert _snapshot_bytes(committed_dir) == before
    rerun = _run_cli(state_root, repo, run_id=committed_id)
    assert rerun["outcome"] == "DENY_BEFORE_PROVIDER"
    assert _state_payload(committed_dir, "run.json")["handoff_intent"] is None

    review_id = "review-result-journal-drift"
    _run_cli(state_root, repo, run_id=review_id, fault="review_result_recover")
    review_dir = _run_dir(state_root, review_id)
    review_journal_path = review_dir / "invocations" / "review-1.json"
    review_journal = _state_payload(review_dir, "invocations/review-1.json")
    review_journal["role"] = "implement"
    _atomic_state(review_journal_path, review_journal)
    before = _snapshot_bytes(review_dir)
    denied = _status_cli(state_root, run_id=review_id)
    assert denied["outcome"] == "DENY_BEFORE_PROVIDER"
    assert denied["terminal"] is None
    assert _snapshot_bytes(review_dir) == before
    assert _run_cli(state_root, repo, run_id=review_id)["outcome"] == "DENY_BEFORE_PROVIDER"

    terminal_id = "terminal-review-artifact-drift"
    terminal = _run_cli(state_root, repo, run_id=terminal_id)
    assert terminal["phase"] == "completed"
    terminal_dir = _run_dir(state_root, terminal_id)
    review_artifact = terminal_dir / "artifacts" / "review-report.json"
    payload = json.loads(review_artifact.read_text(encoding="utf-8"))
    payload["summary"] = "review bytes drifted after terminal"
    review_artifact.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    before = _snapshot_bytes(terminal_dir)
    denied = _status_cli(state_root, run_id=terminal_id)
    assert denied["outcome"] == "DENY_BEFORE_PROVIDER"
    assert denied["terminal"] is None
    assert _snapshot_bytes(terminal_dir) == before
    assert _run_cli(state_root, repo, run_id=terminal_id)["outcome"] == "DENY_BEFORE_PROVIDER"


def test_authorization_erasure_and_duplicates_fail_closed_before_replay(tmp_path: Path) -> None:
    repo = _source_repo(tmp_path)
    state_root = tmp_path / "state"

    erased_id = "auth-erased"
    _run_cli(state_root, repo, run_id=erased_id, fault="auth_authorized_prepared")
    erased_dir = _run_dir(state_root, erased_id)
    run_path = erased_dir / "run.json"
    run_payload = _state_payload(erased_dir, "run.json")
    run_payload["authorizations"] = []
    _atomic_state(run_path, run_payload)
    before = _snapshot_bytes(erased_dir)
    denied = _status_cli(state_root, run_id=erased_id)
    assert denied["outcome"] == "DENY_BEFORE_PROVIDER"
    assert _counts(denied) == {"calls": [], "implement": 0, "review": 0}
    assert _snapshot_bytes(erased_dir) == before
    assert _run_cli(state_root, repo, run_id=erased_id)["outcome"] == "DENY_BEFORE_PROVIDER"

    duplicate_id = "auth-duplicate"
    _run_cli(state_root, repo, run_id=duplicate_id, fault="auth_authorized_prepared")
    duplicate_dir = _run_dir(state_root, duplicate_id)
    run_path = duplicate_dir / "run.json"
    run_payload = _state_payload(duplicate_dir, "run.json")
    run_payload["authorizations"] = [*IMPLEMENT_AUTH, *IMPLEMENT_AUTH]
    _atomic_state(run_path, run_payload)
    before = _snapshot_bytes(duplicate_dir)
    denied = _status_cli(state_root, run_id=duplicate_id)
    assert denied["outcome"] == "DENY_BEFORE_PROVIDER"
    assert _counts(denied) == {"calls": [], "implement": 0, "review": 0}
    assert _snapshot_bytes(duplicate_dir) == before
    assert _run_cli(state_root, repo, run_id=duplicate_id)["outcome"] == "DENY_BEFORE_PROVIDER"


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
