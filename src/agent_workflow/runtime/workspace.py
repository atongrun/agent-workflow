"""Exact local workspace isolation and trusted delta import.

This module owns only local filesystem and credential-free Git effects. It has no Workflow,
transport, provider, remote-Git, GitHub, lifecycle, or Store authority.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

_COMMIT_RE = re.compile(r"[0-9a-f]{7,64}")
_PREFIX_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
_MAX_ENVIRONMENT_BYTES = 512 * 1024
_MAX_GIT_OUTPUT_BYTES = 4 * 1024 * 1024
_MAX_PATCH_BYTES = 64 * 1024 * 1024
_SENSITIVE_ENV_PARTS = ("TOKEN", "PASSWORD", "SECRET", "CREDENTIAL", "AUTHORIZATION")


class WorkspaceError(RuntimeError):
    """One local workspace invariant failed closed."""


def _is_reparse(path: Path) -> bool:
    try:
        details = path.lstat()
    except OSError:
        return False
    attributes = int(getattr(details, "st_file_attributes", 0))
    reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    return path.is_symlink() or bool(attributes & reparse_flag)


def _resolved_path(value: str, label: str, *, must_exist: bool) -> Path:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise WorkspaceError(f"{label} path is invalid")
    raw = Path(value).expanduser().absolute()
    try:
        resolved = raw.resolve(strict=must_exist)
    except (OSError, RuntimeError) as exc:
        raise WorkspaceError(f"{label} path is unavailable") from exc
    if os.path.normcase(str(raw)) != os.path.normcase(str(resolved)) or _is_reparse(raw):
        raise WorkspaceError(f"{label} path is redirected")
    if must_exist and not resolved.is_dir():
        raise WorkspaceError(f"{label} path is not a directory")
    return resolved


def bind_environment(environment: dict[str, str]) -> tuple[tuple[str, str], ...]:
    """Freeze one explicit credential-free child environment."""
    if not isinstance(environment, dict) or not environment or len(environment) > 256:
        raise WorkspaceError("workspace environment is invalid")
    result: list[tuple[str, str]] = []
    seen: set[str] = set()
    total = 0
    for key, value in environment.items():
        if not isinstance(key, str) or not key or "=" in key or "\x00" in key:
            raise WorkspaceError("workspace environment name is invalid")
        if not isinstance(value, str) or "\x00" in value:
            raise WorkspaceError("workspace environment value is invalid")
        normalized = key.upper()
        if normalized in seen or any(part in normalized for part in _SENSITIVE_ENV_PARTS):
            raise WorkspaceError("workspace environment is not credential-stripped")
        seen.add(normalized)
        total += len(key.encode("utf-8")) + len(value.encode("utf-8"))
        if total > _MAX_ENVIRONMENT_BYTES:
            raise WorkspaceError("workspace environment is too large")
        result.append((key, value))
    return tuple(sorted(result, key=lambda item: (item[0].upper(), item[0])))


def _environment_dict(environment: tuple[tuple[str, str], ...]) -> dict[str, str]:
    frozen = bind_environment(dict(environment))
    if frozen != environment:
        raise WorkspaceError("workspace environment is not canonical")
    return dict(frozen)


@dataclass(frozen=True, slots=True)
class WorkspaceSpec:
    source_repo: str
    expected_commit: str
    state_dir: str
    workspace_prefix: str
    environment: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        source = _resolved_path(self.source_repo, "source repository", must_exist=True)
        state = _resolved_path(self.state_dir, "workspace state directory", must_exist=False)
        if not _COMMIT_RE.fullmatch(self.expected_commit):
            raise WorkspaceError("expected workspace commit is invalid")
        if not _PREFIX_RE.fullmatch(self.workspace_prefix):
            raise WorkspaceError("workspace prefix is invalid")
        _environment_dict(self.environment)
        object.__setattr__(self, "source_repo", str(source))
        object.__setattr__(self, "state_dir", str(state))


@dataclass(frozen=True, slots=True)
class PreparedWorkspace:
    path: str
    expected_commit: str
    manifest_sha256: str


@dataclass(frozen=True, slots=True)
class WorkspaceDelta:
    base_tree: str
    model_tree: str
    patch: bytes

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[0-9a-f]{40,64}", self.base_tree):
            raise WorkspaceError("workspace base tree is invalid")
        if not re.fullmatch(r"[0-9a-f]{40,64}", self.model_tree):
            raise WorkspaceError("workspace model tree is invalid")
        if not isinstance(self.patch, bytes) or not self.patch:
            raise WorkspaceError("workspace patch is empty")
        if len(self.patch) > _MAX_PATCH_BYTES:
            raise WorkspaceError("workspace patch is too large")

    @property
    def patch_sha256(self) -> str:
        return hashlib.sha256(self.patch).hexdigest()

    @property
    def identity_sha256(self) -> str:
        value = {
            "base_tree": self.base_tree,
            "model_tree": self.model_tree,
            "patch_length": len(self.patch),
            "patch_sha256": self.patch_sha256,
        }
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


def _run_git(
    environment: tuple[tuple[str, str], ...],
    *args: str,
    input_bytes: bytes | None = None,
    capture_limit: int | None = None,
) -> bytes:
    argv = ["git", *args]
    for token in argv:
        if not isinstance(token, str) or not token or "\x00" in token:
            raise WorkspaceError("workspace Git argument is invalid")
    child_environment = _environment_dict(environment)
    if capture_limit is not None:
        try:
            process = subprocess.Popen(
                argv,
                shell=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env=child_environment,
            )
        except OSError as exc:
            raise WorkspaceError("workspace Git process could not start") from exc
        chunks: list[bytes] = []
        total = 0
        assert process.stdout is not None
        try:
            while True:
                chunk = process.stdout.read(64 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > capture_limit:
                    process.kill()
                    process.wait()
                    raise WorkspaceError("workspace Git output is too large")
                chunks.append(chunk)
            return_code = process.wait()
        except BaseException:
            if process.poll() is None:
                process.kill()
                process.wait()
            raise
        finally:
            process.stdout.close()
        if return_code != 0:
            raise WorkspaceError("workspace Git operation failed")
        return b"".join(chunks)
    try:
        completed = subprocess.run(
            argv,
            check=False,
            shell=False,
            stdin=None if input_bytes is not None else subprocess.DEVNULL,
            input=input_bytes,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=child_environment,
        )
    except OSError as exc:
        raise WorkspaceError("workspace Git process could not start") from exc
    if completed.returncode != 0:
        raise WorkspaceError("workspace Git operation failed")
    return b""


def _git_output(
    repo: Path,
    environment: tuple[tuple[str, str], ...],
    *args: str,
    limit: int = _MAX_GIT_OUTPUT_BYTES,
) -> str:
    raw = _run_git(environment, "-C", str(repo), *args, capture_limit=limit)
    return raw.decode("utf-8", errors="replace").rstrip("\n\r")


def _manifest(
    workspace: Path,
    environment: tuple[tuple[str, str], ...],
    *,
    include_semantic_index: bool = True,
) -> dict[str, tuple[str, str]]:
    git_dir = workspace / ".git"
    if not git_dir.is_dir() or _is_reparse(git_dir):
        raise WorkspaceError("isolated workspace Git directory is unavailable")
    manifest: dict[str, tuple[str, str]] = {}
    try:
        paths = sorted(git_dir.rglob("*"))
    except OSError as exc:
        raise WorkspaceError("isolated workspace Git metadata is unreadable") from exc
    for path in paths:
        relative = path.relative_to(git_dir)
        parts = relative.parts
        if parts and parts[0] == "objects" and parts[:2] != ("objects", "info"):
            continue
        if relative.as_posix() == "index":
            continue
        name = relative.as_posix()
        try:
            if _is_reparse(path):
                try:
                    target = os.readlink(path)
                except OSError:
                    target = ""
                manifest[name] = ("symlink", target)
            elif path.is_file():
                manifest[name] = ("file", hashlib.sha256(path.read_bytes()).hexdigest())
            elif path.is_dir():
                manifest[name] = ("dir", "")
            else:
                manifest[name] = ("other", "")
        except OSError as exc:
            raise WorkspaceError("isolated workspace Git metadata is unreadable") from exc
    if include_semantic_index:
        staged = _git_output(workspace, environment, "ls-files", "--stage", "-z")
        tree = _git_output(workspace, environment, "write-tree")
        manifest["index-semantic"] = (
            "git-index",
            hashlib.sha256(staged.encode("utf-8") + b"\0" + tree.encode("ascii")).hexdigest(),
        )
    return manifest


def _manifest_sha256(manifest: dict[str, tuple[str, str]]) -> str:
    serializable = {key: list(value) for key, value in manifest.items()}
    encoded = json.dumps(
        serializable,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


_FROZEN_MANIFESTS: dict[str, dict[str, tuple[str, str]]] = {}


def workspace_manifest(
    workspace: str,
    environment: tuple[tuple[str, str], ...],
) -> dict[str, tuple[str, str]]:
    resolved = _resolved_path(workspace, "isolated workspace", must_exist=True)
    return _manifest(resolved, environment)


def freeze_workspace(
    workspace: str,
    environment: tuple[tuple[str, str], ...],
) -> str:
    resolved = _resolved_path(workspace, "isolated workspace", must_exist=True)
    manifest = _manifest(resolved, environment)
    _FROZEN_MANIFESTS[str(resolved)] = manifest
    return _manifest_sha256(manifest)


def assert_frozen_workspace(
    workspace: str,
    environment: tuple[tuple[str, str], ...],
) -> None:
    resolved = _resolved_path(workspace, "isolated workspace", must_exist=True)
    expected = _FROZEN_MANIFESTS.get(str(resolved))
    if expected is None:
        raise WorkspaceError("isolated workspace Git control metadata is not frozen")
    expected_control = {key: value for key, value in expected.items() if key != "index-semantic"}
    current_control = _manifest(resolved, environment, include_semantic_index=False)
    if current_control != expected_control or _manifest(resolved, environment) != expected:
        raise WorkspaceError("isolated workspace Git control metadata changed")


def restore_workspace_manifest(
    workspace: str,
    expected_sha256: str,
    environment: tuple[tuple[str, str], ...],
) -> str:
    resolved = _resolved_path(workspace, "durable workspace", must_exist=True)
    manifest = _manifest(resolved, environment)
    if _manifest_sha256(manifest) != expected_sha256:
        raise WorkspaceError("durable workspace Git metadata does not match its checkpoint")
    _FROZEN_MANIFESTS[str(resolved)] = manifest
    return str(resolved)


def workspace_manifest_sha256(
    workspace: str,
    environment: tuple[tuple[str, str], ...],
) -> str:
    return _manifest_sha256(workspace_manifest(workspace, environment))


def workspace_control_sha256(
    workspace: str,
    environment: tuple[tuple[str, str], ...],
) -> str:
    manifest = workspace_manifest(workspace, environment)
    stable = {
        key: value
        for key, value in manifest.items()
        if key not in {"HEAD", "index-semantic"}
    }
    return _manifest_sha256(stable)


def prepare_workspace(spec: WorkspaceSpec) -> PreparedWorkspace:
    source = Path(spec.source_repo)
    state_dir = Path(spec.state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    state_dir = _resolved_path(str(state_dir), "workspace state directory", must_exist=True)
    workspace = Path(tempfile.mkdtemp(prefix=spec.workspace_prefix, dir=str(state_dir))).resolve()
    if workspace.parent != state_dir or _is_reparse(workspace):
        raise WorkspaceError("isolated workspace path escaped its state directory")
    _run_git(
        spec.environment,
        "clone",
        "--no-hardlinks",
        "--no-checkout",
        str(source),
        str(workspace),
    )
    _run_git(spec.environment, "-C", str(workspace), "remote", "remove", "origin")
    _run_git(spec.environment, "-C", str(workspace), "config", "core.logAllRefUpdates", "false")
    _run_git(spec.environment, "-C", str(workspace), "checkout", "--detach", spec.expected_commit)
    git_dir = workspace / ".git"
    logs = git_dir / "logs"
    if logs.exists():
        shutil.rmtree(logs)
    fetch_head = git_dir / "FETCH_HEAD"
    if fetch_head.exists():
        fetch_head.unlink()
    if logs.exists() or fetch_head.exists():
        raise WorkspaceError("isolated workspace source metadata could not be removed")
    head = _git_output(workspace, spec.environment, "rev-parse", "--verify", "HEAD^{commit}")
    if head != spec.expected_commit:
        raise WorkspaceError("isolated workspace does not match its dispatched commit")
    if _git_output(workspace, spec.environment, "remote"):
        raise WorkspaceError("isolated workspace retained a Git remote")
    digest = freeze_workspace(str(workspace), spec.environment)
    return PreparedWorkspace(str(workspace), spec.expected_commit, digest)


def assert_workspace_state(
    workspace: str,
    expected_commit: str,
    environment: tuple[tuple[str, str], ...],
) -> None:
    if not _COMMIT_RE.fullmatch(expected_commit):
        raise WorkspaceError("expected workspace commit is invalid")
    assert_frozen_workspace(workspace, environment)
    resolved = _resolved_path(workspace, "isolated workspace", must_exist=True)
    if (
        _git_output(resolved, environment, "rev-parse", "--verify", "HEAD^{commit}")
        != expected_commit
    ):
        raise WorkspaceError("model process changed isolated workspace HEAD")
    if _git_output(resolved, environment, "remote"):
        raise WorkspaceError("model process added a Git remote")


def serialize_workspace_delta(
    workspace: str,
    environment: tuple[tuple[str, str], ...],
) -> WorkspaceDelta:
    assert_frozen_workspace(workspace, environment)
    resolved = _resolved_path(workspace, "isolated workspace", must_exist=True)
    _run_git(environment, "-C", str(resolved), "add", "-A")
    model_tree = _git_output(resolved, environment, "write-tree")
    base_tree = _git_output(resolved, environment, "rev-parse", "HEAD^{tree}")
    if not model_tree or model_tree == base_tree:
        raise WorkspaceError("isolated workspace has no importable changes")
    patch = _run_git(
        environment,
        "-C",
        str(resolved),
        "diff",
        "--no-ext-diff",
        "--no-textconv",
        "--cached",
        "--binary",
        "--full-index",
        "HEAD",
        capture_limit=_MAX_PATCH_BYTES,
    )
    return WorkspaceDelta(base_tree, model_tree, patch)


def import_workspace_delta(
    delta: WorkspaceDelta,
    trusted_repo: str,
    environment: tuple[tuple[str, str], ...],
) -> str:
    trusted = _resolved_path(trusted_repo, "trusted repository", must_exist=True)
    _run_git(
        environment,
        "-C",
        str(trusted),
        "apply",
        "--index",
        "--binary",
        "-",
        input_bytes=delta.patch,
    )
    trusted_tree = _git_output(trusted, environment, "write-tree")
    if trusted_tree != delta.model_tree:
        raise WorkspaceError("trusted imported tree does not match the verified model tree")
    return trusted_tree
