"""Regression coverage for the operations-surface run control plane."""

from __future__ import annotations

import json
import os
import sys
from argparse import Namespace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

import awf_control_plane
import awf_listen
import awf_role
from awf_control_plane import (
    ControlPlaneDenied,
    RunLedger,
    authorize_operation,
    build_context_packet,
    load_authority_manifest,
    verify_context_packet,
)

AUTHORITY_BINDING = {
    "sha256": "sha256:" + "a" * 64,
    "allowed_operations": ["diagnose", "endpoint_discovery", "listener_restart"],
}


def make_ledger(tmp_path: Path, *, budget: int = 1) -> RunLedger:
    ledger = RunLedger(tmp_path, "run-1")
    packet = build_context_packet(
        run_id="run-1",
        taskcard="docs/task.md",
        frozen_base="a" * 40,
        branch="awf/task-1",
        phase="execute",
        transition="task:awf-impl-v2",
        evidence=["docs/evidence.md"],
        prohibited_actions=["ACK/requeue historical events"],
        authority_manifest=AUTHORITY_BINDING,
        next_action="run coder preflight",
        stage="implement",
        run_contract_sha256="sha256:" + "b" * 64,
    )
    ledger.initialize(packet, stage="implement", max_attempts=1, rework_budget=budget)
    return ledger


def test_packet_is_bounded_and_recoverable_from_a_fresh_session(tmp_path: Path):
    make_ledger(tmp_path)
    recovered_ledger, packet = RunLedger(tmp_path, "run-1").recover()

    verify_context_packet(packet)
    assert recovered_ledger["format"] == "awf.run-ledger.v1"
    assert packet["taskcard"] == "docs/task.md"
    assert packet["next_action"] == "run coder preflight"
    assert packet["run_contract_sha256"] == "sha256:" + "b" * 64
    assert len(json.dumps(packet).encode()) < 32 * 1024
    drifted = build_context_packet(
        run_id="run-1",
        taskcard="docs/task.md",
        frozen_base="a" * 40,
        branch="awf/task-1",
        phase="execute",
        transition="task:awf-impl-v2",
        evidence=["docs/evidence.md"],
        prohibited_actions=["ACK/requeue historical events"],
        authority_manifest=AUTHORITY_BINDING,
        next_action="run coder preflight",
        stage="implement",
        run_contract_sha256="sha256:" + "c" * 64,
    )
    with pytest.raises(ControlPlaneDenied, match="different context packet"):
        RunLedger(tmp_path, "run-1").initialize(
            drifted, stage="implement", max_attempts=1, rework_budget=1
        )


@pytest.mark.parametrize(
    ("verdict", "terminal_state"),
    [("PASS", "completed"), ("BLOCKED", "blocked")],
)
def test_terminal_ledger_and_summary_are_durable_and_idempotent(
    tmp_path: Path, verdict: str, terminal_state: str
):
    ledger = make_ledger(tmp_path)
    terminal = {
        "verdict": verdict,
        "reason": "review_passed" if verdict == "PASS" else "review_blocked",
        "event_id": 41,
        "delivery_id": "review-delivery",
        "payload_sha256": "sha256:review",
        "source_event_id": 40,
        "branch": "awf/task-1",
        "commit": "b" * 40,
        "artifacts": {
            "implementation": {
                "path": ".awf/artifacts/impl-report-task-1.md",
                "sha256": "sha256:" + "c" * 64,
            },
            "review": {
                "path": ".awf/artifacts/review-report-task-1.md",
                "sha256": "sha256:" + "d" * 64,
            },
        },
        "pull_request": {
            "number": 17,
            "base_sha": "a" * 40,
            "head_sha": "b" * 40,
        },
        "ci": {"status": "not_recorded", "conclusion": ""},
        "merge": {"status": "not_merged", "commit": ""},
    }

    first = ledger.mark_terminal(terminal_state=terminal_state, terminal=terminal)
    sequence = first["sequence"]
    second = ledger.mark_terminal(terminal_state=terminal_state, terminal=terminal)

    assert second["sequence"] == sequence
    recovered, packet = RunLedger(tmp_path, "run-1").recover()
    summary = json.loads(ledger.summary_path.read_text(encoding="utf-8"))
    assert recovered["terminal_state"] == terminal_state
    assert recovered["terminal"] == terminal
    assert packet["next_action"] == "stop"
    assert summary["terminal_state"] == terminal_state
    assert summary["terminal"] == terminal
    assert summary["sequence"] == sequence


def test_completed_terminal_can_be_idempotently_finalized_with_merge_evidence(tmp_path: Path):
    ledger = make_ledger(tmp_path)
    terminal = {
        "verdict": "PASS",
        "reason": "review_passed",
        "event_id": 41,
        "delivery_id": "review-delivery",
        "payload_sha256": "sha256:review",
        "source_event_id": 40,
        "branch": "awf/task-1",
        "commit": "b" * 40,
        "artifacts": {},
        "pull_request": {"number": 17, "base_sha": "a" * 40, "head_sha": "b" * 40},
        "ci": {"status": "not_recorded", "conclusion": ""},
        "merge": {"status": "not_merged", "commit": ""},
    }
    first = ledger.mark_terminal(terminal_state="completed", terminal=terminal)

    finalized = ledger.finalize_merge(
        pull_request=17,
        base_sha="a" * 40,
        head_sha="b" * 40,
        ci_conclusion="success",
        merge_commit="e" * 40,
    )
    replay = ledger.finalize_merge(
        pull_request=17,
        base_sha="a" * 40,
        head_sha="b" * 40,
        ci_conclusion="success",
        merge_commit="e" * 40,
    )

    assert finalized == replay
    assert finalized["sequence"] == first["sequence"]
    assert finalized["terminal"]["ci"] == {"status": "completed", "conclusion": "success"}
    assert finalized["terminal"]["merge"] == {
        "status": "merged",
        "commit": "e" * 40,
    }


def test_coder_commit_can_advance_same_run_to_reviewer_before_model(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("AWF_CONTROL_PLANE", "1")
    state_root = tmp_path / "state"
    original_commit = "a" * 40
    executor_commit = "b" * 40
    common = {
        "branch": "feature/task-1",
        "card": "docs/task.md",
        "report": "docs/implementation.md",
        "pull_request": "",
        "phase": "execute",
        "route_override": "",
        "attempt": 1,
        "max_attempts": 1,
        "rework_budget": 1,
        "terminal_state": "",
    }
    coder = Namespace(
        **common,
        commit=original_commit,
        input_type="task:awf-impl-v2",
        delivery_id="coder-delivery",
        payload_sha256="sha256:coder",
    )
    coder_evidence = awf_role.RunEvidence(101, "coder", state_root=state_root)

    coder_decision = awf_role.pre_invocation_gate(coder, "coder", coder_evidence)

    assert coder_decision is not None and coder_decision.allowed

    reviewer = Namespace(
        **common,
        commit=executor_commit,
        input_type="task:awf-review-v2",
        delivery_id="reviewer-delivery",
        payload_sha256="sha256:reviewer",
    )
    reviewer_evidence = awf_role.RunEvidence(102, "reviewer", state_root=state_root)

    reviewer_decision = awf_role.pre_invocation_gate(reviewer, "reviewer", reviewer_evidence)

    assert reviewer_decision is not None and reviewer_decision.allowed
    ledger, packet = RunLedger(state_root, "task-task-1").recover()
    assert ledger["stage"] == packet["stage"] == "review"
    assert packet["frozen_base"] == original_commit
    assert packet["current_stage_evidence_commit"] == executor_commit


def test_v3_initial_pr_zero_is_persisted_before_model(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("AWF_CONTROL_PLANE", "1")
    args = Namespace(
        branch="proof/fork-task",
        card="docs/task.md",
        commit="a" * 40,
        report="docs/implementation.md",
        pull_request=0,
        phase="",
        input_type="task:awf-impl-v3",
        route_override="",
        attempt=1,
        max_attempts=1,
        rework_budget=1,
        terminal_state="",
        delivery_id="v3-delivery",
        payload_sha256="sha256:v3",
    )
    evidence = awf_role.RunEvidence(103, "coder", state_root=tmp_path / "state")

    decision = awf_role.pre_invocation_gate(args, "coder", evidence)

    assert decision is not None and decision.allowed
    _, packet = RunLedger(tmp_path / "state", "task-fork-task").recover()
    assert packet["pull_request"] == "0"


def test_gate_rejects_missing_route_before_authorization(tmp_path: Path):
    ledger = make_ledger(tmp_path)
    decision = ledger.pre_invocation_gate(
        event_id=1,
        event_type="task:unknown",
        role="coder",
        delivery_id="delivery-1",
        payload_sha256="sha256:one",
        stage="implement",
    )

    assert not decision.allowed
    assert decision.reason == "no_unique_compatible_route"
    events = json.loads(ledger.ledger_path.read_text())["events"]
    assert events[-1]["status"] == "rejected"


def test_gate_rejects_over_budget_terminal_and_replay(tmp_path: Path):
    ledger = make_ledger(tmp_path, budget=1)
    first = ledger.pre_invocation_gate(
        event_id=1,
        event_type="task:awf-impl-v2",
        role="coder",
        delivery_id="delivery-1",
        payload_sha256="sha256:one",
        stage="implement",
    )
    assert first.allowed
    recovered, packet = RunLedger(tmp_path, "run-1").recover()
    assert recovered["sequence"] == packet["ledger_sequence"] == 1
    assert packet["transition"] == "task:awf-impl-v2"
    replay = ledger.pre_invocation_gate(
        event_id=1,
        event_type="task:awf-impl-v2",
        role="coder",
        delivery_id="delivery-1",
        payload_sha256="sha256:one",
        stage="implement",
    )
    assert not replay.allowed and replay.reason == "duplicate_event"
    reused = ledger.pre_invocation_gate(
        event_id=2,
        event_type="task:awf-impl-v2",
        role="coder",
        delivery_id="delivery-1",
        payload_sha256="sha256:different",
        stage="implement",
    )
    assert not reused.allowed and reused.reason == "delivery_id_reused"
    distinct = ledger.pre_invocation_gate(
        event_id=3,
        event_type="task:awf-impl-v2",
        role="coder",
        delivery_id="delivery-distinct",
        payload_sha256="sha256:distinct",
        stage="implement",
    )
    assert not distinct.allowed and distinct.reason == "attempt_budget_exceeded"
    decisions = json.loads(ledger.ledger_path.read_text())["decisions"]
    assert [item["status"] for item in decisions[:4]] == [
        "authorized",
        "replay",
        "rejected",
        "rejected",
    ]

    mismatch = ledger.pre_invocation_gate(
        event_id=2,
        event_type="task:awf-review-v2",
        role="reviewer",
        delivery_id="delivery-mismatch",
        payload_sha256="sha256:mismatch",
        stage="plan",
    )
    assert not mismatch.allowed and mismatch.reason == "stage_mismatch"

    over = ledger.pre_invocation_gate(
        event_id=3,
        event_type="task:awf-rework-v2",
        role="coder",
        delivery_id="delivery-2",
        payload_sha256="sha256:two",
        stage="rework",
        rework=True,
    )
    assert over.allowed

    # A new run demonstrates the actual rework-budget denial independently.
    second = RunLedger(tmp_path, "run-2")
    packet = build_context_packet(
        run_id="run-2",
        taskcard="card",
        frozen_base="b" * 40,
        branch="branch",
        next_action="rework",
        stage="rework",
        authority_manifest=AUTHORITY_BINDING,
    )
    second.initialize(packet, stage="rework", max_attempts=1, rework_budget=0)
    denied = second.pre_invocation_gate(
        event_id=4,
        event_type="task:awf-rework-v2",
        role="coder",
        delivery_id="delivery-3",
        payload_sha256="sha256:three",
        stage="rework",
        rework=True,
    )
    assert not denied.allowed and denied.reason == "rework_budget_exceeded"

    terminal = RunLedger(tmp_path, "run-3")
    terminal_packet = build_context_packet(
        run_id="run-3",
        taskcard="card",
        frozen_base="c" * 40,
        branch="branch",
        next_action="stop",
        stage="complete",
        authority_manifest=AUTHORITY_BINDING,
    )
    terminal.initialize(terminal_packet, stage="complete", max_attempts=1, rework_budget=0)
    data = json.loads(terminal.ledger_path.read_text())
    data["terminal_state"] = "completed"
    terminal.ledger_path.write_text(json.dumps(data), encoding="utf-8")
    stopped = terminal.pre_invocation_gate(
        event_id=4,
        event_type="task:awf-impl-v2",
        role="coder",
        delivery_id="delivery-4",
        payload_sha256="sha256:four",
        stage="complete",
    )
    assert not stopped.allowed and stopped.reason == "terminal_state"

    duplicate_terminal = RunLedger(tmp_path, "run-4")
    duplicate_packet = build_context_packet(
        run_id="run-4",
        taskcard="card",
        frozen_base="d" * 40,
        branch="branch",
        next_action="stop",
        stage="implement",
        authority_manifest=AUTHORITY_BINDING,
    )
    duplicate_terminal.initialize(
        duplicate_packet, stage="implement", max_attempts=1, rework_budget=0
    )
    authorized = duplicate_terminal.pre_invocation_gate(
        event_id=5,
        event_type="task:awf-impl-v2",
        role="coder",
        delivery_id="delivery-terminal-replay",
        payload_sha256="sha256:terminal-replay",
        stage="implement",
    )
    assert authorized.allowed
    data = json.loads(duplicate_terminal.ledger_path.read_text())
    data["terminal_state"] = "completed"
    duplicate_terminal.ledger_path.write_text(json.dumps(data), encoding="utf-8")
    terminal_replay = duplicate_terminal.pre_invocation_gate(
        event_id=5,
        event_type="task:awf-impl-v2",
        role="coder",
        delivery_id="delivery-terminal-replay",
        payload_sha256="sha256:terminal-replay",
        stage="implement",
    )
    assert not terminal_replay.allowed and terminal_replay.reason == "terminal_state"


def test_authority_manifest_allows_only_reversible_operations():
    manifest = {
        "format": "awf.authority-manifest.v1",
        "allowed_operations": ["diagnose", "listener_restart"],
    }
    assert authorize_operation(manifest, "diagnose")
    with pytest.raises(ControlPlaneDenied):
        authorize_operation(manifest, "ack")
    with pytest.raises(ControlPlaneDenied):
        authorize_operation(manifest, "endpoint_discovery")


def test_checked_in_authority_manifest_is_bound_into_recovery_packet():
    path = Path(__file__).parents[1] / "scripts" / "authority-manifest.example.json"
    manifest = load_authority_manifest(path)
    assert manifest["allowed_operations"] == [
        "diagnose",
        "endpoint_discovery",
        "listener_restart",
    ]


def test_packet_write_failure_cannot_authorize_an_unrecoverable_sequence(
    monkeypatch, tmp_path: Path
):
    ledger = make_ledger(tmp_path)
    real_write = awf_control_plane._atomic_write

    def fail_packet(path: Path, value: dict[str, object]):
        if path == ledger.packet_path:
            raise OSError("controlled packet write failure")
        return real_write(path, value)

    monkeypatch.setattr(awf_control_plane, "_atomic_write", fail_packet)
    with pytest.raises(OSError, match="controlled packet write failure"):
        ledger.pre_invocation_gate(
            event_id=1,
            event_type="task:awf-impl-v2",
            role="coder",
            delivery_id="delivery-atomic",
            payload_sha256="sha256:atomic",
            stage="implement",
        )

    recovered, packet = RunLedger(tmp_path, "run-1").recover()
    assert recovered["sequence"] == packet["ledger_sequence"] == 0
    assert recovered["events"] == []


def test_role_route_rejection_happens_before_checkout_or_model(monkeypatch, tmp_path: Path):
    repo = tmp_path / "repo"
    scripts = tmp_path / "scripts"
    repo.mkdir()
    scripts.mkdir()
    (scripts / "executor-prompt.md").write_text("prompt", encoding="utf-8")
    monkeypatch.setenv("AWF_REPO_DIR", str(repo))
    monkeypatch.setenv("AWF_SCRIPT_DIR", str(scripts))
    monkeypatch.setenv("AWF_CONTROL_PLANE", "1")
    monkeypatch.setenv("AWF_ACTIVE_ROUTE_TYPES", "task:awf-review-v2")
    monkeypatch.setattr(
        awf_role,
        "fetch_and_checkout",
        lambda *args: pytest.fail("route denial must precede checkout"),
    )
    monkeypatch.setattr(
        awf_role,
        "tool_opencode_exec",
        lambda *args: pytest.fail("route denial must precede model invocation"),
    )
    evidence = awf_role.RunEvidence(41, "coder", state_root=tmp_path / "state")
    args = Namespace(
        branch="feature/task",
        card="task.md",
        commit="abc1234",
        model="",
        tool="opencode",
        report="implementation.md",
        review_report="review.md",
        review_feedback="",
        base="",
        input_type="task:awf-impl-v2",
        source_event_id=0,
        delivery_id="",
        payload_sha256="",
        evidence=evidence,
    )
    payload = awf_role.input_payload(args, "coder")
    args.payload_sha256 = awf_role.canonical_payload_sha256(payload)
    args.delivery_id = awf_role.make_delivery_id(
        "architect", args.input_type, args.payload_sha256, 0
    )

    with pytest.raises(SystemExit):
        awf_role.role_coder(args)

    result = json.loads(evidence.result_path.read_text(encoding="utf-8"))
    assert result["last_phase"] == "pre_invocation_rejected"
    assert result["reason"] == "no_unique_compatible_route"
    assert not (tmp_path / "state" / "inbox").exists()


def test_default_coder_listener_covers_impl_and_rework_with_distinct_handlers(
    monkeypatch, tmp_path: Path
):
    repo = tmp_path / "repo"
    repo.mkdir()
    environment = {
        "AGENT_BUS_URL": "http://bus.invalid",
        "AWF_CODER_TOKEN": "test-token",
    }
    monkeypatch.setattr(awf_listen.os, "environ", environment)
    monkeypatch.setattr(awf_listen, "check_workspace_readiness", lambda repo, _role: repo.resolve())
    seen: list[str] = []

    class Completed:
        returncode = 0

    monkeypatch.setattr(
        awf_listen,
        "run_command",
        lambda argv, **_kwargs: seen.extend(argv) or Completed(),
    )

    assert (
        awf_listen.main(
            [
                "--role",
                "coder",
                "--repo",
                str(repo),
                "--upstream-repo",
                "upstream/project",
                "--head-repo",
                "contributor/project",
                "--state-root",
                str(tmp_path / "state"),
            ]
        )
        == 0
    )
    on_indexes = [index for index, value in enumerate(seen) if value == "--on"]
    assert len(on_indexes) == 2
    first_type, first_handler = seen[on_indexes[0] + 1 : on_indexes[0] + 3]
    second_type, second_handler = seen[on_indexes[1] + 1 : on_indexes[1] + 3]
    assert first_type == "task:awf-impl-v3"
    assert "--review-feedback" not in first_handler
    assert second_type == "task:awf-rework-v3"
    assert "--review-feedback {payload.review_report}" in second_handler


def test_default_architect_listener_covers_ready_and_blocked_terminal_decisions(
    monkeypatch, tmp_path: Path
):
    repo = tmp_path / "repo"
    repo.mkdir()
    environment = {
        "AGENT_BUS_URL": "http://bus.invalid",
        "AWF_ARCH_TOKEN": "test-token",
    }
    monkeypatch.setattr(awf_listen.os, "environ", environment)
    monkeypatch.setattr(awf_listen, "check_workspace_readiness", lambda repo, _role: repo.resolve())
    seen: list[str] = []

    class Completed:
        returncode = 0

    monkeypatch.setattr(
        awf_listen,
        "run_command",
        lambda argv, **_kwargs: seen.extend(argv) or Completed(),
    )

    assert (
        awf_listen.main(
            [
                "--role",
                "architect",
                "--repo",
                str(repo),
                "--upstream-repo",
                "upstream/project",
                "--head-repo",
                "contributor/project",
                "--state-root",
                str(tmp_path / "state"),
            ]
        )
        == 0
    )
    on_indexes = [index for index, value in enumerate(seen) if value == "--on"]
    assert len(on_indexes) == 2
    first_type, first_handler = seen[on_indexes[0] + 1 : on_indexes[0] + 3]
    second_type, second_handler = seen[on_indexes[1] + 1 : on_indexes[1] + 3]
    assert first_type == "decision:awf-ready-v3"
    assert second_type == "decision:awf-blocked-v3"
    assert "--review-feedback" in first_handler
    assert "--review-feedback" in second_handler
    assert "--review-feedback {payload.review_report}" in second_handler


def test_listener_rejects_duplicate_role_before_connecting_to_bus(monkeypatch, tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    environment = {
        "AGENT_BUS_URL": "http://bus.invalid",
        "AWF_CODER_TOKEN": "test-token",
    }
    monkeypatch.setattr(awf_listen.os, "environ", environment)
    monkeypatch.setattr(awf_listen, "check_workspace_readiness", lambda repo, _role: repo.resolve())
    lease_dir = tmp_path / "state" / "listeners"
    lease_dir.mkdir(parents=True)
    (lease_dir / "coder.json").write_text(
        json.dumps({"pid": os.getpid(), "role": "coder", "repo": str(repo.resolve())}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        awf_listen,
        "run_command",
        lambda *_args, **_kwargs: pytest.fail("duplicate listener must fail before Bus connect"),
    )

    with pytest.raises(SystemExit, match="2"):
        awf_listen.main(
            [
                "--role",
                "coder",
                "--repo",
                str(repo),
                "--upstream-repo",
                "upstream/project",
                "--head-repo",
                "contributor/project",
                "--state-root",
                str(tmp_path / "state"),
            ]
        )


def test_listener_rejects_role_repo_conflict_before_connecting_to_bus(monkeypatch, tmp_path: Path):
    repo = tmp_path / "shared-repo"
    repo.mkdir()
    environment = {
        "AGENT_BUS_URL": "http://bus.invalid",
        "AWF_REVIEWER_TOKEN": "test-token",
    }
    monkeypatch.setattr(awf_listen.os, "environ", environment)
    monkeypatch.setattr(awf_listen, "check_workspace_readiness", lambda repo, _role: repo.resolve())
    lease_dir = tmp_path / "state" / "listeners"
    lease_dir.mkdir(parents=True)
    (lease_dir / "coder.json").write_text(
        json.dumps({"pid": os.getpid(), "role": "coder", "repo": str(repo.resolve())}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        awf_listen,
        "run_command",
        lambda *_args, **_kwargs: pytest.fail("role/repo conflict must fail before Bus connect"),
    )

    with pytest.raises(SystemExit, match="2"):
        awf_listen.main(
            [
                "--role",
                "reviewer",
                "--repo",
                str(repo),
                "--upstream-repo",
                "upstream/project",
                "--head-repo",
                "contributor/project",
                "--state-root",
                str(tmp_path / "state"),
            ]
        )


def test_listener_ctrl_c_releases_lease_without_traceback(monkeypatch, tmp_path: Path, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()
    environment = {
        "AGENT_BUS_URL": "http://bus.invalid",
        "AWF_CODER_TOKEN": "test-token",
    }
    monkeypatch.setattr(awf_listen.os, "environ", environment)
    monkeypatch.setattr(awf_listen, "check_workspace_readiness", lambda repo, _role: repo.resolve())
    monkeypatch.setattr(
        awf_listen,
        "run_command",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(KeyboardInterrupt()),
    )

    assert (
        awf_listen.main(
            [
                "--role",
                "coder",
                "--repo",
                str(repo),
                "--upstream-repo",
                "upstream/project",
                "--head-repo",
                "contributor/project",
                "--state-root",
                str(tmp_path / "state"),
            ]
        )
        == 130
    )
    assert not (tmp_path / "state" / "listeners" / "coder.json").exists()
    captured = capsys.readouterr()
    assert "Traceback" not in captured.err
    assert "stopped locally" in captured.err


@pytest.mark.parametrize(
    ("role", "status", "allowed"),
    [
        ("coder", " M task.md\n", False),
        ("reviewer", "?? notes.txt\n", False),
        ("architect", " M task.md\n", True),
    ],
)
def test_listener_workspace_readiness_is_role_scoped(
    monkeypatch, tmp_path: Path, role: str, status: str, allowed: bool
):
    repo = tmp_path / "repo"
    repo.mkdir()

    class Completed:
        returncode = 0

        def __init__(self, stdout: str):
            self.stdout = stdout

    def fake_git(_repo: Path, *args: str):
        if args == ("rev-parse", "--is-inside-work-tree"):
            return Completed("true\n")
        if args == ("rev-parse", "--show-toplevel"):
            return Completed(str(repo.resolve()) + "\n")
        if args == ("status", "--porcelain"):
            return Completed(status)
        raise AssertionError(args)

    monkeypatch.setattr(awf_listen, "_git_read", fake_git)
    if allowed:
        assert awf_listen.check_workspace_readiness(repo, role) == repo.resolve()
    else:
        with pytest.raises(SystemExit, match="2"):
            awf_listen.check_workspace_readiness(repo, role)


def test_default_control_plane_routes_include_all_v3_stage_types():
    assert awf_control_plane.DEFAULT_ROUTES["task:awf-impl-v3"] == ["coder"]
    assert awf_control_plane.DEFAULT_ROUTES["task:awf-review-v3"] == ["reviewer"]
    assert awf_control_plane.DEFAULT_ROUTES["task:awf-rework-v3"] == ["coder"]
