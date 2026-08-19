"""Executable RTS-021 storage comparison acceptance tests."""

from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parents[1]
RUNNER = ROOT / "experiments" / "runtime-v2-storage" / "runner.py"
PROVIDER = ROOT / "tests" / "fixtures" / "runtime_v2_shared_slice_provider.py"
SHARED_CASES = ROOT / "tests" / "fixtures" / "runtime_v2_shared_slice_cases.json"
STORAGE_CASES = ROOT / "tests" / "fixtures" / "runtime_v2_storage_cases.json"
TASK_ID = "runtime-v2-rts-021-storage-comparison"
BACKENDS = ("atomic", "sqlite")


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
    (repo / "README.md").write_text("source repo for RTS-021\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "Seed RTS-021 source")
    return repo


def _cli(
    command: str,
    backend: str,
    state_root: Path,
    run_id: str,
    repo: Path | None = None,
    fault: str = "",
    maintenance: str = "",
    seconds: float = 1.0,
) -> dict[str, Any]:
    args = [
        sys.executable,
        str(RUNNER),
        command,
        "--store",
        backend,
        "--state-root",
        str(state_root),
        "--run-id",
        run_id,
    ]
    if command == "run":
        assert repo is not None
        args.extend(["--repo", str(repo), "--provider", str(PROVIDER)])
        if fault:
            args.extend(["--fault", fault])
    if command == "maintenance":
        args.append(maintenance)
        if repo is not None:
            args.extend(["--repo", str(repo), "--provider", str(PROVIDER)])
        args.extend(["--seconds", str(seconds)])
    completed = subprocess.run(args, check=True, capture_output=True, text=True)
    return json.loads(completed.stdout)


def _read_json_no_duplicate_keys(path: Path) -> dict[str, Any]:
    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            assert key not in result, f"duplicate JSON key: {key}"
            result[key] = value
        return result

    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicate_keys)


def _shared_rows() -> list[dict[str, Any]]:
    fixture = _read_json_no_duplicate_keys(SHARED_CASES)
    rows: list[dict[str, Any]] = []
    for case in fixture["cases"]:
        rows.extend(case.get("subcases") or [case])
    return rows


def _snapshot_bytes(path: Path) -> dict[str, bytes]:
    if not path.exists():
        return {}
    return {
        str(child.relative_to(path)): child.read_bytes()
        for child in sorted(path.rglob("*"))
        if child.is_file()
    }


def _authority(state_root: Path, backend: str, run_id: str) -> dict[str, Any]:
    run_dir = state_root / backend / run_id
    if backend == "atomic":
        return json.loads((run_dir / "authority.json").read_text(encoding="utf-8"))["payload"]
    with sqlite3.connect(run_dir / "state.db") as conn:
        row = conn.execute(
            "SELECT payload FROM records WHERE kind = ? AND key = ?",
            ("authority", "current"),
        ).fetchone()
    assert row is not None
    return json.loads(row[0])


def _authority_bytes(state_root: Path, backend: str, run_id: str) -> bytes:
    run_dir = state_root / backend / run_id
    if backend == "atomic":
        return (run_dir / "authority.json").read_bytes()
    return (run_dir / "state.db").read_bytes()


def _counts(status: dict[str, Any]) -> dict[str, Any]:
    return status["provider_invocation_observation"]["counts"]


def _evaluate_gate(evidence_path: Path) -> dict[str, Any]:
    return json.loads(
        subprocess.run(
            [sys.executable, str(RUNNER), "evaluate", "--evidence", str(evidence_path)],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )


def _assert_shared_assertions(
    state_root: Path,
    backend: str,
    repo: Path,
    run_id: str,
    status: dict[str, Any],
    row: dict[str, Any],
) -> None:
    assertions = set(row["assertions"])
    counts = _counts(status)
    authority = _authority(state_root, backend, run_id)
    run = authority["run"]
    journals = authority["journals"]
    trusted = state_root / backend / run_id / "trusted-repo"

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
        assert run["authorizations"] == [], row["id"]
    if "auth_implement_once" in assertions:
        assert run["authorizations"] == [{"invocation_id": "implement-1", "role": "implement"}]
    if "auth_full_once" in assertions:
        assert run["authorizations"] == [
            {"invocation_id": "implement-1", "role": "implement"},
            {"invocation_id": "review-1", "role": "review"},
        ]
    if "no_handoff" in assertions:
        assert run["handoff_intent"] is None, row["id"]
    if "no_trusted_repo" in assertions:
        assert not trusted.exists(), row["id"]
    if "trusted_repo_exists" in assertions:
        assert trusted.exists(), row["id"]
        assert _git(trusted, "remote") == ""
    if "trusted_remote_absent" in assertions:
        assert trusted.exists(), row["id"]
        assert _git(trusted, "remote") == ""
    if "trusted_commit_exists" in assertions:
        assert trusted.exists(), row["id"]
        assert int(_git(trusted, "rev-list", "--count", "HEAD")) >= 2
    if "trusted_commit_exact" in assertions:
        assert _git(trusted, "rev-parse", "HEAD") == run["trusted_commit"], row["id"]
    if "trusted_head_drifted" in assertions:
        assert _git(trusted, "rev-parse", "HEAD") != run["trusted_commit"], row["id"]
    if "handoff_exact" in assertions:
        assert run["handoff_intent"]["trusted_commit"] == run["trusted_commit"], row["id"]
        assert run["handoff_intent"]["trusted_tree"] == run["trusted_tree"], row["id"]
    if "journal_implement_prepared_only" in assertions:
        assert sorted(journals) == ["implement-1"], row["id"]
        journal = journals["implement-1"]
        assert journal["state"] == "prepared", row["id"]
        assert journal["prepared_is_launch_intent"] is False, row["id"]
        assert journal["launch_intent"] is None, row["id"]
    if "implement_journal_absent" in assertions:
        assert "implement-1" not in journals, row["id"]
    if "journal_state_launch_intent" in assertions:
        journal = journals["implement-1"]
        assert journal["state"] == "launch_intent", row["id"]
        assert journal["launch_intent"] is not None, row["id"]
        assert journal["started"] is None, row["id"]
    if "journal_state_started" in assertions:
        journal = journals["implement-1"]
        assert journal["state"] == "started", row["id"]
        assert journal["started"] is not None, row["id"]
        assert journal["result"] is None, row["id"]
    if "exact_journal_ids" in assertions:
        if "auth_full_once" in assertions:
            assert sorted(journals) == ["implement-1", "review-1"], row["id"]
        elif "implement_journal_absent" in assertions:
            assert journals == {}, row["id"]
        else:
            assert sorted(journals) == ["implement-1"], row["id"]
    if "spec_allowed_delta_stable" in assertions:
        assert authority["spec"]["allowed_delta"] == ["result.txt"], row["id"]
        assert authority["spec"]["task_id"] == TASK_ID, row["id"]

    replay_assertions = {
        "state_stable_on_rerun",
        "implement_count_stable_on_rerun",
        "duplicate_rerun_stable",
    }
    if assertions.intersection(replay_assertions):
        run_dir = state_root / backend / run_id
        before = _snapshot_bytes(run_dir)
        before_counts = counts
        before_head = _git(trusted, "rev-parse", "HEAD") if trusted.exists() else None
        rerun = _cli("run", backend, state_root, run_id, repo=repo, fault=row["inject"])
        if "state_stable_on_rerun" in assertions:
            assert _snapshot_bytes(run_dir) == before, row["id"]
        if "implement_count_stable_on_rerun" in assertions:
            assert _counts(rerun)["implement"] == before_counts["implement"], row["id"]
        if "duplicate_rerun_stable" in assertions:
            assert _counts(rerun) == before_counts, row["id"]
            assert _snapshot_bytes(run_dir) == before, row["id"]
            assert _git(trusted, "rev-parse", "HEAD") == before_head, row["id"]


def _window_gate_fact(fixture: dict[str, Any]) -> bool:
    sqlite_removed = sum(
        1
        for window in fixture["named_windows"]
        if window["candidates"]["sqlite"]["result"] == "eliminated"
    )
    return sqlite_removed >= 2


def test_storage_fixture_is_strict_and_gate_result_is_derived() -> None:
    fixture = _read_json_no_duplicate_keys(STORAGE_CASES)
    assert fixture["task_id"] == TASK_ID
    assert fixture["backends"] == ["atomic", "sqlite"]
    assert {window["id"] for window in fixture["named_windows"]} == {
        "W-AUTH",
        "W-RESULT",
        "W-HANDOFF",
        "W-TERMINAL",
    }
    for window in fixture["named_windows"]:
        for backend in BACKENDS:
            data = window["candidates"][backend]
            assert data["result"] in {"eliminated", "retained_safe", "not_applicable"}
            assert data["transaction_boundary"]
            assert data["joined_records"]
            assert data["recovery_action"]
    assert _window_gate_fact(fixture)
    reported = json.loads(
        subprocess.run(
            [sys.executable, str(RUNNER), "windows"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )
    assert "result" not in reported
    assert set(reported["windows"]) == {"W-AUTH", "W-RESULT", "W-HANDOFF", "W-TERMINAL"}


def test_normal_run_status_stop_are_equivalent_and_status_byte_readonly(tmp_path: Path) -> None:
    repo = _source_repo(tmp_path)
    state_root = tmp_path / "state"
    terminals = {}

    for backend in BACKENDS:
        run_id = f"normal-{backend}"
        terminal = _cli("run", backend, state_root, run_id, repo=repo)
        terminals[backend] = terminal
        assert terminal["phase"] == "completed"
        assert terminal["outcome"] == "TERMINAL_IDEMPOTENT"
        assert _counts(terminal)["implement"] == 1
        assert _counts(terminal)["review"] == 1

        run_dir = state_root / backend / run_id
        before = _snapshot_bytes(run_dir)
        status = _cli("status", backend, state_root, run_id)
        assert _snapshot_bytes(run_dir) == before
        assert status == terminal

        rerun = _cli("run", backend, state_root, run_id, repo=repo)
        assert rerun == terminal
        assert _counts(rerun) == _counts(terminal)

        stopped = _cli("stop", backend, state_root, run_id)
        assert stopped["phase"] == "stopped"
        assert stopped["outcome"] == "TERMINAL_IDEMPOTENT"
        assert stopped["legal_next_action"] == "none"
        stop_fact = _authority(state_root, backend, run_id)["run"]["stop"]
        assert stop_fact == {
            "kind": "exact-local-stop",
            "native_manager": False,
            "unequal_lifecycle_evidence": True,
        }

    comparable = ["outcome", "legal_next_action", "terminal"]
    assert {key: terminals["atomic"][key] for key in comparable} == {
        key: terminals["sqlite"][key] for key in comparable
    }


def test_all_shared_rows_match_outcome_action_and_replay_guards(tmp_path: Path) -> None:
    repo = _source_repo(tmp_path)
    state_root = tmp_path / "state"

    for row in _shared_rows():
        for backend in BACKENDS:
            run_id = f"{backend}-{row['id'].lower()}"
            status = _cli("run", backend, state_root, run_id, repo=repo, fault=row["inject"])
            assert status["outcome"] == row["expected_outcome"], (backend, row["id"])
            assert status["legal_next_action"] == row["legal_next_action"], (backend, row["id"])
            _assert_shared_assertions(state_root, backend, repo, run_id, status, row)

            run_dir = state_root / backend / run_id
            before = _snapshot_bytes(run_dir)
            projected = _cli("status", backend, state_root, run_id)
            assert projected["outcome"] == row["expected_outcome"], (backend, row["id"])
            assert projected["legal_next_action"] == row["legal_next_action"], (backend, row["id"])
            assert _snapshot_bytes(run_dir) == before, (backend, row["id"])


def test_writer_contention_denies_mutation_before_provider(tmp_path: Path) -> None:
    repo = _source_repo(tmp_path)
    state_root = tmp_path / "state"

    for backend in BACKENDS:
        run_id = f"busy-{backend}"
        prepared = _cli(
            "run",
            backend,
            state_root,
            run_id,
            repo=repo,
            fault="auth_authorized_prepared",
        )
        assert prepared["outcome"] == "SAFE_CONTINUE"
        assert _counts(prepared) == {"calls": [], "implement": 0, "review": 0}
        holder = subprocess.Popen(
            [
                sys.executable,
                str(RUNNER),
                "maintenance",
                "--store",
                backend,
                "--state-root",
                str(state_root),
                "--run-id",
                run_id,
                "hold-writer",
                "--seconds",
                "1.5",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            time.sleep(0.2)
            status = _cli("run", backend, state_root, run_id, repo=repo)
            assert status["outcome"] == "AMBIGUOUS_NO_REPLAY"
            assert status["legal_next_action"] == (
                "preserve exact writer/process evidence for owner decision"
            )
            assert _counts(status) == {"calls": [], "implement": 0, "review": 0}
        finally:
            stdout, stderr = holder.communicate(timeout=5)
            assert holder.returncode == 0, (stdout, stderr)


def test_restart_after_named_windows_recovers_without_replay(tmp_path: Path) -> None:
    repo = _source_repo(tmp_path)
    state_root = tmp_path / "state"
    recoverable = {
        "auth_authorized_prepared": (0, 0),
        "result_validate": (1, 0),
        "effect_intent": (1, 0),
        "review_result_recover": (1, 1),
    }

    for backend in BACKENDS:
        for fault, before_counts in recoverable.items():
            run_id = f"{backend}-{fault}"
            first = _cli("run", backend, state_root, run_id, repo=repo, fault=fault)
            assert first["outcome"] == "SAFE_CONTINUE"
            assert (_counts(first)["implement"], _counts(first)["review"]) == before_counts
            terminal = _cli("run", backend, state_root, run_id, repo=repo)
            assert terminal["outcome"] == "TERMINAL_IDEMPOTENT"
            assert _counts(terminal)["implement"] == 1
            assert _counts(terminal)["review"] == 1


def test_corruption_backup_restore_and_stale_restore_fail_closed(tmp_path: Path) -> None:
    repo = _source_repo(tmp_path)
    state_root = tmp_path / "state"

    for backend in BACKENDS:
        corrupt_id = f"corrupt-{backend}"
        _cli("run", backend, state_root, corrupt_id, repo=repo, fault="auth_authorized_prepared")
        run_dir = state_root / backend / corrupt_id
        if backend == "atomic":
            (run_dir / "authority.json").write_text("{", encoding="utf-8")
        else:
            (run_dir / "state.db").write_bytes(b"not a sqlite database")
        corrupt = _cli("status", backend, state_root, corrupt_id)
        assert corrupt["outcome"] == "DENY_BEFORE_PROVIDER"

        current_id = f"current-restore-{backend}"
        terminal = _cli("run", backend, state_root, current_id, repo=repo)
        _cli("maintenance", backend, state_root, current_id, maintenance="backup")
        restored = _cli("maintenance", backend, state_root, current_id, maintenance="restore")
        assert restored["outcome"] == terminal["outcome"]
        assert _counts(restored) == _counts(terminal)

        stale_id = f"stale-restore-{backend}"
        _cli("run", backend, state_root, stale_id, repo=repo, fault="auth_authorized_prepared")
        _cli("maintenance", backend, state_root, stale_id, maintenance="backup")
        _cli("run", backend, state_root, stale_id, repo=repo)
        stale = _cli("maintenance", backend, state_root, stale_id, maintenance="restore")
        assert stale["outcome"] == "TERMINAL_CONFLICT"
        assert stale["legal_next_action"] == "preserve newer authority; deny stale offline restore"


def test_foreign_backup_restore_denies_equal_and_newer_sequences_without_writing(
    tmp_path: Path,
) -> None:
    repo = _source_repo(tmp_path)
    state_root = tmp_path / "state"

    for backend in BACKENDS:
        donor_id = f"foreign-donor-{backend}"
        donor_terminal = _cli("run", backend, state_root, donor_id, repo=repo)
        donor_backup = Path(
            _cli("maintenance", backend, state_root, donor_id, maintenance="backup")["backup"]
        )
        assert donor_terminal["outcome"] == "TERMINAL_IDEMPOTENT"

        equal_victim_id = f"foreign-equal-victim-{backend}"
        equal_terminal = _cli("run", backend, state_root, equal_victim_id, repo=repo)
        equal_backup = Path(
            _cli("maintenance", backend, state_root, equal_victim_id, maintenance="backup")[
                "backup"
            ]
        )
        shutil.copy2(donor_backup, equal_backup)
        before_equal_bytes = _authority_bytes(state_root, backend, equal_victim_id)
        equal_denied = _cli(
            "maintenance", backend, state_root, equal_victim_id, maintenance="restore"
        )
        assert equal_denied["outcome"] == "TERMINAL_CONFLICT"
        assert "identity" in equal_denied["blocker"]["source"]
        assert _authority_bytes(state_root, backend, equal_victim_id) == before_equal_bytes
        assert _counts(_cli("status", backend, state_root, equal_victim_id)) == _counts(
            equal_terminal
        )

        newer_victim_id = f"foreign-newer-victim-{backend}"
        prepared = _cli(
            "run",
            backend,
            state_root,
            newer_victim_id,
            repo=repo,
            fault="auth_authorized_prepared",
        )
        victim_backup = Path(
            _cli("maintenance", backend, state_root, newer_victim_id, maintenance="backup")[
                "backup"
            ]
        )
        shutil.copy2(donor_backup, victim_backup)
        before_newer_bytes = _authority_bytes(state_root, backend, newer_victim_id)
        newer_denied = _cli(
            "maintenance", backend, state_root, newer_victim_id, maintenance="restore"
        )
        assert newer_denied["outcome"] == "TERMINAL_CONFLICT"
        assert "identity" in newer_denied["blocker"]["source"]
        assert _authority_bytes(state_root, backend, newer_victim_id) == before_newer_bytes
        assert _counts(_cli("status", backend, state_root, newer_victim_id)) == _counts(prepared)


def test_restore_denies_active_writer_without_writing(tmp_path: Path) -> None:
    repo = _source_repo(tmp_path)
    state_root = tmp_path / "state"

    for backend in BACKENDS:
        run_id = f"restore-busy-{backend}"
        terminal = _cli("run", backend, state_root, run_id, repo=repo)
        _cli("maintenance", backend, state_root, run_id, maintenance="backup")
        before = _authority_bytes(state_root, backend, run_id)
        holder = subprocess.Popen(
            [
                sys.executable,
                str(RUNNER),
                "maintenance",
                "--store",
                backend,
                "--state-root",
                str(state_root),
                "--run-id",
                run_id,
                "hold-writer",
                "--seconds",
                "1.5",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            time.sleep(0.2)
            denied = _cli("maintenance", backend, state_root, run_id, maintenance="restore")
            assert denied["outcome"] == "AMBIGUOUS_NO_REPLAY"
            assert denied["legal_next_action"] == (
                "preserve exact writer/process evidence for owner decision"
            )
            assert _authority_bytes(state_root, backend, run_id) == before
            assert _counts(_cli("status", backend, state_root, run_id)) == _counts(terminal)
        finally:
            stdout, stderr = holder.communicate(timeout=5)
            assert holder.returncode == 0, (stdout, stderr)


def test_sqlite_migration_is_offline_repeated_and_newer_schema_denied(tmp_path: Path) -> None:
    repo = _source_repo(tmp_path)
    state_root = tmp_path / "state"
    run_id = "sqlite-migration"

    seeded = _cli(
        "maintenance",
        "sqlite",
        state_root,
        run_id,
        repo=repo,
        maintenance="seed-v1",
    )
    assert seeded["schema_version"] == 1
    status_before = _cli("status", "sqlite", state_root, run_id)
    assert status_before["outcome"] == "OWNER_DECISION_REQUIRED"
    assert "status must not migrate" in status_before["legal_next_action"]

    migrated = _cli("maintenance", "sqlite", state_root, run_id, maintenance="migrate")
    assert migrated["migration"]["before"] == 1
    assert migrated["migration"]["after"] == 2
    repeated = _cli("maintenance", "sqlite", state_root, run_id, maintenance="migrate")
    assert repeated["migration"]["before"] == 2
    assert repeated["migration"]["after"] == 2

    newer = _cli("maintenance", "sqlite", state_root, run_id, maintenance="force-newer-schema")
    assert newer["outcome"] == "OWNER_DECISION_REQUIRED"
    assert "newer than supported" in newer["blocker"]["source"]


def test_derived_state_cannot_authorize_or_replace_authority(tmp_path: Path) -> None:
    repo = _source_repo(tmp_path)
    state_root = tmp_path / "state"

    for backend in BACKENDS:
        run_id = f"derived-{backend}"
        terminal = _cli("run", backend, state_root, run_id, repo=repo)
        forged = _cli("maintenance", backend, state_root, run_id, maintenance="forge-derived")
        assert forged["outcome"] == "TERMINAL_IDEMPOTENT"
        assert _counts(forged) == _counts(terminal)
        deleted = _cli("maintenance", backend, state_root, run_id, maintenance="delete-derived")
        assert deleted["outcome"] == "TERMINAL_IDEMPOTENT"
        assert _counts(deleted) == _counts(terminal)


def test_exact_stop_denies_active_invocation_and_active_writer(tmp_path: Path) -> None:
    repo = _source_repo(tmp_path)
    state_root = tmp_path / "state"

    for backend in BACKENDS:
        active_id = f"active-stop-{backend}"
        _cli("run", backend, state_root, active_id, repo=repo, fault="auth_launch_no_result")
        denied = _cli("stop", backend, state_root, active_id)
        assert denied["outcome"] == "DENY_BEFORE_MUTATION"
        assert "active invocation" in denied["blocker"]["source"]

        idle_id = f"idle-stop-{backend}"
        _cli("run", backend, state_root, idle_id, repo=repo, fault="auth_authorized_prepared")
        stopped = _cli("stop", backend, state_root, idle_id)
        assert stopped["outcome"] == "TERMINAL_IDEMPOTENT"
        assert stopped["legal_next_action"] == "none"

        writer_id = f"writer-stop-{backend}"
        _cli("run", backend, state_root, writer_id, repo=repo, fault="auth_authorized_prepared")
        holder = subprocess.Popen(
            [
                sys.executable,
                str(RUNNER),
                "maintenance",
                "--store",
                backend,
                "--state-root",
                str(state_root),
                "--run-id",
                writer_id,
                "hold-writer",
                "--seconds",
                "1.5",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            time.sleep(0.2)
            busy = _cli("stop", backend, state_root, writer_id)
            assert busy["outcome"] == "AMBIGUOUS_NO_REPLAY"
            assert busy["legal_next_action"] == (
                "preserve exact writer/process evidence for owner decision"
            )
        finally:
            stdout, stderr = holder.communicate(timeout=5)
            assert holder.returncode == 0, (stdout, stderr)


def _call_with_fresh_tmp(tmp_path: Path, name: str, fn: Any) -> None:
    child = tmp_path / name
    child.mkdir()
    fn(child)


def test_gate_evaluation_uses_observed_evidence_and_fails_closed(tmp_path: Path) -> None:
    fixture = _read_json_no_duplicate_keys(STORAGE_CASES)
    facts = {key: False for key in _gate_fact_keys()}

    facts["sqlite_removes_two_or_more_windows"] = _window_gate_fact(fixture)

    windows = json.loads(
        subprocess.run(
            [sys.executable, str(RUNNER), "windows"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )
    facts["external_boundaries_preserved"] = (
        "result" not in windows
        and "Agent Bus transport/ACK" in windows["external_boundaries"]
        and "cross-host state ownership" in windows["external_boundaries"]
    )

    _call_with_fresh_tmp(
        tmp_path,
        "normal",
        test_normal_run_status_stop_are_equivalent_and_status_byte_readonly,
    )
    facts["status_byte_readonly"] = True

    _call_with_fresh_tmp(
        tmp_path,
        "shared",
        test_all_shared_rows_match_outcome_action_and_replay_guards,
    )
    facts["shared_equivalence"] = True

    _call_with_fresh_tmp(tmp_path, "lock", test_writer_contention_denies_mutation_before_provider)
    facts["lock_contention"] = True

    _call_with_fresh_tmp(
        tmp_path,
        "restart",
        test_restart_after_named_windows_recovers_without_replay,
    )
    facts["restart_recovery"] = True

    _call_with_fresh_tmp(
        tmp_path,
        "backup",
        test_corruption_backup_restore_and_stale_restore_fail_closed,
    )
    facts["corruption_detection"] = True
    facts["current_backup_restore"] = True
    facts["stale_backup_denied"] = True

    _call_with_fresh_tmp(
        tmp_path,
        "foreign",
        test_foreign_backup_restore_denies_equal_and_newer_sequences_without_writing,
    )
    facts["foreign_backup_denied"] = True

    _call_with_fresh_tmp(
        tmp_path,
        "restore-active-writer",
        test_restore_denies_active_writer_without_writing,
    )
    facts["restore_active_writer"] = True

    _call_with_fresh_tmp(
        tmp_path,
        "migration",
        test_sqlite_migration_is_offline_repeated_and_newer_schema_denied,
    )
    facts["sqlite_migration"] = True

    _call_with_fresh_tmp(
        tmp_path,
        "derived",
        test_derived_state_cannot_authorize_or_replace_authority,
    )
    facts["derived_state_safety"] = True

    _call_with_fresh_tmp(
        tmp_path,
        "exact-stop",
        test_exact_stop_denies_active_invocation_and_active_writer,
    )
    facts["exact_stop"] = True

    evidence = tmp_path / "gate-evidence.json"
    evidence.write_text(
        json.dumps({"task_id": TASK_ID, "facts": facts}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    evaluated = _evaluate_gate(evidence)
    assert evaluated["result"] == "SQLITE_MEETS_MINIMUM_GATE"
    assert evaluated["missing_keys"] == []
    assert evaluated["extra_keys"] == []
    assert evaluated["non_boolean_keys"] == []
    assert evaluated["false_facts"] == []

    facts["restore_active_writer"] = False
    false_evidence = tmp_path / "gate-evidence-false.json"
    false_evidence.write_text(
        json.dumps({"task_id": TASK_ID, "facts": facts}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    false_result = _evaluate_gate(false_evidence)
    assert false_result["result"] == "RETAIN_ATOMIC_FILE_BASELINE"
    assert false_result["false_facts"] == ["restore_active_writer"]


def _gate_fact_keys() -> set[str]:
    return {
        "shared_equivalence",
        "sqlite_removes_two_or_more_windows",
        "lock_contention",
        "restart_recovery",
        "corruption_detection",
        "current_backup_restore",
        "stale_backup_denied",
        "foreign_backup_denied",
        "restore_active_writer",
        "sqlite_migration",
        "derived_state_safety",
        "exact_stop",
        "status_byte_readonly",
        "external_boundaries_preserved",
    }
