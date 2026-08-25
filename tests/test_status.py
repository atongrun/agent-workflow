"""Tests for the read-only factual node status surface."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from agent_workflow import node, status


def make_profile(
    tmp_path: Path, *, role: str = "reviewer", finding_enabled: bool = False
) -> node.NodeProfile:
    values: dict[str, object] = {
        "format": "awf.node-profile.v1",
        "name": f"{role}-node",
        "role": role,
        "repo": str((tmp_path / "repo").resolve()),
        "tool": "none" if role == "architect" else "pi",
        "upstream_repo": "owner/project",
        "head_repo": "contributor/project",
        "config": str((tmp_path / "dispatch.env").resolve()),
        "state_root": str((tmp_path / "state").resolve()),
        "finding_enabled": finding_enabled,
    }
    return node.NodeProfile(tmp_path / "profile.json", values)


def test_workspace_reports_role_scope_and_dirty_readiness(monkeypatch, tmp_path: Path):
    profile = make_profile(tmp_path)
    profile.repo.mkdir()
    outputs = iter(
        [
            (0, str(profile.repo)),
            (0, "a" * 40),
            (0, "feature/task"),
            (0, "?? operator-note.txt"),
        ]
    )
    commands = []

    def command(argv):
        commands.append(argv)
        return next(outputs)

    monkeypatch.setattr(status, "_command", command)

    facts = status._workspace(profile)

    assert facts["scope"] == "dedicated_role"
    assert facts["status"] == "not_ready"
    assert facts["dirty"] is True
    assert all("--no-optional-locks" in argv for argv in commands)


def test_architect_workspace_can_report_ready_when_source_is_dirty(monkeypatch, tmp_path: Path):
    profile = make_profile(tmp_path, role="architect")
    profile.repo.mkdir()
    outputs = iter([(0, str(profile.repo)), (0, "b" * 40), (0, "main"), (0, " M README.md")])
    monkeypatch.setattr(status, "_command", lambda argv: next(outputs))

    facts = status._workspace(profile)

    assert facts["scope"] == "source"
    assert facts["status"] == "ready"
    assert facts["dirty"] is True


def test_pi_architect_workspace_is_dedicated_and_requires_cleanliness(monkeypatch, tmp_path: Path):
    profile = make_profile(tmp_path, role="architect")
    profile.values["tool"] = "pi"
    profile.repo.mkdir()
    outputs = iter([(0, str(profile.repo)), (0, "b" * 40), (0, "main"), (0, " M README.md")])
    monkeypatch.setattr(status, "_command", lambda argv: next(outputs))

    facts = status._workspace(profile)

    assert facts["scope"] == "dedicated_role"
    assert facts["status"] == "not_ready"
    assert facts["dirty"] is True


def test_review_artifact_distinguishes_file_and_canonical_hashes(tmp_path: Path):
    profile = make_profile(tmp_path)
    report = profile.repo / ".awf/artifacts/review.md"
    report.parent.mkdir(parents=True)
    report.write_text("review markdown\n", encoding="utf-8")
    file_sha = "sha256:" + hashlib.sha256(report.read_bytes()).hexdigest()
    canonical_sha = "sha256:" + "c" * 64
    ledger = {
        "terminal": {
            "artifacts": {
                "implementation": {"path": "implementation.md", "sha256": "sha256:impl"},
                "review": {"path": ".awf/artifacts/review.md", "sha256": canonical_sha},
            }
        }
    }

    facts = status._artifacts(profile, ledger, file_sha)

    assert facts["review"]["file_sha256"] == file_sha
    assert facts["review"]["file_sha256_source"] == "delivery_checkpoint"
    assert facts["review"]["live_file_sha256"] == file_sha
    assert facts["review"]["canonical_report_sha256"] == canonical_sha
    assert facts["review"]["canonical_report_sha256_source"] == "terminal_ledger"


def test_delivery_checkpoint_supplies_the_recorded_review_file_hash(tmp_path: Path):
    profile = make_profile(tmp_path)
    directory = profile.state_root / "checkpoint" / profile.role
    directory.mkdir(parents=True)
    checkpoint_path = directory / "delivery.json"
    checkpoint_path.write_text(
        json.dumps(
            {
                "branch": "feature/task",
                "phase": "outbox_sent",
                "facts": {
                    "review_report_sha256": "d" * 64,
                    "outbox_delivery_id": "review-delivery",
                },
            }
        ),
        encoding="utf-8",
    )
    original_bytes = checkpoint_path.read_bytes()
    ledger = {"terminal": {"branch": "feature/task", "delivery_id": "review-delivery"}}

    facts, file_sha = status._delivery_checkpoints(profile, ledger)

    assert facts == {
        "source": "delivery_checkpoint_files",
        "status": "recorded",
        "count": 1,
        "unreadable": 0,
        "latest_phase": "outbox_sent",
    }
    assert file_sha == "sha256:" + "d" * 64
    assert checkpoint_path.read_bytes() == original_bytes

    mismatched = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    mismatched["state_root_sha256"] = "sha256:" + "f" * 64
    checkpoint_path.write_text(json.dumps(mismatched), encoding="utf-8")
    facts, file_sha = status._delivery_checkpoints(profile, ledger)

    assert facts["status"] == "partial"
    assert facts["count"] == 0
    assert facts["unreadable"] == 1
    assert file_sha == ""


def test_live_pr_and_ci_are_separate_from_recorded_facts(monkeypatch, tmp_path: Path):
    profile = make_profile(tmp_path)
    ledger = {
        "terminal": {
            "pull_request": {"number": 17, "head_sha": "a" * 40},
            "ci": {"status": "recorded", "conclusion": "success"},
        }
    }
    live = {
        "state": "OPEN",
        "headRefOid": "b" * 40,
        "baseRefOid": "c" * 40,
        "statusCheckRollup": [{"conclusion": "SUCCESS"}, {"conclusion": "FAILURE"}],
    }
    monkeypatch.setattr(status, "_command", lambda argv: (0, json.dumps(live)))

    pull_request, ci = status._pr_and_ci(profile, ledger)

    assert pull_request["recorded"]["head_sha"] == "a" * 40
    assert pull_request["live"]["head_sha"] == "b" * 40
    assert ci["recorded"]["conclusion"] == "success"
    assert ci["live"]["all_green"] is False


def test_snapshot_labels_unavailable_queue_without_failing(monkeypatch, tmp_path: Path):
    profile = make_profile(tmp_path)
    monkeypatch.setattr(status, "_listener", lambda value: {"status": "stopped"})
    monkeypatch.setattr(status, "_workspace", lambda value: {"status": "unknown"})
    monkeypatch.setattr(
        status,
        "_ledger",
        lambda value, run_id: ({"source": "run_ledger", "status": "not_requested"}, {}),
    )
    monkeypatch.setattr(
        status,
        "_delivery_checkpoints",
        lambda value, ledger: ({"status": "not_recorded"}, ""),
    )
    monkeypatch.setattr(
        status,
        "_queue",
        lambda value: {"source": "agent_bus_pending_read_only", "status": "unknown"},
    )
    monkeypatch.setattr(status, "_artifacts", lambda *args: {"status": "not_recorded"})
    monkeypatch.setattr(
        status,
        "_feedback",
        lambda value: (_ for _ in ()).throw(
            AssertionError("Finding-off status must not inspect Feedback")
        ),
    )
    monkeypatch.setattr(status, "_model_invocation", lambda *args: None)
    monkeypatch.setattr(
        node,
        "lifecycle_facts",
        lambda *args, **kwargs: {"dispatch_capable": None},
    )
    monkeypatch.setattr(
        status,
        "_pr_and_ci",
        lambda *args: (
            {"recorded": "not_recorded", "live": "not_requested"},
            {"recorded": "not_recorded", "live": "not_requested"},
        ),
    )

    value = status.snapshot(profile)

    assert value["format"] == "awf.node-status.v1"
    assert value["queue"]["status"] == "unknown"
    assert value["checkpoint"]["ledger"]["status"] == "not_requested"
    assert "feedback" not in value


def test_causal_status_identifies_lifecycle_boundary_before_model():
    lifecycle = {
        "configured": True,
        "installed": False,
        "running": False,
        "connected": None,
        "dispatch_capable": False,
        "next_legal_action": {"command": "awf node install --profile reviewer-node"},
    }

    causal = status._causal_status(
        "task-1",
        lifecycle,
        {"status": "not_requested", "stage": "not_recorded", "attempts": 0},
        {},
        None,
    )

    assert causal["status"] == "blocked"
    assert causal["owner"] == "node_lifecycle"
    assert causal["cause"] == "lifecycle_installed_false"
    assert causal["model_invocation"] == "unknown"
    assert causal["next_legal_action"] == "awf node install --profile reviewer-node"


def test_snapshot_reports_rejected_pre_model_event_without_payload_or_mutation(
    monkeypatch, tmp_path: Path
):
    profile = make_profile(tmp_path)
    ledger = {
        "stage": "implement",
        "stage_attempts": {},
        "terminal_state": "",
        "events": [
            {
                "event_id": 901,
                "event_type": "task:synthetic-impl-v3",
                "role": "coder",
                "status": "rejected",
                "reason": "stage_mismatch",
                "delivery_id": "synthetic-delivery",
                "payload_sha256": "sha256:synthetic",
                "payload": "must-not-appear",
            }
        ],
        "decisions": [
            {
                "status": "rejected",
                "reason": "stage_mismatch",
                "role": "coder",
            }
        ],
    }
    lifecycle = {"dispatch_capable": True}
    mutations: list[str] = []

    def forbidden(*args, **kwargs):
        mutations.append("called")
        raise AssertionError("read-only status must not mutate runtime state")

    monkeypatch.setattr(node, "start", forbidden)
    monkeypatch.setattr(node, "stop", forbidden)
    monkeypatch.setattr(status, "_listener", lambda value: {"status": "running"})
    monkeypatch.setattr(status, "_workspace", lambda value: {"status": "ready"})
    monkeypatch.setattr(
        status,
        "_ledger",
        lambda value, run_id: (
            {
                "source": "run_ledger",
                "status": "recorded",
                "run_id": run_id,
                "stage": "implement",
                "attempts": 0,
                "next_action": "stop",
            },
            ledger,
        ),
    )
    monkeypatch.setattr(
        status,
        "_delivery_checkpoints",
        lambda *args: ({"status": "not_recorded"}, ""),
    )
    monkeypatch.setattr(status, "_queue", lambda value: {"status": "unknown"})
    monkeypatch.setattr(status, "_artifacts", lambda *args: {"status": "not_recorded"})
    monkeypatch.setattr(
        status,
        "_pr_and_ci",
        lambda *args: (
            {"recorded": "not_recorded", "live": "not_requested"},
            {"recorded": "not_recorded", "live": "not_requested"},
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "agent_workflow.operations.awf_feedback",
        SimpleNamespace(
            FeedbackStateError=ValueError,
            feedback_status=lambda value: {
                "pending": 0,
                "sent": 0,
                "rejected": 0,
                "corrupt": 0,
            },
            flush_feedback=forbidden,
            ingest_occurrence=forbidden,
            queue_occurrence=forbidden,
        ),
    )
    monkeypatch.setattr(status, "_model_invocation", lambda *args: None)
    monkeypatch.setattr(node, "lifecycle_facts", lambda *args, **kwargs: lifecycle)

    value = status.snapshot(profile, "task-1")

    assert mutations == []
    assert value["causal"]["status"] == "blocked"
    assert value["causal"]["owner"] == "workflow_control_plane"
    assert value["causal"]["cause"] == "stage_mismatch"
    assert value["causal"]["model_invocation"] == "not_observed"
    assert "payload" not in value["causal"]["event_observation"]["latest"]
    assert "delivery_id" not in value["causal"]["event_observation"]["latest"]
    assert "payload_sha256" not in value["causal"]["event_observation"]["latest"]
    assert value["causal"]["event_observation"]["payload_hash_observed"] is True


def test_business_terminal_keeps_feedback_pending_independent(monkeypatch, tmp_path: Path):
    profile = make_profile(tmp_path)
    ledger = {
        "terminal_state": "completed",
        "stage": "review",
        "stage_attempts": {"review": 1},
        "events": [{"event_id": 902, "role": "reviewer", "status": "authorized"}],
        "decisions": [{"status": "authorized", "reason": "authorized"}],
    }

    monkeypatch.setitem(
        sys.modules,
        "agent_workflow.operations.awf_feedback",
        SimpleNamespace(
            FeedbackStateError=ValueError,
            feedback_status=lambda value: {
                "pending": 1,
                "sent": 0,
                "rejected": 0,
                "corrupt": 0,
            },
        ),
    )

    causal = status._causal_status(
        "task-2",
        {"dispatch_capable": False},
        {
            "status": "recorded",
            "stage": "review",
            "attempts": 2,
            "next_action": "stop",
        },
        ledger,
        True,
    )
    feedback = status._feedback(profile)

    assert causal["status"] == "terminal"
    assert causal["cause"] == "business_completed"
    assert causal["model_invocation"] == "observed"
    assert feedback["outbox"] == "pending"
    assert feedback["flush"] == "pending"
    assert feedback["next_legal_action"].startswith("awf feedback flush")


def test_human_status_names_both_review_hash_semantics(capsys):
    value = {
        "profile": {"name": "reviewer", "role": "reviewer"},
        "lifecycle": {
            "configured": None,
            "installed": True,
            "running": False,
            "connected": None,
            "dispatch_capable": False,
            "installation": {"status": "current"},
            "running_observation": {"status": "stale"},
            "preflight": {"status": "missing"},
            "next_legal_action": {"command": "awf node stop --profile reviewer"},
        },
        "listener": {"status": "running"},
        "workspace": {
            "status": "ready",
            "scope": "dedicated_role",
            "branch": "main",
            "head_sha": "a" * 40,
            "dirty": False,
        },
        "checkpoint": {
            "ledger": {"status": "recorded", "phase": "review"},
            "delivery": {"status": "recorded", "latest_phase": "outbox_sent"},
        },
        "queue": {"status": "observed", "pending": 0, "source": "bus"},
        "artifacts": {
            "review": {
                "file_sha256": "sha256:file",
                "canonical_report_sha256": "sha256:canonical",
            }
        },
        "pull_request": {"recorded": {"number": 1}, "live": {"state": "OPEN"}},
        "ci": {"recorded": {"status": "recorded"}, "live": {"all_green": True}},
        "feedback": {
            "capture": "recorded",
            "outbox": "pending",
            "flush": "pending",
            "counts": {"pending": 1},
        },
        "causal": {
            "run_id": "task-1",
            "stage": "review",
            "attempt": 1,
            "status": "blocked",
            "owner": "workflow_control_plane",
            "cause": "stage_mismatch",
            "model_invocation": "not_observed",
            "next_legal_action": "correct stage_mismatch",
        },
    }

    status.print_human(value, explain=True)

    output = capsys.readouterr().out
    assert "configured=unknown installed=true running=false" in output
    assert "running_observation=stale preflight=missing" in output
    assert "next_legal_action=awf node stop --profile reviewer" in output
    assert "file_sha256=sha256:file" in output
    assert "canonical_report_sha256=sha256:canonical" in output
    assert "feedback: capture=recorded outbox=pending flush=pending pending=1" in output
    assert "causal: run=task-1 stage=review attempt=1 status=blocked" in output
    assert "owner=workflow_control_plane cause=stage_mismatch" in output
