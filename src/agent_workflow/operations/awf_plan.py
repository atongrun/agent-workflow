#!/usr/bin/env python3
"""Narrow Agent-facing Plan start and Architect handler.

Execution after TaskCard creation is delegated to the existing production
dispatcher and role handlers.  Fast/Deep readiness is also the existing
``awf_preflight.py`` contract; this module only places those gates in the
Plan happy path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from contextlib import contextmanager
from pathlib import Path

from agent_workflow import facade
from agent_workflow.operations.awf_artifact_contract import (
    compile_implementation_report_path,
    compile_review_report_path,
)
from agent_workflow.operations.awf_config import (
    ConfigError,
    load_config,
    load_into_environment,
    native_executable,
)
from agent_workflow.operations.awf_dispatch import DispatchError
from agent_workflow.operations.awf_executor import ExecutionFailure
from agent_workflow.operations.awf_executor import run as run_command
from agent_workflow.operations.awf_network import add_url_host_to_no_proxy
from agent_workflow.operations.awf_role import _gh_json, _provider_spec, spawn_rendered
from agent_workflow.operations.awf_taskcard import reviewer_selection_contract
from agent_workflow.plan_loop import (
    PLAN_START_TYPE,
    ArchitectBinding,
    PlanFact,
    PlanLoopError,
    PlanRunStore,
    architect_binding,
    architect_context,
    compile_plan_fact,
    completed_card_fact,
    find_plan_run,
    next_architect_context,
    parse_decision,
    parse_next_output,
    plan_start_payload,
    validate_plan_start_payload,
    validate_taskcard_binding,
)
from agent_workflow.resources import authority_manifest_path
from agent_workflow.runtime.architect import persist_architect_taskcard
from agent_workflow.runtime.artifact import ArtifactError
from agent_workflow.runtime.renderers import render_provider_invocation


class PlanOperationError(RuntimeError):
    """Credential-safe failure at the Plan operations boundary."""


def _git(repo: Path, *args: str, binary: bool = False) -> str | bytes:
    try:
        result = run_command(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=not binary,
            encoding=None if binary else "utf-8",
            timeout=60,
        )
    except ExecutionFailure as exc:
        raise PlanOperationError("trusted Git operation failed") from exc
    if result.returncode:
        raise PlanOperationError("trusted Git operation failed")
    if binary:
        return result.stdout if isinstance(result.stdout, bytes) else result.stdout.encode("utf-8")
    return result.stdout.strip()


def _profile_for_machine(machine: facade.MachineContract, role: str):
    profile = next((item for item in machine.profiles if item.role == role), None)
    if profile is None:
        raise PlanOperationError(f"machine configuration has no {role} profile")
    return profile


def _send_plan_start(profile, payload: dict[str, object]) -> None:
    try:
        load_into_environment(profile.config_path)
    except ConfigError as exc:
        raise PlanOperationError("strict operations configuration is invalid") from exc
    url = os.environ.get("AGENT_BUS_URL", "")
    token = os.environ.get("AWF_ARCH_TOKEN", "")
    if not url or not token:
        raise PlanOperationError("Architect Agent Bus configuration is incomplete")
    environment = dict(os.environ)
    environment.update(
        {
            "AGENT_BUS_URL": url,
            "AGENT_BUS_TOKEN": token,
            "AGENT_BUS_AGENT": "architect",
        }
    )
    add_url_host_to_no_proxy(environment, url)
    bus = native_executable(os.environ.get("AWF_BUS_BIN", "agent-bus"))
    try:
        result = run_command(
            [
                bus,
                "send",
                "--from",
                "architect",
                "--to",
                "architect",
                "--type",
                PLAN_START_TYPE,
                "--payload",
                json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
            ],
            env=environment,
            secrets=(token,),
            allow_shell_wrapper=True,
        )
    except ExecutionFailure as exc:
        raise PlanOperationError(
            "Plan start send outcome is ambiguous; do not retry automatically"
        ) from exc
    if result.returncode:
        raise PlanOperationError("Plan start send outcome is ambiguous; do not retry automatically")


def start_plan(
    *,
    repo: Path,
    plan: Path,
    mode: str,
    coder_tool: str,
    coder_model: str,
    reviewer_tool: str,
    reviewer_model: str,
) -> dict[str, object]:
    root = repo.resolve()
    machine = facade.load_machine(root)
    binding = architect_binding(machine)
    profile = _profile_for_machine(machine, "architect")
    if profile.values.get("enable_preflight") is not True:
        raise PlanOperationError(
            "Architect profile does not register existing Preflight handlers; "
            "rerun awf init --replace"
        )
    fact, _raw = compile_plan_fact(root, plan, binding)
    payload = plan_start_payload(
        fact,
        binding,
        mode=mode,
        coder_tool=coder_tool,
        coder_model=coder_model,
        reviewer_tool=reviewer_tool,
        reviewer_model=reviewer_model,
    )
    store = PlanRunStore(profile.state_root, str(payload["run_id"]))
    store.create(payload, repo=root)
    preflight_args = argparse.Namespace(
        config=str(profile.config_path),
        state_root=str(profile.state_root),
        authority_manifest=str(authority_manifest_path()),
        upstream_remote=str(profile.values.get("upstream_remote", "upstream")),
        head_remote=str(profile.values.get("head_remote", "fork")),
        head_repo=str(profile.values.get("head_repo", "")),
        gh_bin=str(profile.values.get("gh_bin", "gh")),
        model_tool=str(profile.values.get("tool_executable", "")),
    )
    _checkout_plan_main(profile.repo, fact)
    _run_authoring_fast(preflight_args, store=store, repo=profile.repo)
    _run_dispatch_preflight(preflight_args, store=store, repo=profile.repo)
    store.update(status="start_sending")
    try:
        _send_plan_start(profile, payload)
    except BaseException:
        store.update(status="start_ambiguous", stop_reason="Plan start send was not observed")
        raise
    return store.update(status="start_sent")


def _validate_local_architect(args: argparse.Namespace, binding: ArchitectBinding) -> None:
    observed = {
        "profile": args.profile,
        "profile_sha256": args.profile_sha256,
        "workspace": str(Path(args.repo).resolve()),
        "tool": args.tool,
        "model": args.model,
    }
    expected = {
        "profile": binding.profile,
        "profile_sha256": binding.profile_sha256,
        "workspace": str(Path(binding.workspace).resolve()),
        "tool": binding.tool,
        "model": binding.model,
    }
    if observed != expected:
        raise PlanOperationError("Plan start Architect RoleBinding drifted before Pi invocation")


def _checkout_fresh_main(
    repo: Path,
    plan: PlanFact,
    *,
    expected_main: str | None = None,
) -> tuple[bytes, str]:
    if str(_git(repo, "status", "--porcelain")):
        raise PlanOperationError("Architect workspace is dirty before Plan handling")
    tracking = f"refs/remotes/{plan.upstream_remote}/{plan.base_ref}"
    _git(
        repo,
        "fetch",
        "--no-tags",
        plan.upstream_remote,
        f"+refs/heads/{plan.base_ref}:{tracking}",
    )
    live = str(_git(repo, "rev-parse", f"{tracking}^{{commit}}"))
    if expected_main is not None and live != expected_main:
        raise PlanOperationError("upstream main advanced after Plan start; start a fresh PlanRun")
    controller_branch = f"awf-plan/{hashlib.sha256(plan.identity.encode()).hexdigest()[:16]}"
    _git(repo, "checkout", "-q", "-B", controller_branch, live)
    bound_blob = str(_git(repo, "rev-parse", f"{plan.commit}:{plan.path}"))
    if bound_blob != plan.blob_oid:
        raise PlanOperationError("committed Plan blob identity drifted")
    raw = _git(repo, "cat-file", "blob", plan.blob_oid, binary=True)
    if not isinstance(raw, bytes) or hashlib.sha256(raw).hexdigest() != plan.blob_sha256:
        raise PlanOperationError("committed Plan blob bytes drifted")
    return raw, live


def _checkout_plan_main(repo: Path, plan: PlanFact) -> bytes:
    raw, _live = _checkout_fresh_main(repo, plan, expected_main=plan.main_sha)
    return raw


def _preflight_args(
    args: argparse.Namespace,
    *,
    repo: Path,
    intent: str,
) -> argparse.Namespace:
    return argparse.Namespace(
        repo=repo,
        config=Path(args.config).resolve(),
        state_root=Path(args.state_root).resolve(),
        authority_manifest=Path(args.authority_manifest).resolve(),
        source_role="architect",
        target_role="coder",
        upstream_remote=args.upstream_remote,
        head_remote=args.head_remote,
        gh_bin=args.gh_bin,
        model_tool=getattr(args, "model_tool", "") or os.environ.get("AWF_PI_BIN", "pi"),
        model_tool_policy="required",
        run_id="",
        profile="loop",
        repo_required=True,
        intent=intent,
        ttl_seconds=86400,
        timeout=60.0,
        force=False,
    )


@contextmanager
def _preflight_environment(config_path: Path):
    """Bind Fast/Deep to one deterministic non-provider network environment."""
    names = ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "NO_PROXY", "no_proxy")
    previous = {name: os.environ.get(name) for name in names}
    try:
        for name in names:
            os.environ.pop(name, None)
        config = load_config(config_path)
        for url in (config["AGENT_BUS_URL"], "https://github.com", "https://api.github.com"):
            add_url_host_to_no_proxy(os.environ, url)
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _run_authoring_fast(
    args: argparse.Namespace,
    *,
    store: PlanRunStore,
    repo: Path,
) -> dict[str, object]:
    from agent_workflow.operations import awf_preflight

    with _preflight_environment(Path(args.config).resolve()):
        report = awf_preflight.run_fast(_preflight_args(args, repo=repo, intent="taskcard")).report
    current = store.load().get("preflight")
    preflight = dict(current) if isinstance(current, dict) else {}
    preflight["authoring"] = report
    store.update(preflight=preflight)
    if report.get("status") != "PASS" or report.get("allow_taskcard_authoring") is not True:
        raise PlanOperationError("Fast Preflight denied TaskCard authoring")
    return report


def _run_dispatch_preflight(
    args: argparse.Namespace,
    *,
    store: PlanRunStore,
    repo: Path,
) -> dict[str, object]:
    from agent_workflow.operations import awf_preflight

    if store.load().get("stop_requested") is True:
        raise PlanOperationError("PlanRun stop was requested before business dispatch")
    preflight_args = _preflight_args(args, repo=repo, intent="remote-dispatch")
    with _preflight_environment(Path(args.config).resolve()):
        fast = awf_preflight.run_fast(preflight_args).report
        report = fast
        if fast.get("allow_remote_dispatch") is not True:
            if fast.get("required_next_action") != "run_deep_preflight":
                raise PlanOperationError("Fast Preflight denied remote business dispatch")
            report = awf_preflight.run_deep(preflight_args)
    current = store.load().get("preflight")
    preflight = dict(current) if isinstance(current, dict) else {}
    preflight["remote_dispatch"] = report
    store.update(preflight=preflight)
    if report.get("status") != "PASS" or report.get("allow_remote_dispatch") is not True:
        raise PlanOperationError("existing Deep Preflight did not authorize remote dispatch")
    return report


def _invoke_taskcard_architect(
    args: argparse.Namespace,
    *,
    store: PlanRunStore,
    plan: PlanFact,
    binding: ArchitectBinding,
    plan_bytes: bytes,
    repo: Path,
    coder: dict[str, object],
    reviewer: dict[str, object],
) -> tuple[bytes, str, str]:
    run = store.load()
    invocation = run.get("architect_invocation")
    if isinstance(invocation, dict):
        if invocation.get("kind") == "taskcard" and invocation.get("status") == "result_persisted":
            card = run.get("current_card")
            if isinstance(card, dict):
                return b"", str(card["task_id"]), str(card["branch"])
        raise PlanOperationError("Architect invocation is ambiguous; Pi will not be replayed")

    context = architect_context(
        plan=plan,
        plan_bytes=plan_bytes,
        architect=binding,
        coder=coder,
        reviewer=reviewer,
    )
    context_path = repo / ".awf" / f"architect-context-{run['run_id']}.md"
    context_path.parent.mkdir(parents=True, exist_ok=True)
    output = store.directory / "architect-taskcard.stdout"
    authorization = hashlib.sha256(
        (str(run["start_payload_sha256"]) + "\0taskcard").encode("utf-8")
    ).hexdigest()
    store.update(
        status="architect_taskcard_running",
        architect_invocation={
            "kind": "taskcard",
            "status": "launch_intent",
            "authorization_sha256": authorization,
        },
    )
    spec = _provider_spec(
        (f"{run['run_id']}-taskcard", str(run["run_id"]), "plan", authorization),
        role="architect",
        provider="pi",
        model=binding.model,
        executable=os.environ.get("AWF_PI_BIN", "pi"),
        workspace=str(repo),
        input_path=str(context_path),
        input_text=context,
        report_path="docs/tasks/architect-generated.md",
    )
    try:
        rc = spawn_rendered(
            render_provider_invocation(spec),
            stdout_path=str(output),
            stdout_max_bytes=64 * 1024,
        )
    except BaseException:
        store.update(
            status="architect_ambiguous",
            stop_reason="Pi Architect outcome is ambiguous; provider replay is forbidden",
        )
        raise
    finally:
        context_path.unlink(missing_ok=True)
    if rc != 0:
        store.update(
            status="architect_failed_no_replay",
            architect_invocation={
                "kind": "taskcard",
                "status": "failed_no_replay",
                "authorization_sha256": authorization,
            },
            stop_reason="Pi Architect exited non-zero; provider replay is forbidden",
        )
        raise PlanOperationError("Pi Architect TaskCard invocation failed")
    raw = output.read_bytes()
    try:
        task_id, branch = validate_taskcard_binding(
            raw,
            frozen_base=plan.main_sha,
            coder=coder,
            reviewer=reviewer,
        )
    except PlanLoopError:
        store.update(
            status="architect_output_invalid_no_replay",
            architect_invocation={
                "kind": "taskcard",
                "status": "result_invalid",
                "authorization_sha256": authorization,
                "result_sha256": hashlib.sha256(raw).hexdigest(),
            },
            stop_reason="Pi Architect TaskCard output is invalid; provider replay is forbidden",
        )
        raise
    store.update(
        architect_invocation={
            "kind": "taskcard",
            "status": "result_persisted",
            "authorization_sha256": authorization,
            "result_sha256": hashlib.sha256(raw).hexdigest(),
        }
    )
    return raw, task_id, branch


def _persist_and_dispatch_taskcard(
    args: argparse.Namespace,
    *,
    store: PlanRunStore,
    plan: PlanFact,
    repo: Path,
    coder: dict[str, object],
    reviewer: dict[str, object],
    raw: bytes,
    task_id: str,
    branch: str,
    frozen_base: str,
) -> dict[str, object]:
    destination = repo / "docs" / "tasks" / f"{task_id}.md"
    if raw:
        try:
            persist_architect_taskcard(repo=str(repo), destination=str(destination), stdout=raw)
        except ArtifactError as exc:
            store.update(
                status="architect_output_invalid_no_replay",
                stop_reason=f"trusted TaskCard persistence rejected output: {exc}",
            )
            raise PlanOperationError("trusted TaskCard persistence rejected Pi output") from exc
    elif not destination.is_file():
        raise PlanOperationError("persisted Architect TaskCard is unavailable")
    selections = reviewer_selection_contract(
        destination.read_text(encoding="utf-8"),
        fallback_tool=str(coder["tool"]),
        fallback_model=str(coder["model"]),
    )
    if (selections.coder.tool, selections.coder.model) != (coder["tool"], coder["model"]):
        raise PlanOperationError("persisted Coder selection drifted")
    if (selections.reviewer.tool, selections.reviewer.model) != (
        reviewer["tool"],
        reviewer["model"],
    ):
        raise PlanOperationError("persisted Reviewer selection drifted")
    card = {
        "task_id": task_id,
        "path": destination.relative_to(repo).as_posix(),
        "branch": branch,
        "frozen_base": frozen_base,
        "status": "dispatching",
    }
    store.update(status="card_dispatching", current_card=card)

    from agent_workflow.operations import awf_dispatch

    dispatch_args = argparse.Namespace(
        repo=repo,
        card=card["path"],
        branch=branch,
        manifest=None,
        to="coder",
        tool=str(coder["tool"]),
        model=str(coder["model"]),
        reviewer_tool=str(reviewer["tool"]),
        reviewer_model=str(reviewer["model"]),
        report=compile_implementation_report_path(task_id),
        review_report=compile_review_report_path(task_id),
        upstream_repo=plan.repository,
        upstream_remote=plan.upstream_remote,
        head_repo=args.head_repo,
        head_remote=args.head_remote,
        base_ref=plan.base_ref,
        event_type="task:awf-impl-v3",
        no_push=False,
        dry_run=False,
    )
    try:
        awf_dispatch.dispatch(
            dispatch_args,
            before_send=lambda current_repo, _payload: _run_dispatch_preflight(
                args,
                store=store,
                repo=current_repo,
            ),
        )
    except PlanOperationError as exc:
        store.update(status="dispatch_blocked", stop_reason=str(exc))
        raise
    except DispatchError:
        store.update(
            status="dispatch_ambiguous",
            stop_reason="business dispatch failed or became ambiguous; no automatic retry",
        )
        raise
    card = {**card, "status": "active", "taskcard_commit": str(_git(repo, "rev-parse", "HEAD"))}
    return store.update(status="card_active", current_card=card)


def handle_start(args: argparse.Namespace) -> dict[str, object]:
    value = {
        "run_id": args.run_id,
        "mode": args.mode,
        "plan": json.loads(args.plan_json),
        "architect": json.loads(args.architect_json),
        "coder": json.loads(args.coder_json),
        "reviewer": json.loads(args.reviewer_json),
        "awf_payload_sha256": args.payload_sha256,
        "awf_delivery_id": args.delivery_id,
    }
    parsed = validate_plan_start_payload(value)
    binding = parsed["architect_binding"]
    plan = parsed["plan_fact"]
    if not isinstance(binding, ArchitectBinding) or not isinstance(plan, PlanFact):
        raise PlanOperationError("Plan start facts are unavailable")
    _validate_local_architect(args, binding)
    repo = Path(args.repo).resolve()
    store = PlanRunStore(Path(args.state_root), str(value["run_id"]))
    store.create(value, repo=repo)
    existing = store.load()
    if existing.get("stop_requested") is True:
        raise PlanOperationError("PlanRun stop was requested; no new Architect work is legal")
    if existing.get("status") == "card_active":
        return existing
    invocation = existing.get("architect_invocation")
    if isinstance(invocation, dict):
        raise PlanOperationError("Architect invocation already started; Pi replay is forbidden")
    plan_bytes = _checkout_plan_main(repo, plan)
    _run_authoring_fast(args, store=store, repo=repo)
    coder = dict(value["coder"])
    reviewer = dict(value["reviewer"])
    raw, task_id, branch = _invoke_taskcard_architect(
        args,
        store=store,
        plan=plan,
        binding=binding,
        plan_bytes=plan_bytes,
        repo=repo,
        coder=coder,
        reviewer=reviewer,
    )
    return _persist_and_dispatch_taskcard(
        args,
        store=store,
        plan=plan,
        repo=repo,
        coder=coder,
        reviewer=reviewer,
        raw=raw,
        task_id=task_id,
        branch=branch,
        frozen_base=plan.main_sha,
    )


def _listener_plan_args(*, state_root: Path, plan: PlanFact) -> argparse.Namespace:
    values = {
        "config": os.environ.get("AWF_DISPATCH_ENV", ""),
        "authority_manifest": os.environ.get("AWF_AUTHORITY_MANIFEST", ""),
        "head_repo": os.environ.get("AWF_HEAD_REPO", ""),
    }
    if not all(values.values()):
        raise PlanOperationError("managed Architect listener is missing Plan operation bindings")
    return argparse.Namespace(
        config=values["config"],
        state_root=str(state_root.resolve()),
        authority_manifest=values["authority_manifest"],
        upstream_remote=plan.upstream_remote,
        head_remote=os.environ.get("AWF_HEAD_REMOTE", "fork"),
        head_repo=values["head_repo"],
        gh_bin=os.environ.get("AWF_GH_BIN", "gh"),
        model_tool=os.environ.get("AWF_PI_BIN", "pi"),
    )


def _validate_listener_architect(binding: ArchitectBinding, workspace: Path) -> None:
    observed = argparse.Namespace(
        profile=os.environ.get("AWF_PROFILE_PATH", ""),
        profile_sha256=os.environ.get("AWF_PROFILE_SHA256", ""),
        repo=str(workspace.resolve()),
        tool=os.environ.get("AWF_TOOL", ""),
        model=os.environ.get("AWF_MODEL", ""),
    )
    _validate_local_architect(observed, binding)


def _invoke_next_architect(
    *,
    store: PlanRunStore,
    run: dict[str, object],
    binding: ArchitectBinding,
    workspace: Path,
    context: str,
    last_completion: dict[str, object],
    fresh_main: str,
    coder: dict[str, object],
    reviewer: dict[str, object],
) -> tuple[str, bytes, str, str]:
    if run.get("current_card") is not None:
        raise PlanOperationError("next Architect invocation requires no active card")
    completed_card = last_completion.get("card")
    last_task_id = completed_card.get("task_id") if isinstance(completed_card, dict) else ""
    if not isinstance(last_task_id, str) or not last_task_id:
        raise PlanOperationError("last CompletedCardFact has no TaskCard identity")
    authorization = hashlib.sha256(
        (
            str(run["start_payload_sha256"])
            + "\0milestone-next\0"
            + str(last_completion.get("sha256", ""))
            + "\0"
            + fresh_main
        ).encode("utf-8")
    ).hexdigest()
    output = store.directory / f"architect-next-{last_task_id}.stdout"
    invocation = run.get("architect_invocation")
    if isinstance(invocation, dict) and invocation.get("kind") == "milestone-next":
        if (
            invocation.get("authorization_sha256") != authorization
            or invocation.get("status") != "result_persisted"
            or not output.is_file()
        ):
            raise PlanOperationError("next Architect invocation is ambiguous; Pi will not replay")
        raw = output.read_bytes()
    else:
        context_path = workspace / ".awf" / f"architect-next-context-{last_task_id}.md"
        context_path.parent.mkdir(parents=True, exist_ok=True)
        store.update(
            status="architect_next_running",
            architect_invocation={
                "kind": "milestone-next",
                "status": "launch_intent",
                "authorization_sha256": authorization,
                "fresh_main": fresh_main,
                "last_completion_sha256": last_completion.get("sha256", ""),
            },
        )
        spec = _provider_spec(
            (
                f"{run['run_id']}-next-{last_task_id}",
                str(run["run_id"]),
                last_task_id,
                authorization,
            ),
            role="architect",
            provider="pi",
            model=binding.model,
            executable=os.environ.get("AWF_PI_BIN", "pi"),
            workspace=str(workspace),
            input_path=str(context_path),
            input_text=context,
            report_path=f".awf/architect-next/{last_task_id}.md",
            provider_args=("milestone-next",),
        )
        try:
            rc = spawn_rendered(
                render_provider_invocation(spec),
                stdout_path=str(output),
                stdout_max_bytes=64 * 1024,
            )
        except BaseException:
            store.update(
                status="architect_ambiguous",
                stop_reason="Pi next decision outcome is ambiguous; provider replay is forbidden",
            )
            raise
        finally:
            context_path.unlink(missing_ok=True)
        if rc != 0:
            store.update(
                status="architect_failed_no_replay",
                architect_invocation={
                    "kind": "milestone-next",
                    "status": "failed_no_replay",
                    "authorization_sha256": authorization,
                    "fresh_main": fresh_main,
                    "last_completion_sha256": last_completion.get("sha256", ""),
                },
                stop_reason="Pi next decision exited non-zero; provider replay is forbidden",
            )
            raise PlanOperationError("Pi Architect next decision invocation failed")
        raw = output.read_bytes()
    try:
        outcome, body = parse_next_output(raw)
        task_id = ""
        branch = ""
        if outcome == "NEXT_TASK_CARD":
            normalized = body.encode("utf-8")
            task_id, branch = validate_taskcard_binding(
                normalized,
                frozen_base=fresh_main,
                coder=coder,
                reviewer=reviewer,
            )
            raw = normalized
    except PlanLoopError:
        store.update(
            status="architect_output_invalid_no_replay",
            architect_invocation={
                "kind": "milestone-next",
                "status": "result_invalid",
                "authorization_sha256": authorization,
                "result_sha256": hashlib.sha256(raw).hexdigest(),
                "fresh_main": fresh_main,
                "last_completion_sha256": last_completion.get("sha256", ""),
            },
            stop_reason="Pi Architect next output is invalid; provider replay is forbidden",
        )
        raise
    store.update(
        architect_invocation={
            "kind": "milestone-next",
            "status": "result_persisted",
            "authorization_sha256": authorization,
            "result_sha256": hashlib.sha256(raw).hexdigest(),
            "fresh_main": fresh_main,
            "last_completion_sha256": last_completion.get("sha256", ""),
            "outcome": outcome,
        }
    )
    return outcome, raw, task_id, branch


def _continue_milestone(
    *,
    store: PlanRunStore,
    source_repo: Path,
    state_root: Path,
) -> dict[str, object]:
    run = store.load()
    if run.get("mode") != "milestone":
        return run
    if run.get("current_card") is not None:
        raise PlanOperationError("milestone continuation requires no active card")
    if run.get("stop_requested") is True:
        return store.update(status="stopped", stop_reason="PlanRun stop was requested")
    plan = PlanFact.from_mapping(run["plan"])
    binding = ArchitectBinding.from_mapping(run["architect"])
    _validate_listener_architect(binding, source_repo)
    plan_bytes, fresh_main = _checkout_fresh_main(source_repo, plan)
    operation_args = _listener_plan_args(state_root=state_root, plan=plan)
    _run_authoring_fast(operation_args, store=store, repo=source_repo)
    completions = store.completions()
    last_completion = run.get("last_completion")
    if not completions or not isinstance(last_completion, dict):
        raise PlanOperationError("milestone continuation requires a CompletedCardFact")
    if not any(
        completion.get("sha256") == last_completion.get("sha256") for completion in completions
    ):
        raise PlanOperationError("PlanRun last completion does not match immutable facts")
    for completion in completions:
        if completion.get("plan") != run["plan"] or completion.get("architect") != run["architect"]:
            raise PlanOperationError("CompletedCardFact Plan/Architect binding drifted")
    completed_ids = tuple(str(completion["card"]["task_id"]) for completion in completions)
    coder = dict(run["coder"])
    reviewer = dict(run["reviewer"])
    outcome, raw, task_id, branch = _invoke_next_architect(
        store=store,
        run=store.load(),
        binding=binding,
        workspace=source_repo,
        context=next_architect_context(
            plan=plan,
            plan_bytes=plan_bytes,
            fresh_main=fresh_main,
            last_completion=last_completion,
            coder=coder,
            reviewer=reviewer,
            completed_task_ids=completed_ids,
        ),
        last_completion=last_completion,
        fresh_main=fresh_main,
        coder=coder,
        reviewer=reviewer,
    )
    if outcome == "MILESTONE_COMPLETE":
        return store.update(status="milestone_completed", current_card=None, stop_reason="")
    if outcome == "BLOCKED":
        _closed, reason = parse_next_output(raw)
        return store.update(status="blocked", current_card=None, stop_reason=reason)
    if task_id in completed_ids:
        store.update(
            status="architect_output_invalid_no_replay",
            stop_reason="Pi Architect repeated a completed TaskCard identity",
        )
        raise PlanOperationError("Architect repeated a completed TaskCard")
    return _persist_and_dispatch_taskcard(
        operation_args,
        store=store,
        plan=plan,
        repo=source_repo,
        coder=coder,
        reviewer=reviewer,
        raw=raw,
        task_id=task_id,
        branch=branch,
        frozen_base=fresh_main,
    )


def _terminal_context(
    *,
    run: dict[str, object],
    card: dict[str, object],
    review_report: dict[str, object],
    provenance: dict[str, object],
    artifacts: dict[str, object],
) -> str:
    facts = {
        "plan": run["plan"],
        "architect": run["architect"],
        "current_card": card,
        "review_report": review_report,
        "pull_request": {
            key: provenance[key]
            for key in (
                "upstream_repo",
                "base_ref",
                "base_sha",
                "head_repo",
                "head_ref",
                "head_sha",
                "pull_request",
            )
        },
        "artifacts": artifacts,
    }
    return (
        "# Trusted terminal ArchitectContext\n\n"
        "Return the complete Decision template with exactly one verdict. Only approve can make a "
        "Reviewer PASS eligible for the trusted merge gate; you have no merge authority.\n\n"
        "```json\n" + json.dumps(facts, ensure_ascii=False, indent=2, sort_keys=True) + "\n```\n\n"
        "# Decision\n\n## Verdict\n\n"
        "**Verdict:** [approve | request_changes | reject | escalate]\n\n"
        "## Rationale\n\n[Rationale]\n\n## Mandatory Actions\n\n- [Action]\n\n"
        "## Optional Actions\n\n- [Action]\n\n## Next Stage\n\n[next-stage-id]\n"
    )


def _invoke_terminal_decision(
    *,
    store: PlanRunStore,
    run: dict[str, object],
    binding: ArchitectBinding,
    workspace: Path,
    context: str,
    task_id: str,
) -> dict[str, object]:
    invocation = run.get("architect_invocation")
    if isinstance(invocation, dict) and invocation.get("kind") == "terminal-decision":
        if invocation.get("status") == "result_persisted":
            decision = invocation.get("decision")
            if isinstance(decision, dict):
                return dict(decision)
        raise PlanOperationError("terminal Architect invocation is ambiguous; Pi will not replay")
    authorization = hashlib.sha256(
        (str(run["start_payload_sha256"]) + "\0decision\0" + task_id).encode("utf-8")
    ).hexdigest()
    output = store.directory / f"architect-decision-{task_id}.stdout"
    input_path = workspace / ".awf" / f"architect-decision-context-{task_id}.md"
    input_path.parent.mkdir(parents=True, exist_ok=True)
    store.update(
        status="architect_decision_running",
        architect_invocation={
            "kind": "terminal-decision",
            "status": "launch_intent",
            "authorization_sha256": authorization,
        },
    )
    spec = _provider_spec(
        (f"{run['run_id']}-decision-{task_id}", str(run["run_id"]), task_id, authorization),
        role="architect",
        provider="pi",
        model=binding.model,
        executable=os.environ.get("AWF_PI_BIN", "pi"),
        workspace=str(workspace),
        input_path=str(input_path),
        input_text=context,
        report_path=f".awf/architect-decisions/{task_id}.md",
        provider_args=("terminal-decision",),
    )
    try:
        rc = spawn_rendered(
            render_provider_invocation(spec),
            stdout_path=str(output),
            stdout_max_bytes=64 * 1024,
        )
    except BaseException:
        store.update(
            status="architect_ambiguous",
            stop_reason="Pi terminal Decision outcome is ambiguous; provider replay is forbidden",
        )
        raise
    finally:
        input_path.unlink(missing_ok=True)
    if rc != 0:
        store.update(
            status="architect_failed_no_replay",
            architect_invocation={
                "kind": "terminal-decision",
                "status": "failed_no_replay",
                "authorization_sha256": authorization,
            },
            stop_reason="Pi terminal Decision exited non-zero; provider replay is forbidden",
        )
        raise PlanOperationError("Pi Architect terminal Decision invocation failed")
    decision = parse_decision(output.read_bytes())
    store.update(
        architect_invocation={
            "kind": "terminal-decision",
            "status": "result_persisted",
            "authorization_sha256": authorization,
            "decision": decision,
        }
    )
    return decision


def _check_conclusion(item: dict[str, object]) -> str:
    conclusion = str(item.get("conclusion") or item.get("state") or "").upper()
    status = str(item.get("status") or "").upper()
    if conclusion in {"FAILURE", "ERROR", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED"}:
        return "failed"
    if conclusion in {"SUCCESS", "NEUTRAL", "SKIPPED"}:
        return "passed"
    if status in {"COMPLETED"} and not conclusion:
        return "failed"
    return "pending"


def _wait_exact_ci(
    repo: Path,
    provenance: dict[str, object],
) -> dict[str, object]:
    timeout = float(os.environ.get("AWF_CI_WAIT_SECONDS", "1800"))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = _gh_json(
            str(repo),
            "pr",
            "view",
            str(provenance["pull_request"]),
            "--repo",
            str(provenance["upstream_repo"]),
            "--json",
            "number,state,baseRefOid,headRefOid,statusCheckRollup",
        )
        if not isinstance(value, dict):
            raise PlanOperationError("trusted GitHub CI observation is invalid")
        if (
            value.get("number") != provenance["pull_request"]
            or value.get("state") != "OPEN"
            or value.get("baseRefOid") != provenance["base_sha"]
            or value.get("headRefOid") != provenance["head_sha"]
        ):
            raise PlanOperationError("pull request identity drifted before CI completion")
        checks = value.get("statusCheckRollup")
        if not isinstance(checks, list) or not checks:
            raise PlanOperationError("pull request has no observable CI checks")
        states = [_check_conclusion(item) for item in checks if isinstance(item, dict)]
        if len(states) != len(checks) or "failed" in states:
            raise PlanOperationError("exact-head CI failed")
        if all(state == "passed" for state in states):
            return {
                "conclusion": "SUCCESS",
                "head_sha": provenance["head_sha"],
                "checks": len(states),
            }
        time.sleep(5)
    raise PlanOperationError("exact-head CI did not complete inside the bounded wait")


def _merge_and_observe(
    *,
    store: PlanRunStore,
    repo: Path,
    provenance: dict[str, object],
    card: dict[str, object],
) -> dict[str, object]:
    intent = {
        "status": "intent",
        "method": "merge",
        "pull_request": provenance["pull_request"],
        "head_sha": provenance["head_sha"],
    }
    store.update(status="merge_intent", current_card={**card, "merge": intent})
    gh = os.environ.get("AWF_GH_BIN", "gh")
    try:
        result = run_command(
            [
                gh,
                "pr",
                "merge",
                str(provenance["pull_request"]),
                "--repo",
                str(provenance["upstream_repo"]),
                "--merge",
                "--match-head-commit",
                str(provenance["head_sha"]),
            ],
            cwd=repo,
            timeout=120,
        )
    except ExecutionFailure as exc:
        store.update(
            status="merge_ambiguous",
            stop_reason="merge effect is ambiguous; no automatic retry",
        )
        raise PlanOperationError("merge effect is ambiguous; do not retry automatically") from exc
    if result.returncode:
        store.update(
            status="merge_ambiguous",
            stop_reason="merge effect is ambiguous; no automatic retry",
        )
        raise PlanOperationError("merge effect is ambiguous; do not retry automatically")
    observed = _gh_json(
        str(repo),
        "pr",
        "view",
        str(provenance["pull_request"]),
        "--repo",
        str(provenance["upstream_repo"]),
        "--json",
        "number,state,headRefOid,mergeCommit",
    )
    merge_commit = observed.get("mergeCommit") if isinstance(observed, dict) else None
    merge_oid = merge_commit.get("oid") if isinstance(merge_commit, dict) else ""
    if (
        not isinstance(observed, dict)
        or observed.get("number") != provenance["pull_request"]
        or observed.get("state") != "MERGED"
        or observed.get("headRefOid") != provenance["head_sha"]
        or re.fullmatch(r"[0-9a-f]{40,64}", str(merge_oid)) is None
    ):
        store.update(
            status="merge_ambiguous",
            stop_reason="merge command returned but exact merged observation is unavailable",
        )
        raise PlanOperationError("merge observation is ambiguous; do not retry automatically")
    plan = PlanFact.from_mapping(store.load()["plan"])
    tracking = f"refs/remotes/{plan.upstream_remote}/{plan.base_ref}"
    _git(
        repo,
        "fetch",
        "--no-tags",
        plan.upstream_remote,
        f"+refs/heads/{plan.base_ref}:{tracking}",
    )
    if str(_git(repo, "rev-parse", f"{tracking}^{{commit}}")) != merge_oid:
        store.update(status="merge_ambiguous", stop_reason="upstream main merge fact drifted")
        raise PlanOperationError("upstream main does not match the exact observed merge")
    return {"state": "MERGED", "commit": str(merge_oid), "method": "merge"}


def handle_card_terminal(
    *,
    args: argparse.Namespace,
    evidence: object,
    input_context: dict[str, object],
    review_report: dict[str, object],
    provenance: dict[str, object],
    terminal_repo: Path,
    implementation_sha256: str,
    review_sha256: str,
) -> dict[str, object] | None:
    state_root = Path(evidence.state_dir)
    store = find_plan_run(state_root, branch=args.branch)
    if store is None:
        return None
    run = store.load()
    if run.get("status") in {"merge_intent", "merge_ambiguous"}:
        raise PlanOperationError("merge mutation is ambiguous; no automatic terminal replay")
    card_value = run.get("current_card")
    if card_value is None and run.get("status") in {
        "completed",
        "milestone_completed",
        "blocked",
        "stopped",
    }:
        completed = run.get("last_completion")
        completed_card = completed.get("card") if isinstance(completed, dict) else None
        if isinstance(completed_card, dict) and completed_card.get("branch") == args.branch:
            merge = completed.get("merge", {})
            artifacts = {
                "implementation": {
                    "path": args.report,
                    "sha256": completed_card.get("implementation_report_sha256", ""),
                },
                "review": {
                    "path": args.review_report,
                    "sha256": completed_card.get("review_report_sha256", ""),
                },
            }
            return {
                "terminal_state": "completed",
                "terminal": {
                    "verdict": "PASS",
                    "architect_decision": completed.get("decision", {}),
                    "reason": "review_passed_architect_approved_and_merged",
                    "event_id": evidence.event_id,
                    "delivery_id": input_context["delivery_id"],
                    "payload_sha256": input_context["payload_sha256"],
                    "source_event_id": input_context["source_event_id"],
                    "branch": args.branch,
                    "commit": args.commit,
                    "artifacts": artifacts,
                    "pull_request": {
                        "number": completed_card.get("pull_request", 0),
                        "base_sha": completed_card.get("base_sha", ""),
                        "head_sha": completed_card.get("head_sha", ""),
                    },
                    "ci": {"status": "completed", "conclusion": "success"},
                    "merge": {"status": "merged", "commit": merge.get("commit", "")},
                    "completed_card_fact_sha256": completed.get("sha256", ""),
                },
            }
    if (
        isinstance(card_value, dict)
        and run.get("status") in {"blocked", "rejected"}
        and card_value.get("status") == run.get("status")
    ):
        decision = card_value.get("decision", {})
        artifacts = {
            "implementation": {
                "path": args.report,
                "sha256": card_value.get("implementation_report_sha256", ""),
            },
            "review": {
                "path": args.review_report,
                "sha256": card_value.get("review_report_sha256", ""),
            },
        }
        return {
            "terminal_state": run["status"],
            "terminal": {
                "verdict": card_value.get("reviewer_verdict", ""),
                "architect_decision": decision,
                "reason": f"architect_{decision.get('verdict', '')}",
                "event_id": evidence.event_id,
                "delivery_id": input_context["delivery_id"],
                "payload_sha256": input_context["payload_sha256"],
                "source_event_id": input_context["source_event_id"],
                "branch": args.branch,
                "commit": args.commit,
                "artifacts": artifacts,
                "pull_request": {
                    "number": card_value.get("pull_request", 0),
                    "base_sha": card_value.get("base_sha", ""),
                    "head_sha": card_value.get("head_sha", ""),
                },
                "ci": {"status": "not_recorded", "conclusion": ""},
                "merge": {"status": "not_merged", "commit": ""},
            },
        }
    if not isinstance(card_value, dict) or card_value.get("status") not in {"active", "deciding"}:
        raise PlanOperationError("PlanRun current card is not eligible for terminal Decision")
    binding = ArchitectBinding.from_mapping(run["architect"])
    card = {
        **card_value,
        "status": "deciding",
        "head_sha": provenance["head_sha"],
        "pull_request": provenance["pull_request"],
        "base_sha": provenance["base_sha"],
        "implementation_report_sha256": implementation_sha256,
        "review_report_sha256": review_sha256,
        "reviewer_verdict": review_report["verdict"],
    }
    store.update(status="architect_deciding", current_card=card)
    artifacts = {
        "implementation": {"path": args.report, "sha256": implementation_sha256},
        "review": {"path": args.review_report, "sha256": review_sha256},
    }
    decision = _invoke_terminal_decision(
        store=store,
        run=store.load(),
        binding=binding,
        workspace=terminal_repo,
        context=_terminal_context(
            run=run,
            card=card,
            review_report=review_report,
            provenance=provenance,
            artifacts=artifacts,
        ),
        task_id=str(card["task_id"]),
    )
    card = {**card, "decision": decision}
    if review_report["verdict"] != "PASS" or decision["verdict"] != "approve":
        state = "blocked" if review_report["verdict"] == "BLOCKED" else "rejected"
        store.update(
            status=state,
            current_card={**card, "status": state},
            stop_reason=f"Architect Decision={decision['verdict']}",
        )
        return {
            "terminal_state": state,
            "terminal": {
                "verdict": review_report["verdict"],
                "architect_decision": decision,
                "reason": f"architect_{decision['verdict']}",
                "event_id": evidence.event_id,
                "delivery_id": input_context["delivery_id"],
                "payload_sha256": input_context["payload_sha256"],
                "source_event_id": input_context["source_event_id"],
                "branch": args.branch,
                "commit": args.commit,
                "artifacts": artifacts,
                "pull_request": {
                    "number": provenance["pull_request"],
                    "base_sha": provenance["base_sha"],
                    "head_sha": provenance["head_sha"],
                },
                "ci": {"status": "not_recorded", "conclusion": ""},
                "merge": {"status": "not_merged", "commit": ""},
            },
        }

    source_repo = Path(os.environ["AWF_REPO_DIR"]).resolve()
    ci = _wait_exact_ci(source_repo, provenance)
    store.update(status="ci_green", current_card={**card, "ci": ci})
    merge = _merge_and_observe(
        store=store,
        repo=source_repo,
        provenance=provenance,
        card={**card, "ci": ci},
    )
    card = {**card, "status": "completed", "ci": ci, "merge": merge}
    completed = completed_card_fact(
        run=run,
        card=card,
        decision=decision,
        ci=ci,
        merge=merge,
    )
    store.persist_completion(completed)
    if run.get("mode") == "one-card":
        store.update(
            status="completed",
            current_card=None,
            last_completion=completed,
            stop_reason="",
        )
    else:
        store.update(
            status="card_completed",
            current_card=None,
            last_completion=completed,
            stop_reason="",
        )
        _continue_milestone(
            store=store,
            source_repo=source_repo,
            state_root=state_root,
        )
    return {
        "terminal_state": "completed",
        "terminal": {
            "verdict": "PASS",
            "architect_decision": decision,
            "reason": "review_passed_architect_approved_and_merged",
            "event_id": evidence.event_id,
            "delivery_id": input_context["delivery_id"],
            "payload_sha256": input_context["payload_sha256"],
            "source_event_id": input_context["source_event_id"],
            "branch": args.branch,
            "commit": args.commit,
            "artifacts": artifacts,
            "pull_request": {
                "number": provenance["pull_request"],
                "base_sha": provenance["base_sha"],
                "head_sha": provenance["head_sha"],
            },
            "ci": {"status": "completed", "conclusion": "success"},
            "merge": {"status": "merged", "commit": merge["commit"]},
            "completed_card_fact_sha256": completed["sha256"],
        },
    }


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(prog="awf-plan")
    commands = value.add_subparsers(dest="command", required=True)
    start = commands.add_parser("start")
    start.add_argument("--repo", type=Path, default=Path.cwd())
    start.add_argument("--plan", type=Path, required=True)
    start.add_argument("--mode", choices=("one-card", "milestone"), default="one-card")
    start.add_argument("--coder-tool", default="opencode")
    start.add_argument("--coder-model", default="")
    start.add_argument("--reviewer-tool", default="opencode")
    start.add_argument("--reviewer-model", default="")
    handler = commands.add_parser("handle-start")
    for name in (
        "run-id",
        "mode",
        "plan-json",
        "architect-json",
        "coder-json",
        "reviewer-json",
        "payload-sha256",
        "delivery-id",
        "repo",
        "state-root",
        "profile",
        "profile-sha256",
        "tool",
        "model",
        "config",
        "authority-manifest",
        "upstream-remote",
        "head-remote",
        "head-repo",
        "gh-bin",
    ):
        handler.add_argument(f"--{name}", required=True)
    return value


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "start":
            result = start_plan(
                repo=args.repo,
                plan=args.plan,
                mode=args.mode,
                coder_tool=args.coder_tool,
                coder_model=args.coder_model,
                reviewer_tool=args.reviewer_tool,
                reviewer_model=args.reviewer_model,
            )
        else:
            result = handle_start(args)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (
        PlanLoopError,
        PlanOperationError,
        facade.FacadeError,
        OSError,
        json.JSONDecodeError,
    ) as exc:
        print(f"awf-plan: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
