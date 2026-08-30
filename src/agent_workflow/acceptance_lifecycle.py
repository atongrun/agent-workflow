"""Exact, credential-free lifecycle closeout for disposable acceptance runs."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import uuid
from pathlib import Path
from typing import Iterable

from agent_workflow import node

MANIFEST_FORMAT = "awf.acceptance-lifecycle.v1"
CLOSEOUT_FORMAT = "awf.acceptance-lifecycle-closeout.v1"
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_RETAINED_REVIEW_REPORT_RE = re.compile(
    r"^\?\?\s+(\.awf/artifacts/review-report-[A-Za-z0-9._-]+\.md)$"
)
_RETAINED_TASKCARD_RE = re.compile(r"^\?\?\s+(docs/tasks/([A-Za-z0-9._-]+)\.md)$")
_MAX_RETAINED_REVIEW_REPORT_BYTES = 64 * 1024
_MAX_RETAINED_TASKCARD_BYTES = 64 * 1024
_ENTRY_FIELDS = {
    "profile",
    "profile_sha256",
    "installed_profile",
    "workspace",
    "manager",
    "manager_id",
}


class AcceptanceLifecycleError(RuntimeError):
    """Fail-closed disposable lifecycle closeout error."""


def _write_json(path: Path, value: dict[str, object], *, replace: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    staged = path.with_name(f".{path.name}.{uuid.uuid4().hex}.stage")
    try:
        with staged.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(value, indent=2, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        if not replace and path.exists():
            raise AcceptanceLifecycleError("acceptance lifecycle evidence already exists")
        if replace:
            os.replace(staged, path)
        else:
            os.link(staged, path)
            staged.unlink()
    finally:
        staged.unlink(missing_ok=True)


def _load(path: Path) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise AcceptanceLifecycleError("acceptance lifecycle manifest is unavailable")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AcceptanceLifecycleError("acceptance lifecycle manifest is invalid") from exc
    if not isinstance(value, dict):
        raise AcceptanceLifecycleError("acceptance lifecycle manifest is invalid")
    return value


def _has_symlink(path: Path) -> bool:
    candidate = path.expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    return any(current.is_symlink() for current in (candidate, *candidate.parents))


def _canonical_path(value: object, *, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise AcceptanceLifecycleError(f"CLEANUP_BLOCKED: {label} identity is invalid")
    path = Path(value).expanduser()
    if not path.is_absolute() or _has_symlink(path):
        raise AcceptanceLifecycleError(f"CLEANUP_BLOCKED: {label} identity is noncanonical")
    canonical = path.resolve()
    if str(path) != str(canonical):
        raise AcceptanceLifecycleError(f"CLEANUP_BLOCKED: {label} identity is noncanonical")
    return canonical


def _installation(profile: node.NodeProfile) -> dict[str, object]:
    installation = node.lifecycle_facts(profile).get("installation")
    if not isinstance(installation, dict):
        raise AcceptanceLifecycleError("CLEANUP_BLOCKED: native installation identity is unknown")
    return installation


def _active_profile(profile: node.NodeProfile) -> node.NodeProfile:
    return node.load_installed_profile(str(profile.authoring_path)) or profile


def create_manifest(
    path: Path, *, run_id: str, profiles: Iterable[node.NodeProfile], workspaces: Iterable[Path]
) -> dict[str, object]:
    """Persist exact disposable identities before acceptance lifecycle mutation."""
    if not _RUN_ID_RE.fullmatch(run_id):
        raise AcceptanceLifecycleError("acceptance run identity is invalid")
    expected_workspaces = set()
    for workspace in workspaces:
        raw = Path(workspace).expanduser()
        if _has_symlink(raw):
            raise AcceptanceLifecycleError("acceptance workspace identity is not exact")
        expected_workspaces.add(raw.resolve())
    entries = []
    for original in profiles:
        raw_source = original.authoring_path
        raw_workspace = Path(str(original.values.get("repo", ""))).expanduser()
        if original.source_was_symlink or _has_symlink(raw_source) or _has_symlink(raw_workspace):
            raise AcceptanceLifecycleError("acceptance profile identity is not exact")
        source, workspace = raw_source.resolve(), raw_workspace.resolve()
        if not source.is_file() or workspace not in expected_workspaces:
            raise AcceptanceLifecycleError("acceptance profile identity is not exact")
        profile = _active_profile(original)
        if profile.digest != original.digest or profile.repo != workspace:
            raise AcceptanceLifecycleError("acceptance profile identity is not exact")
        installation = _installation(profile)
        manager, manager_id = installation.get("manager"), installation.get("manager_id")
        if not isinstance(manager, str) or not isinstance(manager_id, str) or not manager_id:
            raise AcceptanceLifecycleError("acceptance native lifecycle identity is unknown")
        entries.append(
            {
                "profile": str(source),
                "profile_sha256": original.digest,
                "installed_profile": str(node._snapshot_path(original)),
                "workspace": str(workspace),
                "manager": manager,
                "manager_id": manager_id,
            }
        )
    if not entries or len({entry["profile"] for entry in entries}) != len(entries):
        raise AcceptanceLifecycleError("acceptance profiles are missing or duplicated")
    value: dict[str, object] = {
        "format": MANIFEST_FORMAT,
        "run_id": run_id,
        "profiles": sorted(entries, key=lambda entry: str(entry["profile"])),
        "workspaces": sorted(str(workspace) for workspace in expected_workspaces),
    }
    _write_json(Path(path), value, replace=False)
    return value


def _validated_entries(value: dict[str, object]) -> tuple[list[dict[str, object]], list[str]]:
    if (
        set(value) != {"format", "run_id", "profiles", "workspaces"}
        or value.get("format") != MANIFEST_FORMAT
        or not isinstance(value.get("run_id"), str)
        or not _RUN_ID_RE.fullmatch(value["run_id"])
    ):
        raise AcceptanceLifecycleError("CLEANUP_BLOCKED: acceptance lifecycle manifest is invalid")
    profiles, workspaces = value.get("profiles"), value.get("workspaces")
    if not isinstance(profiles, list) or not profiles or not isinstance(workspaces, list):
        raise AcceptanceLifecycleError("CLEANUP_BLOCKED: acceptance lifecycle manifest is invalid")
    entries = []
    for entry in profiles:
        if not isinstance(entry, dict) or set(entry) != _ENTRY_FIELDS:
            raise AcceptanceLifecycleError(
                "CLEANUP_BLOCKED: acceptance lifecycle profile entry is invalid"
            )
        profile = _canonical_path(entry["profile"], label="profile")
        installed = entry["installed_profile"]
        if installed:
            _canonical_path(installed, label="installed profile")
        workspace = _canonical_path(entry["workspace"], label="workspace")
        if (
            not isinstance(entry["profile_sha256"], str)
            or not isinstance(entry["manager"], str)
            or not isinstance(entry["manager_id"], str)
            or not entry["manager_id"]
        ):
            raise AcceptanceLifecycleError(
                "CLEANUP_BLOCKED: acceptance lifecycle profile entry is invalid"
            )
        entries.append({**entry, "profile": str(profile), "workspace": str(workspace)})
    if len({entry["profile"] for entry in entries}) != len(entries):
        raise AcceptanceLifecycleError("CLEANUP_BLOCKED: acceptance profiles are duplicated")
    normalized_workspaces = [
        _canonical_path(workspace, label="workspace") for workspace in workspaces
    ]
    if len(set(normalized_workspaces)) != len(normalized_workspaces) or {
        str(workspace) for workspace in normalized_workspaces
    } != {entry["workspace"] for entry in entries}:
        raise AcceptanceLifecycleError("CLEANUP_BLOCKED: workspace identities drifted")
    return entries, [str(workspace) for workspace in normalized_workspaces]


def _partial_workspace_removal(status: str) -> bool:
    lines = [line.strip() for line in status.splitlines() if line.strip()]
    return bool(lines) and all(re.fullmatch(r"D\s+.+", line) is not None for line in lines)


def _explicit_frozen_recovery_status(status: str) -> bool:
    lines = [line.strip() for line in status.splitlines() if line.strip()]
    if not lines:
        return False
    for line in lines:
        if re.fullmatch(r"D\s+.+", line) is not None:
            continue
        untracked = re.fullmatch(r"\?\?\s+(.+)", line)
        if untracked is None:
            return False
        path = untracked.group(1)
        if not (
            path.endswith("/__pycache__/")
            or re.fullmatch(r"(?:^|.*/)__pycache__/[^/]+\.pyc", path) is not None
        ):
            return False
    return True


def _mirrored_retained_review_status(workspace: Path, status: str, state_root: Path) -> bool:
    """Accept only run-owned ReviewReports already retained byte-for-byte in event evidence."""
    lines = [line.strip() for line in status.splitlines() if line.strip()]
    if not lines:
        return False
    for line in lines:
        match = _RETAINED_REVIEW_REPORT_RE.fullmatch(line)
        if match is None:
            return False
        relative = match.group(1)
        source = workspace / relative
        if source.is_symlink() or not source.is_file():
            return False
        try:
            source_size = source.stat().st_size
            if source_size > _MAX_RETAINED_REVIEW_REPORT_BYTES:
                return False
            content = source.read_bytes()
        except OSError:
            return False
        if len(content) != source_size:
            return False
        digest = hashlib.sha256(content).digest()
        mirrored = False
        for event_dir in state_root.iterdir():
            if (
                not re.fullmatch(r"event-[1-9][0-9]*", event_dir.name)
                or event_dir.is_symlink()
                or not event_dir.is_dir()
            ):
                continue
            for candidate in event_dir.rglob(source.name):
                if candidate.is_symlink() or not candidate.is_file():
                    continue
                candidate_relative = candidate.relative_to(event_dir).as_posix()
                if not candidate_relative.endswith(f"/.awf/artifacts/{source.name}"):
                    continue
                try:
                    candidate_size = candidate.stat().st_size
                    if candidate_size != len(content):
                        continue
                    candidate_content = candidate.read_bytes()
                except OSError:
                    continue
                if (
                    len(candidate_content) == len(content)
                    and hashlib.sha256(candidate_content).digest() == digest
                ):
                    mirrored = True
                    break
            if mirrored:
                break
        if not mirrored:
            return False
    return True


def _bound_plan_run_dir(
    state_root: Path, workspace: Path, relative: str, task_id: str
) -> Path | None:
    from agent_workflow.plan_loop import PlanLoopError, PlanRunStore

    matches: list[Path] = []
    plan_runs = state_root / "plan-runs"
    if not plan_runs.is_dir() or plan_runs.is_symlink():
        return None
    for candidate in plan_runs.iterdir():
        if (
            candidate.is_symlink()
            or not candidate.is_dir()
            or not candidate.name.startswith("plan-")
        ):
            continue
        try:
            run = PlanRunStore(state_root, candidate.name).load()
            run_repo = _canonical_path(run.get("repo"), label="PlanRun repository")
        except (AcceptanceLifecycleError, PlanLoopError):
            continue
        card = run.get("current_card")
        if (
            run_repo != workspace.resolve()
            or run.get("status") not in {"dispatch_ambiguous", "dispatch_blocked"}
            or not isinstance(card, dict)
            or card.get("status") != "dispatching"
            or card.get("path") != relative
            or card.get("task_id") != task_id
        ):
            continue
        matches.append(candidate)
    return matches[0] if len(matches) == 1 else None


def _freeze_retained_taskcards(workspace: Path, status: str, state_root: Path) -> bool:
    lines = [line.strip() for line in status.splitlines() if line.strip()]
    if not lines:
        return False
    prepared: list[tuple[Path, bytes]] = []
    for line in lines:
        match = _RETAINED_TASKCARD_RE.fullmatch(line)
        if match is None:
            return False
        relative, task_id = match.groups()
        source = workspace / relative
        if source.is_symlink() or not source.is_file():
            return False
        try:
            content = source.read_bytes()
        except OSError:
            return False
        if len(content) > _MAX_RETAINED_TASKCARD_BYTES:
            return False
        plan_dir = _bound_plan_run_dir(state_root, workspace, relative, task_id)
        if plan_dir is None:
            return False
        prepared.append((plan_dir / "retained-taskcards" / source.name, content))
    for destination, content in prepared:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            if destination.is_symlink() or destination.read_bytes() != content:
                return False
            continue
        try:
            with destination.open("xb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
        except OSError:
            return False
    return True


def _mirrored_retained_taskcard_status(workspace: Path, status: str, state_root: Path) -> bool:
    lines = [line.strip() for line in status.splitlines() if line.strip()]
    if not lines:
        return False
    for line in lines:
        match = _RETAINED_TASKCARD_RE.fullmatch(line)
        if match is None:
            return False
        relative, task_id = match.groups()
        source = workspace / relative
        plan_dir = _bound_plan_run_dir(state_root, workspace, relative, task_id)
        if plan_dir is None or source.is_symlink() or not source.is_file():
            return False
        mirror = plan_dir / "retained-taskcards" / source.name
        try:
            content = source.read_bytes()
            if (
                len(content) > _MAX_RETAINED_TASKCARD_BYTES
                or mirror.is_symlink()
                or not mirror.is_file()
                or mirror.read_bytes() != content
            ):
                return False
        except OSError:
            return False
    return True


def _remove_workspace(path: Path, *, windows: bool | None = None) -> None:
    """Remove one exact workspace, retrying Windows read-only Git files only."""
    root = path.resolve()
    use_windows_retry = os.name == "nt" if windows is None else windows
    if not use_windows_retry:
        shutil.rmtree(root)
        return

    def retry_readonly(function, candidate: str, error_info) -> None:
        error = error_info[1]
        resolved = Path(candidate).resolve()
        if not isinstance(error, PermissionError) or (
            resolved != root and root not in resolved.parents
        ):
            raise error
        os.chmod(resolved, stat.S_IWRITE | stat.S_IREAD)
        function(resolved)

    shutil.rmtree(root, onerror=retry_readonly)


def closeout(
    path: Path,
    *,
    authorize_frozen_recovery: bool = False,
) -> dict[str, object]:
    """Freeze evidence, then stop/uninstall only exact manifest-owned identities."""
    path = Path(path)
    value = _load(path)
    frozen = {
        "format": CLOSEOUT_FORMAT,
        "manifest_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "state": "FROZEN",
    }
    frozen_path = path.with_name(f"{path.stem}.closeout.json")
    validated_path = path.with_name(f"{path.stem}.validated.json")
    closed_path = path.with_name(f"{path.stem}.closed.json")
    frozen_exists = frozen_path.exists()
    if frozen_exists:
        if _load(frozen_path) != frozen:
            raise AcceptanceLifecycleError("CLEANUP_BLOCKED: frozen closeout identity drifted")
    else:
        _write_json(frozen_path, frozen, replace=False)
    expected_validated = {**frozen, "state": "VALIDATED"}
    validated_exists = validated_path.exists()
    if validated_exists and _load(validated_path) != expected_validated:
        raise AcceptanceLifecycleError("CLEANUP_BLOCKED: validated identity drifted")
    explicit_frozen_recovery = frozen_exists and authorize_frozen_recovery and not validated_exists
    recovering = validated_exists or explicit_frozen_recovery
    expected_closed = {**frozen, "state": "CLOSED"}
    if closed_path.exists():
        closed = _load(closed_path)
        if closed != expected_closed:
            raise AcceptanceLifecycleError("CLEANUP_BLOCKED: closed identity drifted")
        return closed
    entries, workspaces = _validated_entries(value)
    loaded: list[tuple[node.NodeProfile, dict[str, object], str]] = []
    for entry in entries:
        profile = node.load_profile(str(_canonical_path(entry["profile"], label="profile")))
        active, expected_installed = _active_profile(profile), str(entry["installed_profile"])
        if (
            profile.digest != entry["profile_sha256"]
            or str(profile.repo) != entry["workspace"]
            or (active is not profile and str(active.path) != expected_installed)
        ):
            raise AcceptanceLifecycleError("CLEANUP_BLOCKED: profile identity drifted")
        installation = _installation(active)
        if (
            installation.get("manager") != entry["manager"]
            or installation.get("manager_id") != entry["manager_id"]
        ):
            raise AcceptanceLifecycleError("CLEANUP_BLOCKED: native manager identity drifted")
        status = installation.get("status")
        if status not in {"current", "not_installed"}:
            raise AcceptanceLifecycleError(
                "CLEANUP_BLOCKED: native installation identity is unknown"
            )
        loaded.append((active, entry, str(status)))
    installation_by_workspace = {entry[1]["workspace"]: entry[2] for entry in loaded}
    state_roots = {profile.state_root for profile, _entry, _status in loaded}
    if len(state_roots) != 1:
        raise AcceptanceLifecycleError("CLEANUP_BLOCKED: state root identity is unknown")
    state_root = next(iter(state_roots))
    for workspace in workspaces:
        candidate = _canonical_path(workspace, label="workspace")
        if not candidate.is_dir():
            if recovering and installation_by_workspace.get(workspace) == "not_installed":
                continue
            raise AcceptanceLifecycleError("CLEANUP_BLOCKED: workspace identity is unknown")
        result = subprocess.run(
            ["git", "-C", str(candidate), "status", "--porcelain", "--untracked-files=all"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0 and result.stdout and not recovering:
            _freeze_retained_taskcards(candidate, result.stdout, state_root)
        recoverable_status = _partial_workspace_removal(result.stdout)
        if explicit_frozen_recovery:
            recoverable_status = (
                _explicit_frozen_recovery_status(result.stdout)
                or _mirrored_retained_review_status(candidate, result.stdout, state_root)
                or _mirrored_retained_taskcard_status(candidate, result.stdout, state_root)
            )
        if result.returncode or (result.stdout and (not recovering or not recoverable_status)):
            raise AcceptanceLifecycleError("CLEANUP_BLOCKED: workspace status is unavailable")
    if not validated_exists:
        _write_json(validated_path, expected_validated, replace=False)
    for profile, entry, status in loaded:
        if status == "not_installed":
            observation = node.lifecycle_facts(profile).get("running_observation")
            if not isinstance(observation, dict) or observation.get("status") != "stopped":
                raise AcceptanceLifecycleError(
                    f"CLEANUP_BLOCKED: listener remains active for {profile.role}"
                )
        if status == "current":
            if node.stop(profile):
                raise AcceptanceLifecycleError(
                    f"CLEANUP_BLOCKED: exact stop failed for {profile.role}"
                )
            observation = node.lifecycle_facts(profile).get("running_observation")
            if not isinstance(observation, dict) or observation.get("status") != "stopped":
                raise AcceptanceLifecycleError(
                    f"CLEANUP_BLOCKED: listener remains active for {profile.role}"
                )
            if node.uninstall(profile):
                raise AcceptanceLifecycleError(
                    f"CLEANUP_BLOCKED: exact uninstall failed for {profile.role}"
                )
        if _installation(profile).get("status") != "not_installed":
            raise AcceptanceLifecycleError(
                f"CLEANUP_BLOCKED: native installation remains for {profile.role}"
            )
        if node.load_installed_profile(str(entry["profile"])) is not None:
            raise AcceptanceLifecycleError(
                f"CLEANUP_BLOCKED: installed profile registry remains for {profile.role}"
            )
        installed_path = entry["installed_profile"]
        if installed_path and Path(str(installed_path)).exists():
            raise AcceptanceLifecycleError(
                f"CLEANUP_BLOCKED: installed profile snapshot remains for {profile.role}"
            )
    for workspace in workspaces:
        candidate = _canonical_path(workspace, label="workspace")
        if candidate.exists():
            _remove_workspace(candidate)
        if candidate.exists():
            raise AcceptanceLifecycleError("CLEANUP_BLOCKED: generated workspace remains")
    _write_json(closed_path, expected_closed, replace=False)
    return _load(closed_path)
