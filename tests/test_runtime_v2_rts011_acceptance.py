"""Disposable full-loop acceptance for Runtime v2 RTS-011.

The fixture uses the shipped persistence and recovery primitives with real local
Git repositories and real child processes. Provider intelligence, GitHub facts,
transport delivery, and ACK observations are deliberately synthetic.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
MODULE_PATH = SCRIPTS_DIR / "awf_role.py"
SPEC = importlib.util.spec_from_file_location("awf_role_rts011", MODULE_PATH)
assert SPEC and SPEC.loader
awf_role = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(awf_role)


SCRIPTED_PROVIDER = Path(__file__).parent / "fixtures" / "runtime_v2_scripted_provider.py"
TASK_ID = "runtime-v2-rts-011-deterministic-rework-acceptance"
BRANCH = f"codex/{TASK_ID}"
RUN_ID = f"task-{TASK_ID}"


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)
    return completed.stdout.strip()


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _clone_at(source: Path, destination: Path, commit: str) -> Path:
    subprocess.run(
        ["git", "clone", "--no-hardlinks", str(source), str(destination)],
        check=True,
        capture_output=True,
        text=True,
    )
    _git(destination, "checkout", "--detach", commit)
    return destination


def _provenance(base_sha: str, head_sha: str) -> dict[str, object]:
    return {
        "provenance_version": "awf.pr-provenance.v1",
        "upstream_repo": "synthetic/runtime-v2",
        "upstream_remote": "upstream",
        "base_ref": "main",
        "base_sha": base_sha,
        "head_repo": "synthetic/runtime-v2-fork",
        "head_remote": "fork",
        "head_ref": BRANCH,
        "head_sha": head_sha,
        "pull_request": 11011,
    }


def _input_context(payload: dict[str, object]) -> dict[str, object]:
    return {
        "key": payload["awf_delivery_id"],
        "delivery_id": payload["awf_delivery_id"],
        "payload_sha256": payload["awf_payload_sha256"],
        "source_event_id": payload["awf_source_event_id"],
    }


def _initial_input() -> dict[str, object]:
    payload = {"task_id": TASK_ID, "branch": BRANCH}
    payload_hash = awf_role.canonical_payload_sha256(payload)
    delivery_id = awf_role.make_delivery_id("architect", "task:awf-impl-v3", payload_hash, 100)
    return {
        "key": delivery_id,
        "delivery_id": delivery_id,
        "payload_sha256": payload_hash,
        "source_event_id": 100,
    }


def _invoke_provider(
    evidence: awf_role.RunEvidence,
    *,
    action: str,
    counter: Path,
    workspace: Path,
    report: str = "",
) -> None:
    command = [
        sys.executable,
        str(SCRIPTED_PROVIDER),
        "--action",
        action,
        "--counter",
        str(counter),
        "--workspace",
        str(workspace),
    ]
    if report:
        command.extend(["--report", report])
    process = subprocess.Popen(command, cwd=workspace)
    evidence.record("opencode_start", opencode_pid=process.pid)
    return_code = process.wait()
    evidence.record("opencode_exit", opencode_rc=return_code)
    assert return_code == 0


def _begin_checkpoint(
    evidence: awf_role.RunEvidence,
    input_context: dict[str, object],
    *,
    role: str,
    source_commit: str,
    provenance: dict[str, object],
    lineage: tuple[str, str] = ("", ""),
) -> tuple[Path, dict[str, object]]:
    return awf_role.begin_recovery_checkpoint(
        evidence,
        input_context,
        role=role,
        branch=BRANCH,
        source_commit=source_commit,
        provenance=provenance,
        workspace_lineage_delivery_id=lineage[0],
        workspace_lineage_checkpoint_sha256=lineage[1],
    )


def _advance(
    evidence: awf_role.RunEvidence,
    path: Path,
    checkpoint: dict[str, object],
    phase: str,
    **facts: object,
) -> dict[str, object]:
    return awf_role.advance_recovery_checkpoint(evidence, path, checkpoint, phase, **facts)


def _provider_checkpoint(
    evidence: awf_role.RunEvidence,
    input_context: dict[str, object],
    *,
    role: str,
    source_commit: str,
    provenance: dict[str, object],
    workspace: Path,
    counter: Path,
    action: str,
    report: str = "",
    leave_started: bool = False,
    lineage: tuple[str, str] = ("", ""),
) -> tuple[Path, dict[str, object]]:
    checkpoint_path, checkpoint = _begin_checkpoint(
        evidence,
        input_context,
        role=role,
        source_commit=source_commit,
        provenance=provenance,
        lineage=lineage,
    )
    manifest = awf_role.durable_model_manifest_sha256(str(workspace))
    checkpoint = _advance(
        evidence,
        checkpoint_path,
        checkpoint,
        "model_started",
        model_workspace=str(workspace.resolve()),
        model_manifest_sha256=manifest,
        model_event_id=evidence.event_id,
        model_process="opencode",
    )
    _invoke_provider(
        evidence,
        action=action,
        counter=counter,
        workspace=workspace,
        report=report,
    )
    if not leave_started:
        checkpoint = _advance(
            evidence,
            checkpoint_path,
            checkpoint,
            "model_completed",
            model_workspace=str(workspace.resolve()),
            model_manifest_sha256=manifest,
            model_event_id=evidence.event_id,
            model_process="opencode",
        )
    return checkpoint_path, checkpoint


def _complete_review_checkpoint(
    evidence: awf_role.RunEvidence,
    checkpoint_path: Path,
    checkpoint: dict[str, object],
    *,
    report: Path,
    trusted_repo: Path,
    provenance: dict[str, object],
) -> dict[str, object]:
    trusted_report = awf_role.import_model_report(
        str(report.parent), str(trusted_repo), report.name
    )
    report_sha = hashlib.sha256(trusted_report.read_bytes()).hexdigest()
    manifest = awf_role.durable_model_manifest_sha256(str(report.parent))
    checkpoint = _advance(
        evidence,
        checkpoint_path,
        checkpoint,
        "model_imported",
        review_report_sha256=report_sha,
        postflight_model_manifest_sha256=manifest,
    )
    return _advance(
        evidence,
        checkpoint_path,
        checkpoint,
        "pr_tuple_verified",
        verified_provenance=awf_role.provenance_payload(provenance),
    )


def _handoff(
    monkeypatch: pytest.MonkeyPatch,
    observer: list[str],
    *,
    label: str,
    evidence: awf_role.RunEvidence,
    input_context: dict[str, object],
    checkpoint_path: Path,
    checkpoint: dict[str, object],
    action: str,
    source_commit: str,
    evidence_commit: str,
    to_role: str,
    event_type: str,
    payload_base: dict[str, object],
    provenance: dict[str, object],
) -> tuple[dict[str, object], dict[str, object]]:
    payload = awf_role.build_delivery_payload(evidence.role, event_type, payload_base, evidence)
    outbox = awf_role.prepare_outbox(
        evidence,
        input_context,
        action=action,
        branch=BRANCH,
        source_commit=source_commit,
        evidence_commit=evidence_commit,
        to_role=to_role,
        event_type=event_type,
        payload=payload,
        provenance=provenance,
    )
    assert outbox is not None
    outbox_path, outbox_record = outbox
    assert json.loads(outbox_path.read_text(encoding="utf-8"))["status"] == "prepared"
    observer.append(f"{label}:outbox_prepared")
    checkpoint = _advance(
        evidence,
        checkpoint_path,
        checkpoint,
        "outbox_prepared",
        outbox_delivery_id=payload["awf_delivery_id"],
    )

    def synthetic_send(*_args: object, **_kwargs: object) -> bool:
        observer.append(f"{label}:synthetic_send")
        return True

    monkeypatch.setattr(awf_role, "send_event", synthetic_send)
    assert awf_role.deliver_outbox(evidence, outbox_path, outbox_record)
    assert json.loads(outbox_path.read_text(encoding="utf-8"))["status"] == "sent"
    observer.append(f"{label}:outbox_sent")
    checkpoint = _advance(
        evidence,
        checkpoint_path,
        checkpoint,
        "outbox_sent",
        outbox_delivery_id=payload["awf_delivery_id"],
    )
    awf_role.complete_inbox(
        evidence,
        str(input_context["delivery_id"]),
        str(input_context["payload_sha256"]),
    )
    observer.append(f"{label}:inbox_completed")
    observer.append(f"{label}:handler_success")
    observer.append(f"{label}:synthetic_ack_observed")
    return payload, checkpoint


def _assert_order(observer: list[str], label: str) -> None:
    expected = [
        f"{label}:outbox_prepared",
        f"{label}:synthetic_send",
        f"{label}:outbox_sent",
        f"{label}:inbox_completed",
        f"{label}:handler_success",
        f"{label}:synthetic_ack_observed",
    ]
    positions = [observer.index(item) for item in expected]
    assert positions == sorted(positions)


def test_rts011_disposable_scripted_provider_restart_acceptance(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo = tmp_path / "disposable-repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "RTS-011 Fixture")
    _git(repo, "config", "user.email", "rts011@example.invalid")
    _git(repo, "config", "core.autocrlf", "false")
    (repo / "task.md").write_text("# Disposable RTS-011 Task\n", encoding="utf-8")
    (repo / "impl.md").write_text("# Disposable Implementation Report\n", encoding="utf-8")
    base_commit = _commit(repo, "freeze disposable inputs")
    _git(repo, "switch", "-c", BRANCH)

    state_root = tmp_path / "disposable-state"
    counter_path = tmp_path / "scripted-provider-counts.json"
    observer: list[str] = []
    ledger = awf_role.RunLedger(state_root, RUN_ID)
    packet = awf_role.build_context_packet(
        run_id=RUN_ID,
        taskcard="task.md",
        frozen_base=base_commit,
        branch=BRANCH,
        authority_manifest={
            "sha256": "sha256:" + "a" * 64,
            "allowed_operations": ["diagnose", "endpoint_discovery", "listener_restart"],
        },
        next_action="implement",
        stage="implement",
        current_stage_evidence_commit=base_commit,
    )
    ledger.initialize(packet, stage="implement", max_attempts=1, rework_budget=1)

    implement_input = _initial_input()
    assert ledger.pre_invocation_gate(
        event_id=101,
        event_type="task:awf-impl-v3",
        role="coder",
        delivery_id=str(implement_input["delivery_id"]),
        payload_sha256=str(implement_input["payload_sha256"]),
        stage="implement",
        attempt=1,
        current_stage_evidence_commit=base_commit,
    ).allowed
    implement_evidence = awf_role.RunEvidence(101, "coder", state_root=state_root)
    implement_workspace = Path(
        awf_role.prepare_model_workspace(
            str(repo), base_commit, state_dir=implement_evidence.run_dir
        )
    )
    implement_path, implement_checkpoint = _provider_checkpoint(
        implement_evidence,
        implement_input,
        role="coder",
        source_commit=base_commit,
        provenance=_provenance(base_commit, base_commit),
        workspace=implement_workspace,
        counter=counter_path,
        action="implement",
    )
    imported_tree = awf_role.import_model_delta(str(implement_workspace), str(repo))
    control_sha = awf_role.durable_model_control_sha256(str(implement_workspace))
    implementation_commit = _commit(repo, "trusted scripted implementation")
    trusted_manifest = awf_role.advance_model_workspace_to_trusted_commit(
        implement_evidence,
        str(implement_workspace),
        str(repo),
        source_commit=base_commit,
        imported_tree=imported_tree,
        trusted_commit=implementation_commit,
        expected_control_sha256=control_sha,
    )
    implementation_provenance = _provenance(base_commit, implementation_commit)
    for phase, facts in (
        ("postflight_completed", {"postflight_model_manifest_sha256": trusted_manifest}),
        (
            "model_imported",
            {
                "imported_tree": imported_tree,
                "trusted_workspace_source_commit": base_commit,
                "trusted_workspace_control_sha256": control_sha,
            },
        ),
        (
            "commit_created",
            {
                "commit_sha": implementation_commit,
                "trusted_workspace_commit_sha": implementation_commit,
                "trusted_workspace_manifest_sha256": trusted_manifest,
            },
        ),
        ("fork_sha_verified", {"head_sha": implementation_commit}),
        (
            "pr_tuple_verified",
            {"verified_provenance": awf_role.provenance_payload(implementation_provenance)},
        ),
    ):
        implement_checkpoint = _advance(
            implement_evidence,
            implement_path,
            implement_checkpoint,
            phase,
            **facts,
        )
    review1_payload, implement_checkpoint = _handoff(
        monkeypatch,
        observer,
        label="implement",
        evidence=implement_evidence,
        input_context=implement_input,
        checkpoint_path=implement_path,
        checkpoint=implement_checkpoint,
        action="coder.review_handoff",
        source_commit=base_commit,
        evidence_commit=implementation_commit,
        to_role="reviewer",
        event_type="task:awf-review-v3",
        payload_base={
            "task_id": TASK_ID,
            "branch": BRANCH,
            "commit": implementation_commit,
            **awf_role.provenance_payload(implementation_provenance),
        },
        provenance=implementation_provenance,
    )

    review1_input = _input_context(review1_payload)
    assert ledger.pre_invocation_gate(
        event_id=102,
        event_type="task:awf-review-v3",
        role="reviewer",
        delivery_id=str(review1_input["delivery_id"]),
        payload_sha256=str(review1_input["payload_sha256"]),
        stage="review",
        attempt=1,
        current_stage_evidence_commit=implementation_commit,
    ).allowed
    review1_evidence = awf_role.RunEvidence(102, "reviewer", state_root=state_root)
    review1_workspace = Path(
        awf_role.prepare_model_workspace(
            str(repo), implementation_commit, state_dir=review1_evidence.run_dir
        )
    )
    review1_path, review1_checkpoint = _provider_checkpoint(
        review1_evidence,
        review1_input,
        role="reviewer",
        source_commit=implementation_commit,
        provenance=implementation_provenance,
        workspace=review1_workspace,
        counter=counter_path,
        action="review-request-changes",
        report="review-1.md",
    )
    review1_report = review1_workspace / "review-1.md"
    review1_normalized = awf_role.parse_review_report(review1_report)
    assert review1_normalized["verdict"] == "REQUEST_CHANGES"
    assert review1_normalized["deterministic_failures"]
    review1_checkpoint = _complete_review_checkpoint(
        review1_evidence,
        review1_path,
        review1_checkpoint,
        report=review1_report,
        trusted_repo=_clone_at(
            repo, tmp_path / "review1-trusted-repo", implementation_commit
        ),
        provenance=implementation_provenance,
    )
    rework_payload, review1_checkpoint = _handoff(
        monkeypatch,
        observer,
        label="review1",
        evidence=review1_evidence,
        input_context=review1_input,
        checkpoint_path=review1_path,
        checkpoint=review1_checkpoint,
        action="reviewer.request_changes",
        source_commit=implementation_commit,
        evidence_commit=implementation_commit,
        to_role="coder",
        event_type="task:awf-rework-v3",
        payload_base={
            "task_id": TASK_ID,
            "branch": BRANCH,
            "commit": implementation_commit,
            "review_report": review1_normalized,
            **awf_role.provenance_payload(implementation_provenance),
        },
        provenance=implementation_provenance,
    )
    assert not ledger.summary_path.exists()

    rework_input = _input_context(rework_payload)
    assert ledger.pre_invocation_gate(
        event_id=103,
        event_type="task:awf-rework-v3",
        role="coder",
        delivery_id=str(rework_input["delivery_id"]),
        payload_sha256=str(rework_input["payload_sha256"]),
        stage="rework",
        attempt=1,
        rework=True,
        current_stage_evidence_commit=implementation_commit,
    ).allowed
    rework_evidence = awf_role.RunEvidence(103, "coder", state_root=state_root)
    unopened_rework_state = [
        awf_role.delivery_state_path(
            rework_evidence, kind, str(rework_input["delivery_id"])
        )
        for kind in ("checkpoint", "outbox", "inbox")
    ]
    assert not any(path.exists() for path in unopened_rework_state)
    before_duplicate = json.loads(counter_path.read_text(encoding="utf-8"))
    duplicate = ledger.pre_invocation_gate(
        event_id=103,
        event_type="task:awf-rework-v3",
        role="coder",
        delivery_id=str(rework_input["delivery_id"]),
        payload_sha256=str(rework_input["payload_sha256"]),
        stage="rework",
        attempt=1,
        rework=True,
        current_stage_evidence_commit=implementation_commit,
    )
    assert not duplicate.allowed and duplicate.reason == "duplicate_event"
    assert json.loads(counter_path.read_text(encoding="utf-8")) == before_duplicate
    assert not any(path.exists() for path in unopened_rework_state)

    rework_args = argparse.Namespace(branch=BRANCH, commit=implementation_commit, run_id=RUN_ID)
    lineage = awf_role.resolve_fresh_rework_workspace_lineage(
        rework_evidence, rework_args, implementation_provenance
    )
    rework_path, rework_checkpoint = _begin_checkpoint(
        rework_evidence,
        rework_input,
        role="coder",
        source_commit=implementation_commit,
        provenance=implementation_provenance,
        lineage=lineage,
    )
    drifted_checkpoint = {
        **rework_checkpoint,
        "workspace_lineage_checkpoint_sha256": "sha256:" + "0" * 64,
    }
    with pytest.raises(SystemExit, match="1"):
        awf_role.restore_rework_workspace_lineage(
            rework_evidence,
            rework_args,
            implementation_provenance,
            drifted_checkpoint,
        )
    before_rework = json.loads(counter_path.read_text(encoding="utf-8"))
    restored_workspace, restored_manifest = awf_role.restore_rework_workspace_lineage(
        rework_evidence,
        rework_args,
        implementation_provenance,
        rework_checkpoint,
    )
    assert restored_workspace == str(implement_workspace.resolve())
    assert restored_manifest == trusted_manifest
    rework_checkpoint = _advance(
        rework_evidence,
        rework_path,
        rework_checkpoint,
        "model_started",
        model_workspace=restored_workspace,
        model_manifest_sha256=restored_manifest,
        model_event_id=103,
        model_process="opencode",
    )
    _invoke_provider(
        rework_evidence,
        action="rework",
        counter=counter_path,
        workspace=Path(restored_workspace),
    )
    assert json.loads(counter_path.read_text(encoding="utf-8"))["rework"] == 1
    restarted_evidence = awf_role.RunEvidence(103, "coder", state_root=state_root)
    assert awf_role.recovery_model_policy(rework_checkpoint) == "recover_or_fail"
    recovered_checkpoint = awf_role.recover_completed_model_checkpoint(
        restarted_evidence, rework_path, rework_checkpoint
    )
    assert recovered_checkpoint is not None
    rework_checkpoint = recovered_checkpoint
    assert rework_checkpoint["phase"] == "model_completed"
    assert awf_role.recovery_model_policy(rework_checkpoint) == "skip"
    assert json.loads(counter_path.read_text(encoding="utf-8"))["rework"] == 1
    assert before_rework["rework"] == 0

    rework_tree = awf_role.import_model_delta(restored_workspace, str(repo))
    rework_control_sha = awf_role.durable_model_control_sha256(restored_workspace)
    rework_commit = _commit(repo, "trusted scripted rework")
    rework_manifest = awf_role.advance_model_workspace_to_trusted_commit(
        restarted_evidence,
        restored_workspace,
        str(repo),
        source_commit=implementation_commit,
        imported_tree=rework_tree,
        trusted_commit=rework_commit,
        expected_control_sha256=rework_control_sha,
    )
    rework_provenance = _provenance(base_commit, rework_commit)
    for phase, facts in (
        ("postflight_completed", {"postflight_model_manifest_sha256": rework_manifest}),
        (
            "model_imported",
            {
                "imported_tree": rework_tree,
                "trusted_workspace_source_commit": implementation_commit,
                "trusted_workspace_control_sha256": rework_control_sha,
            },
        ),
        (
            "commit_created",
            {
                "commit_sha": rework_commit,
                "trusted_workspace_commit_sha": rework_commit,
                "trusted_workspace_manifest_sha256": rework_manifest,
            },
        ),
        ("fork_sha_verified", {"head_sha": rework_commit}),
        (
            "pr_tuple_verified",
            {"verified_provenance": awf_role.provenance_payload(rework_provenance)},
        ),
    ):
        rework_checkpoint = _advance(
            restarted_evidence,
            rework_path,
            rework_checkpoint,
            phase,
            **facts,
        )
    review2_payload, rework_checkpoint = _handoff(
        monkeypatch,
        observer,
        label="rework",
        evidence=restarted_evidence,
        input_context=rework_input,
        checkpoint_path=rework_path,
        checkpoint=rework_checkpoint,
        action="coder.review_handoff",
        source_commit=implementation_commit,
        evidence_commit=rework_commit,
        to_role="reviewer",
        event_type="task:awf-review-v3",
        payload_base={
            "task_id": TASK_ID,
            "branch": BRANCH,
            "commit": rework_commit,
            **awf_role.provenance_payload(rework_provenance),
        },
        provenance=rework_provenance,
    )

    review2_input = _input_context(review2_payload)
    assert ledger.pre_invocation_gate(
        event_id=104,
        event_type="task:awf-review-v3",
        role="reviewer",
        delivery_id=str(review2_input["delivery_id"]),
        payload_sha256=str(review2_input["payload_sha256"]),
        stage="review",
        attempt=1,
        current_stage_evidence_commit=rework_commit,
    ).allowed
    illegal_attempt = ledger.pre_invocation_gate(
        event_id=199,
        event_type="task:awf-review-v3",
        role="reviewer",
        delivery_id="awf:" + "e" * 64,
        payload_sha256="sha256:" + "e" * 64,
        stage="review",
        attempt=2,
        current_stage_evidence_commit=rework_commit,
    )
    assert not illegal_attempt.allowed and illegal_attempt.reason == "attempt_budget_exceeded"
    review2_evidence = awf_role.RunEvidence(104, "reviewer", state_root=state_root)
    review2_workspace = Path(
        awf_role.prepare_model_workspace(
            str(repo), rework_commit, state_dir=review2_evidence.run_dir
        )
    )
    review2_path, review2_checkpoint = _provider_checkpoint(
        review2_evidence,
        review2_input,
        role="reviewer",
        source_commit=rework_commit,
        provenance=rework_provenance,
        workspace=review2_workspace,
        counter=counter_path,
        action="review-pass",
        report="review-2.md",
    )
    review2_report = review2_workspace / "review-2.md"
    review2_normalized = awf_role.parse_review_report(review2_report)
    assert review2_normalized["verdict"] == "PASS"
    review2_checkpoint = _complete_review_checkpoint(
        review2_evidence,
        review2_path,
        review2_checkpoint,
        report=review2_report,
        trusted_repo=_clone_at(repo, tmp_path / "review2-trusted-repo", rework_commit),
        provenance=rework_provenance,
    )
    terminal_payload, review2_checkpoint = _handoff(
        monkeypatch,
        observer,
        label="review2",
        evidence=review2_evidence,
        input_context=review2_input,
        checkpoint_path=review2_path,
        checkpoint=review2_checkpoint,
        action="reviewer.pass",
        source_commit=rework_commit,
        evidence_commit=rework_commit,
        to_role="architect",
        event_type="decision:awf-ready-v3",
        payload_base={
            "task_id": TASK_ID,
            "branch": BRANCH,
            "commit": rework_commit,
            "review_report": review2_normalized,
            **awf_role.provenance_payload(rework_provenance),
        },
        provenance=rework_provenance,
    )

    terminal_input = _input_context(terminal_payload)
    architect_evidence = awf_role.RunEvidence(105, "architect", state_root=state_root)
    monkeypatch.setenv("AWF_REPO_DIR", str(repo))
    monkeypatch.setenv("AWF_CONTROL_PLANE", "1")
    monkeypatch.setattr(
        awf_role,
        "validate_input_delivery",
        lambda *_args, **_kwargs: terminal_input,
    )
    monkeypatch.setattr(
        awf_role,
        "provenance_from_args",
        lambda *_args, **_kwargs: rework_provenance,
    )
    monkeypatch.setattr(
        awf_role,
        "prepare_terminal_workspace",
        lambda *_args, **_kwargs: str(repo),
    )
    real_complete_inbox = awf_role.complete_inbox

    def terminal_inbox_after_ledger(
        evidence: awf_role.RunEvidence,
        delivery_id: str,
        payload_sha256: str,
    ) -> None:
        terminal_ledger, _ = ledger.recover()
        assert terminal_ledger["terminal_state"] == "completed"
        assert ledger.summary_path.is_file()
        observer.append("terminal:ledger_and_summary_durable")
        real_complete_inbox(evidence, delivery_id, payload_sha256)
        observer.append("terminal:inbox_completed")

    monkeypatch.setattr(awf_role, "complete_inbox", terminal_inbox_after_ledger)
    architect_args = argparse.Namespace(
        evidence=architect_evidence,
        event_id=105,
        input_type="decision:awf-ready-v3",
        branch=BRANCH,
        card="task.md",
        commit=rework_commit,
        report="impl.md",
        review_report="review-2.md",
        review_feedback=json.dumps(review2_normalized),
        run_id=RUN_ID,
    )
    assert awf_role.role_architect(architect_args) == 0
    observer.append("terminal:handler_success")
    observer.append("terminal:synthetic_ack_observed")
    terminal_ledger, terminal_packet = ledger.recover()
    terminal_sequence = terminal_ledger["sequence"]
    assert terminal_ledger["terminal_state"] == "completed"
    assert terminal_ledger["terminal"]["reason"] == "review_passed"
    assert terminal_packet["next_action"] == "stop"
    architect_args.evidence = awf_role.RunEvidence(105, "architect", state_root=state_root)
    assert awf_role.role_architect(architect_args) == 0
    assert ledger.recover()[0]["sequence"] == terminal_sequence

    counts = json.loads(counter_path.read_text(encoding="utf-8"))
    assert counts == {
        "calls": [
            "implement",
            "review-request-changes",
            "rework",
            "review-pass",
        ],
        "implement": 1,
        "rework": 1,
        "review": 2,
    }
    assert terminal_ledger["attempts"] == 4
    assert terminal_ledger["reworks"] == 1
    assert terminal_ledger["stage_attempts"] == {
        "implement": 1,
        "review": 2,
        "rework": 1,
    }
    for label in ("implement", "review1", "rework", "review2"):
        _assert_order(observer, label)
    terminal_order = [
        observer.index("terminal:ledger_and_summary_durable"),
        observer.index("terminal:inbox_completed"),
        observer.index("terminal:handler_success"),
        observer.index("terminal:synthetic_ack_observed"),
    ]
    assert terminal_order == sorted(terminal_order)

    acceptance_record = {
        "format": "awf.runtime-v2-rts011-acceptance.v1",
        "run_id": RUN_ID,
        "branch": BRANCH,
        "disposable_repo": str(repo),
        "disposable_state_root": str(state_root),
        "deliveries": [
            implement_input["delivery_id"],
            review1_input["delivery_id"],
            rework_input["delivery_id"],
            review2_input["delivery_id"],
            terminal_input["delivery_id"],
        ],
        "provider_counts": counts,
        "ordered_effects": observer,
        "terminal": {
            "state": terminal_ledger["terminal_state"],
            "reason": terminal_ledger["terminal"]["reason"],
            "sequence": terminal_sequence,
        },
        "synthetic_boundaries": [
            "provider intelligence and report content",
            "GitHub PR/API/CI provenance",
            "transport send and ACK observer",
            "event identifiers and timestamps",
        ],
        "real_boundaries": [
            "RunLedger authorization and terminal",
            "checkpoint, outbox, and inbox persistence",
            "child subprocess start and exit",
            "disposable Git and exact workspace lineage",
            "ReviewReport normalization and architect terminal ordering",
        ],
    }
    assert acceptance_record["format"] == "awf.runtime-v2-rts011-acceptance.v1"
    assert len(set(acceptance_record["deliveries"])) == 5
    assert sum(counts[key] for key in ("implement", "rework", "review")) == 4
    assert "transport send and ACK observer" in acceptance_record["synthetic_boundaries"]
    assert all(str(path).startswith(str(tmp_path)) for path in (repo, state_root, counter_path))
