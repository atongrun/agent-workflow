"""Beginner-oriented composition over the existing local AWF contracts."""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

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
) -> dict[str, object]:
    route = "task:awf-review-v3" if role == "reviewer" else "task:awf-impl-v3"
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


def _selected(contract: ProjectContract, role: str = "") -> tuple[node.NodeProfile, ...]:
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
    contract = load_project(repo)
    if explain:
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
    contract = load_project(repo)
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


def status(repo: Path, *, role: str = "", explain: bool = False) -> int:
    contract = load_project(repo)
    results = [
        node.status(profile, contract.run_id, explain=explain)
        for profile in _selected(contract, role)
    ]
    return next((result for result in results if result), 0)


def stop(repo: Path, *, role: str = "") -> int:
    contract = load_project(repo)
    for profile in _selected(contract, role):
        result = node.stop(profile)
        if result:
            return result
    return 0


def drain(repo: Path, *, role: str = "") -> int:
    contract = load_project(repo)
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
