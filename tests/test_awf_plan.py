from __future__ import annotations

import argparse
import json
import sys
from contextlib import nullcontext
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


def facts(tmp_path: Path, *, mode: str = "one-card"):
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
        mode=mode,
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


def test_local_architect_accepts_exact_registered_managed_snapshot(
    monkeypatch, tmp_path: Path
) -> None:
    binding, _plan, payload = facts(tmp_path)
    args = handler_args(tmp_path, payload)
    snapshot = tmp_path / "installed" / "architect.json"
    snapshot.parent.mkdir()
    snapshot.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        awf_plan.node,
        "load_installed_profile",
        lambda value: (
            SimpleNamespace(path=snapshot, digest=binding.profile_sha256)
            if Path(value).resolve() == Path(binding.profile).resolve()
            else None
        ),
    )
    args.profile = str(snapshot)

    awf_plan._validate_local_architect(args, binding)

    args.profile = str(tmp_path / "other-installed.json")
    with pytest.raises(awf_plan.PlanOperationError, match="RoleBinding drifted"):
        awf_plan._validate_local_architect(args, binding)


def test_local_architect_rejects_registered_snapshot_digest_drift(
    monkeypatch, tmp_path: Path
) -> None:
    binding, _plan, payload = facts(tmp_path)
    args = handler_args(tmp_path, payload)
    snapshot = tmp_path / "installed" / "architect.json"
    snapshot.parent.mkdir()
    snapshot.write_text("{}", encoding="utf-8")
    args.profile = str(snapshot)
    monkeypatch.setattr(
        awf_plan.node,
        "load_installed_profile",
        lambda _value: SimpleNamespace(path=snapshot, digest="sha256:" + "b" * 64),
    )

    with pytest.raises(awf_plan.PlanOperationError, match="installed profile identity drifted"):
        awf_plan._validate_local_architect(args, binding)


def test_remote_dispatch_reuses_current_deep_or_runs_existing_deep(
    monkeypatch, tmp_path: Path
) -> None:
    _binding, _plan, payload = facts(tmp_path)
    store = PlanRunStore(tmp_path / "state", str(payload["run_id"]))
    store.create(payload, repo=tmp_path / "repo")
    args = handler_args(tmp_path, payload)
    calls: list[str] = []
    monkeypatch.setattr(awf_plan, "_preflight_environment", lambda _path: nullcontext())
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


def test_internal_preflight_environment_is_deterministic_and_restored(monkeypatch, tmp_path):
    config = tmp_path / "dispatch.env"
    config.write_text(
        "AGENT_BUS_URL=http://100.108.67.47:8800\n"
        "AWF_ARCH_TOKEN=arch\nAWF_CODER_TOKEN=coder\nAWF_REVIEWER_TOKEN=review\n",
        encoding="utf-8",
    )
    config.chmod(0o600)
    monkeypatch.setattr(
        awf_plan,
        "load_config",
        lambda _path: {"AGENT_BUS_URL": "http://100.108.67.47:8800"},
    )
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:7897")
    monkeypatch.setenv("NO_PROXY", "original")
    monkeypatch.setenv("no_proxy", "original")

    with awf_plan._preflight_environment(config):
        assert "HTTP_PROXY" not in awf_plan.os.environ
        assert set(awf_plan.os.environ["NO_PROXY"].split(",")) == {
            "100.108.67.47",
            "github.com",
            "api.github.com",
        }
        assert awf_plan.os.environ["no_proxy"] == awf_plan.os.environ["NO_PROXY"]

    assert awf_plan.os.environ["HTTP_PROXY"] == "http://127.0.0.1:7897"
    assert awf_plan.os.environ["NO_PROXY"] == "original"


def test_invalid_pi_taskcard_result_is_persisted_and_never_replayed(monkeypatch, tmp_path):
    binding, plan, payload = facts(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    store = PlanRunStore(tmp_path / "state", str(payload["run_id"]))
    store.create(payload, repo=repo)
    args = handler_args(tmp_path, payload)

    def invalid_result(_rendered, **kwargs):
        Path(kwargs["stdout_path"]).parent.mkdir(parents=True, exist_ok=True)
        Path(kwargs["stdout_path"]).write_text("# invalid TaskCard\n", encoding="utf-8")
        return 0

    monkeypatch.setattr(awf_plan, "spawn_rendered", invalid_result)
    monkeypatch.setattr(awf_plan, "_architect_workspace", lambda source, _commit, _store: source)
    monkeypatch.setattr(awf_plan, "assert_model_workspace_state", lambda *_args: None)

    with pytest.raises(awf_plan.PlanLoopError):
        awf_plan._invoke_taskcard_architect(
            args,
            store=store,
            plan=plan,
            binding=binding,
            plan_bytes=b"# Plan\n",
            repo=repo,
            coder={"tool": "opencode", "model": ""},
            reviewer={"tool": "opencode", "model": ""},
        )

    run = store.load()
    assert run["status"] == "architect_output_invalid_no_replay"
    assert run["architect_invocation"]["status"] == "result_invalid"
    assert not (repo / ".awf" / f"architect-context-{run['run_id']}.md").exists()


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


def terminal_fixture(tmp_path: Path, *, mode: str = "one-card"):
    _binding, _plan, payload = facts(tmp_path, mode=mode)
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
    assert store.completions() == (run["last_completion"],)


def _completed_milestone_store(tmp_path: Path):
    binding, plan, payload = facts(tmp_path, mode="milestone")
    source = tmp_path / "repo"
    source.mkdir()
    store = PlanRunStore(tmp_path / "state", str(payload["run_id"]))
    run = store.create(payload, repo=source)
    completion = awf_plan.completed_card_fact(
        run=run,
        card={
            "task_id": "CARD-001",
            "path": "docs/tasks/CARD-001.md",
            "branch": "agent/CARD-001",
            "frozen_base": "4" * 40,
            "head_sha": "6" * 40,
        },
        decision={"verdict": "approve"},
        ci={"conclusion": "SUCCESS"},
        merge={"state": "MERGED", "commit": "7" * 40},
    )
    store.persist_completion(completion)
    store.update(status="card_completed", current_card=None, last_completion=completion)
    return binding, plan, store, source, completion


def _bind_listener_environment(monkeypatch, binding: ArchitectBinding, tmp_path: Path) -> None:
    monkeypatch.setenv("AWF_PROFILE_PATH", binding.profile)
    monkeypatch.setenv("AWF_PROFILE_SHA256", binding.profile_sha256)
    monkeypatch.setenv("AWF_TOOL", "pi")
    monkeypatch.setenv("AWF_MODEL", "")
    monkeypatch.setenv("AWF_DISPATCH_ENV", str(tmp_path / "dispatch.env"))
    monkeypatch.setenv("AWF_AUTHORITY_MANIFEST", str(tmp_path / "authority.json"))
    monkeypatch.setenv("AWF_HEAD_REPO", "contributor/project")
    monkeypatch.setenv("AWF_HEAD_REMOTE", "fork")


@pytest.mark.parametrize(
    ("outcome", "raw", "expected_status", "expected_reason"),
    [
        ("MILESTONE_COMPLETE", b"MILESTONE_COMPLETE\n", "milestone_completed", ""),
        ("BLOCKED", b"BLOCKED\nmissing owner fact\n", "blocked", "missing owner fact"),
    ],
)
def test_milestone_continuation_is_closed_and_reruns_authoring_fast(
    monkeypatch,
    tmp_path: Path,
    outcome: str,
    raw: bytes,
    expected_status: str,
    expected_reason: str,
) -> None:
    binding, _plan, store, source, _completion = _completed_milestone_store(tmp_path)
    _bind_listener_environment(monkeypatch, binding, tmp_path)
    calls: list[object] = []
    monkeypatch.setattr(
        awf_plan,
        "_checkout_fresh_main",
        lambda *_a, **_k: (b"# Exact Plan\n", "9" * 40),
    )
    monkeypatch.setattr(
        awf_plan,
        "_run_authoring_fast",
        lambda *_a, **_k: calls.append("authoring-fast") or {"status": "PASS"},
    )
    monkeypatch.setattr(
        awf_plan,
        "_invoke_next_architect",
        lambda **kwargs: calls.append(kwargs["context"]) or (outcome, raw, "", ""),
    )

    result = awf_plan._continue_milestone(
        store=store,
        source_repo=source,
        state_root=tmp_path / "state",
    )

    assert result["status"] == expected_status
    assert result["stop_reason"] == expected_reason
    assert calls[0] == "authoring-fast"
    assert '"fresh_main": "' + "9" * 40 + '"' in str(calls[1])


def test_milestone_next_card_reuses_single_card_dispatch_with_fresh_base(
    monkeypatch,
    tmp_path: Path,
) -> None:
    binding, plan, store, source, _completion = _completed_milestone_store(tmp_path)
    _bind_listener_environment(monkeypatch, binding, tmp_path)
    next_raw = b"next TaskCard"
    observed: dict[str, object] = {}
    monkeypatch.setattr(
        awf_plan,
        "_checkout_fresh_main",
        lambda *_a, **_k: (b"# Exact Plan\n", "9" * 40),
    )
    monkeypatch.setattr(awf_plan, "_run_authoring_fast", lambda *_a, **_k: {"status": "PASS"})
    monkeypatch.setattr(
        awf_plan,
        "_invoke_next_architect",
        lambda **_kwargs: ("NEXT_TASK_CARD", next_raw, "CARD-002", "agent/CARD-002"),
    )
    monkeypatch.setattr(
        awf_plan,
        "_persist_and_dispatch_taskcard",
        lambda _args, **kwargs: observed.update(kwargs) or {"status": "card_active"},
    )

    result = awf_plan._continue_milestone(
        store=store,
        source_repo=source,
        state_root=tmp_path / "state",
    )

    assert result["status"] == "card_active"
    assert observed["plan"] == plan
    assert observed["raw"] == next_raw
    assert observed["task_id"] == "CARD-002"
    assert observed["frozen_base"] == "9" * 40


def test_next_architect_ambiguous_invocation_is_never_replayed(monkeypatch, tmp_path: Path) -> None:
    binding, _plan, store, source, completion = _completed_milestone_store(tmp_path)
    monkeypatch.setattr(
        awf_plan,
        "spawn_rendered",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("provider lost")),
    )
    monkeypatch.setattr(awf_plan, "_architect_workspace", lambda source, _commit, _store: source)
    monkeypatch.setattr(awf_plan, "assert_model_workspace_state", lambda *_args: None)
    kwargs = {
        "store": store,
        "binding": binding,
        "workspace": source,
        "context": "context",
        "last_completion": completion,
        "fresh_main": "9" * 40,
        "coder": {"tool": "opencode", "model": ""},
        "reviewer": {"tool": "opencode", "model": ""},
    }

    with pytest.raises(RuntimeError, match="provider lost"):
        awf_plan._invoke_next_architect(run=store.load(), **kwargs)
    with pytest.raises(awf_plan.PlanOperationError, match="will not replay"):
        awf_plan._invoke_next_architect(run=store.load(), **kwargs)


def test_terminal_completion_enters_milestone_only_after_fact_is_persisted(
    monkeypatch,
    tmp_path: Path,
) -> None:
    store, args, provenance, evidence, input_context = terminal_fixture(
        tmp_path,
        mode="milestone",
    )
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
    observed: list[str] = []

    def continue_after_fact(**_kwargs):
        observed.append(str(store.completions()[0]["sha256"]))
        return store.load()

    monkeypatch.setattr(awf_plan, "_continue_milestone", continue_after_fact)

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
    assert observed == [store.load()["last_completion"]["sha256"]]
    assert store.load()["status"] == "card_completed"


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
