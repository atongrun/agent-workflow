#!/usr/bin/env python3
"""Disposable Runtime v2 storage comparison runner."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any

from storage import (
    FORMAT,
    SCHEMA_VERSION,
    StateError,
    WriterBusy,
    create_sqlite_v1,
    digest,
    force_sqlite_schema,
    make_store,
    new_authority,
)


TASK_ID = "runtime-v2-rts-021-storage-comparison"
BRANCH = f"codex/{TASK_ID}"
ALLOWED_DELTA = ["result.txt"]
SAFE_CHILD_ENV_KEYS = ("LANG", "LC_ALL", "PATH", "PYTHONIOENCODING", "SYSTEMROOT", "WINDIR")
AUTHORIZED_JOURNAL_ACTION = (
    "preserve the consumed authorization/budget and deny automatic provider replay"
)
GATE_FACT_KEYS = {
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


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["GIT_OPTIONAL_LOCKS"] = "0"
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=check,
        capture_output=True,
        text=True,
        env=env,
    )


def _git_stdout(repo: Path, *args: str) -> str:
    return _git(repo, *args).stdout.strip()


def _configure_repo(repo: Path) -> None:
    _git(repo, "config", "user.email", "runtime-v2-storage@example.invalid")
    _git(repo, "config", "user.name", "Runtime V2 Storage Slice")
    for remote in [line for line in _git_stdout(repo, "remote").splitlines() if line.strip()]:
        _git(repo, "remote", "remove", remote)


def _clone_without_remote(source: Path, destination: Path, commit: str) -> None:
    if destination.exists():
        return
    subprocess.run(
        ["git", "clone", "--no-hardlinks", str(source), str(destination)],
        check=True,
        capture_output=True,
        text=True,
    )
    _git(destination, "checkout", "--detach", commit)
    _configure_repo(destination)


def _tree(repo: Path) -> str:
    return _git_stdout(repo, "rev-parse", "HEAD^{tree}")


def _head(repo: Path) -> str:
    return _git_stdout(repo, "rev-parse", "HEAD")


def _status_paths(repo: Path) -> list[str]:
    output = _git_stdout(repo, "status", "--porcelain")
    return [line[3:] for line in output.splitlines() if line]


def _child_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for key in SAFE_CHILD_ENV_KEYS:
        if key in os.environ:
            env[key] = os.environ[key]
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _compiled_spec(repo: Path, provider: Path, run_id: str) -> dict[str, Any]:
    source_head = _head(repo)
    return {
        "task_id": TASK_ID,
        "branch": BRANCH,
        "run_id": run_id,
        "repository": str(repo.resolve()),
        "source_head": source_head,
        "source_tree": _tree(repo),
        "allowed_delta": ALLOWED_DELTA,
        "provider_command": [sys.executable, str(provider.resolve())],
        "synthetic_external": [
            "provider intelligence",
            "delivery observation",
            "downstream intent",
            "timestamps",
            "GitHub-shaped fields",
        ],
    }


def _workspace(store_dir: Path, invocation_id: str) -> Path:
    if invocation_id == "implement-1":
        return store_dir / "workspaces" / "implement-1"
    return store_dir / "trusted-repo"


def _artifact(store_dir: Path, invocation_id: str) -> Path:
    if invocation_id == "implement-1":
        return store_dir / "artifacts" / "implementation-report.json"
    return store_dir / "artifacts" / "review-report.json"


def _provider_argv(
    spec: dict[str, Any], run_dir: Path, journal: dict[str, Any], mode: str
) -> list[str]:
    return [
        *spec["provider_command"],
        "--role",
        journal["role"],
        "--workspace",
        journal["workspace"],
        "--artifact",
        journal["artifact"],
        "--counter",
        str(run_dir / "provider-counts.json"),
        "--mode",
        mode,
    ]


def _journal(spec: dict[str, Any], run_dir: Path, invocation_id: str, role: str) -> dict[str, Any]:
    return {
        "invocation_id": invocation_id,
        "role": role,
        "spec_digest": digest(spec),
        "workspace": str(_workspace(run_dir, invocation_id)),
        "artifact": str(_artifact(run_dir, invocation_id)),
        "provider_command_digest": digest(spec["provider_command"]),
        "state": "prepared",
        "prepared_is_launch_intent": False,
        "launch_intent": None,
        "started": None,
        "result": None,
        "validated": None,
    }


def _journal_checked(state: dict[str, Any], invocation_id: str) -> dict[str, Any]:
    journal = state["journals"].get(invocation_id)
    if not isinstance(journal, dict):
        raise StateError("OWNER_DECISION_REQUIRED", AUTHORIZED_JOURNAL_ACTION, "journal is absent")
    return journal


def _counter(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "provider-counts.json"
    if not path.exists():
        return {"implement": 0, "review": 0, "calls": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - evidence only.
        return {"implement": "corrupt", "review": "corrupt", "calls": []}


def _read_artifact(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - provider artifact validation is fail-closed.
        raise StateError(
            "HANDLER_FAILURE_NO_ACK",
            "record failure/ambiguity and preserve the same delivery evidence",
            f"cannot read artifact {path.name}: {exc}",
        ) from exc


def _invoke_provider(
    store: Any,
    invocation_id: str,
    mode: str = "normal",
    record_phase: str | None = None,
) -> None:
    state = store.read()
    spec = state["spec"]
    journal = _journal_checked(state, invocation_id)
    command = _provider_argv(spec, store.run_dir, journal, mode)

    def launch(current: dict[str, Any]) -> dict[str, Any]:
        entry = dict(current["journals"][invocation_id])
        entry["state"] = "launch_intent"
        entry["launch_intent"] = {"argv": command, "mode": mode}
        current["journals"][invocation_id] = entry
        if record_phase:
            current["run"]["phase"] = record_phase
        return current

    store.mutate(launch)
    process = subprocess.Popen(command, cwd=journal["workspace"], env=_child_env())

    def started(current: dict[str, Any]) -> dict[str, Any]:
        entry = dict(current["journals"][invocation_id])
        entry["state"] = "started"
        entry["started"] = {"pid": process.pid}
        if record_phase:
            current["run"]["phase"] = "implement_started"
        current["journals"][invocation_id] = entry
        return current

    store.mutate(started)
    returncode = process.wait()

    def result(current: dict[str, Any]) -> dict[str, Any]:
        entry = dict(current["journals"][invocation_id])
        entry["state"] = "result"
        entry["result"] = {"returncode": returncode}
        current["journals"][invocation_id] = entry
        if invocation_id == "implement-1":
            current["run"]["phase"] = "implement_result"
        else:
            current["run"]["phase"] = "review_result"
        return current

    store.mutate(result)


def _validate_implementation(store: Any, state: dict[str, Any]) -> tuple[Path, str]:
    journal = _journal_checked(state, "implement-1")
    if journal.get("state") not in {"result", "validated"}:
        raise StateError(
            "DENY_BEFORE_PROVIDER",
            "preserve files and diagnose exact run identity",
            "implement journal lacks durable result",
        )
    if (journal.get("result") or {}).get("returncode") != 0:
        raise StateError(
            "HANDLER_FAILURE_NO_ACK",
            "record failure/ambiguity and preserve the same delivery evidence",
            "implement provider returned non-zero",
        )
    artifact = Path(journal["artifact"])
    report = _read_artifact(artifact)
    if report.get("artifact_type") != "ImplementationReport":
        raise StateError(
            "HANDLER_FAILURE_NO_ACK",
            "record failure/ambiguity and preserve the same delivery evidence",
            "missing valid ImplementationReport",
        )
    if report.get("changed_files") != ALLOWED_DELTA:
        raise StateError(
            "HANDLER_FAILURE_NO_ACK",
            "record failure/ambiguity and preserve the same delivery evidence",
            "implementation changed files outside the allowlist",
        )
    workspace = Path(journal["workspace"])
    if sorted(_status_paths(workspace)) != ALLOWED_DELTA:
        raise StateError(
            "HANDLER_FAILURE_NO_ACK",
            "record failure/ambiguity and preserve the same delivery evidence",
            "workspace delta does not match allowed paths",
        )
    return workspace, hashlib.sha256(artifact.read_bytes()).hexdigest()


def _copy_allowed(source: Path, destination: Path) -> None:
    for relative in ALLOWED_DELTA:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / relative, target)


def _import_and_commit(store: Any, state: dict[str, Any], workspace: Path) -> tuple[str, str]:
    trusted = store.run_dir / "trusted-repo"
    _clone_without_remote(Path(state["spec"]["repository"]), trusted, state["spec"]["source_head"])
    _copy_allowed(workspace, trusted)
    if sorted(_status_paths(trusted)) != ALLOWED_DELTA:
        raise StateError(
            "DENY_BEFORE_MUTATION",
            "preserve exact workspace/evidence for owner decision",
            "trusted import delta does not match allowed paths",
        )
    _git(trusted, "add", *ALLOWED_DELTA)
    _git(trusted, "commit", "-m", "Apply RTS-021 disposable implementation")
    return _head(trusted), _tree(trusted)


def _verify_trusted(store: Any, run: dict[str, Any]) -> None:
    trusted = store.run_dir / "trusted-repo"
    if not trusted.exists() or _head(trusted) != run.get("trusted_commit"):
        raise StateError(
            "DENY_BEFORE_MUTATION",
            "preserve both facts for owner decision",
            "trusted HEAD drift",
        )
    if _tree(trusted) != run.get("trusted_tree") or _status_paths(trusted):
        raise StateError(
            "DENY_BEFORE_MUTATION",
            "preserve both facts for owner decision",
            "trusted tree/worktree drift",
        )


def _validate_review(store: Any, state: dict[str, Any]) -> str:
    journal = _journal_checked(state, "review-1")
    if journal.get("state") not in {"result", "validated"}:
        raise StateError(
            "DENY_BEFORE_PROVIDER",
            "preserve files and diagnose exact run identity",
            "review journal lacks durable result",
        )
    if (journal.get("result") or {}).get("returncode") != 0:
        raise StateError(
            "HANDLER_FAILURE_NO_ACK",
            "record failure/ambiguity and preserve the same delivery evidence",
            "review provider returned non-zero",
        )
    artifact = Path(journal["artifact"])
    report = _read_artifact(artifact)
    if report.get("artifact_type") != "ReviewReport" or report.get("verdict") != "PASS":
        raise StateError(
            "HANDLER_FAILURE_NO_ACK",
            "record failure/ambiguity and preserve the same delivery evidence",
            "missing normalized PASS ReviewReport",
        )
    return hashlib.sha256(artifact.read_bytes()).hexdigest()


def _prepare_implement(store: Any, state: dict[str, Any]) -> None:
    spec = state["spec"]
    workspace = _workspace(store.run_dir, "implement-1")
    _clone_without_remote(Path(spec["repository"]), workspace, spec["source_head"])

    def update(current: dict[str, Any]) -> dict[str, Any]:
        current["journals"]["implement-1"] = _journal(
            spec, store.run_dir, "implement-1", "implement"
        )
        current["run"]["authorizations"] = [{"invocation_id": "implement-1", "role": "implement"}]
        current["run"]["phase"] = "implement_authorized"
        return current

    store.mutate(update)


def _prepare_review(store: Any, state: dict[str, Any]) -> None:
    spec = state["spec"]
    run = state["run"]

    def update(current: dict[str, Any]) -> dict[str, Any]:
        current["run"]["handoff_intent"] = {
            "kind": "synthetic-local-review",
            "trusted_commit": run["trusted_commit"],
            "trusted_tree": run["trusted_tree"],
        }
        current["journals"]["review-1"] = _journal(spec, store.run_dir, "review-1", "review")
        current["run"]["authorizations"] = [
            {"invocation_id": "implement-1", "role": "implement"},
            {"invocation_id": "review-1", "role": "review"},
        ]
        current["run"]["phase"] = "review_authorized"
        return current

    store.mutate(update)


def _continue(store: Any, mode: str = "normal") -> None:
    while True:
        state = store.read()
        run = state["run"]
        phase = run["phase"]
        if phase == "initialized":
            _prepare_implement(store, state)
        elif phase == "prepared_without_authorization":
            raise StateError(
                "DENY_BEFORE_PROVIDER",
                "commit exact RunStore authorization before launch",
                "prepared journal is not launch intent",
            )
        elif phase == "implement_authorized":
            journal = _journal_checked(state, "implement-1")
            if journal["state"] == "prepared":
                _invoke_provider(store, "implement-1", mode=mode)
            elif journal["state"] in {"launch_intent", "started"}:
                raise StateError(
                    "AMBIGUOUS_NO_REPLAY",
                    "preserve exact process/workspace/evidence for owner decision",
                    "implement launch/start has no recoverable result",
                )
            elif journal["state"] in {"result", "validated"}:
                store.mutate(lambda current: _set_phase(current, "implement_result"))
        elif phase in {"implement_launch_intent", "implement_started"}:
            raise StateError(
                "AMBIGUOUS_NO_REPLAY",
                "preserve exact process/workspace/evidence for owner decision",
                "launch/start has no recoverable result",
            )
        elif phase == "implement_result":
            workspace, artifact_sha = _validate_implementation(store, state)
            commit, tree = _import_and_commit(store, state, workspace)

            def update(current: dict[str, Any]) -> dict[str, Any]:
                entry = dict(current["journals"]["implement-1"])
                entry["state"] = "validated"
                entry["validated"] = {"artifact_sha256": artifact_sha}
                current["journals"]["implement-1"] = entry
                current["run"]["phase"] = "implement_committed"
                current["run"]["implementation_report_sha256"] = artifact_sha
                current["run"]["trusted_commit"] = commit
                current["run"]["trusted_tree"] = tree
                return current

            store.mutate(update)
        elif phase == "implement_committed":
            _verify_trusted(store, run)
            _prepare_review(store, state)
        elif phase == "review_authorized":
            _verify_trusted(store, run)
            journal = _journal_checked(state, "review-1")
            if journal["state"] == "prepared":
                _invoke_provider(store, "review-1")
            elif journal["state"] in {"launch_intent", "started"}:
                raise StateError(
                    "AMBIGUOUS_NO_REPLAY",
                    "preserve exact process/workspace/evidence for owner decision",
                    "review launch/start has no recoverable result",
                )
            elif journal["state"] in {"result", "validated"}:
                store.mutate(lambda current: _set_phase(current, "review_result"))
        elif phase == "review_result":
            _verify_trusted(store, run)
            review_sha = _validate_review(store, state)

            def update(current: dict[str, Any]) -> dict[str, Any]:
                entry = dict(current["journals"]["review-1"])
                entry["state"] = "validated"
                entry["validated"] = {"artifact_sha256": review_sha}
                current["journals"]["review-1"] = entry
                current["run"]["review_report_sha256"] = review_sha
                current["run"]["phase"] = "completed"
                current["run"]["terminal"] = {
                    "outcome": "completed",
                    "synthetic_external": True,
                    "unequal_lifecycle_evidence": True,
                }
                return current

            store.mutate(update)
            return
        elif phase in {"completed", "blocked", "stopped"}:
            return
        else:
            raise StateError(
                "OWNER_DECISION_REQUIRED",
                "preserve program and state evidence; use only a compatible program",
                f"unknown phase {phase}",
            )


def _set_phase(current: dict[str, Any], phase: str) -> dict[str, Any]:
    current["run"]["phase"] = phase
    return current


def _mark_failure(store: Any, error: StateError) -> None:
    def update(current: dict[str, Any]) -> dict[str, Any]:
        current["run"]["phase"] = "blocked"
        current["run"]["outcome"] = error.outcome
        current["run"]["legal_next_action"] = error.legal_next_action
        current["run"]["blocker"] = {"owner": "owner", "source": error.source}
        current["run"]["terminal"] = None
        return current

    store.mutate(update)


def _continue_until(store: Any, target_phase: str) -> None:
    while store.read()["run"]["phase"] != target_phase:
        _continue_one_step(store)


def _continue_one_step(store: Any) -> None:
    state = store.read()
    phase = state["run"]["phase"]
    if phase == "initialized":
        _prepare_implement(store, state)
    elif phase == "implement_authorized":
        _invoke_provider(store, "implement-1")
    elif phase == "implement_result":
        workspace, artifact_sha = _validate_implementation(store, state)
        commit, tree = _import_and_commit(store, state, workspace)

        def update(current: dict[str, Any]) -> dict[str, Any]:
            entry = dict(current["journals"]["implement-1"])
            entry["state"] = "validated"
            entry["validated"] = {"artifact_sha256": artifact_sha}
            current["journals"]["implement-1"] = entry
            current["run"]["phase"] = "implement_committed"
            current["run"]["implementation_report_sha256"] = artifact_sha
            current["run"]["trusted_commit"] = commit
            current["run"]["trusted_tree"] = tree
            return current

        store.mutate(update)
    elif phase == "implement_committed":
        _prepare_review(store, state)
    elif phase == "review_authorized":
        _invoke_provider(store, "review-1")
    elif phase == "review_result":
        review_sha = _validate_review(store, state)

        def update(current: dict[str, Any]) -> dict[str, Any]:
            entry = dict(current["journals"]["review-1"])
            entry["state"] = "validated"
            entry["validated"] = {"artifact_sha256": review_sha}
            current["journals"]["review-1"] = entry
            current["run"]["phase"] = "completed"
            current["run"]["review_report_sha256"] = review_sha
            current["run"]["terminal"] = {
                "outcome": "completed",
                "synthetic_external": True,
                "unequal_lifecycle_evidence": True,
            }
            return current

        store.mutate(update)


def _inject_fault(store: Any, fault: str) -> None:
    state = store.read()
    if state["run"]["phase"] != "initialized":
        return
    spec = state["spec"]
    if fault == "auth_prepared_only":
        workspace = _workspace(store.run_dir, "implement-1")
        _clone_without_remote(Path(spec["repository"]), workspace, spec["source_head"])

        def update(current: dict[str, Any]) -> dict[str, Any]:
            current["journals"]["implement-1"] = _journal(
                spec, store.run_dir, "implement-1", "implement"
            )
            current["run"]["phase"] = "prepared_without_authorization"
            return current

        store.mutate(update)
    elif fault == "auth_without_journal":
        store.mutate(
            lambda current: _set_auth_phase(current, "implement_authorized", "implement")
        )
    elif fault in {"auth_authorized_prepared", "duplicate_pre_start"}:
        _prepare_implement(store, state)
    elif fault == "auth_launch_no_result":
        _prepare_implement(store, state)
        current = store.read()
        journal = current["journals"]["implement-1"]
        command = _provider_argv(current["spec"], store.run_dir, journal, "normal")

        def update(next_state: dict[str, Any]) -> dict[str, Any]:
            entry = dict(next_state["journals"]["implement-1"])
            entry["state"] = "launch_intent"
            entry["launch_intent"] = {"argv": command, "mode": "normal"}
            next_state["journals"]["implement-1"] = entry
            next_state["run"]["phase"] = "implement_launch_intent"
            return next_state

        store.mutate(update)
    elif fault == "start_result":
        _prepare_implement(store, state)

        def update(next_state: dict[str, Any]) -> dict[str, Any]:
            journal = dict(next_state["journals"]["implement-1"])
            command = _provider_argv(next_state["spec"], store.run_dir, journal, "normal")
            journal["state"] = "started"
            journal["launch_intent"] = {"argv": command, "mode": "normal"}
            journal["started"] = {"pid": 424242}
            next_state["journals"]["implement-1"] = journal
            next_state["run"]["phase"] = "implement_started"
            return next_state

        store.mutate(update)
    elif fault == "artifact":
        _continue(store, mode="invalid-artifact")
    elif fault == "result_validate":
        _prepare_implement(store, state)
        _invoke_provider(store, "implement-1")
    elif fault == "effect_intent":
        _prepare_implement(store, state)
        _invoke_provider(store, "implement-1")
        _continue_one_step(store)
    elif fault == "duplicate_terminal":
        _continue(store)
    elif fault in {
        "review_authorized_prepared",
        "review_launch_no_result",
        "review_started_no_result",
    }:
        _continue_until(store, "implement_committed")
        _prepare_review(store, store.read())
        if fault == "review_launch_no_result":
            current = store.read()
            journal = current["journals"]["review-1"]
            command = _provider_argv(current["spec"], store.run_dir, journal, "normal")

            def update(next_state: dict[str, Any]) -> dict[str, Any]:
                entry = dict(next_state["journals"]["review-1"])
                entry["state"] = "launch_intent"
                entry["launch_intent"] = {"argv": command, "mode": "normal"}
                next_state["journals"]["review-1"] = entry
                return next_state

            store.mutate(update)
        elif fault == "review_started_no_result":
            current = store.read()
            journal = current["journals"]["review-1"]
            command = _provider_argv(current["spec"], store.run_dir, journal, "normal")

            def update(next_state: dict[str, Any]) -> dict[str, Any]:
                entry = dict(next_state["journals"]["review-1"])
                entry["state"] = "started"
                entry["launch_intent"] = {"argv": command, "mode": "normal"}
                entry["started"] = {"pid": 525252}
                next_state["journals"]["review-1"] = entry
                return next_state

            store.mutate(update)
    elif fault == "review_result_recover":
        _continue_until(store, "review_authorized")
        _invoke_provider(store, "review-1")
    elif fault == "state_drift":
        _corrupt_spec_checksum(store)
    elif fault == "runspec_rechecksum_drift":
        _drift_spec(store)
    elif fault == "journal_rechecksum_drift":
        _prepare_implement(store, state)
        _drift_journal(store)
    elif fault == "git_drift":
        _continue_until(store, "review_result")
        trusted = store.run_dir / "trusted-repo"
        (trusted / "result.txt").write_text("drifted after review\n", encoding="utf-8")
        _git(trusted, "add", "result.txt")
        _git(trusted, "commit", "-m", "Inject trusted git drift")
    else:
        raise SystemExit(f"unknown fault injection: {fault}")


def _set_auth_phase(current: dict[str, Any], phase: str, role: str) -> dict[str, Any]:
    current["run"]["phase"] = phase
    current["run"]["authorizations"] = [{"invocation_id": f"{role}-1", "role": role}]
    return current


def _drift_spec(store: Any) -> None:
    state = store.read()
    state["spec"]["source_head"] = "0" * 40
    _write_unvalidated_authority(store, state, valid_checksum=True)


def _corrupt_spec_checksum(store: Any) -> None:
    state = store.read()
    state["spec"]["source_head"] = "0" * 40
    _write_unvalidated_authority(store, state, valid_checksum=False)


def _drift_journal(store: Any) -> None:
    state = store.read()
    state["journals"]["implement-1"]["role"] = "review"
    _write_unvalidated_authority(store, state, valid_checksum=True)


def _write_unvalidated_authority(
    store: Any, state: dict[str, Any], valid_checksum: bool
) -> None:
    checksum = digest(state) if valid_checksum else "0" * 64
    if store.backend == "atomic":
        envelope = {"format": FORMAT, "payload": state, "checksum": checksum}
        store.path.write_text(
            json.dumps(envelope, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return
    with sqlite3.connect(store.path) as conn:
        conn.execute(
            "UPDATE records SET payload = ?, checksum = ? WHERE kind = ? AND key = ?",
            (json.dumps(state, sort_keys=True), checksum, "authority", "current"),
        )


def _status_from_state(store: Any, state: dict[str, Any] | None) -> dict[str, Any]:
    if state is None:
        return {
            "run_id": store.run_dir.name,
            "task_id": TASK_ID,
            "backend": store.backend,
            "phase": "unknown",
            "outcome": "EXTERNAL_OBSERVATION_UNKNOWN",
            "blocker": {"owner": "status", "source": "run state is absent"},
            "provider_invocation_observation": {},
            "terminal": None,
            "legal_next_action": "create a separately authorized run or inspect the state root",
            "prohibited_actions": ["status mutation", "provider start", "guessed repair"],
        }
    run = state["run"]
    phase = run["phase"]
    outcome = run.get("outcome")
    action = run.get("legal_next_action")
    blocker = run.get("blocker")
    if phase == "completed":
        try:
            _verify_trusted(store, run)
            _validate_review(store, state)
            outcome = "TERMINAL_IDEMPOTENT"
            action = "status or exact stop only"
            blocker = None
        except StateError as exc:
            outcome = exc.outcome
            action = exc.legal_next_action
            blocker = {"owner": "owner", "source": exc.source}
    elif phase == "stopped":
        outcome = "TERMINAL_IDEMPOTENT"
        action = "none"
        blocker = None
    elif phase == "prepared_without_authorization":
        outcome = "DENY_BEFORE_PROVIDER"
        action = "commit exact RunStore authorization before launch"
        blocker = {"owner": "runstore", "source": "prepared journal is not launch intent"}
    elif phase in {"implement_authorized", "review_authorized"}:
        invocation_id = "implement-1" if phase == "implement_authorized" else "review-1"
        role = "implement" if invocation_id == "implement-1" else "review"
        journal = state["journals"].get(invocation_id)
        if not isinstance(journal, dict):
            outcome = "OWNER_DECISION_REQUIRED"
            action = AUTHORIZED_JOURNAL_ACTION
            blocker = {"owner": "owner", "source": "authorized journal is absent"}
        elif journal.get("role") != role:
            outcome = "DENY_BEFORE_PROVIDER"
            action = "preserve files and diagnose exact run identity"
            blocker = {"owner": "owner", "source": "InvocationJournal identity drift"}
        elif journal.get("state") == "prepared":
            outcome = "SAFE_CONTINUE"
            action = "invoke once after exact gates and journal revalidation"
            blocker = None
        elif journal.get("state") in {"result", "validated"}:
            outcome = "SAFE_CONTINUE"
            action = (
                "skip provider and run frozen postflight against exact durable workspace"
                if role == "implement"
                else "skip provider and validate the durable review result"
            )
            blocker = None
        else:
            outcome = "AMBIGUOUS_NO_REPLAY"
            action = "preserve exact process/workspace/evidence for owner decision"
            blocker = {"owner": "journal", "source": "authorized invocation is past prepared"}
    elif phase in {"implement_launch_intent", "implement_started"}:
        outcome = "AMBIGUOUS_NO_REPLAY"
        action = "preserve exact process/workspace/evidence for owner decision"
        blocker = {"owner": "journal", "source": "launch/start lacks recoverable result"}
    elif phase == "implement_result":
        try:
            _validate_implementation(store, state)
            outcome = "SAFE_CONTINUE"
            action = "skip provider and run frozen postflight against exact durable workspace"
            blocker = None
        except StateError as exc:
            outcome = exc.outcome
            action = exc.legal_next_action
            blocker = {"owner": "owner", "source": exc.source}
    elif phase == "implement_committed":
        try:
            _verify_trusted(store, run)
            outcome = "SAFE_CONTINUE"
            action = "revalidate exact effects and persist one local review intent"
            blocker = None
        except StateError as exc:
            outcome = exc.outcome
            action = exc.legal_next_action
            blocker = {"owner": "owner", "source": exc.source}
    elif phase == "review_result":
        try:
            _verify_trusted(store, run)
            _validate_review(store, state)
            outcome = "SAFE_CONTINUE"
            action = "revalidate exact Git/workspace identity and persist terminal"
            blocker = None
        except StateError as exc:
            outcome = exc.outcome
            action = exc.legal_next_action
            blocker = {"owner": "owner", "source": exc.source}
    elif phase == "blocked":
        outcome = outcome or "OWNER_DECISION_REQUIRED"
        action = action or "preserve evidence for owner decision"
        blocker = blocker or {"owner": "owner", "source": "blocked"}
    return {
        "run_id": run.get("run_id", store.run_dir.name),
        "task_id": TASK_ID,
        "backend": store.backend,
        "phase": phase,
        "outcome": outcome,
        "blocker": blocker,
        "provider_invocation_observation": {
            "counts": _counter(store.run_dir),
            "journals": _journal_observations(state),
        },
        "terminal": run.get("terminal") if blocker is None else None,
        "legal_next_action": action,
        "prohibited_actions": [
            "status mutation",
            "guessed repair",
            "provider replay without exact durable authorization",
            "remote Git/GitHub/ACK/lifecycle claim",
        ],
    }


def _journal_observations(state: dict[str, Any]) -> dict[str, Any]:
    observations: dict[str, Any] = {}
    for invocation_id, journal in sorted(state["journals"].items()):
        observations[invocation_id] = {
            "role": journal.get("role"),
            "state": journal.get("state"),
            "has_launch_intent": journal.get("launch_intent") is not None,
            "has_started": journal.get("started") is not None,
            "has_result": journal.get("result") is not None,
            "has_validated": journal.get("validated") is not None,
        }
    return observations


def _error_status(store: Any, error: StateError) -> dict[str, Any]:
    return {
        "run_id": store.run_dir.name,
        "task_id": TASK_ID,
        "backend": store.backend,
        "phase": "state_drift",
        "outcome": error.outcome,
        "blocker": {"owner": "owner", "source": error.source},
        "provider_invocation_observation": {
            "counts": _counter(store.run_dir),
            "journals": {},
        },
        "terminal": None,
        "legal_next_action": error.legal_next_action,
        "prohibited_actions": ["provider start", "mutation", "guessed repair"],
    }


def _status(store: Any) -> dict[str, Any]:
    try:
        if not store.exists():
            return _status_from_state(store, None)
        return _status_from_state(store, store.read())
    except StateError as exc:
        return _error_status(store, exc)


def _run(args: argparse.Namespace) -> dict[str, Any]:
    store = make_store(args.store, Path(args.state_root), args.run_id)
    try:
        spec = _compiled_spec(Path(args.repo), Path(args.provider), args.run_id)
        store.initialize(spec)
        state = store.read()
        if state["run"]["phase"] in {"completed", "blocked", "stopped"}:
            return _status(store)
        if args.fault:
            try:
                _inject_fault(store, args.fault)
            except StateError as exc:
                if exc.outcome == "HANDLER_FAILURE_NO_ACK":
                    _mark_failure(store, exc)
                else:
                    return _error_status(store, exc)
        else:
            try:
                _continue(store)
            except StateError as exc:
                if exc.outcome == "HANDLER_FAILURE_NO_ACK":
                    _mark_failure(store, exc)
                else:
                    return _error_status(store, exc)
        return _status(store)
    except WriterBusy as exc:
        return _error_status(store, exc)
    except StateError as exc:
        return _error_status(store, exc)


def _stop(args: argparse.Namespace) -> dict[str, Any]:
    store = make_store(args.store, Path(args.state_root), args.run_id)
    try:
        if store.writer_active():
            raise WriterBusy("writer active during exact stop")
        state = store.read()
        for invocation_id, journal in state["journals"].items():
            if journal.get("state") in {"launch_intent", "started"}:
                raise StateError(
                    "DENY_BEFORE_MUTATION",
                    "preserve process/lease records and diagnose exact identity",
                    f"active invocation {invocation_id}",
                )

        def update(current: dict[str, Any]) -> dict[str, Any]:
            current["run"]["phase"] = "stopped"
            current["run"]["stop"] = {
                "kind": "exact-local-stop",
                "native_manager": False,
                "unequal_lifecycle_evidence": True,
            }
            current["run"]["terminal"] = current["run"].get("terminal") or {"outcome": "stopped"}
            return current

        stopped = store.mutate(update)
        return _status_from_state(store, stopped)
    except StateError as exc:
        return _error_status(store, exc)


def _maintenance(args: argparse.Namespace) -> dict[str, Any]:
    store = make_store(args.store, Path(args.state_root), args.run_id)
    try:
        if args.maintenance == "backup":
            return store.backup()
        if args.maintenance == "restore":
            restored = store.restore()
            return _status_from_state(store, restored)
        if args.maintenance == "delete-derived":
            store.delete_derived()
            return _status(store)
        if args.maintenance == "forge-derived":
            store.forge_derived({"phase": "completed", "authorizes_provider": True})
            return _status(store)
        if args.maintenance == "migrate":
            return {"outcome": "SAFE_CONTINUE", "migration": store.migrate()}
        if args.maintenance == "hold-writer":
            store.hold_writer(args.seconds)
            return {"outcome": "SAFE_CONTINUE", "held_seconds": args.seconds}
        if args.maintenance == "seed-v1":
            if args.store != "sqlite":
                raise SystemExit("seed-v1 applies only to sqlite")
            spec = _compiled_spec(Path(args.repo), Path(args.provider), args.run_id)
            create_sqlite_v1(store.run_dir, new_authority(spec))
            return {"outcome": "SAFE_CONTINUE", "schema_version": 1}
        if args.maintenance == "force-newer-schema":
            if args.store != "sqlite":
                raise SystemExit("force-newer-schema applies only to sqlite")
            force_sqlite_schema(store.run_dir, SCHEMA_VERSION + 1)
            return _status(store)
    except StateError as exc:
        return _error_status(store, exc)
    raise SystemExit(f"unknown maintenance command: {args.maintenance}")


def _windows(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "task_id": TASK_ID,
        "external_boundaries": [
            "provider execution",
            "Git process and filesystem",
            "Agent Bus transport/ACK",
            "GitHub/PR/CI",
            "native lifecycle manager",
            "cross-host state ownership",
        ],
        "windows": {
            "W-AUTH": {"atomic": "eliminated", "sqlite": "eliminated"},
            "W-RESULT": {"atomic": "eliminated", "sqlite": "eliminated"},
            "W-HANDOFF": {"atomic": "eliminated", "sqlite": "eliminated"},
            "W-TERMINAL": {"atomic": "eliminated", "sqlite": "eliminated"},
        },
        "sqlite_unique_cost": [
            "schema migration gate",
            "database lock behavior",
            "backup artifact handling",
            "platform sqlite compatibility",
        ],
    }


def _evaluate(args: argparse.Namespace) -> dict[str, Any]:
    evidence_path = Path(args.evidence)
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    facts = evidence.get("facts")
    if not isinstance(facts, dict):
        facts = {}
    keys = set(facts)
    missing = sorted(GATE_FACT_KEYS - keys)
    extra = sorted(keys - GATE_FACT_KEYS)
    non_boolean = sorted(key for key, value in facts.items() if not isinstance(value, bool))
    false_facts = sorted(key for key in GATE_FACT_KEYS if facts.get(key) is False)
    task_id_matches = evidence.get("task_id") == TASK_ID
    eligible = (
        task_id_matches
        and not missing
        and not extra
        and not non_boolean
        and not false_facts
    )
    return {
        "task_id": TASK_ID,
        "evidence_task_id_matches": task_id_matches,
        "evidence": str(evidence_path),
        "result": "SQLITE_MEETS_MINIMUM_GATE" if eligible else "RETAIN_ATOMIC_FILE_BASELINE",
        "facts": {key: facts.get(key) for key in sorted(GATE_FACT_KEYS)},
        "missing_keys": missing,
        "extra_keys": extra,
        "non_boolean_keys": non_boolean,
        "false_facts": false_facts,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("run", "status", "stop", "maintenance"):
        command = sub.add_parser(name)
        command.add_argument("--store", choices=["atomic", "sqlite"], required=True)
        command.add_argument("--state-root", required=True)
        command.add_argument("--run-id", default=TASK_ID)
        if name == "run":
            command.add_argument("--repo", required=True)
            command.add_argument("--provider", required=True)
            command.add_argument("--fault", default="")
        if name == "maintenance":
            command.add_argument(
                "maintenance",
                choices=[
                    "backup",
                    "restore",
                    "delete-derived",
                    "forge-derived",
                    "migrate",
                    "hold-writer",
                    "seed-v1",
                    "force-newer-schema",
                ],
            )
            command.add_argument("--repo", default=".")
            command.add_argument(
                "--provider",
                default="tests/fixtures/runtime_v2_shared_slice_provider.py",
            )
            command.add_argument("--seconds", type=float, default=1.0)
    sub.add_parser("windows")
    evaluate = sub.add_parser("evaluate")
    evaluate.add_argument("--evidence", required=True)
    args = parser.parse_args()
    if args.command == "run":
        result = _run(args)
    elif args.command == "status":
        result = _status(make_store(args.store, Path(args.state_root), args.run_id))
    elif args.command == "stop":
        result = _stop(args)
    elif args.command == "maintenance":
        result = _maintenance(args)
    elif args.command == "windows":
        result = _windows(args)
    else:
        result = _evaluate(args)
    sys.stdout.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
