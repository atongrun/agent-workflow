from __future__ import annotations

import argparse
import hashlib
import json
from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_workflow.operations import (
    awf_dispatch,  # noqa: E402
    awf_plan,  # noqa: E402
    awf_preflight,  # noqa: E402
)
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


def prepared_payload(commit: str) -> tuple[dict[str, object], dict[str, str]]:
    payload: dict[str, object] = {
        "awf_delivery_id": "awf:" + "d" * 64,
        "awf_payload_sha256": "p" * 64,
        "commit": commit,
    }
    prepared = {
        "format": "awf.plan-prepared-dispatch.v1",
        "delivery_id": str(payload["awf_delivery_id"]),
        "payload_sha256": str(payload["awf_payload_sha256"]),
        "commit": commit,
        "canonical_sha256": hashlib.sha256(
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        ).hexdigest(),
    }
    return payload, prepared


def handler_args(tmp_path: Path, payload: dict[str, object]) -> argparse.Namespace:
    return argparse.Namespace(
        event_id="299",
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


def test_handler_reuses_exact_initiating_deep_after_current_fast_passes(
    monkeypatch, tmp_path: Path
) -> None:
    _binding, _plan, payload = facts(tmp_path)
    store = PlanRunStore(tmp_path / "state", str(payload["run_id"]))
    store.create(payload, repo=tmp_path / "repo")
    previous = {
        "format": "awf.preflight-report.v1",
        "mode": "deep",
        "status": "PASS",
        "allow_remote_dispatch": True,
        "required_next_action": "remote_dispatch_allowed",
        "fingerprint": "a" * 64,
        "deep": {"current": True},
    }
    store.update(preflight={"remote_dispatch": previous})
    args = handler_args(tmp_path, payload)
    selected: dict[str, object] = {}
    monkeypatch.setattr(awf_plan, "_preflight_environment", lambda _path: nullcontext())
    monkeypatch.setattr(
        awf_preflight,
        "run_fast",
        lambda _args: SimpleNamespace(
            report={
                "status": "FAIL",
                "allow_remote_dispatch": False,
                "required_next_action": "run_deep_preflight",
                "layers": [
                    {
                        "id": "agent-bus",
                        "status": "PASS",
                        "evidence": {"pending": {"architect": 1, "coder": 0}},
                    }
                ],
            },
            config={"AWF_ARCH_TOKEN": "a", "AWF_CODER_TOKEN": "b"},
        ),
    )
    monkeypatch.setattr(awf_preflight, "cache_path", lambda root: root / "latest-deep.json")
    monkeypatch.setattr(awf_preflight, "utc_now", lambda: "now")

    def load(path, fingerprint, now, **kwargs):
        selected.update(path=path, fingerprint=fingerprint, now=now, **kwargs)
        return previous

    monkeypatch.setattr(awf_preflight, "load_current_cache", load)
    monkeypatch.setattr(
        awf_preflight,
        "run_deep",
        lambda _args: pytest.fail("busy Architect listener must not start a second Deep probe"),
    )

    report = awf_plan._run_dispatch_preflight(args, store=store, repo=tmp_path / "repo")

    assert report == previous
    assert selected["fingerprint"] == "a" * 64
    assert selected["source_role"] == "architect"
    assert selected["target_role"] == "coder"


def test_remote_dispatch_resumes_only_the_same_inflight_timed_out_probe(
    monkeypatch, tmp_path: Path
) -> None:
    _binding, _plan, payload = facts(tmp_path)
    store = PlanRunStore(tmp_path / "state", str(payload["run_id"]))
    store.create(payload, repo=tmp_path / "repo")
    store.update(
        status="dispatch_blocked",
        preflight={
            "remote_dispatch": {
                "required_next_action": "resume_deep_preflight",
                "deep": {
                    "error_code": "DEEP_REPLY_TIMEOUT",
                    "probe_id": "awf-preflight-" + "5" * 32,
                    "inflight_event_id": 299,
                },
            }
        },
    )
    args = handler_args(tmp_path, payload)
    observed: dict[str, object] = {}
    monkeypatch.setattr(awf_plan, "_preflight_environment", lambda _path: nullcontext())
    monkeypatch.setattr(
        awf_preflight,
        "run_resume_deep",
        lambda selected: (
            observed.update(
                probe_id=selected.probe_id,
                inflight_event_id=selected.inflight_event_id,
            )
            or {"status": "PASS", "allow_remote_dispatch": True}
        ),
    )
    monkeypatch.setattr(
        awf_preflight,
        "run_deep",
        lambda _args: (_ for _ in ()).throw(AssertionError("must not send a new probe")),
    )

    awf_plan._run_dispatch_preflight(args, store=store, repo=tmp_path / "repo")

    assert observed == {
        "probe_id": "awf-preflight-" + "5" * 32,
        "inflight_event_id": 299,
    }


def test_failed_deep_resume_keeps_same_probe_lineage_for_next_reentry(
    monkeypatch, tmp_path: Path
) -> None:
    _binding, _plan, payload = facts(tmp_path)
    store = PlanRunStore(tmp_path / "state", str(payload["run_id"]))
    store.create(payload, repo=tmp_path / "repo")
    lineage = {
        "required_next_action": "resume_deep_preflight",
        "deep": {
            "error_code": "DEEP_REPLY_TIMEOUT",
            "probe_id": "awf-preflight-" + "6" * 32,
            "inflight_event_id": 299,
        },
    }
    store.update(status="dispatch_blocked", preflight={"remote_dispatch": lineage})
    args = handler_args(tmp_path, payload)
    calls: list[str] = []
    monkeypatch.setattr(awf_plan, "_preflight_environment", lambda _path: nullcontext())

    def resume(selected):
        calls.append(selected.probe_id)
        if len(calls) == 1:
            return {
                "status": "FAIL",
                "allow_remote_dispatch": False,
                "required_next_action": "resume_deep_preflight",
                "deep": {
                    "error_code": "DEEP_RESULT_MISSING",
                    "probe_id": selected.probe_id,
                    "inflight_event_id": selected.inflight_event_id,
                },
            }
        return {"status": "PASS", "allow_remote_dispatch": True}

    monkeypatch.setattr(awf_preflight, "run_resume_deep", resume)
    monkeypatch.setattr(
        awf_preflight,
        "run_deep",
        lambda _args: (_ for _ in ()).throw(AssertionError("must not send a new probe")),
    )

    with pytest.raises(awf_plan.PlanOperationError, match="did not authorize"):
        awf_plan._run_dispatch_preflight(args, store=store, repo=tmp_path / "repo")
    awf_plan._run_dispatch_preflight(args, store=store, repo=tmp_path / "repo")

    assert calls == ["awf-preflight-" + "6" * 32] * 2


def test_handler_preflight_binds_exact_inflight_event(tmp_path: Path) -> None:
    _binding, _plan, payload = facts(tmp_path)
    args = handler_args(tmp_path, payload)

    result = awf_plan._preflight_args(args, repo=tmp_path / "repo", intent="remote-dispatch")

    assert result.inflight_event_id == 299


def test_managed_architect_snapshot_matches_frozen_source_binding(
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
        lambda _source: SimpleNamespace(
            path=snapshot,
            authoring_path=Path(binding.profile),
            digest=binding.profile_sha256,
        ),
    )

    awf_plan._validate_local_architect(args, binding)


def test_managed_architect_snapshot_rejects_unbound_path(monkeypatch, tmp_path: Path) -> None:
    binding, _plan, payload = facts(tmp_path)
    args = handler_args(tmp_path, payload)
    snapshot = tmp_path / "installed" / "architect.json"
    alternate = tmp_path / "installed" / "other.json"
    snapshot.parent.mkdir()
    snapshot.write_text("{}", encoding="utf-8")
    alternate.write_text("{}", encoding="utf-8")
    args.profile = str(alternate)
    monkeypatch.setattr(
        awf_plan.node,
        "load_installed_profile",
        lambda _source: SimpleNamespace(
            path=snapshot,
            authoring_path=Path(binding.profile),
            digest=binding.profile_sha256,
        ),
    )

    with pytest.raises(awf_plan.PlanOperationError, match="RoleBinding drifted"):
        awf_plan._validate_local_architect(args, binding)


def test_authorized_replacement_dispatches_one_fresh_causally_bound_delivery(
    monkeypatch, tmp_path: Path
) -> None:
    _binding, plan, payload = facts(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    state_root = tmp_path / "state"
    store = PlanRunStore(state_root, str(payload["run_id"]))
    store.create(payload, repo=repo)
    lineage = {
        "old_delivery_id": "awf:" + "1" * 64,
        "old_payload_sha256": "sha256:" + "2" * 64,
        "old_checkpoint_sha256": "sha256:" + "3" * 64,
        "old_role": "coder",
        "old_event_id": "7",
        "old_branch": "feature/replacement",
        "old_source_commit": "b" * 40,
        "old_base_sha": "a" * 40,
        "old_provenance_sha256": "sha256:" + "4" * 64,
    }
    store.update(
        status="card_active",
        current_card={
            "task_id": "replacement",
            "path": "docs/tasks/replacement.md",
            "branch": "feature/replacement",
            "frozen_base": "a" * 40,
            "status": "active",
            "replacement_authorization": lineage,
        },
    )
    operation_args = SimpleNamespace(head_repo="contributor/project", head_remote="fork")
    monkeypatch.setattr(awf_plan, "_profile_operation_args", lambda *_args: operation_args)
    observed: dict[str, object] = {}
    monkeypatch.setattr(
        awf_plan,
        "_validate_local_architect",
        lambda _args, binding: observed.update(binding=binding),
    )
    monkeypatch.setattr(awf_plan, "_run_dispatch_preflight", lambda *_args, **_kwargs: None)
    from agent_workflow.operations import awf_dispatch

    seen: dict[str, object] = {}

    def dispatch(args, *, before_send):
        seen["source_event_id"] = args.source_event_id
        result = {
            "awf_delivery_id": "awf:" + "5" * 64,
            "awf_payload_sha256": "sha256:" + "2" * 64,
            "awf_source_event_id": 7,
            "branch": "feature/replacement",
            "commit": "b" * 40,
            "base_sha": "a" * 40,
        }
        before_send(repo, result)
        return result

    monkeypatch.setattr(awf_dispatch, "dispatch", dispatch)

    result = awf_plan.dispatch_authorized_replacement(
        repo=repo,
        state_root=state_root,
        run_id=str(payload["run_id"]),
        architect_profile=SimpleNamespace(),
    )

    assert seen["source_event_id"] == 7
    assert observed["binding"].profile == str(tmp_path / "architect.json")
    assert result["replacement_delivery"]["delivery_id"] != lineage["old_delivery_id"]
    assert store.load()["current_card"]["replacement_delivery"] == result["replacement_delivery"]


def test_internal_preflight_environment_bypasses_only_bus_and_restores(monkeypatch, tmp_path):
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
        assert awf_plan.os.environ["HTTP_PROXY"] == "http://127.0.0.1:7897"
        assert set(awf_plan.os.environ["NO_PROXY"].split(",")) == {
            "original",
            "100.108.67.47",
        }
        assert "github.com" not in awf_plan.os.environ["NO_PROXY"]
        assert awf_plan.os.environ["no_proxy"] == awf_plan.os.environ["NO_PROXY"]

    assert awf_plan.os.environ["HTTP_PROXY"] == "http://127.0.0.1:7897"
    assert awf_plan.os.environ["NO_PROXY"] == "original"


def test_exact_config_environment_overrides_and_restores_process_values(monkeypatch, tmp_path):
    config = tmp_path / "dispatch.env"
    monkeypatch.setattr(
        awf_plan,
        "load_config",
        lambda path: (
            {
                "AGENT_BUS_URL": "http://same-host-bus:8800",
                "AWF_ARCH_TOKEN": "exact-architect-token",
            }
            if path == config
            else {}
        ),
    )
    monkeypatch.setenv("AGENT_BUS_URL", "http://unrelated-bus:8800")
    monkeypatch.delenv("AWF_ARCH_TOKEN", raising=False)

    with awf_plan._exact_config_environment(config):
        assert awf_plan.os.environ["AGENT_BUS_URL"] == "http://same-host-bus:8800"
        assert awf_plan.os.environ["AWF_ARCH_TOKEN"] == "exact-architect-token"

    assert awf_plan.os.environ["AGENT_BUS_URL"] == "http://unrelated-bus:8800"
    assert "AWF_ARCH_TOKEN" not in awf_plan.os.environ


def test_plan_start_send_captures_agent_bus_stdio(monkeypatch, tmp_path):
    profile = SimpleNamespace(config_path=tmp_path / "dispatch.env")
    monkeypatch.setattr(awf_plan, "load_into_environment", lambda _path: None)
    monkeypatch.setenv("AGENT_BUS_URL", "http://127.0.0.1:18802")
    monkeypatch.setenv("AWF_ARCH_TOKEN", "controlled-test-token")
    monkeypatch.setenv("AWF_BUS_BIN", str(tmp_path / "agent-bus.exe"))
    observed: dict[str, object] = {}

    def fake_run(argv, **kwargs):
        observed["argv"] = argv
        observed.update(kwargs)
        return SimpleNamespace(returncode=0, stdout="sent\n", stderr="")

    monkeypatch.setattr(awf_plan, "run_command", fake_run)

    awf_plan._send_plan_start(profile, {"run_id": "plan-test"})

    assert observed["capture_output"] is True
    assert observed["text"] is True
    assert observed["encoding"] == "utf-8"
    assert observed["errors"] == "replace"
    assert "controlled-test-token" in observed["secrets"]


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


def test_opencode_taskcard_accepts_only_exact_whole_output_json_fence(monkeypatch, tmp_path):
    binding, plan, _payload = facts(tmp_path)
    binding = replace(binding, tool="opencode")
    payload = plan_start_payload(
        plan,
        binding,
        mode="one-card",
        coder_tool="opencode",
        coder_model="",
        reviewer_tool="opencode",
        reviewer_model="",
    )
    repo = tmp_path / "repo"
    repo.mkdir()
    store = PlanRunStore(tmp_path / "state", str(payload["run_id"]))
    store.create(payload, repo=repo)
    args = handler_args(tmp_path, payload)
    args.tool = "opencode"
    semantic = json.dumps(
        {
            "task_id": "CARD-001",
            "objective": "Bounded first card",
            "scope": ["Implement one bounded change."],
            "change_paths": ["src/example.py"],
            "constraints": ["Preserve authority."],
            "acceptance_criteria": ["Focused test passes."],
            "verification_commands": [["python", "-m", "pytest", "-q"]],
        }
    ).encode("utf-8")
    fenced = b"```json\n" + semantic + b"\n```\n"
    fenced_crlf = b"```json\r\n" + semantic + b"\r\n```\r\n"

    def fenced_result(_rendered, **kwargs):
        Path(kwargs["stdout_path"]).write_bytes(fenced)
        return 0

    monkeypatch.setattr(awf_plan, "spawn_rendered", fenced_result)

    raw, task_id, branch = awf_plan._invoke_taskcard_architect(
        args,
        store=store,
        plan=plan,
        binding=binding,
        plan_bytes=b"# Plan\n",
        repo=repo,
        coder={"tool": "opencode", "model": ""},
        reviewer={"tool": "opencode", "model": ""},
    )

    assert (task_id, branch) == ("CARD-001", "agent/CARD-001")
    assert b"<!-- awf-reviewer-selection" in raw
    assert (
        store.load()["architect_invocation"]["result_sha256"] == hashlib.sha256(fenced).hexdigest()
    )
    assert awf_plan._normalize_architect_provider_output(fenced_crlf, tool="opencode") == semantic
    assert (
        awf_plan._normalize_architect_provider_output(
            b"prose\n" + fenced,
            tool="opencode",
        )
        == b"prose\n" + fenced
    )


@pytest.mark.parametrize(
    "invalid",
    [
        b"```json\n{}\n```\n```json\n{}\n```\n",
        b"prose\n```json\n{}\n```\n",
    ],
    ids=("extra-fence", "leading-prose"),
)
def test_opencode_taskcard_rejects_nonexact_fence_without_replay(monkeypatch, tmp_path, invalid):
    binding, plan, _payload = facts(tmp_path)
    binding = replace(binding, tool="opencode")
    payload = plan_start_payload(
        plan,
        binding,
        mode="one-card",
        coder_tool="opencode",
        coder_model="",
        reviewer_tool="opencode",
        reviewer_model="",
    )
    repo = tmp_path / "repo"
    repo.mkdir()
    store = PlanRunStore(tmp_path / "state", str(payload["run_id"]))
    store.create(payload, repo=repo)
    args = handler_args(tmp_path, payload)
    args.tool = "opencode"

    def extra_fence_result(_rendered, **kwargs):
        Path(kwargs["stdout_path"]).write_bytes(invalid)
        return 0

    monkeypatch.setattr(awf_plan, "spawn_rendered", extra_fence_result)

    with pytest.raises(awf_plan.PlanLoopError, match="invalid"):
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
    assert run["architect_invocation"]["result_sha256"] == hashlib.sha256(invalid).hexdigest()


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
        before_send(repo, prepared_payload("5" * 40)[0])
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


def test_handle_start_reentry_resumes_persisted_card_without_provider_replay(
    monkeypatch, tmp_path: Path
) -> None:
    _binding, plan, payload = facts(tmp_path)
    repo = tmp_path / "repo"
    destination = repo / "docs/tasks/CARD-001.md"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(
        f"""# TaskCard

## Task ID

CARD-001

- **Task branch**: `codex/CARD-001`
- **Frozen base**: `{plan.main_sha}`

<!-- awf-reviewer-selection
{{"coder":{{"model":"","tool":"opencode"}},"reviewer":{{"model":"","tool":"opencode"}}}}
-->
""".encode()
    )
    args = handler_args(tmp_path, payload)
    store = PlanRunStore(tmp_path / "state", str(payload["run_id"]))
    store.create(payload, repo=repo)
    dispatch_payload, prepared = prepared_payload("6" * 40)
    store.update(
        status="dispatch_blocked",
        current_card={
            "task_id": "CARD-001",
            "path": "docs/tasks/CARD-001.md",
            "branch": "codex/CARD-001",
            "frozen_base": plan.main_sha,
            "status": "dispatching",
            "prepared_dispatch": prepared,
        },
        architect_invocation={"kind": "taskcard", "status": "result_persisted"},
    )
    monkeypatch.setattr(
        awf_plan,
        "_checkout_plan_main",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("must not reset workspace")),
    )
    monkeypatch.setattr(
        awf_plan,
        "_run_authoring_fast",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("must not repeat authoring Fast")),
    )
    monkeypatch.setattr(
        awf_plan,
        "persist_architect_taskcard",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("must not persist again")),
    )
    monkeypatch.setattr(awf_plan, "_run_dispatch_preflight", lambda *_a, **_k: {"status": "PASS"})
    monkeypatch.setattr(awf_plan, "_git", lambda *_a, **_k: "6" * 40)

    def dispatch(_args, *, before_send):
        before_send(repo, dispatch_payload)

    monkeypatch.setattr(awf_dispatch, "dispatch", dispatch)

    result = awf_plan.handle_start(args)

    assert result["status"] == "card_active"
    assert result["current_card"]["taskcard_commit"] == "6" * 40


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
        card="docs/tasks/CARD-001.md",
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
            "baseRefOid": "4" * 40,
            "headRefOid": "6" * 40,
            "statusCheckRollup": [{"status": "COMPLETED", "conclusion": "SUCCESS"}],
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


def test_local_merge_authority_uses_exact_authenticated_repository_permissions(
    monkeypatch, tmp_path: Path
) -> None:
    observed = []
    monkeypatch.setattr(
        awf_plan,
        "_gh_json",
        lambda *args: observed.append(args) or {"permissions": {"pull": True, "push": False}},
    )

    assert not awf_plan._local_merge_authority(tmp_path, "owner/project")
    assert observed == [(str(tmp_path), "api", "repos/owner/project")]


def test_read_only_human_merge_observation_preserves_waiting_when_pr_is_open(
    monkeypatch, tmp_path: Path
) -> None:
    store, _args, provenance, _evidence, _input_context = terminal_fixture(tmp_path)
    store.update(status="waiting_for_human_approval")
    calls = []
    monkeypatch.setattr(
        awf_plan,
        "_gh_json",
        lambda *args: (
            calls.append(args)
            or {
                "number": provenance["pull_request"],
                "state": "OPEN",
                "baseRefOid": provenance["base_sha"],
                "headRefOid": provenance["head_sha"],
                "statusCheckRollup": [{"status": "COMPLETED", "conclusion": "SUCCESS"}],
                "mergeCommit": None,
            }
        ),
    )
    monkeypatch.setattr(
        awf_plan,
        "_git",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("an unmerged PR must not reach upstream merge observation")
        ),
    )

    with pytest.raises(awf_plan.PlanOperationError, match="not yet safely observable"):
        awf_plan._observe_exact_merge(
            store=store,
            repo=tmp_path,
            provenance=provenance,
            effect_attempted=False,
            method="external",
        )

    assert store.load()["status"] == "waiting_for_human_approval"
    assert store.completions() == ()
    assert len(calls) == 1
    assert "merge" not in calls[0]


def test_human_merge_marker_requires_complete_approved_clean_external_facts() -> None:
    with pytest.raises(awf_plan.PlanOperationError, match="Human merge marker is invalid"):
        awf_plan._human_merge_requested(
            {"status": "human_merge_required", "merge_authority": "external"}
        )

    assert awf_plan._human_merge_requested(
        {
            "status": "human_merge_required",
            "review_decision": "APPROVED",
            "mergeability": "CLEAN",
            "merge_authority": "external",
        }
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
        "_approval_observation",
        lambda *_a, **_k: {
            "status": "approved",
            "review_decision": "APPROVED",
            "mergeability": "CLEAN",
        },
    )
    monkeypatch.setattr(
        awf_plan,
        "_merge_and_observe",
        lambda **_kwargs: {"state": "MERGED", "commit": "7" * 40, "method": "merge"},
    )
    monkeypatch.setattr(awf_plan, "_local_merge_authority", lambda *_a, **_k: True)

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


def test_terminal_exact_provenance_recovers_ambiguous_business_dispatch(
    monkeypatch, tmp_path: Path
) -> None:
    store, args, provenance, evidence, input_context = terminal_fixture(tmp_path)
    current = dict(store.load()["current_card"])
    store.update(
        status="dispatch_ambiguous",
        current_card={
            **current,
            "status": "dispatching",
            "prepared_dispatch": {
                "commit": "5" * 40,
                "delivery_id": "awf:" + "a" * 64,
                "payload_sha256": "sha256:" + "b" * 64,
            },
        },
        stop_reason="business dispatch failed or became ambiguous; no automatic retry",
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
        "_approval_observation",
        lambda *_a, **_k: {
            "status": "approved",
            "review_decision": "APPROVED",
            "mergeability": "CLEAN",
        },
    )
    monkeypatch.setattr(
        awf_plan,
        "_merge_and_observe",
        lambda **_kwargs: {"state": "MERGED", "commit": "7" * 40, "method": "merge"},
    )
    monkeypatch.setattr(awf_plan, "_local_merge_authority", lambda *_a, **_k: True)
    monkeypatch.setattr(awf_plan, "_git", lambda *_args, **_kwargs: "9" * 40)
    monkeypatch.setattr(awf_plan, "_git_is_ancestor", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        awf_plan,
        "terminal_delivery_chain_matches",
        lambda *_args, **_kwargs: True,
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
    recovery = store.load()["last_completion"]["card"]["dispatch_recovery"]
    assert recovery["source"] == "verified_terminal_provenance"
    assert recovery["pull_request"] == 7
    assert recovery["prepared_delivery_id"] == "awf:" + "a" * 64


def test_terminal_ambiguous_dispatch_rejects_unrelated_pr_head(monkeypatch, tmp_path: Path) -> None:
    store, args, provenance, evidence, input_context = terminal_fixture(tmp_path)
    current = dict(store.load()["current_card"])
    store.update(
        status="dispatch_ambiguous",
        current_card={
            **current,
            "status": "dispatching",
            "prepared_dispatch": {
                "commit": "5" * 40,
                "delivery_id": "awf:" + "a" * 64,
                "payload_sha256": "sha256:" + "b" * 64,
            },
        },
    )
    monkeypatch.setattr(awf_plan, "_git", lambda *_args, **_kwargs: "9" * 40)
    monkeypatch.setattr(awf_plan, "_git_is_ancestor", lambda *_args, **_kwargs: False)

    with pytest.raises(awf_plan.PlanOperationError, match="not eligible"):
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


def test_plan_terminal_waits_for_approval_without_merge(monkeypatch, tmp_path: Path) -> None:
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
        "_approval_observation",
        lambda *_a, **_k: {
            "status": "waiting",
            "review_decision": "REVIEW_REQUIRED",
            "mergeability": "BLOCKED",
        },
    )
    monkeypatch.setattr(
        awf_plan,
        "_merge_and_observe",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("merge must wait for Human approval")
        ),
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

    assert result == {"pending_state": "WAITING_FOR_HUMAN_APPROVAL"}
    assert store.load()["status"] == "waiting_for_human_approval"


def test_plan_terminal_waits_for_human_merge_without_local_upstream_authority(
    monkeypatch, tmp_path: Path
) -> None:
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
        "_approval_observation",
        lambda *_a, **_k: {
            "status": "approved",
            "review_decision": "APPROVED",
            "mergeability": "CLEAN",
        },
    )
    monkeypatch.setattr(awf_plan, "_local_merge_authority", lambda *_a, **_k: False)
    monkeypatch.setattr(
        awf_plan,
        "_merge_and_observe",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("read-only local identity must not attempt upstream merge")
        ),
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

    assert result == {"pending_state": "WAITING_FOR_HUMAN_APPROVAL"}
    waiting = store.load()
    assert waiting["status"] == "waiting_for_human_approval"
    assert waiting["current_card"]["approval"] == {
        "status": "human_merge_required",
        "review_decision": "APPROVED",
        "mergeability": "CLEAN",
        "merge_authority": "external",
    }


def test_continue_after_approval_observes_exact_human_merge_without_local_merge(
    monkeypatch, tmp_path: Path
) -> None:
    from agent_workflow.operations import awf_control_plane

    store, _args, provenance, _evidence, _input_context = terminal_fixture(tmp_path)
    run = store.load()
    current = dict(run["current_card"])
    terminal_delivery = {
        "run_id": "task-CARD-001",
        "event_id": 9,
        "delivery_id": "awf:" + "a" * 64,
        "payload_sha256": "sha256:" + "b" * 64,
        "source_event_id": 8,
        "branch": current["branch"],
        "commit": provenance["head_sha"],
        "implementation_path": ".awf/artifacts/impl-report-CARD-001.md",
        "review_path": ".awf/artifacts/review-report-CARD-001.md",
        "implementation_sha256": "sha256:" + "1" * 64,
        "review_sha256": "sha256:" + "2" * 64,
    }
    store.update(
        status="waiting_for_human_approval",
        current_card={
            **current,
            "status": "deciding",
            "pull_request": provenance["pull_request"],
            "base_sha": provenance["base_sha"],
            "head_sha": provenance["head_sha"],
            "implementation_report_sha256": terminal_delivery["implementation_sha256"],
            "review_report_sha256": terminal_delivery["review_sha256"],
            "decision": {"verdict": "approve", "sha256": "8" * 64, "bytes": 10},
            "ci": {"conclusion": "SUCCESS", "head_sha": provenance["head_sha"], "checks": 1},
            "approval": {
                "status": "human_merge_required",
                "review_decision": "APPROVED",
                "mergeability": "CLEAN",
                "merge_authority": "external",
            },
            "terminal_delivery": terminal_delivery,
        },
    )
    terminal = {}

    class Ledger:
        def __init__(self, *_args, **_kwargs):
            pass

        def recover(self):
            return {}, {"branch": current["branch"]}

        def mark_terminal(self, **kwargs):
            terminal.update(kwargs)

    monkeypatch.setattr(awf_control_plane, "RunLedger", Ledger)
    monkeypatch.setattr(
        awf_plan,
        "_observe_exact_merge",
        lambda **_kwargs: {"state": "MERGED", "commit": "7" * 40, "method": "external"},
    )
    monkeypatch.setattr(
        awf_plan,
        "_approval_observation",
        lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("already-merged Human path must not require an OPEN PR")
        ),
    )
    monkeypatch.setattr(
        awf_plan,
        "_merge_and_observe",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("read-only local identity must not attempt upstream merge")
        ),
    )

    result = awf_plan.continue_after_approval(
        repo=tmp_path / "source",
        state_root=tmp_path / "state",
        run_id=str(run["run_id"]),
        architect_profile=SimpleNamespace(),
    )

    assert result["status"] == "completed"
    assert result["last_completion"]["merge"]["commit"] == "7" * 40
    assert result["last_completion"]["merge"]["method"] == "external"
    assert terminal["terminal_state"] == "completed"


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


@pytest.mark.parametrize("tool", ["pi", "opencode", "codex"])
def test_next_architect_assembles_semantic_taskcard_for_every_provider(
    monkeypatch, tmp_path: Path, tool: str
) -> None:
    binding, _plan, store, source, completion = _completed_milestone_store(tmp_path)
    binding = replace(binding, tool=tool)
    semantic = json.dumps(
        {
            "task_id": "CARD-002",
            "objective": "Bounded next card",
            "scope": ["Implement one bounded change."],
            "change_paths": ["src/example.py"],
            "constraints": ["Preserve authority."],
            "acceptance_criteria": ["Focused test passes."],
            "verification_commands": [["python", "-m", "pytest", "-q"]],
        }
    ).encode("utf-8")
    observed: dict[str, object] = {}

    def rendered_call(rendered, **kwargs):
        observed["provider"] = rendered.executable
        provider_output = b"```json\n" + semantic + b"\n```\n" if tool == "opencode" else semantic
        Path(kwargs["stdout_path"]).write_bytes(provider_output)
        return 0

    monkeypatch.setattr(awf_plan, "spawn_rendered", rendered_call)
    outcome, raw, task_id, branch = awf_plan._invoke_next_architect(
        store=store,
        run=store.load(),
        binding=binding,
        workspace=source,
        context="context",
        last_completion=completion,
        fresh_main="9" * 40,
        coder={"tool": "opencode", "model": ""},
        reviewer={"tool": "codex", "model": ""},
    )

    assert outcome == "NEXT_TASK_CARD"
    assert (task_id, branch) == ("CARD-002", "agent/CARD-002")
    assert b"<!-- awf-reviewer-selection" in raw
    assert observed["provider"] == tool


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
        "_approval_observation",
        lambda *_a, **_k: {
            "status": "approved",
            "review_decision": "APPROVED",
            "mergeability": "CLEAN",
        },
    )
    monkeypatch.setattr(
        awf_plan,
        "_merge_and_observe",
        lambda **_kwargs: {"state": "MERGED", "commit": "7" * 40, "method": "merge"},
    )
    monkeypatch.setattr(awf_plan, "_local_merge_authority", lambda *_a, **_k: True)
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
