#!/usr/bin/env python3
"""Native cross-platform Agent Workflow TaskCard dispatcher."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

from awf_artifact_contract import ArtifactContractError, compile_stage_artifact_contract
from awf_config import ConfigError, default_config_path, load_into_environment, native_executable
from awf_delivery import canonical_json, canonical_payload_sha256, make_delivery_id

try:
    from agent_workflow.manifest import (
        ManifestError,
        default_manifest_path,
        load_manifest,
        resolve_manifest_card,
    )
except ModuleNotFoundError:
    from src.agent_workflow.manifest import (
        ManifestError,
        default_manifest_path,
        load_manifest,
        resolve_manifest_card,
    )

try:
    from awf_executor import CompletedProcess, ExecutionFailure
    from awf_executor import run as run_command
except ModuleNotFoundError:  # package import in tests
    from .awf_executor import CompletedProcess, ExecutionFailure
    from .awf_executor import run as run_command
from awf_network import add_url_host_to_no_proxy
from awf_taskcard import TaskCardContractError, reviewer_selection_contract

_REPO_SLUG_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,38})/[A-Za-z0-9_.-]{1,100}$")
_REMOTE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class DispatchError(RuntimeError):
    """Credential-safe dispatch failure."""


def fail(message: str) -> None:
    raise DispatchError(message)


def git(repo: Path, *args: str, quiet: bool = True) -> CompletedProcess:
    return run_command(
        ["git", "-C", str(repo), *args],
        capture_output=quiet,
        text=True,
        encoding="utf-8",
    )


def git_out(repo: Path, *args: str) -> str:
    completed = git(repo, *args)
    if completed.returncode != 0:
        fail("Git command failed")
    return completed.stdout.strip()


def require(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def validate_remote_url(url: str, expected_repo: str) -> None:
    parsed = urlsplit(url)
    expected_path = f"/{expected_repo}.git"
    require(
        parsed.scheme == "https"
        and parsed.hostname == "github.com"
        and parsed.username is None
        and parsed.password is None
        and parsed.port is None
        and not parsed.query
        and not parsed.fragment
        and parsed.path in {expected_path, expected_path.removesuffix(".git")},
        "invalid remote URL",
    )


def validate_branch(repo: Path, branch: str) -> None:
    checked = git(repo, "check-ref-format", "--branch", branch)
    require(
        checked.returncode == 0
        and not branch.startswith(("refs/", "-"))
        and not any(char.isspace() for char in branch),
        "invalid Git branch",
    )


def validate_trusted_v3(
    repo: Path,
    *,
    upstream_repo: str,
    upstream_remote: str,
    head_repo: str,
    head_remote: str,
    base_ref: str,
    head_ref: str,
) -> None:
    try:
        require(bool(_REPO_SLUG_RE.fullmatch(upstream_repo)), "invalid upstream repository")
        require(bool(_REPO_SLUG_RE.fullmatch(head_repo)), "invalid head repository")
        require(bool(_REMOTE_NAME_RE.fullmatch(upstream_remote)), "invalid upstream remote")
        require(bool(_REMOTE_NAME_RE.fullmatch(head_remote)), "invalid head remote")
        require(upstream_repo.casefold() != head_repo.casefold(), "repositories must be distinct")
        require(upstream_remote != head_remote, "remotes must be distinct")
        validate_branch(repo, base_ref)
        validate_branch(repo, head_ref)
        for remote, expected_repo in (
            (upstream_remote, upstream_repo),
            (head_remote, head_repo),
        ):
            fetch_url = git_out(repo, "remote", "get-url", remote)
            validate_remote_url(fetch_url, expected_repo)
            push_urls = git_out(repo, "remote", "get-url", "--push", "--all", remote).splitlines()
            require(push_urls == [fetch_url], "push URL differs from fetch URL")
            validate_remote_url(push_urls[0], expected_repo)
    except (DispatchError, IndexError):
        fail("invalid or untrusted GitHub remote/repository/ref configuration")


def build_payload(
    *,
    event_type: str,
    task_id: str,
    branch: str,
    card: str,
    commit: str,
    tool: str,
    model: str,
    report: str,
    review_report: str,
    provenance: dict[str, object] | None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "task_id": task_id,
        "branch": branch,
        "card": card,
        "commit": commit,
        "tool": tool,
        "model": model,
        "report": report,
        "review_report": review_report,
    }
    if provenance is not None:
        payload.update(provenance)
    payload_sha256 = canonical_payload_sha256(payload)
    return {
        **payload,
        "awf_delivery_id": make_delivery_id("architect", event_type, payload_sha256, 0),
        "awf_payload_sha256": payload_sha256,
        "awf_source_event_id": 0,
    }


def load_optional_config() -> None:
    try:
        config_path = default_config_path()
    except RuntimeError:
        return
    if not config_path.exists():
        return
    try:
        load_into_environment(config_path)
    except ConfigError as exc:
        fail(f"invalid operations configuration: {exc}")


def resolve_bus_executable(configured: str, *, platform: str | None = None) -> str:
    resolved_platform = platform or ("windows" if os.name == "nt" else "posix")
    native = native_executable(configured, platform=resolved_platform)
    resolved = shutil.which(native) or native
    if resolved_platform == "windows" and resolved.lower().endswith((".cmd", ".bat")):
        fail("AWF_BUS_BIN must resolve to a native executable on Windows")
    return resolved


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(prog="awf-dispatch")
    value.add_argument("--repo", required=True, type=Path)
    value.add_argument("--card", required=True)
    value.add_argument("--branch", default="")
    value.add_argument("--manifest", type=Path, default=None)
    value.add_argument("--to", default="coder")
    value.add_argument("--tool", default="")
    value.add_argument("--model", default="")
    value.add_argument("--reviewer-tool", default="")
    value.add_argument("--reviewer-model", default="")
    value.add_argument("--report", default="")
    value.add_argument("--review-report", default="")
    value.add_argument("--upstream-repo", default="")
    value.add_argument("--upstream-remote", default="")
    value.add_argument("--head-repo", default="")
    value.add_argument("--head-remote", default="")
    value.add_argument("--base-ref", default="")
    value.add_argument("--type", dest="event_type", default="task:awf-impl-v3")
    value.add_argument("--no-push", action="store_true")
    value.add_argument("--dry-run", action="store_true")
    return value


def dispatch(
    args: argparse.Namespace,
    *,
    before_send: Callable[[Path, dict[str, object]], None] | None = None,
) -> None:
    repo = args.repo.resolve()
    card_path = Path(args.card)
    if not card_path.is_absolute():
        card_path = repo / card_path
    if not card_path.exists():
        card_path = next(
            (
                item
                for item in (repo / ".awf" / "cards" / args.card, repo / "docs" / args.card)
                if item.is_file()
            ),
            card_path,
        )
    require(repo.is_dir(), f"repo not found: {repo}")
    require(card_path.is_file(), f"card not found: {card_path}")
    manifest = None
    manifest_path = args.manifest
    if manifest_path is None:
        candidate = default_manifest_path(repo)
        if candidate.is_file():
            manifest_path = candidate
    if manifest_path is not None:
        try:
            manifest = load_manifest(manifest_path)
        except ManifestError as exc:
            fail(f"invalid RunManifest: {exc}")
        if resolve_manifest_card(manifest, repo) != card_path.resolve():
            fail("RunManifest card does not match --card")
    elif not args.branch:
        fail("owner RunManifest is required when --branch is omitted; run awf setup first")
    if manifest is not None:
        expected = {
            "branch": str(manifest["branch"]),
            "tool": str(manifest.get("models", {}).get("tool", "")),
            "model": str(manifest.get("models", {}).get("model", "")),
            "reviewer_tool": str(manifest.get("models", {}).get("reviewer_tool", "")),
            "reviewer_model": str(manifest.get("models", {}).get("reviewer_model", "")),
            "report": str(manifest["report_paths"]["implementation"]),
            "review_report": str(manifest["report_paths"]["review"]),
        }
        for field, value in expected.items():
            supplied = getattr(args, field, "")
            if supplied and supplied != value:
                fail(f"--{field.replace('_', '-')} conflicts with owner RunManifest")
            if value:
                setattr(args, field, value)
        if args.event_type == "task:awf-impl-v3":
            args.event_type = str(manifest.get("routes", {}).get("implement", args.event_type))
        provenance_values = manifest.get("provenance", {})
        for field in ("upstream_repo", "head_repo", "upstream_remote", "head_remote", "base_ref"):
            value = str(provenance_values.get(field, ""))
            if value:
                supplied = getattr(args, field)
                if supplied and supplied != value:
                    fail(f"--{field.replace('_', '-')} conflicts with owner RunManifest")
                setattr(args, field, value)
    require(bool(args.tool), "dispatch requires an explicit --tool or owner RunManifest selection")
    try:
        selections = reviewer_selection_contract(
            card_path.read_text(encoding="utf-8"),
            fallback_tool=args.tool,
            fallback_model=args.model,
        )
    except (OSError, UnicodeError, TaskCardContractError) as exc:
        fail(f"TaskCard reviewer selection rejected before dispatch: {exc}")
    reviewer_tool_arg = getattr(args, "reviewer_tool", "")
    reviewer_model_arg = getattr(args, "reviewer_model", "")
    reviewer_tool = reviewer_tool_arg or args.tool
    reviewer_model = reviewer_model_arg or args.model
    require(
        (selections.coder.tool, selections.coder.model) == (args.tool, args.model),
        "TaskCard coder selection conflicts with owner RunManifest",
    )
    require(
        (selections.reviewer.tool, selections.reviewer.model) == (reviewer_tool, reviewer_model),
        "TaskCard reviewer selection conflicts with owner RunManifest",
    )
    args.upstream_remote = args.upstream_remote or "upstream"
    args.head_remote = args.head_remote or "fork"
    args.base_ref = args.base_ref or "main"
    is_v3 = args.event_type.endswith("-v3")
    task_id = args.branch.rsplit("/", 1)[-1]
    report = args.report or f".awf/artifacts/impl-report-{task_id}.md"
    if is_v3:
        require(bool(args.upstream_repo), "need --upstream-repo owner/repository")
        require(bool(args.head_repo), "need --head-repo owner/contribution-fork")
        require(
            not args.no_push,
            "v3 fork/PR dispatch requires a freshly verified contribution-fork push",
        )

    print(
        f"[dispatch] repo={repo} card={args.card} branch={args.branch} "
        f"to={args.to} tool={args.tool} model={args.model or '<default>'}"
    )
    require(
        git(repo, "rev-parse", "--is-inside-work-tree").returncode == 0,
        "repo is not a git work tree",
    )
    validate_branch(repo, args.branch)
    if is_v3:
        validate_trusted_v3(
            repo,
            upstream_repo=args.upstream_repo,
            upstream_remote=args.upstream_remote,
            head_repo=args.head_repo,
            head_remote=args.head_remote,
            base_ref=args.base_ref,
            head_ref=args.branch,
        )
        try:
            artifact_contract = compile_stage_artifact_contract(
                card_path=card_path,
                task_id=task_id,
                requested_report_path=args.report,
            )
        except ArtifactContractError as exc:
            fail(f"artifact contract rejected before dispatch: {exc}")
        report = artifact_contract.implementation_report_path

    if git_out(repo, "branch", "--show-current") != args.branch:
        require(
            git(repo, "checkout", "-B", args.branch).returncode == 0,
            f"cannot checkout branch {args.branch}",
        )
    require(git(repo, "add", "--", args.card).returncode == 0, "git add failed")
    staged = git(repo, "diff", "--cached", "--quiet")
    require(staged.returncode in {0, 1}, "could not inspect staged TaskCard")
    if staged.returncode == 1:
        require(
            git(repo, "commit", "-q", "-m", f"chore(awf): dispatch TaskCard {args.card}").returncode
            == 0,
            "commit failed",
        )
    commit = git_out(repo, "rev-parse", "HEAD")

    if not args.no_push:
        if is_v3:
            require(
                git(
                    repo,
                    "push",
                    "-u",
                    args.head_remote,
                    f"HEAD:refs/heads/{args.branch}",
                ).returncode
                == 0,
                "fork push failed; refusing to send an event for an unavailable TaskCard",
            )
            require(
                git(
                    repo,
                    "fetch",
                    "--no-tags",
                    args.head_remote,
                    f"+refs/heads/{args.branch}:refs/remotes/{args.head_remote}/{args.branch}",
                ).returncode
                == 0,
                "cannot freshly verify the TaskCard fork ref",
            )
        else:
            require(
                git(repo, "push", "-u", "origin", args.branch).returncode == 0,
                "push failed; refusing to send an event for a TaskCard "
                "the remote executor cannot fetch",
            )
    else:
        print("[dispatch] --no-push: LOCAL-ONLY. A remote executor cannot pull this card.")

    provenance = None
    if is_v3:
        head_sha = git_out(
            repo,
            "rev-parse",
            "--verify",
            f"refs/remotes/{args.head_remote}/{args.branch}^{{commit}}",
        )
        require(head_sha == commit, "fresh TaskCard fork SHA does not match local HEAD")
        require(
            git(
                repo,
                "fetch",
                "--no-tags",
                args.upstream_remote,
                f"+refs/heads/{args.base_ref}:refs/remotes/{args.upstream_remote}/{args.base_ref}",
            ).returncode
            == 0,
            "cannot fetch the trusted upstream base",
        )
        base_sha = git_out(
            repo,
            "rev-parse",
            "--verify",
            f"refs/remotes/{args.upstream_remote}/{args.base_ref}^{{commit}}",
        )
        provenance = {
            "provenance_version": "awf.pr-provenance.v1",
            "upstream_repo": args.upstream_repo,
            "base_ref": args.base_ref,
            "base_sha": base_sha,
            "head_repo": args.head_repo,
            "head_ref": args.branch,
            "head_sha": head_sha,
            "pull_request": 0,
        }
    print(f"[dispatch] card committed at {commit} on {args.branch}")

    review_report = args.review_report or f".awf/artifacts/review-report-{task_id}.md"
    payload = build_payload(
        event_type=args.event_type,
        task_id=task_id,
        branch=args.branch,
        card=args.card,
        commit=commit,
        tool=args.tool,
        model=args.model,
        report=report,
        review_report=review_report,
        provenance=provenance,
    )
    encoded_payload = canonical_json(payload)
    if args.dry_run:
        print("[dispatch] --dry-run: would send event")
        print(f"           type={args.event_type}  from=architect  to={args.to}")
        print(f"           payload={encoded_payload}")
        print("[dispatch] (dry-run) nothing sent.")
        return

    if before_send is not None:
        # The Plan product path injects the existing Fast/Deep gate here: after
        # the exact TaskCard ref is publishable, before the business event.
        before_send(repo, payload)

    bus_url = os.environ.get("AGENT_BUS_URL", "")
    token = os.environ.get("AWF_ARCH_TOKEN", "")
    require(bool(bus_url), "set AGENT_BUS_URL or create strict dispatch.env")
    require(bool(token), "set AWF_ARCH_TOKEN or create strict dispatch.env")
    environment = dict(os.environ)
    environment.update(
        {
            "AGENT_BUS_URL": bus_url,
            "AGENT_BUS_TOKEN": token,
            "AGENT_BUS_AGENT": "architect",
        }
    )
    add_url_host_to_no_proxy(environment, bus_url)
    configured_bus = os.environ.get("AWF_BUS_BIN", "agent-bus")
    resolved_bus = resolve_bus_executable(configured_bus)
    bus_argv = [
        resolved_bus,
        "send",
        "--from",
        "architect",
        "--to",
        args.to,
        "--type",
        args.event_type,
        "--payload",
        encoded_payload,
    ]
    try:
        sent = run_command(bus_argv, env=environment, secrets=(token,))
    except ExecutionFailure as exc:
        fail(str(exc))
    require(sent.returncode == 0, "agent-bus send failed")
    print(
        f"[dispatch] event sent (type={args.event_type} to={args.to}). "
        f"A '{args.to}' listener will pick it up and execute."
    )


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        load_optional_config()
        dispatch(args)
    except DispatchError as exc:
        print(f"awf-dispatch: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
