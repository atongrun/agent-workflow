from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPTS_DIR = Path(__file__).parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import awf_dispatch  # noqa: E402
import awf_plan  # noqa: E402
import awf_preflight  # noqa: E402

from agent_workflow.plan_loop import (  # noqa: E402
    ArchitectBinding,
    PlanFact,
    PlanRunStore,
    plan_start_payload,
)


def facts(tmp_path: Path):
    profile = tmp_path / "architect.json"
    profile.write_text("{}", encoding="utf-8")
    binding = ArchitectBinding(
        profile=str(profile),
        profile_sha256="sha256:" + "a" * 64,
        workspace=str((tmp_path / "repo").resolve()),
        tool="pi",
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
    payload = plan_start_payload(
        plan,
        binding,
        mode="one-card",
        coder_tool="opencode",
        coder_model="",
        reviewer_tool="opencode",
        reviewer_model="",
    )
    return binding, plan, payload


def handler_args(tmp_path: Path, payload: dict[str, object]) -> argparse.Namespace:
    return argparse.Namespace(
        run_id=payload["run_id"],
        mode=payload["mode"],
        plan_json=json.dumps(payload["plan"]),
        architect_json=json.dumps(payload["architect"]),
        coder_json=json.dumps(payload["coder"]),
        reviewer_json=json.dumps(payload["reviewer"]),
        payload_sha256=payload["awf_payload_sha256"],
        delivery_id=payload["awf_delivery_id"],
        repo=str((tmp_path / "repo").resolve()),
        state_root=str((tmp_path / "state").resolve()),
        profile=payload["architect"]["profile"],
        profile_sha256=payload["architect"]["profile_sha256"],
        tool="pi",
        model="",
        config=str(tmp_path / "dispatch.env"),
        authority_manifest=str(tmp_path / "authority.json"),
        upstream_remote="upstream",
        head_remote="fork",
        head_repo="contributor/project",
        gh_bin="gh",
    )


def test_remote_dispatch_reuses_current_deep_or_runs_existing_deep(
    monkeypatch, tmp_path: Path
) -> None:
    _binding, _plan, payload = facts(tmp_path)
    store = PlanRunStore(tmp_path / "state", str(payload["run_id"]))
    store.create(payload, repo=tmp_path / "repo")
    args = handler_args(tmp_path, payload)
    calls: list[str] = []
    fast = {
        "status": "FAIL",
        "allow_remote_dispatch": False,
        "required_next_action": "run_deep_preflight",
    }
    monkeypatch.setattr(
        awf_preflight,
        "run_fast",
        lambda _args: SimpleNamespace(report=fast),
    )
    monkeypatch.setattr(
        awf_preflight,
        "run_deep",
        lambda _args: (
            calls.append("deep")
            or {"status": "PASS", "allow_remote_dispatch": True, "deep": {"current": True}}
        ),
    )

    report = awf_plan._run_dispatch_preflight(
        args,
        store=store,
        repo=tmp_path / "repo",
    )

    assert calls == ["deep"]
    assert report["allow_remote_dispatch"] is True
    assert store.load()["preflight"]["remote_dispatch"] == report


def test_handle_start_orders_fast_before_pi_and_deep_before_business_send(
    monkeypatch, tmp_path: Path
) -> None:
    binding, plan, payload = facts(tmp_path)
    repo = tmp_path / "repo"
    (repo / "docs/tasks").mkdir(parents=True)
    args = handler_args(tmp_path, payload)
    store = PlanRunStore(tmp_path / "state", str(payload["run_id"]))
    store.create(payload, repo=repo)
    calls: list[str] = []
    raw = f"""# TaskCard

## Task ID

CARD-001

- **Task branch**: `codex/CARD-001`
- **Frozen base**: `{plan.main_sha}`

<!-- awf-reviewer-selection
{{"coder":{{"model":"","tool":"opencode"}},"reviewer":{{"model":"","tool":"opencode"}}}}
-->
""".encode()

    monkeypatch.setattr(awf_plan, "_checkout_plan_main", lambda *_a, **_k: b"# Plan\n")
    monkeypatch.setattr(
        awf_plan,
        "_run_authoring_fast",
        lambda *_a, **_k: calls.append("authoring-fast") or {"status": "PASS"},
    )
    monkeypatch.setattr(
        awf_plan,
        "_invoke_taskcard_architect",
        lambda *_a, **_k: calls.append("pi") or (raw, "CARD-001", "codex/CARD-001"),
    )

    def persist(**kwargs):
        Path(kwargs["destination"]).write_bytes(kwargs["stdout"])

    monkeypatch.setattr(awf_plan, "persist_architect_taskcard", persist)
    monkeypatch.setattr(
        awf_plan,
        "_run_dispatch_preflight",
        lambda *_a, **_k: calls.append("remote-fast-deep") or {"status": "PASS"},
    )
    monkeypatch.setattr(awf_plan, "_git", lambda *_a, **_k: "5" * 40)

    def dispatch(_args, *, before_send):
        calls.append("dispatch-prepared")
        before_send(repo, {})
        calls.append("business-send")

    monkeypatch.setattr(awf_dispatch, "dispatch", dispatch)

    result = awf_plan.handle_start(args)

    assert binding.workspace == str(repo.resolve())
    assert calls == [
        "authoring-fast",
        "pi",
        "dispatch-prepared",
        "remote-fast-deep",
        "business-send",
    ]
    assert result["status"] == "card_active"
    assert result["current_card"]["branch"] == "codex/CARD-001"


def terminal_fixture(tmp_path: Path):
    _binding, _plan, payload = facts(tmp_path)
    store = PlanRunStore(tmp_path / "state", str(payload["run_id"]))
    store.create(payload, repo=tmp_path / "source")
    store.update(
        status="card_active",
        current_card={
            "task_id": "CARD-001",
            "path": "docs/tasks/CARD-001.md",
            "branch": "codex/CARD-001",
            "frozen_base": "4" * 40,
            "status": "active",
            "taskcard_commit": "5" * 40,
        },
    )
    args = argparse.Namespace(
        branch="codex/CARD-001",
        commit="6" * 40,
        report=".awf/artifacts/impl-report-CARD-001.md",
        review_report=".awf/artifacts/review-report-CARD-001.md",
    )
    provenance = {
        "upstream_repo": "owner/project",
        "upstream_remote": "upstream",
        "base_ref": "main",
        "base_sha": "4" * 40,
        "head_repo": "contributor/project",
        "head_remote": "fork",
        "head_ref": "codex/CARD-001",
        "head_sha": "6" * 40,
        "pull_request": 7,
    }
    evidence = SimpleNamespace(event_id=9, state_dir=tmp_path / "state")
    input_context = {
        "delivery_id": "delivery",
        "payload_sha256": "payload",
        "source_event_id": 8,
    }
    return store, args, provenance, evidence, input_context


def test_merge_intent_precedes_exact_effect_and_observation(monkeypatch, tmp_path: Path) -> None:
    store, _args, provenance, _evidence, _input = terminal_fixture(tmp_path)
    source = tmp_path / "source"
    source.mkdir()

    def merge_command(*_args, **_kwargs):
        assert store.load()["status"] == "merge_intent"
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(awf_plan, "run_command", merge_command)
    monkeypatch.setattr(
        awf_plan,
        "_gh_json",
        lambda *_a, **_k: {
            "number": 7,
            "state": "MERGED",
            "headRefOid": "6" * 40,
            "mergeCommit": {"oid": "7" * 40},
        },
    )
    monkeypatch.setattr(
        awf_plan,
        "_git",
        lambda _repo, *git_args, **_kwargs: (
            "7" * 40 if git_args[:2] == ("rev-parse", "refs/remotes/upstream/main^{commit}") else ""
        ),
    )

    observed = awf_plan._merge_and_observe(
        store=store,
        repo=source,
        provenance=provenance,
        card=dict(store.load()["current_card"]),
    )

    assert observed == {"state": "MERGED", "commit": "7" * 40, "method": "merge"}


def test_ambiguous_merge_is_persisted_and_never_retried(monkeypatch, tmp_path: Path) -> None:
    store, args, provenance, evidence, input_context = terminal_fixture(tmp_path)
    source = tmp_path / "source"
    source.mkdir()
    monkeypatch.setattr(
        awf_plan,
        "run_command",
        lambda *_a, **_k: SimpleNamespace(returncode=1),
    )

    with pytest.raises(awf_plan.PlanOperationError, match="do not retry"):
        awf_plan._merge_and_observe(
            store=store,
            repo=source,
            provenance=provenance,
            card=dict(store.load()["current_card"]),
        )

    assert store.load()["status"] == "merge_ambiguous"
    with pytest.raises(awf_plan.PlanOperationError, match="no automatic terminal replay"):
        awf_plan.handle_card_terminal(
            args=args,
            evidence=evidence,
            input_context=input_context,
            review_report={"verdict": "PASS"},
            provenance=provenance,
            terminal_repo=tmp_path / "terminal",
            implementation_sha256="sha256:" + "1" * 64,
            review_sha256="sha256:" + "2" * 64,
        )


def test_plan_terminal_approve_creates_completed_card_fact(monkeypatch, tmp_path: Path) -> None:
    store, args, provenance, evidence, input_context = terminal_fixture(tmp_path)
    source = tmp_path / "source"
    source.mkdir()
    monkeypatch.setenv("AWF_REPO_DIR", str(source))
    monkeypatch.setattr(
        awf_plan,
        "_invoke_terminal_decision",
        lambda **_kwargs: {"verdict": "approve", "sha256": "8" * 64, "bytes": 10},
    )
    monkeypatch.setattr(
        awf_plan,
        "_wait_exact_ci",
        lambda *_a, **_k: {"conclusion": "SUCCESS", "head_sha": "6" * 40, "checks": 1},
    )
    monkeypatch.setattr(
        awf_plan,
        "_merge_and_observe",
        lambda **_kwargs: {"state": "MERGED", "commit": "7" * 40, "method": "merge"},
    )

    result = awf_plan.handle_card_terminal(
        args=args,
        evidence=evidence,
        input_context=input_context,
        review_report={"verdict": "PASS"},
        provenance=provenance,
        terminal_repo=tmp_path / "terminal",
        implementation_sha256="sha256:" + "1" * 64,
        review_sha256="sha256:" + "2" * 64,
    )

    assert result["terminal_state"] == "completed"
    run = store.load()
    assert run["status"] == "completed"
    assert run["current_card"] is None
    assert run["last_completion"]["merge"]["commit"] == "7" * 40


def test_plan_terminal_nonapprove_stops_without_ci_or_merge(monkeypatch, tmp_path: Path) -> None:
    store, args, provenance, evidence, input_context = terminal_fixture(tmp_path)
    monkeypatch.setattr(
        awf_plan,
        "_invoke_terminal_decision",
        lambda **_kwargs: {"verdict": "reject", "sha256": "8" * 64, "bytes": 10},
    )
    monkeypatch.setattr(
        awf_plan,
        "_wait_exact_ci",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("CI must not run")),
    )

    result = awf_plan.handle_card_terminal(
        args=args,
        evidence=evidence,
        input_context=input_context,
        review_report={"verdict": "PASS"},
        provenance=provenance,
        terminal_repo=tmp_path / "terminal",
        implementation_sha256="sha256:" + "1" * 64,
        review_sha256="sha256:" + "2" * 64,
    )

    assert result["terminal_state"] == "rejected"
    assert store.load()["status"] == "rejected"
    assert store.load()["current_card"]["decision"]["verdict"] == "reject"
