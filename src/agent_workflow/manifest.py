"""Owner-controlled, credential-free run manifest.

The manifest is the single source for TaskCard-derived execution metadata.  It
intentionally contains no tokens and is never treated as shell input.
"""

from __future__ import annotations

import json
import os
import re
import stat
import tempfile
from pathlib import Path
from subprocess import run as _run
from typing import Any

FORMAT = "awf.run-manifest.v1"
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
}
_PROVENANCE_KEYS = {"upstream_repo", "head_repo", "upstream_remote", "head_remote", "base_ref"}
DEFAULT_MANIFEST_NAME = ".awf/run-manifest.json"


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
    if not isinstance(value, dict) or value.get("format") != FORMAT:
        raise ManifestError("manifest format is invalid")
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
    return dict(value)


def load_manifest(path: Path) -> dict[str, Any]:
    path = Path(path).resolve()
    _validate_path(path)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ManifestError("manifest is unreadable or invalid JSON") from exc
    return validate_manifest(value)


def write_manifest(path: Path, value: dict[str, Any], *, replace: bool = True) -> Path:
    path = Path(path).expanduser().resolve()
    validate_manifest(value)
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
    return {
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
