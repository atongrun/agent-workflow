"""Owner-controlled, credential-free run manifest.

The manifest is the single source for TaskCard-derived execution metadata.  It
intentionally contains no tokens and is never treated as shell input.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
from pathlib import Path
from subprocess import run as _run
from typing import Any

FORMAT = "awf.run-manifest.v1"
COMPILER_FORMAT = "awf.run-contract-compiler.v1"
REPORT_FORMAT = "awf.run-contract-report.v1"
_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_ACE_RE = re.compile(r"(.+?):((?:\([A-Za-z,]+\))+)\Z")
_ALLOWED = {
    "format",
    "task_id",
    "card",
    "branch",
    "routes",
    "report_paths",
    "models",
    "rework_budget",
    "provenance",
    "state_root",
    "profiles",
}
_PROVENANCE_KEYS = {"upstream_repo", "head_repo", "upstream_remote", "head_remote", "base_ref"}
DEFAULT_MANIFEST_NAME = ".awf/run-manifest.json"
DEFAULT_COMPILED_REPORT_NAME = ".awf/run-contract.json"


class ManifestError(RuntimeError):
    """Credential-safe manifest validation failure."""


def _same_windows_principal(left: str, right: str) -> bool:
    """Match whoami and icacls forms when one omits the domain prefix."""
    left = left.casefold()
    right = right.casefold()
    return left == right or left.rsplit("\\", 1)[-1] == right.rsplit("\\", 1)[-1]


def default_manifest_path(repo: Path) -> Path:
    """Return the repository-local owner manifest location."""
    return Path(repo).resolve() / DEFAULT_MANIFEST_NAME


def default_compiled_report_path(repo: Path) -> Path:
    """Return the repository-local compiled run contract location."""
    return Path(repo).resolve() / DEFAULT_COMPILED_REPORT_NAME


def resolve_manifest_card(value: dict[str, Any], repo: Path) -> Path:
    """Resolve and validate the card bound into an owner manifest."""
    card = Path(str(value["card"]))
    if not card.is_absolute():
        card = Path(repo).resolve() / card
    return card.resolve()


def _validate_path(path: Path) -> None:
    if not path.is_absolute():
        raise ManifestError("manifest path must be absolute")
    try:
        info = path.lstat()
    except OSError as exc:
        raise ManifestError("manifest file is unavailable") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise ManifestError("manifest must be a regular, non-symlink file")
    if os.name == "nt":
        acl = _run(["icacls", str(path)], capture_output=True, text=True)
        identity = _run(["whoami"], capture_output=True, text=True)
        principal = identity.stdout.strip() if identity.returncode == 0 else ""
        if acl.returncode != 0 or not principal:
            raise ManifestError("could not verify manifest owner ACL")
        entries = _parse_windows_aces(path, acl.stdout)
        if not entries or any(
            not _same_windows_principal(owner, principal) for owner, _ in entries
        ):
            raise ManifestError("manifest ACL grants another principal")
        if any("(I)" in permissions for _, permissions in entries):
            raise ManifestError("manifest ACL must not be inherited")
        return
    if stat.S_IMODE(info.st_mode) & 0o077:
        raise ManifestError("manifest must be owner-only")
    if info.st_uid != os.geteuid():
        raise ManifestError("manifest owner does not match the current user")


def _parse_windows_aces(path: Path, output: str) -> list[tuple[str, str]]:
    """Extract icacls ACEs without treating its echoed target path as one."""
    target = str(path)
    entries: list[tuple[str, str]] = []
    for raw in output.splitlines():
        line = raw.strip()
        if not line or line.casefold().startswith("successfully processed"):
            continue
        if line.casefold().startswith(target.casefold()):
            line = line[len(target) :].strip()
        match = _ACE_RE.fullmatch(line)
        if match:
            entries.append((match.group(1), match.group(2)))
        elif ":(" in line:
            return []
    return entries


def _lock_windows_manifest(path: Path) -> None:
    """Restrict a manifest ACL to the current Windows principal."""
    identity = _run(["whoami"], capture_output=True, text=True)
    principal = identity.stdout.strip() if identity.returncode == 0 else ""
    if not principal:
        raise ManifestError("could not determine manifest owner")
    locked = _run(
        ["icacls", str(path), "/inheritance:r", "/grant:r", f"{principal}:F"],
        capture_output=True,
        text=True,
    )
    if locked.returncode != 0:
        raise ManifestError("could not apply owner-only manifest ACL")
    for _ in range(3):
        acl = _run(["icacls", str(path)], capture_output=True, text=True)
        if acl.returncode != 0:
            raise ManifestError("could not verify manifest owner ACL")
        entries = _parse_windows_aces(path, acl.stdout)
        if not entries:
            raise ManifestError("could not parse manifest owner ACL")
        extras = [
            owner
            for owner, _permissions in entries
            if not _same_windows_principal(owner, principal)
        ]
        for owner in extras:
            for removal in ("/remove:g", "/remove:d"):
                removed = _run(
                    ["icacls", str(path), removal, owner],
                    capture_output=True,
                    text=True,
                )
                if removed.returncode != 0:
                    raise ManifestError("could not remove an extra manifest principal")
        try:
            _validate_path(path)
            return
        except ManifestError:
            if not extras:
                raise
    raise ManifestError("could not establish an owner-only manifest ACL")


def validate_manifest(value: dict[str, Any]) -> dict[str, Any]:
    received_format = value.get("format") if isinstance(value, dict) else type(value).__name__
    if not isinstance(value, dict) or received_format != FORMAT:
        raise ManifestError(f"RunManifest requires {FORMAT}; received {received_format!r}")
    unknown = set(value) - _ALLOWED
    if unknown:
        raise ManifestError("manifest contains unknown fields")
    for key in ("task_id", "card", "branch"):
        item = value.get(key)
        if not isinstance(item, str) or not item.strip():
            raise ManifestError(f"manifest {key} is required")
    if not _ID_RE.fullmatch(value["task_id"]):
        raise ManifestError("manifest task_id is invalid")
    routes = value.get("routes", {})
    if (
        not isinstance(routes, dict)
        or not routes
        or any(not isinstance(k, str) or not isinstance(v, str) or not v for k, v in routes.items())
    ):
        raise ManifestError("manifest routes must be a non-empty string map")
    paths = value.get("report_paths", {})
    if not isinstance(paths, dict) or set(paths) != {"implementation", "review"}:
        raise ManifestError("manifest report_paths must contain implementation and review")
    if any(
        not isinstance(v, str) or not v or "\\" in v or ".." in v.split("/") for v in paths.values()
    ):
        raise ManifestError("manifest report paths are invalid")
    models = value.get("models", {})
    if not isinstance(models, dict) or any(
        not isinstance(k, str) or not isinstance(v, str) for k, v in models.items()
    ):
        raise ManifestError("manifest models must be a string map")
    model_keys = set(models)
    if model_keys - {"tool", "model", "reviewer_tool", "reviewer_model"}:
        raise ManifestError("manifest models contains unknown fields")
    reviewer_keys = model_keys & {"reviewer_tool", "reviewer_model"}
    if reviewer_keys and reviewer_keys != {"reviewer_tool", "reviewer_model"}:
        raise ManifestError("manifest reviewer selection must contain tool and model")
    budget = value.get("rework_budget", 0)
    if not isinstance(budget, int) or isinstance(budget, bool) or not 0 <= budget <= 100:
        raise ManifestError("manifest rework_budget is invalid")
    provenance = value.get("provenance", {})
    if not isinstance(provenance, dict) or set(provenance) - _PROVENANCE_KEYS:
        raise ManifestError("manifest provenance must be an object")
    if any(not isinstance(v, str) or not v for v in provenance.values()):
        raise ManifestError("manifest provenance values must be non-empty strings")
    state_root = value.get("state_root")
    profiles = value.get("profiles")
    if (state_root is None) != (profiles is None):
        raise ManifestError("manifest state_root and profiles must be configured together")
    if state_root is not None:
        if not isinstance(state_root, str) or not state_root or not Path(state_root).is_absolute():
            raise ManifestError("manifest state_root must be an absolute path")
        if not isinstance(profiles, dict) or set(profiles) != {"coder", "reviewer"}:
            raise ManifestError("manifest profiles must contain coder and reviewer")
        if any(not isinstance(item, str) or not item for item in profiles.values()):
            raise ManifestError("manifest profile references must be non-empty strings")
    return dict(value)


def load_manifest(path: Path) -> dict[str, Any]:
    path = Path(path).resolve()
    _validate_path(path)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ManifestError("manifest is unreadable or invalid JSON") from exc
    return validate_manifest(value)


def _write_owner_json(path: Path, value: dict[str, Any], *, replace: bool) -> Path:
    path = Path(path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not replace:
        raise ManifestError("manifest already exists; pass an explicit replacement flag")
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
        if os.name == "nt":
            _lock_windows_manifest(path)
    finally:
        if os.path.exists(name):
            os.unlink(name)
    return path


def write_manifest(path: Path, value: dict[str, Any], *, replace: bool = True) -> Path:
    validate_manifest(value)
    return _write_owner_json(path, value, replace=replace)


def derive_manifest(
    card: Path,
    *,
    branch: str = "",
    tool: str = "",
    model: str = "",
    reviewer_tool: str = "",
    reviewer_model: str = "",
    rework_budget: int = 1,
    upstream_repo: str = "",
    head_repo: str = "",
    upstream_remote: str = "upstream",
    head_remote: str = "fork",
    base_ref: str = "main",
    state_root: str = "",
    profiles: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Derive deterministic metadata from a self-contained TaskCard."""
    card = Path(card).resolve()
    try:
        text = card.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ManifestError("TaskCard is unreadable") from exc
    section = re.search(r"(?ms)^## Task ID\s*$([\s\S]*?)(?=^## |\Z)", text)
    task_id = ""
    if section:
        for line in section.group(1).splitlines():
            candidate = line.strip()
            if candidate and not candidate.startswith("<!--") and not candidate.endswith("-->"):
                task_id = candidate.strip("[]")
                break
    task_id = task_id or card.stem
    task_id = re.sub(r"[^A-Za-z0-9._-]+", "-", task_id).strip("-")
    if not _ID_RE.fullmatch(task_id):
        raise ManifestError("TaskCard does not contain a usable Task ID")
    branch_match = re.search(r"(?m)^- \*\*Task branch\*\*: `([^`]+)`", text)
    selected_branch = branch or (branch_match.group(1) if branch_match else f"awf/{task_id}")
    values = {
        "format": FORMAT,
        "task_id": task_id,
        "card": str(card),
        "branch": selected_branch,
        "routes": {
            "implement": "task:awf-impl-v3",
            "review": "task:awf-review-v3",
            "rework": "task:awf-rework-v3",
        },
        "report_paths": {
            "implementation": f".awf/artifacts/impl-report-{task_id}.md",
            "review": f".awf/artifacts/review-report-{task_id}.md",
        },
        "models": {
            "tool": tool,
            "model": model,
            "reviewer_tool": reviewer_tool or tool,
            "reviewer_model": reviewer_model if reviewer_tool or reviewer_model else model,
        },
        "rework_budget": rework_budget,
        "provenance": {
            key: value
            for key, value in {
                "upstream_repo": upstream_repo,
                "head_repo": head_repo,
                "upstream_remote": upstream_remote,
                "head_remote": head_remote,
                "base_ref": base_ref,
            }.items()
            if value
        },
    }
    if state_root or profiles:
        values["state_root"] = str(Path(state_root).expanduser().resolve()) if state_root else ""
        values["profiles"] = dict(profiles or {})
    return validate_manifest(values)


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _sha256(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def _route_version(route: str, stem: str) -> str:
    match = re.fullmatch(rf"task:awf-{re.escape(stem)}(?:-(v[23]))?", route)
    if match is None:
        raise ManifestError(f"RunManifest {stem} route is not compatible with v1-v3")
    return match.group(1) or "v1"


def _profile_selection(profile: dict[str, Any]) -> tuple[str, str]:
    return str(profile["values"].get("tool", "")), str(profile["values"].get("model", ""))


def compile_run_contract(
    *,
    repo: Path,
    run_id: str,
    run_manifest: dict[str, Any],
    run_manifest_path: Path,
    authority_manifest: dict[str, Any],
    authority_manifest_path: Path,
    authority_binding: dict[str, Any],
    taskcard_binding: dict[str, Any],
    state_root: Path,
    state_root_sha256: str,
    profiles: list[dict[str, Any]],
    compiler_version: str,
) -> dict[str, Any]:
    """Compile one local compatibility report without performing any external action."""
    values = validate_manifest(run_manifest)
    repo = Path(repo).resolve()
    branch = str(values["branch"])
    task_id = str(values["task_id"])
    branch_task_id = branch.rsplit("/", 1)[-1]
    if branch_task_id != task_id:
        raise ManifestError("RunManifest task_id must exactly match the task branch leaf")
    expected_run_id = f"task-{branch_task_id}"
    if run_id != expected_run_id:
        raise ManifestError(f"run id must be {expected_run_id!r} for the bound branch")

    routes = values["routes"]
    required_routes = {"implement": "impl", "review": "review", "rework": "rework"}
    if set(routes) != set(required_routes):
        raise ManifestError("RunManifest routes must contain implement, review, and rework")
    route_versions = {
        stage: _route_version(str(routes[stage]), stem) for stage, stem in required_routes.items()
    }

    by_role: dict[str, dict[str, Any]] = {}
    for profile in profiles:
        role = str(profile.get("role", ""))
        if role in by_role:
            raise ManifestError(f"multiple node profiles are bound to role {role!r}")
        by_role[role] = profile
    if set(by_role) != {"coder", "reviewer"}:
        raise ManifestError("compiler requires exactly one coder and one reviewer profile")

    models = values["models"]
    expected_selections = {
        "coder": (str(models.get("tool", "")), str(models.get("model", ""))),
        "reviewer": (
            str(models.get("reviewer_tool", "")),
            str(models.get("reviewer_model", "")),
        ),
    }
    provenance = values.get("provenance", {})
    role_routes = {
        "coder": {str(routes["implement"]), str(routes["rework"])},
        "reviewer": {str(routes["review"])},
    }
    profile_report: dict[str, dict[str, Any]] = {}
    for role, profile in by_role.items():
        profile_values = profile["values"]
        if _profile_selection(profile) != expected_selections[role]:
            raise ManifestError(f"{role} profile tool/model conflicts with RunManifest")
        if Path(str(profile_values["repo"])).expanduser().resolve() != repo:
            raise ManifestError(f"{role} profile repository conflicts with the compiled repository")
        if Path(str(profile["state_root"])).resolve() != Path(state_root).resolve():
            raise ManifestError(f"{role} profile state root conflicts with the compiled state root")
        on_type = str(profile_values.get("on_type", ""))
        if on_type and on_type not in role_routes[role]:
            raise ManifestError(f"{role} profile route conflicts with RunManifest")
        for key in (
            "upstream_repo",
            "head_repo",
            "upstream_remote",
            "head_remote",
            "base_ref",
        ):
            manifest_value = str(provenance.get(key, ""))
            profile_value = str(profile_values.get(key, ""))
            if manifest_value and profile_value and manifest_value != profile_value:
                raise ManifestError(f"{role} profile {key} conflicts with RunManifest")
        profile_report[role] = {
            "format": str(profile_values.get("format", "")),
            "name": str(profile_values.get("name", "")),
            "path": str(Path(profile["path"]).resolve()),
            "profile_source": str(profile.get("profile_source", "authoring")),
            "sha256": str(profile["sha256"]),
            "state_root_sha256": state_root_sha256,
        }

    report_paths = values["report_paths"]
    if taskcard_binding.get("task_id") != task_id:
        raise ManifestError("TaskCard task identity conflicts with RunManifest")
    if taskcard_binding.get("implementation_report_path") != report_paths["implementation"]:
        raise ManifestError("TaskCard ImplementationReport conflicts with RunManifest")
    if taskcard_binding.get("review_report_path") != report_paths["review"]:
        raise ManifestError("TaskCard ReviewReport conflicts with RunManifest")

    bindings = {
        "run_manifest": {
            "format": FORMAT,
            "path": str(Path(run_manifest_path).resolve()),
            "sha256": _sha256(values),
        },
        "authority_manifest": {
            "format": str(authority_manifest.get("format", "")),
            "path": str(Path(authority_manifest_path).resolve()),
            "sha256": str(authority_binding["sha256"]),
        },
        "taskcard": taskcard_binding,
        "state_root": {
            "path": str(Path(state_root).resolve()),
            "sha256": state_root_sha256,
        },
        "profiles": profile_report,
    }
    result: dict[str, Any] = {
        "format": REPORT_FORMAT,
        "compiler": {
            "format": COMPILER_FORMAT,
            "name": "agent-workflow",
            "version": compiler_version,
        },
        "compatibility": {
            "status": "compatible",
            "run_manifest": FORMAT,
            "route_versions": route_versions,
        },
        "identity": {
            "run_id": run_id,
            "task_id": task_id,
            "branch": branch,
            "repo": str(repo),
            "rework_budget": values.get("rework_budget", 0),
        },
        "bindings": bindings,
    }
    result["contract_sha256"] = _sha256(result)
    return result


def validate_compiled_report(value: dict[str, Any]) -> dict[str, Any]:
    """Validate a persisted compiler report and its self-binding."""
    required = {
        "format",
        "compiler",
        "compatibility",
        "identity",
        "bindings",
        "contract_sha256",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise ManifestError("compiled run contract fields are invalid")
    if value.get("format") != REPORT_FORMAT:
        raise ManifestError(
            f"compiled run contract requires {REPORT_FORMAT}; received {value.get('format')!r}"
        )
    compiler = value.get("compiler")
    if not isinstance(compiler, dict) or compiler.get("format") != COMPILER_FORMAT:
        raise ManifestError("compiled run contract compiler provenance is invalid")
    compatibility = value.get("compatibility")
    if not isinstance(compatibility, dict) or compatibility.get("status") != "compatible":
        raise ManifestError("compiled run contract is not compatible")
    digest = value.get("contract_sha256")
    body = {key: item for key, item in value.items() if key != "contract_sha256"}
    if not isinstance(digest, str) or digest != _sha256(body):
        raise ManifestError("compiled run contract checksum mismatch")
    if not isinstance(value.get("identity"), dict) or not isinstance(value.get("bindings"), dict):
        raise ManifestError("compiled run contract bindings are invalid")
    return dict(value)


def load_compiled_report(path: Path) -> dict[str, Any]:
    path = Path(path).resolve()
    _validate_path(path)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ManifestError("compiled run contract is unreadable or invalid JSON") from exc
    return validate_compiled_report(value)


def write_compiled_report(
    path: Path, value: dict[str, Any], *, replace: bool = True
) -> Path:
    validate_compiled_report(value)
    return _write_owner_json(path, value, replace=replace)
