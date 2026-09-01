from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_workflow import application
from agent_workflow.operations import awf_plan, awf_role
from agent_workflow.plan_loop import ArchitectBinding, PlanFact, PlanRunStore, plan_start_payload


def _machine(state_root: Path) -> SimpleNamespace:
    return SimpleNamespace(profiles=(SimpleNamespace(state_root=state_root),))


def _payload(tmp_path: Path) -> dict[str, object]:
    binding = ArchitectBinding(
        profile=str(tmp_path / "architect.json"),
        profile_sha256="sha256:" + "a" * 64,
        workspace=str(tmp_path),
        tool="opencode",
        model_mode="tool-default",
        model_ref="",
    )
    plan = PlanFact(
        repository="owner/project",
        upstream_remote="upstream",
        base_ref="main",
        path="docs/plan.md",
        commit="1" * 40,
        blob_oid="2" * 40,
        blob_sha256="3" * 64,
        main_sha="4" * 40,
    )
    return plan_start_payload(
        plan,
        binding,
        mode="milestone",
        coder_tool="opencode",
        coder_model="",
        reviewer_tool="codex",
        reviewer_model="",
    )


def test_status_is_a_stable_credential_free_projection(monkeypatch, tmp_path: Path):
    payload = _payload(tmp_path)
    state_root = tmp_path / "state"
    store = PlanRunStore(state_root, str(payload["run_id"]))
    store.create(payload, repo=tmp_path)
    store.update(
        status="card_active",
        current_card={
            "task_id": "RC2-P3-001",
            "branch": "codex/rc2-p3",
            "status": "active",
            "ignored": "not projected",
        },
    )
    monkeypatch.setattr(application, "_machine", lambda _repo: _machine(state_root))

    first = application.status(tmp_path, run_id=str(payload["run_id"]))
    second = application.status(tmp_path, run_id=str(payload["run_id"]))

    assert first == second
    assert set(first) == {
        "current_state",
        "current_card",
        "last_completion",
        "roles",
        "blocker",
        "next_safe_action",
        "allowed_actions",
    }
    assert first["current_card"] == {
        "task_id": "RC2-P3-001",
        "branch": "codex/rc2-p3",
        "status": "active",
    }
    assert first["allowed_actions"] == ["get_status", "doctor", "stop"]
    assert "profile" not in str(first)


def test_unknown_status_never_advertises_continue_or_replacement(monkeypatch, tmp_path: Path):
    payload = _payload(tmp_path)
    state_root = tmp_path / "state"
    store = PlanRunStore(state_root, str(payload["run_id"]))
    store.create(payload, repo=tmp_path)
    store.update(status="unrecognized_authority_state")
    monkeypatch.setattr(application, "_machine", lambda _repo: _machine(state_root))

    result = application.status(tmp_path, run_id=str(payload["run_id"]))

    assert result["allowed_actions"] == ["get_status", "doctor", "stop"]


@pytest.mark.parametrize("review_decision", ["", "APPROVED"])
def test_exact_external_human_merge_marker_advertises_only_bounded_continuation(
    monkeypatch, tmp_path: Path, review_decision: str
):
    payload = _payload(tmp_path)
    state_root = tmp_path / "state"
    store = PlanRunStore(state_root, str(payload["run_id"]))
    store.create(payload, repo=tmp_path)
    store.update(
        status="waiting_for_human_approval",
        current_card={
            "task_id": "RC2-P3-001",
            "branch": "codex/rc2-p3",
            "status": "deciding",
            "approval": {
                "status": "human_merge_required",
                "review_decision": review_decision,
                "mergeability": "CLEAN",
                "merge_authority": "external",
            },
            "terminal_delivery": {
                "run_id": "task-RC2-P3-001",
                "event_id": 9,
                "delivery_id": "awf:" + "a" * 64,
                "payload_sha256": "sha256:" + "b" * 64,
                "source_event_id": 8,
                "branch": "codex/rc2-p3",
                "commit": "c" * 40,
                "implementation_path": ".awf/artifacts/impl.md",
                "review_path": ".awf/artifacts/review.md",
                "implementation_sha256": "sha256:" + "d" * 64,
                "review_sha256": "sha256:" + "e" * 64,
            },
        },
    )
    monkeypatch.setattr(application, "_machine", lambda _repo: _machine(state_root))

    result = application.status(tmp_path, run_id=str(payload["run_id"]))

    assert result["allowed_actions"] == [
        "get_status",
        "doctor",
        "continue_after_approval",
        "stop",
    ]


def test_no_replay_provider_failure_projects_blocked_ambiguous_without_replacement(
    monkeypatch, tmp_path: Path
):
    payload = _payload(tmp_path)
    state_root = tmp_path / "state"
    store = PlanRunStore(state_root, str(payload["run_id"]))
    store.create(payload, repo=tmp_path)
    store.update(status="architect_failed_no_replay", stop_reason="provider result is ambiguous")
    monkeypatch.setattr(application, "_machine", lambda _repo: _machine(state_root))

    result = application.status(tmp_path, run_id=str(payload["run_id"]))

    assert result["current_state"] == "BLOCKED_AMBIGUOUS"
    assert result["allowed_actions"] == ["get_status", "doctor", "stop"]


def test_exact_merge_intent_ambiguity_advertises_only_reobservation(monkeypatch, tmp_path: Path):
    payload = _payload(tmp_path)
    state_root = tmp_path / "state"
    store = PlanRunStore(state_root, str(payload["run_id"]))
    store.create(payload, repo=tmp_path)
    store.update(
        status="merge_ambiguous",
        current_card={
            "task_id": "RC2-P3-001",
            "branch": "codex/rc2-p3",
            "status": "deciding",
            "pull_request": 38,
            "head_sha": "5" * 40,
            "merge": {
                "status": "intent",
                "method": "merge",
                "pull_request": 38,
                "head_sha": "5" * 40,
            },
        },
    )
    monkeypatch.setattr(application, "_machine", lambda _repo: _machine(state_root))

    result = application.status(tmp_path, run_id=str(payload["run_id"]))

    assert result["current_state"] == "BLOCKED_AMBIGUOUS"
    assert result["allowed_actions"] == [
        "get_status",
        "doctor",
        "continue_after_approval",
        "stop",
    ]


def test_conflicting_completed_facts_never_advertise_deinit(monkeypatch, tmp_path: Path):
    payload = _payload(tmp_path)
    state_root = tmp_path / "state"
    store = PlanRunStore(state_root, str(payload["run_id"]))
    store.create(payload, repo=tmp_path)
    store.update(
        status="milestone_completed",
        current_card={"task_id": "still-active"},
        stop_requested=True,
    )
    monkeypatch.setattr(application, "_machine", lambda _repo: _machine(state_root))

    result = application.status(tmp_path, run_id=str(payload["run_id"]))

    assert result["allowed_actions"] == ["get_status", "doctor", "stop"]
    assert result["blocker"]["code"] == "authority_conflict"


def test_unpersisted_completed_fact_never_advertises_deinit(monkeypatch, tmp_path: Path):
    payload = _payload(tmp_path)
    state_root = tmp_path / "state"
    store = PlanRunStore(state_root, str(payload["run_id"]))
    store.create(payload, repo=tmp_path)
    store.update(
        status="milestone_completed",
        last_completion={"sha256": "a" * 64},
    )
    monkeypatch.setattr(application, "_machine", lambda _repo: _machine(state_root))

    result = application.status(tmp_path, run_id=str(payload["run_id"]))

    assert result["allowed_actions"] == ["get_status", "doctor", "stop"]


def test_start_plan_requires_exact_human_intent_and_current_machine_roles(
    monkeypatch, tmp_path: Path
):
    profiles = tuple(
        SimpleNamespace(role=role, values={"tool": tool, "model": model})
        for role, tool, model in (
            ("architect", "opencode", ""),
            ("coder", "opencode", "coder-model"),
            ("reviewer", "codex", ""),
        )
    )
    monkeypatch.setattr(application, "_machine", lambda _repo: SimpleNamespace(profiles=profiles))
    observed: dict[str, object] = {}
    monkeypatch.setattr(
        awf_plan, "start_plan", lambda **kwargs: observed.update(kwargs) or {"ok": True}
    )

    with pytest.raises(application.ApplicationError, match="Human intent"):
        application.start_plan(
            tmp_path, plan="docs/plan.md", mode="milestone", human_intent="approved"
        )

    result = application.start_plan(
        tmp_path,
        plan="docs/plan.md",
        mode="milestone",
        human_intent=application.HUMAN_PLAN_INTENT,
    )

    assert result == {"ok": True}
    assert observed["coder_tool"] == "opencode"
    assert observed["coder_model"] == "coder-model"
    assert observed["reviewer_tool"] == "codex"
    assert observed["reviewer_model"] == ""


def test_stop_requires_its_own_human_intent_and_forwards_exact_run(monkeypatch, tmp_path: Path):
    observed: dict[str, object] = {}
    monkeypatch.setattr(
        application, "status", lambda *_args, **_kwargs: {"allowed_actions": ["stop"]}
    )
    monkeypatch.setattr(
        application.facade,
        "stop",
        lambda repo, *, run_id: observed.update(repo=repo, run_id=run_id) or 0,
    )

    with pytest.raises(application.ApplicationError, match="intent for stop"):
        application.stop(
            tmp_path, run_id="plan-current", human_intent=application.HUMAN_PLAN_INTENT
        )

    assert (
        application.stop(
            tmp_path, run_id="plan-current", human_intent=application.HUMAN_STOP_INTENT
        )
        == 0
    )
    assert observed["run_id"] == "plan-current"


def test_deinit_requires_its_own_human_intent_and_forwards_exact_run(monkeypatch, tmp_path: Path):
    observed: dict[str, object] = {}
    monkeypatch.setattr(
        application, "status", lambda *_args, **_kwargs: {"allowed_actions": ["deinit"]}
    )
    monkeypatch.setattr(
        application.facade,
        "deinit",
        lambda repo, *, run_id: observed.update(repo=repo, run_id=run_id) or 0,
    )

    with pytest.raises(application.ApplicationError, match="intent for deinit"):
        application.deinit(
            tmp_path, run_id="plan-completed", human_intent=application.HUMAN_PLAN_INTENT
        )

    assert (
        application.deinit(
            tmp_path,
            run_id="plan-completed",
            human_intent=application.HUMAN_DEINIT_INTENT,
        )
        == 0
    )
    assert observed["run_id"] == "plan-completed"


def test_continue_after_approval_requires_its_own_intent_and_exact_run(monkeypatch, tmp_path: Path):
    observed: dict[str, object] = {}
    monkeypatch.setattr(
        application,
        "status",
        lambda *_args, **_kwargs: {"allowed_actions": ["continue_after_approval"]},
    )
    architect = SimpleNamespace(role="architect")
    monkeypatch.setattr(
        application, "_machine", lambda *_args: SimpleNamespace(profiles=(architect,))
    )
    monkeypatch.setattr(application, "_store", lambda *_args: SimpleNamespace(state_root=tmp_path))
    monkeypatch.setattr(
        awf_plan,
        "continue_after_approval",
        lambda **kwargs: observed.update(kwargs) or {"status": "completed"},
    )

    with pytest.raises(application.ApplicationError, match="intent for approval continuation"):
        application.continue_after_approval(
            tmp_path, run_id="plan-current", human_intent=application.HUMAN_PLAN_INTENT
        )

    assert application.continue_after_approval(
        tmp_path,
        run_id="plan-current",
        human_intent=application.HUMAN_APPROVAL_CONTINUE_INTENT,
    ) == {"status": "completed"}
    assert observed["run_id"] == "plan-current"


def test_replacement_requires_its_own_human_intent(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(application, "status", lambda *_args, **_kwargs: {"allowed_actions": []})

    with pytest.raises(application.ApplicationError, match="intent for replacement"):
        application.authorize_replacement(
            tmp_path,
            run_id="plan-example",
            human_intent=application.HUMAN_PLAN_INTENT,
            old_event_id=1,
            old_delivery_id="awf:" + "1" * 64,
            old_role="coder",
        )


def test_replacement_authorization_is_one_shot_per_old_delivery(monkeypatch, tmp_path: Path):
    payload = _payload(tmp_path)
    state_root = tmp_path / "state"
    store = PlanRunStore(state_root, str(payload["run_id"]))
    store.create(payload, repo=tmp_path)
    store.update(
        status="card_active",
        current_card={"branch": "feature/replacement", "frozen_base": "a" * 40},
    )
    lineage = {
        "old_delivery_id": "awf:" + "1" * 64,
        "old_payload_sha256": "sha256:" + "2" * 64,
        "old_checkpoint_sha256": "sha256:" + "3" * 64,
        "old_role": "coder",
        "old_event_id": "1",
        "old_branch": "feature/replacement",
        "old_source_commit": "b" * 40,
        "old_base_sha": "a" * 40,
        "old_provenance_sha256": "sha256:" + "4" * 64,
    }
    dispatches: list[dict[str, object]] = []
    monkeypatch.setattr(application, "_store", lambda *_args: store)
    monkeypatch.setattr(awf_role, "replacement_evidence", lambda *_args, **_kwargs: lineage)
    delivery = {
        "delivery_id": "awf:" + "5" * 64,
        "payload_sha256": "sha256:" + "6" * 64,
        "source_event_id": 1,
    }

    def dispatch(**kwargs):
        dispatches.append(kwargs)
        current = store.load()["current_card"]
        store.update(current_card={**current, "replacement_delivery": delivery})
        return {"replacement_authorization": lineage, "replacement_delivery": delivery}

    monkeypatch.setattr(awf_plan, "dispatch_authorized_replacement", dispatch)
    monkeypatch.setattr(
        application,
        "_machine",
        lambda _repo: SimpleNamespace(profiles=(SimpleNamespace(role="architect"),)),
    )

    first = application.authorize_replacement(
        tmp_path,
        run_id=str(payload["run_id"]),
        human_intent=application.HUMAN_REPLACEMENT_INTENT,
        old_event_id=1,
        old_delivery_id=lineage["old_delivery_id"],
        old_role="coder",
    )
    second = application.authorize_replacement(
        tmp_path,
        run_id=str(payload["run_id"]),
        human_intent=application.HUMAN_REPLACEMENT_INTENT,
        old_event_id=1,
        old_delivery_id=lineage["old_delivery_id"],
        old_role="coder",
    )

    assert first == second
    assert first["replacement_authorization"] == lineage
    assert len(dispatches) == 1
    assert store.load()["current_card"]["replacement_authorization"] == lineage
