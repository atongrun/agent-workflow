"""Beginner-oriented composition over the existing local AWF contracts."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

from agent_workflow import node
from agent_workflow import status as factual_status
from agent_workflow.manifest import (
    default_compiled_report_path,
    default_manifest_path,
    load_compiled_report,
    load_manifest,
    resolve_manifest_card,
)
from agent_workflow.state_root import resolve_state_root


class FacadeError(RuntimeError):
    """A credential-safe failure at the thin usability boundary."""


MACHINE_CONFIG_FORMAT = "awf.machine-config.v1"
MACHINE_CONFIG_NAME = "machine.json"
LEGACY_MACHINE_CONFIG_NAME = ".awf/machine.json"
ROLE_ORDER = ("architect", "coder", "reviewer")
ROLE_PROVIDER_CAPABILITIES: dict[str, tuple[str, ...]] = {
    "architect": ("pi", "opencode", "codex"),
    "coder": ("opencode", "pi", "codex"),
    "reviewer": ("opencode", "pi", "codex"),
}


@dataclass(frozen=True)
class ProjectContract:
    repo: Path
    manifest_path: Path
    contract_path: Path
    manifest: dict
    contract: dict
    profiles: tuple[node.NodeProfile, ...]

    @property
    def run_id(self) -> str:
        return str(self.contract["identity"]["run_id"])

    @property
    def card(self) -> Path:
        return resolve_manifest_card(self.manifest, self.repo)


@dataclass(frozen=True)
class MachineContract:
    repo: Path
    config_path: Path
    machine: str
    project: str
    finding_enabled: bool
    profiles: tuple[node.NodeProfile, ...]

    @property
    def run_id(self) -> str:
        return ""


def default_machine_config_path(repo: Path) -> Path:
    identity = hashlib.sha256(str(Path(repo).resolve()).encode("utf-8")).hexdigest()
    config_home = node.default_config_home().expanduser().absolute()
    return config_home / "projects" / identity / MACHINE_CONFIG_NAME


def legacy_machine_config_path(repo: Path) -> Path:
    return Path(repo).resolve() / LEGACY_MACHINE_CONFIG_NAME


def _machine_binding_path_has_symlink(path: Path, scoped_root: Path) -> bool:
    cursor = path
    while cursor != scoped_root.parent:
        if cursor.is_symlink():
            return True
        if cursor == scoped_root:
            return False
        cursor = cursor.parent
    return True


def _machine_config_path_for_load(repo: Path) -> Path:
    current = default_machine_config_path(repo)
    legacy = legacy_machine_config_path(repo)
    current_exists = current.exists() or current.is_symlink()
    legacy_exists = legacy.exists() or legacy.is_symlink()
    if current_exists and legacy_exists:
        raise FacadeError(
            "platform and legacy machine configurations both exist; preserve both and resolve "
            "the binding conflict explicitly"
        )
    path = current if current_exists else legacy
    scoped_root = (
        node.default_config_home().expanduser().absolute()
        if path == current
        else Path(repo).resolve()
    )
    if _machine_binding_path_has_symlink(path, scoped_root):
        raise FacadeError("machine configuration must not be a symbolic link")
    return path


def _run_checked(argv: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            argv,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise FacadeError(f"dependency command failed: {argv[0]}") from exc
    if result.returncode:
        raise FacadeError(f"dependency command returned non-zero: {argv[0]}")
    return result


def _resolved_tool(config: Mapping[str, str], tool: str) -> str:
    key, fallback = node.TOOL_CONFIG[tool]
    configured = str(config.get(key, fallback))
    resolved = shutil.which(configured)
    if resolved:
        # Preserve an installed shim/symlink entrypoint. Dereferencing a Node
        # tool to its JavaScript target loses the interpreter-bearing PATH.
        return os.path.abspath(resolved)
    candidate = Path(configured).expanduser()
    return str(candidate.resolve()) if candidate.is_file() else ""


def discover_machine_capabilities(
    repo: Path,
    *,
    config_path: Path | None = None,
) -> dict[str, object]:
    """Read local dependency facts without creating profiles, workspaces, or runs."""
    repo = Path(repo).resolve()
    git = shutil.which("git")
    gh = shutil.which("gh")
    if not git:
        raise FacadeError("Git is unavailable; install Git before awf init")
    if not gh:
        raise FacadeError("GitHub CLI is unavailable; install and authenticate gh before awf init")
    top = _run_checked([git, "-C", str(repo), "rev-parse", "--show-toplevel"])
    if Path(top.stdout.strip()).resolve() != repo:
        raise FacadeError("awf init --repo must name the Git worktree root")
    _run_checked([git, "--version"])
    _run_checked([gh, "--version"])
    _run_checked([gh, "auth", "status", "--active", "--hostname", "github.com"])

    awf_config, _awf_listen = node._operations_modules()
    selected_config = (config_path or node.default_config_path()).expanduser().resolve()
    try:
        config = awf_config.load_config(selected_config)
    except awf_config.ConfigError as exc:
        raise FacadeError(
            "Agent Bus/provider configuration is unavailable; configure dispatch.env before init"
        ) from exc
    if not config.get("AGENT_BUS_URL"):
        raise FacadeError("Agent Bus server URL is missing from the existing credential source")
    configured_bus = awf_config.native_executable(config.get("AWF_BUS_BIN", "agent-bus"))
    bus = shutil.which(configured_bus) or (
        str(Path(configured_bus).expanduser().resolve())
        if Path(configured_bus).expanduser().is_file()
        else ""
    )
    if not bus:
        raise FacadeError("Agent Bus client is unavailable; install a compatible client")
    bus_facts = node.probe_agent_bus_client(str(bus))

    tools: dict[str, dict[str, object]] = {}
    for tool in node.TOOL_CONFIG:
        executable = _resolved_tool(config, tool)
        version_sha256 = ""
        available = bool(executable)
        if executable:
            try:
                result = _run_checked([executable, "--version"])
            except FacadeError:
                available = False
            else:
                version_sha256 = node._version_sha256(result.stdout or "", result.stderr or "")
        tools[tool] = {
            "available": available,
            "executable": executable,
            "version_sha256": version_sha256,
        }
    return {
        "repo": str(repo),
        "git": str(Path(git).resolve()),
        "github": str(Path(gh).resolve()),
        "config_path": str(selected_config),
        "configured_keys": frozenset(key for key, value in config.items() if value),
        "agent_bus": bus_facts,
        "tools": tools,
    }


def recommended_bindings(capabilities: Mapping[str, object]) -> dict[str, tuple[str, str]]:
    tools = capabilities.get("tools")
    if not isinstance(tools, Mapping):
        raise FacadeError("detected agent-tool facts are unavailable")

    def available(tool: str) -> bool:
        facts = tools.get(tool)
        return isinstance(facts, Mapping) and facts.get("available") is True

    result: dict[str, tuple[str, str]] = {}
    if available("pi"):
        result["architect"] = ("pi", "")
    if available("opencode"):
        result["coder"] = ("opencode", "")
        result["reviewer"] = ("opencode", "")
    elif available("pi"):
        result["reviewer"] = ("pi", "")
    elif available("codex"):
        result["reviewer"] = ("codex", "")
    return result


def _model_selection(value: str) -> tuple[str, dict[str, str]]:
    if value in {"", "tool-default"}:
        return "", {"mode": "tool-default", "ref": ""}
    if value != value.strip() or len(value) > 200 or re.search(r"[\s\x00-\x1f\x7f]", value):
        raise FacadeError("model reference must be one bounded tool-native token")
    return value, {"mode": "explicit", "ref": value}


def _safe_name(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9_.-]+", "-", value.strip().lower()).strip("-._")
    if not normalized:
        raise FacadeError("machine and project names must contain a letter or number")
    if not normalized[0].isalpha():
        normalized = f"p-{normalized}"
    return normalized[:48].rstrip("-._")


def profile_name(*, project: str, machine: str, role: str) -> str:
    prefix = f"{_safe_name(project)}-{_safe_name(machine)}"
    return f"{prefix[: 63 - len(role)].rstrip('-._')}-{role}"


def _profile_values(
    *,
    name: str,
    role: str,
    repo: Path,
    state_root: Path,
    tool: str,
    model: str,
    lifecycle: str,
    upstream_repo: str,
    head_repo: str,
    upstream_remote: str,
    head_remote: str,
    base_ref: str,
    tool_executable: str = "",
) -> dict[str, object]:
    route = _role_route(role)
    values: dict[str, object] = {
        "format": node.PROFILE_FORMAT,
        "name": name,
        "role": role,
        "repo": str(repo),
        "tool": tool,
        "model": model,
        "on_type": route,
        "upstream_repo": upstream_repo,
        "upstream_remote": upstream_remote,
        "head_repo": head_repo,
        "head_remote": head_remote,
        "base_ref": base_ref,
        "state_root": str(state_root),
        "lifecycle": {"mode": lifecycle},
    }
    if lifecycle == "managed":
        values["lifecycle"] = {"mode": "managed", "manager": "auto", "scope": "user"}
    if tool_executable:
        values["tool_executable"] = os.path.abspath(os.path.expanduser(tool_executable))
    return values


def _write_profile(path: Path, values: dict[str, object], *, replace: bool) -> node.NodeProfile:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not replace:
        raise FacadeError(f"generated profile already exists: {path}; pass --replace")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(values, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        node.load_profile(str(temporary))
        os.replace(temporary, path)
        return node.load_profile(str(path))
    except (OSError, node.NodeError) as exc:
        raise FacadeError(f"could not generate profile {path}: {exc}") from exc
    finally:
        temporary.unlink(missing_ok=True)


def _git_output(repo: Path, *args: str) -> str:
    return _run_checked(["git", "-C", str(repo), *args]).stdout.strip()


def _github_repo_slug(url: str) -> str:
    value = url.strip().removesuffix(".git")
    match = re.search(r"(?:github\.com[/:])([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)$", value)
    if match is None:
        raise FacadeError("trusted remotes must be GitHub repositories or be named explicitly")
    return match.group(1)


def _role_route(role: str) -> str:
    return {
        "architect": "decision:awf-ready-v3",
        "coder": "task:awf-impl-v3",
        "reviewer": "task:awf-review-v3",
    }[role]


def _role_workspace(*, project: str, machine: str, role: str) -> Path:
    name = profile_name(project=project, machine=machine, role=role)
    return node.default_config_home() / "workspaces" / name


def _workspace_matches(
    workspace: Path,
    *,
    expected_head: str,
    upstream_remote: str,
    upstream_url: str,
    head_remote: str,
    head_url: str,
) -> bool:
    try:
        return (
            Path(_git_output(workspace, "rev-parse", "--show-toplevel")).resolve()
            == workspace.resolve()
            and _git_output(workspace, "rev-parse", "HEAD") == expected_head
            and not _git_output(workspace, "status", "--porcelain")
            and _git_output(workspace, "remote", "get-url", upstream_remote) == upstream_url
            and _git_output(workspace, "remote", "get-url", head_remote) == head_url
        )
    except FacadeError:
        return False


def _stage_role_workspace(
    source: Path,
    destination: Path,
    *,
    expected_head: str,
    upstream_remote: str,
    upstream_url: str,
    head_remote: str,
    head_url: str,
) -> Path | None:
    if destination.exists():
        if _workspace_matches(
            destination,
            expected_head=expected_head,
            upstream_remote=upstream_remote,
            upstream_url=upstream_url,
            head_remote=head_remote,
            head_url=head_url,
        ):
            return None
        raise FacadeError(
            f"role workspace is not the exact clean initialized checkout: {destination}; "
            "move or remove it explicitly before retrying"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    staged = destination.with_name(f".{destination.name}.init-{uuid.uuid4().hex}")
    try:
        _run_checked(["git", "clone", "--no-hardlinks", "--quiet", str(source), str(staged)])
        _run_checked(["git", "-C", str(staged), "checkout", "--quiet", "--detach", expected_head])
        remotes = _git_output(staged, "remote").splitlines()
        for remote in remotes:
            _run_checked(["git", "-C", str(staged), "remote", "remove", remote])
        _run_checked(["git", "-C", str(staged), "remote", "add", upstream_remote, upstream_url])
        _run_checked(["git", "-C", str(staged), "remote", "add", head_remote, head_url])
        if not _workspace_matches(
            staged,
            expected_head=expected_head,
            upstream_remote=upstream_remote,
            upstream_url=upstream_url,
            head_remote=head_remote,
            head_url=head_url,
        ):
            raise FacadeError("staged role workspace did not preserve exact Git identity")
        return staged
    except Exception:
        shutil.rmtree(staged, ignore_errors=True)
        raise


def _write_machine_config(path: Path, value: dict[str, object], *, replace: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not replace:
        raise FacadeError(f"machine config already exists: {path}; pass --replace")
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError as exc:
        raise FacadeError("machine config could not be persisted") from exc
    finally:
        temporary.unlink(missing_ok=True)


def _replace_file(source: Path, destination: Path) -> None:
    os.replace(source, destination)


def _commit_machine_files(
    files: tuple[tuple[Path, Path], ...],
    validate: Callable[[], MachineContract],
) -> MachineContract:
    """Commit staged config files as one recoverable batch or restore their exact predecessors."""
    transaction = uuid.uuid4().hex
    backups: list[tuple[Path, Path]] = []
    committed: list[Path] = []
    try:
        for staged, destination in files:
            if destination.exists() or destination.is_symlink():
                backup = destination.with_name(f".{destination.name}.backup-{transaction}")
                _replace_file(destination, backup)
                backups.append((destination, backup))
            _replace_file(staged, destination)
            committed.append(destination)
        contract = validate()
    except Exception as exc:
        for destination in reversed(committed):
            destination.unlink(missing_ok=True)
        restore_error: OSError | None = None
        for destination, backup in reversed(backups):
            try:
                _replace_file(backup, destination)
            except OSError as restore_exc:
                restore_error = restore_exc
        if restore_error is not None:
            raise FacadeError(
                "machine config rollback is incomplete; preserve backup files and inspect"
            ) from restore_error
        if isinstance(exc, FacadeError):
            raise
        raise FacadeError("machine config batch commit failed and was rolled back") from exc
    for _destination, backup in backups:
        backup.unlink(missing_ok=True)
    return contract


def initialize_machine(
    *,
    repo: Path,
    machine: str,
    project: str,
    bindings: Mapping[str, tuple[str, str]],
    capabilities: Mapping[str, object],
    lifecycle: str,
    upstream_repo: str,
    head_repo: str,
    upstream_remote: str,
    head_remote: str,
    base_ref: str,
    finding_enabled: bool,
    replace: bool,
) -> tuple[MachineContract, tuple[str, ...]]:
    """Validate the full machine plan before creating exact profiles and role checkouts."""
    source = Path(repo).resolve()
    machine = _safe_name(machine)
    project = _safe_name(project)
    if upstream_remote == head_remote:
        raise FacadeError("upstream and contribution-fork remote names must be distinct")
    if set(bindings) - set(ROLE_ORDER):
        raise FacadeError("machine role selection contains an unsupported role")
    tools = capabilities.get("tools")
    configured_keys = capabilities.get("configured_keys")
    if not isinstance(tools, Mapping) or not isinstance(configured_keys, frozenset):
        raise FacadeError("dependency discovery facts are incomplete")
    selected_config = Path(str(capabilities["config_path"])).resolve()
    normalized_bindings: dict[str, tuple[str, str]] = {}
    model_selections: dict[str, dict[str, str]] = {}
    for role, selection in bindings.items():
        if (
            not isinstance(selection, tuple)
            or len(selection) != 2
            or selection[0] not in ROLE_PROVIDER_CAPABILITIES[role]
        ):
            raise FacadeError(f"{role} does not support the selected agent tool")
        facts = tools.get(selection[0])
        if not isinstance(facts, Mapping) or facts.get("available") is not True:
            raise FacadeError(f"{role} agent tool is not installed: {selection[0]}")
        token_name = node.ROLE_TOKEN[role]
        if token_name not in configured_keys:
            raise FacadeError(f"{role} requires {token_name} in the existing credential source")
        if not isinstance(selection[1], str):
            raise FacadeError(f"{role} model selection must be text")
        model, model_selection = _model_selection(selection[1])
        normalized_bindings[role] = (selection[0], model)
        model_selections[role] = model_selection
    bindings = normalized_bindings

    upstream_url = _git_output(source, "remote", "get-url", upstream_remote)
    head_url = _git_output(source, "remote", "get-url", head_remote)
    if re.search(r"https?://[^/@:]+:[^/@]+@", upstream_url + "\n" + head_url):
        raise FacadeError("trusted remote URLs must not contain embedded credentials")
    inferred_upstream = _github_repo_slug(upstream_url)
    inferred_head = _github_repo_slug(head_url)
    if upstream_repo and upstream_repo != inferred_upstream:
        raise FacadeError("configured upstream repository does not match its Git remote")
    if head_repo and head_repo != inferred_head:
        raise FacadeError("configured contribution fork does not match its Git remote")
    upstream_repo = upstream_repo or inferred_upstream
    head_repo = head_repo or inferred_head
    expected_head = _git_output(source, "rev-parse", "HEAD")
    state_root = node.default_state_root().resolve()
    profile_root = node.default_config_home() / "profiles"
    machine_path = default_machine_config_path(source)
    legacy_machine_path = legacy_machine_config_path(source)
    if _machine_binding_path_has_symlink(
        machine_path, node.default_config_home().expanduser().absolute()
    ):
        raise FacadeError("machine configuration path must not contain a symbolic link")
    destinations = {
        role: profile_root / f"{profile_name(project=project, machine=machine, role=role)}.json"
        for role in bindings
    }
    if not replace:
        existing = [
            path
            for path in (machine_path, legacy_machine_path, *destinations.values())
            if path.exists() or path.is_symlink()
        ]
        if existing:
            raise FacadeError(
                f"machine configuration already exists: {existing[0]}; pass --replace"
            )
    elif legacy_machine_path.exists() or legacy_machine_path.is_symlink():
        raise FacadeError(
            "--replace does not migrate a legacy repository-local machine config; preserve it "
            "and migrate through a separately authorized boundary"
        )
    elif machine_path.exists():
        load_machine(source)
    elif any(path.exists() for path in destinations.values()):
        raise FacadeError("--replace requires an existing exact machine config for these profiles")

    values_by_role: dict[str, dict[str, object]] = {}
    workspaces: dict[str, Path] = {}
    for role in ROLE_ORDER:
        if role not in bindings:
            continue
        tool, model = bindings[role]
        workspace = _role_workspace(project=project, machine=machine, role=role).resolve()
        workspaces[role] = workspace
        values = _profile_values(
            name=destinations[role].stem,
            role=role,
            repo=workspace,
            state_root=state_root,
            tool=tool,
            model=model,
            lifecycle=lifecycle,
            upstream_repo=upstream_repo,
            head_repo=head_repo,
            upstream_remote=upstream_remote,
            head_remote=head_remote,
            base_ref=base_ref,
            tool_executable=str(tools[tool]["executable"]),
        )
        values["config"] = str(selected_config)
        values["finding_enabled"] = finding_enabled
        # Managed Phase 5 roles use the existing no-model Fast/Deep handlers.
        # Init only provisions registration; it never runs Deep.
        values["enable_preflight"] = lifecycle == "managed"
        values_by_role[role] = values

    profile_root.mkdir(parents=True, exist_ok=True)
    staged_profile_root = Path(
        tempfile.mkdtemp(prefix="awf-init-profiles-", dir=profile_root)
    ).resolve()
    machine_path.parent.mkdir(parents=True, exist_ok=True)
    staged_machine_path = machine_path.with_name(f".{machine_path.name}.stage-{uuid.uuid4().hex}")
    try:
        staged_profiles = tuple(
            _write_profile(
                staged_profile_root / f"{role}.json",
                values_by_role[role],
                replace=True,
            )
            for role in ROLE_ORDER
            if role in values_by_role
        )
        config = {
            "format": MACHINE_CONFIG_FORMAT,
            "machine": machine,
            "project": project,
            "repo": str(source),
            "state_root": str(state_root),
            "finding_enabled": finding_enabled,
            "roles": {
                profile.role: {
                    "profile": str(destinations[profile.role].resolve()),
                    "profile_sha256": profile.digest,
                    "workspace": str(profile.repo),
                    "tool": str(profile.values["tool"]),
                    "model_selection": model_selections[profile.role],
                }
                for profile in staged_profiles
            },
        }
        _write_machine_config(staged_machine_path, config, replace=True)
    except Exception:
        shutil.rmtree(staged_profile_root, ignore_errors=True)
        staged_machine_path.unlink(missing_ok=True)
        raise

    staged_workspaces: dict[str, Path] = {}
    created_workspaces: list[Path] = []
    try:
        for role, destination in workspaces.items():
            temporary = _stage_role_workspace(
                source,
                destination,
                expected_head=expected_head,
                upstream_remote=upstream_remote,
                upstream_url=upstream_url,
                head_remote=head_remote,
                head_url=head_url,
            )
            if temporary is not None:
                staged_workspaces[role] = temporary
        for role, temporary in staged_workspaces.items():
            destination = workspaces[role]
            os.replace(temporary, destination)
            created_workspaces.append(destination)
        files = tuple(
            (staged_profile_root / f"{role}.json", destinations[role])
            for role in ROLE_ORDER
            if role in values_by_role
        ) + ((staged_machine_path, machine_path),)
        contract = _commit_machine_files(
            files,
            lambda: load_machine(source),
        )
    except Exception:
        for temporary in staged_workspaces.values():
            shutil.rmtree(temporary, ignore_errors=True)
        for destination in created_workspaces:
            shutil.rmtree(destination, ignore_errors=True)
        raise
    finally:
        shutil.rmtree(staged_profile_root, ignore_errors=True)
        staged_machine_path.unlink(missing_ok=True)

    warnings: list[str] = []
    if "coder" in bindings and "reviewer" in bindings:
        if bindings["coder"] == bindings["reviewer"] and bindings["coder"][1]:
            warnings.append(
                "Coder and Reviewer use the same agent tool and model; "
                "review independence may be weaker."
            )
        elif bindings["coder"] == bindings["reviewer"]:
            warnings.append(
                "Coder and Reviewer use the same agent tool with tool-default; "
                "the resolved models are tool-owned."
            )
        elif bindings["coder"][0] == bindings["reviewer"][0]:
            warnings.append("Coder and Reviewer use the same agent tool installation.")
    return contract, tuple(warnings)


def load_machine(repo: Path) -> MachineContract:
    repo = Path(repo).resolve()
    path = _machine_config_path_for_load(repo)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FacadeError("machine configuration is unavailable or invalid") from exc
    expected = {
        "format",
        "machine",
        "project",
        "repo",
        "state_root",
        "finding_enabled",
        "roles",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise FacadeError("machine configuration has missing or unknown fields")
    if value["format"] != MACHINE_CONFIG_FORMAT or Path(str(value["repo"])).resolve() != repo:
        raise FacadeError("machine configuration identity does not match this repository")
    if not isinstance(value["finding_enabled"], bool) or not isinstance(value["roles"], dict):
        raise FacadeError("machine configuration role or Finding state is invalid")
    if set(value["roles"]) - set(ROLE_ORDER):
        raise FacadeError("machine configuration contains an unsupported role")
    profiles: list[node.NodeProfile] = []
    workspaces: set[Path] = set()
    for role in ROLE_ORDER:
        if role not in value["roles"]:
            continue
        binding = value["roles"][role]
        if not isinstance(binding, dict) or set(binding) != {
            "profile",
            "profile_sha256",
            "workspace",
            "tool",
            "model_selection",
        }:
            raise FacadeError(f"machine {role} binding is invalid")
        reference = str(binding["profile"])
        authoring = node.load_profile(reference)
        installed = node.load_installed_profile(reference)
        profile = (
            installed
            if installed is not None and installed.digest == binding["profile_sha256"]
            else authoring
        )
        if profile.role != role:
            raise FacadeError(f"machine {role} profile identity drifted")
        model_selection = binding["model_selection"]
        if (
            not isinstance(model_selection, dict)
            or set(model_selection) != {"mode", "ref"}
            or model_selection.get("mode") not in {"tool-default", "explicit"}
            or not isinstance(model_selection.get("ref"), str)
            or (model_selection["mode"] == "tool-default" and model_selection["ref"])
            or (model_selection["mode"] == "explicit" and not model_selection["ref"])
        ):
            raise FacadeError(f"machine {role} model selection is invalid")
        expected_model, normalized_selection = _model_selection(model_selection["ref"])
        if normalized_selection != model_selection:
            raise FacadeError(f"machine {role} model selection drifted")
        if (
            profile.digest != binding["profile_sha256"]
            or profile.repo != Path(str(binding["workspace"])).resolve()
            or profile.values["tool"] != binding["tool"]
            or profile.values.get("model", "") != expected_model
        ):
            raise FacadeError(f"machine {role} profile binding drifted")
        if bool(profile.values.get("finding_enabled", False)) != value["finding_enabled"]:
            raise FacadeError(f"machine {role} Finding binding drifted")
        if profile.state_root != Path(str(value["state_root"])).resolve():
            raise FacadeError(f"machine {role} state-root binding drifted")
        if profile.repo in workspaces:
            raise FacadeError("machine roles cannot share one active workspace")
        workspaces.add(profile.repo)
        profiles.append(profile)
    return MachineContract(
        repo=repo,
        config_path=path,
        machine=str(value["machine"]),
        project=str(value["project"]),
        finding_enabled=value["finding_enabled"],
        profiles=tuple(profiles),
    )


def enroll_profiles(
    *,
    repo: Path,
    machine: str,
    project: str,
    coder_runtime: str,
    coder_model: str,
    reviewer_runtime: str,
    reviewer_model: str,
    lifecycle: str,
    upstream_repo: str,
    head_repo: str,
    upstream_remote: str,
    head_remote: str,
    base_ref: str,
    replace: bool,
) -> tuple[Path, tuple[node.NodeProfile, ...]]:
    """Generate and validate the two credential-free profiles consumed by setup."""
    repo = Path(repo).resolve()
    state_root = node.default_state_root().resolve()
    destinations = {
        role: node.default_config_home()
        / "profiles"
        / f"{profile_name(project=project, machine=machine, role=role)}.json"
        for role in ("coder", "reviewer")
    }
    existing = [path for path in destinations.values() if path.exists()]
    if existing and not replace:
        raise FacadeError(f"generated profile already exists: {existing[0]}; pass --replace")
    profiles: list[node.NodeProfile] = []
    for role, tool, model in (
        ("coder", coder_runtime, coder_model),
        ("reviewer", reviewer_runtime, reviewer_model),
    ):
        path = destinations[role]
        name = path.stem
        values = _profile_values(
            name=name,
            role=role,
            repo=repo,
            state_root=state_root,
            tool=tool,
            model=model,
            lifecycle=lifecycle,
            upstream_repo=upstream_repo,
            head_repo=head_repo,
            upstream_remote=upstream_remote,
            head_remote=head_remote,
            base_ref=base_ref,
        )
        profiles.append(_write_profile(path, values, replace=replace))
    return state_root, tuple(profiles)


def load_project(repo: Path) -> ProjectContract:
    """Discover and verify exact local artifacts without scanning other state."""
    repo = Path(repo).resolve()
    manifest_path = default_manifest_path(repo).resolve()
    contract_path = default_compiled_report_path(repo).resolve()
    manifest = load_manifest(manifest_path)
    contract = load_compiled_report(contract_path)
    identity = contract.get("identity", {})
    bindings = contract.get("bindings", {})
    if Path(str(identity.get("repo", ""))).resolve() != repo:
        raise FacadeError("compiled run contract repository does not match this project")
    manifest_binding = bindings.get("run_manifest", {})
    if Path(str(manifest_binding.get("path", ""))).resolve() != manifest_path:
        raise FacadeError("compiled run contract does not bind the default owner RunManifest")
    expected_root = resolve_state_root(str(manifest.get("state_root", "")))
    root_binding = bindings.get("state_root", {})
    if Path(str(root_binding.get("path", ""))).resolve() != expected_root:
        raise FacadeError("compiled run contract state root conflicts with the RunManifest")

    loaded: list[node.NodeProfile] = []
    profile_bindings = bindings.get("profiles", {})
    references = manifest.get("profiles", {})
    for role in ("coder", "reviewer"):
        reference = str(references.get(role, ""))
        binding = profile_bindings.get(role, {})
        bound_path = Path(str(binding.get("path", ""))).resolve()
        if not reference or bound_path != node.resolve_profile_path(reference):
            raise FacadeError(f"compiled run contract {role} profile binding drifted")
        profile = node.load_installed_profile(reference) or node.load_profile(reference)
        if profile.role != role or profile.digest != binding.get("sha256"):
            raise FacadeError(f"compiled run contract {role} profile identity drifted")
        if profile.repo != repo or profile.state_root != expected_root:
            raise FacadeError(f"compiled run contract {role} profile scope drifted")
        loaded.append(profile)
    return ProjectContract(
        repo=repo,
        manifest_path=manifest_path,
        contract_path=contract_path,
        manifest=manifest,
        contract=contract,
        profiles=tuple(loaded),
    )


def _load_profile_contract(repo: Path) -> MachineContract | ProjectContract:
    resolved = Path(repo).resolve()
    if any(
        path.exists() or path.is_symlink()
        for path in (
            default_machine_config_path(resolved),
            legacy_machine_config_path(resolved),
        )
    ):
        return load_machine(resolved)
    return load_project(resolved)


def _selected(
    contract: MachineContract | ProjectContract, role: str = ""
) -> tuple[node.NodeProfile, ...]:
    if not role:
        return contract.profiles
    profiles = tuple(profile for profile in contract.profiles if profile.role == role)
    if not profiles:
        raise FacadeError(f"compiled run contract has no {role} profile")
    return profiles


def check(
    repo: Path,
    compile_current: Callable[[ProjectContract], dict],
) -> ProjectContract:
    contract = load_project(repo)
    if compile_current(contract) != contract.contract:
        raise FacadeError("compiled run contract drifted; rerun awf init --replace")
    return contract


def doctor(
    repo: Path,
    *,
    role: str = "",
    ttl_seconds: int = 3600,
    explain: bool = False,
) -> int:
    contract = _load_profile_contract(repo)
    if explain:
        if isinstance(contract, MachineContract):
            print(
                f"project={contract.repo} machine={contract.machine} source={contract.config_path}"
            )
        else:
            print(f"project={contract.repo} run={contract.run_id} source={contract.manifest_path}")
    results = [
        node.doctor(profile, ttl_seconds=ttl_seconds) for profile in _selected(contract, role)
    ]
    return next((result for result in results if result), 0)


def start(
    repo: Path,
    *,
    role: str = "",
    allow_session_bound: bool = False,
) -> int:
    contract = _load_profile_contract(repo)
    plans: list[tuple[str, node.NodeProfile]] = []
    for profile in _selected(contract, role):
        facts = node.lifecycle_facts(profile)
        if profile.lifecycle_mode == "session":
            plans.append(("start", profile))
        elif (
            facts.get("installed") is True
            and facts.get("installation", {}).get("status") == "current"
        ):
            plans.append(("start", profile))
        elif (
            facts.get("installed") is False
            and facts.get("installation", {}).get("status") == "not_installed"
        ):
            plans.append(("install_start", profile))
        else:
            status = facts.get("installation", {}).get("status", "unknown")
            raise FacadeError(
                f"start denied for profile={profile.name}: installation evidence is {status}"
            )

    for action, profile in plans:
        selected = profile
        if action == "install_start":
            result = node.install(profile)
            if result:
                return result
            installed = node.load_installed_profile(str(profile.authoring_path))
            if installed is None:
                raise FacadeError(
                    f"installed profile identity is unavailable after install: {profile.name}"
                )
            selected = installed
        result = node.start(selected, allow_session_bound=allow_session_bound)
        if result:
            return result
    return 0


def activate_machine(
    contract: MachineContract,
    *,
    readiness_timeout_seconds: float = 30.0,
) -> tuple[dict[str, object], ...]:
    """Install/start every selected local managed role and prove exact readiness.

    Valid configuration is preserved on failure. Only listeners observed as not
    running before this call are eligible for bounded exact rollback.
    """
    if readiness_timeout_seconds <= 0:
        raise FacadeError("machine readiness timeout must be positive")
    if any(profile.lifecycle_mode != "managed" for profile in contract.profiles):
        raise FacadeError("normal awf init requires managed lifecycle for every selected role")
    if any(profile.values.get("enable_preflight") is not True for profile in contract.profiles):
        raise FacadeError("managed role profile does not register existing Preflight handlers")

    selected: list[tuple[node.NodeProfile, bool]] = []
    newly_started: list[node.NodeProfile] = []
    ready: list[dict[str, object]] = []
    try:
        for profile in contract.profiles:
            facts = node.lifecycle_facts(profile)
            was_running = facts.get("running") is True
            active = profile
            if (
                facts.get("installed") is False
                and facts.get("installation", {}).get("status") == "not_installed"
            ):
                if node.install(profile):
                    raise FacadeError(f"listener install failed for role={profile.role}")
                active = node.load_installed_profile(str(profile.authoring_path)) or profile
            elif facts.get("installation", {}).get("status") == "stale":
                installed = node.load_installed_profile(str(profile.authoring_path))
                if installed is None:
                    raise FacadeError(
                        f"stale listener installation has no exact snapshot for role={profile.role}"
                    )
                if node.upgrade(installed, replacement=profile):
                    raise FacadeError(f"listener reconcile failed for role={profile.role}")
                active = node.load_installed_profile(str(profile.authoring_path)) or profile
                was_running = True
                newly_started.append(active)
            elif facts.get("installed") is not True:
                status = facts.get("installation", {}).get("status", "unknown")
                raise FacadeError(
                    f"listener install evidence is {status} for role={profile.role}; "
                    "run awf node status and repair that exact profile"
                )
            else:
                active = node.load_installed_profile(str(profile.authoring_path)) or profile
            selected.append((active, was_running))

        for active, was_running in selected:
            if not was_running:
                if node.start(active):
                    raise FacadeError(f"listener start failed for role={active.role}")
                newly_started.append(active)

            deadline = time.monotonic() + readiness_timeout_seconds
            last_error: Exception | None = None
            while time.monotonic() < deadline:
                try:
                    if node.doctor(active, ttl_seconds=3600):
                        raise node.NodeError("node doctor returned non-zero")
                    readiness = node._local_readiness(active)
                    report = node.doctor_report(
                        active,
                        readiness,
                        ttl_seconds=3600,
                        observed_at=node._now(),
                    )
                    if (
                        report.get("configured") is True
                        and report.get("installed") is True
                        and report.get("running") is True
                        and report.get("connected") is True
                        and report.get("listener", {}).get("lease_bound") is True
                    ):
                        ready.append(report)
                        break
                    last_error = node.NodeError("exact listener readiness is incomplete")
                except node.TransientBusReadinessError as exc:
                    last_error = exc
                time.sleep(0.25)
            else:
                detail = str(last_error or "exact listener readiness is incomplete")
                raise FacadeError(
                    f"listener not Ready for role={active.role}: {detail}; "
                    "run awf doctor --role for the exact remediation"
                )
    except Exception as exc:
        rollback_failures: list[str] = []
        for active in reversed(newly_started):
            try:
                node.stop(active)
            except (node.NodeError, OSError):
                rollback_failures.append(active.role)
        suffix = (
            "; exact rollback needs inspection for roles=" + ",".join(rollback_failures)
            if rollback_failures
            else ""
        )
        if isinstance(exc, FacadeError):
            raise FacadeError(str(exc) + suffix) from exc
        raise FacadeError(
            f"machine listener activation failed: {exc}; configuration was preserved" + suffix
        ) from exc
    return tuple(ready)


def status(repo: Path, *, role: str = "", explain: bool = False) -> int:
    contract = _load_profile_contract(repo)
    if isinstance(contract, MachineContract) and contract.profiles:
        from agent_workflow.plan_loop import find_plan_run, plan_status_lines

        plan_run = find_plan_run(
            contract.profiles[0].state_root,
            repo=contract.repo,
        )
        if plan_run is not None:
            for line in plan_status_lines(plan_run.load()):
                print(line)
    results = [
        node.status(profile, contract.run_id, explain=explain)
        for profile in _selected(contract, role)
    ]
    return next((result for result in results if result), 0)


def _exact_plan_run(contract: MachineContract, run_id: str):
    from agent_workflow.plan_loop import PlanLoopError, PlanRunStore

    if not contract.profiles:
        raise FacadeError("exact PlanRun action requires a local role profile")
    try:
        store = PlanRunStore(contract.profiles[0].state_root, run_id)
        run = store.load()
    except PlanLoopError as exc:
        raise FacadeError("exact PlanRun is unavailable or invalid") from exc
    if Path(str(run.get("repo", ""))).resolve() != contract.repo:
        raise FacadeError("exact PlanRun does not belong to this repository")
    return store, run


def _deny_active_other_plan_runs(contract: MachineContract, run_id: str) -> None:
    from agent_workflow.plan_loop import PlanLoopError, PlanRunStore

    if not contract.profiles:
        raise FacadeError("exact PlanRun action requires a local role profile")
    terminal = {
        "completed",
        "milestone_completed",
        "blocked",
        "rejected",
        "stopped",
        "architect_failed_no_replay",
        "architect_output_invalid_no_replay",
        "architect_ambiguous",
        "start_ambiguous",
        "dispatch_ambiguous",
        "merge_ambiguous",
    }
    root = contract.profiles[0].state_root / "plan-runs"
    for path in root.glob("*/run.json"):
        if path.parent.name == run_id:
            continue
        try:
            candidate = PlanRunStore(contract.profiles[0].state_root, path.parent.name).load()
        except PlanLoopError as exc:
            raise FacadeError("another PlanRun is unreadable; deinit is denied") from exc
        if Path(str(candidate.get("repo", ""))).resolve() != contract.repo:
            continue
        if candidate.get("status") not in terminal:
            raise FacadeError("another PlanRun remains active; deinit is denied")


def stop(repo: Path, *, role: str = "", run_id: str = "") -> int:
    contract = _load_profile_contract(repo)
    profiles = _selected(contract, role)
    if isinstance(contract, MachineContract) and not role and contract.profiles:
        from agent_workflow.plan_loop import find_plan_run

        plan_run = None
        if run_id:
            plan_run, _run = _exact_plan_run(contract, run_id)
        else:
            plan_run = find_plan_run(contract.profiles[0].state_root, repo=contract.repo)
        if plan_run is not None:
            run = plan_run.update(
                stop_requested=True,
                stop_reason="operator requested no new work and exact local stop",
            )
            if run.get("status") == "merge_intent":
                raise FacadeError(
                    f"stop denied: PlanRun authority is active at {run['status']}; inspect status"
                )
    observations = [(profile, factual_status._queue(profile)) for profile in profiles]
    for profile, queue in observations:
        pending = queue.get("pending")
        if queue.get("status") != "observed" or not isinstance(pending, int):
            raise FacadeError(
                f"stop denied for profile={profile.name}: queue is not safely observed"
            )
        if pending != 0:
            raise FacadeError(
                f"stop denied for profile={profile.name}: pending deliveries={pending}"
            )
    for profile, _queue in observations:
        result = node.stop(profile)
        if result:
            return result
    return 0


def deinit(repo: Path, *, run_id: str = "") -> int:
    """Remove one exact platform-local machine binding without touching Workflow evidence."""
    repo = Path(repo).resolve()
    contract = load_machine(repo)
    if run_id:
        store, run = _exact_plan_run(contract, run_id)
        if run.get("status") != "milestone_completed" or run.get("current_card") is not None:
            raise FacadeError("deinit requires the exact completed PlanRun")
        completion = run.get("last_completion")
        if (
            not isinstance(completion, dict)
            or not isinstance(completion.get("sha256"), str)
            or not any(item.get("sha256") == completion["sha256"] for item in store.completions())
        ):
            raise FacadeError(
                "deinit requires an immutable CompletedCardFact for the exact PlanRun"
            )
        _deny_active_other_plan_runs(contract, run_id)
    if contract.config_path != default_machine_config_path(repo):
        raise FacadeError("deinit refuses legacy repository-local machine configuration")
    expected_profiles: list[tuple[node.NodeProfile, Path, Path, str]] = []
    for profile in contract.profiles:
        profile_filename = (
            profile_name(project=contract.project, machine=contract.machine, role=profile.role)
            + ".json"
        )
        expected_profile = node.default_config_home() / "profiles" / profile_filename
        expected_workspace = _role_workspace(
            project=contract.project, machine=contract.machine, role=profile.role
        ).resolve()
        if (
            profile.authoring_path != expected_profile.resolve()
            or profile.repo != expected_workspace
        ):
            raise FacadeError(f"deinit refused: {profile.role} binding is not AWF-generated")
        if profile.source_aliases and set(profile.source_aliases) != {expected_profile.resolve()}:
            raise FacadeError(f"deinit refused: {profile.role} has noncanonical profile aliases")
        facts = node.lifecycle_facts(profile)
        if facts.get("running") is not False:
            raise FacadeError(f"deinit refused: {profile.role} listener is active or unknown")
        installation_status = str(facts.get("installation", {}).get("status", ""))
        if installation_status not in {"current", "not_installed"}:
            raise FacadeError(f"deinit refused: {profile.role} installation identity is unknown")
        if not expected_workspace.is_dir() or _git_output(
            expected_workspace, "status", "--porcelain"
        ):
            raise FacadeError(f"deinit refused: {profile.role} workspace is missing or dirty")
        expected_profiles.append(
            (profile, expected_profile, expected_workspace, installation_status)
        )
    for profile, _source, _workspace, installation_status in expected_profiles:
        if installation_status == "not_installed":
            continue
        if node.uninstall(profile):
            raise FacadeError(f"deinit incomplete: uninstall failed for {profile.role}")
        if node.lifecycle_facts(profile).get("installation", {}).get("status") != "not_installed":
            raise FacadeError(f"deinit incomplete: installation remains for {profile.role}")
    for _profile, source, workspace, _installation_status in expected_profiles:
        source.unlink(missing_ok=True)
        shutil.rmtree(workspace)
    contract.config_path.unlink(missing_ok=True)
    return 0


def drain(repo: Path, *, role: str = "") -> int:
    contract = _load_profile_contract(repo)
    profiles = _selected(contract, role)
    observations: list[tuple[node.NodeProfile, dict[str, object]]] = [
        (profile, factual_status._queue(profile)) for profile in profiles
    ]
    for profile, queue in observations:
        pending = queue.get("pending")
        if queue.get("status") != "observed" or not isinstance(pending, int):
            raise FacadeError(f"drain denied for profile={profile.name}: queue is not observed")
        if pending != 0:
            raise FacadeError(
                f"drain denied for profile={profile.name}: pending deliveries={pending}"
            )
    for profile, _queue in observations:
        result = node.stop(profile)
        if result:
            return result
    return 0


def logs(repo: Path, *, role: str = "", lines: int = 100) -> int:
    contract = _load_profile_contract(repo)
    for profile in _selected(contract, role):
        result = node.logs(profile, lines)
        if result:
            return result
    return 0
