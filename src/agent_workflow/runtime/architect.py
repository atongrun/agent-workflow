"""Trusted, non-authorizing persistence for one Pi Architect TaskCard proposal."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from .artifact import (
    ArtifactError,
    ArtifactFact,
    compile_implementation_report_path,
    compile_review_report_path,
    scan_secret_text,
)

_MAX_TASKCARD_BYTES = 64 * 1024
_TASK_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_TASK_ID_SECTION = re.compile(
    r"(?m)^## Task ID[ \t]*\r?\n(?:[ \t]*\r?\n)*`?"
    r"([A-Za-z0-9][A-Za-z0-9._-]*)`?[ \t]*$"
)
_TASK_BRANCH = re.compile(r"(?m)^- \*\*Task branch\*\*: `([^`]+)`\s*$")
_POSTFLIGHT = re.compile(r"<!--\s*awf-postflight\s*\n(.*?)\n\s*-->", re.DOTALL)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ArtifactError("Architect TaskCard postflight contains a duplicate key")
        value[key] = item
    return value


def _validated_taskcard(raw: bytes, destination: Path, repo: Path) -> tuple[str, str]:
    if not isinstance(raw, bytes) or not raw or len(raw) > _MAX_TASKCARD_BYTES:
        raise ArtifactError("Architect TaskCard stdout must be bounded non-empty bytes")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ArtifactError("Architect TaskCard stdout is not valid UTF-8") from exc
    if any((ord(char) < 0x20 and char not in "\t\n\r") or ord(char) == 0x7F for char in text):
        raise ArtifactError("Architect TaskCard stdout contains a prohibited control character")
    secret = scan_secret_text(text)
    if secret:
        raise ArtifactError(f"Architect TaskCard contains prohibited {secret} material")

    task_match = _TASK_ID_SECTION.search(text)
    branch_match = _TASK_BRANCH.search(text)
    postflight_match = _POSTFLIGHT.search(text)
    if task_match is None or branch_match is None or postflight_match is None:
        raise ArtifactError("Architect TaskCard is missing Task ID, Task branch, or postflight")
    task_id = task_match.group(1).strip()
    branch = branch_match.group(1).strip()
    if (
        _TASK_ID.fullmatch(task_id) is None
        or branch.rsplit("/", 1)[-1] != task_id
        or branch.startswith("/")
        or ".." in branch.split("/")
        or re.fullmatch(r"[A-Za-z0-9._/-]+", branch) is None
    ):
        raise ArtifactError("Architect TaskCard identity does not match its branch")
    try:
        postflight = json.loads(postflight_match.group(1), object_pairs_hook=_unique_object)
    except (ValueError, json.JSONDecodeError) as exc:
        raise ArtifactError("Architect TaskCard postflight is invalid JSON") from exc
    if not isinstance(postflight, dict):
        raise ArtifactError("Architect TaskCard postflight must be an object")
    allowed = postflight.get("allowed_paths")
    if (
        not isinstance(allowed, list)
        or not allowed
        or len(allowed) != len(set(allowed))
        or not all(isinstance(item, str) and item for item in allowed)
    ):
        raise ArtifactError("Architect TaskCard allowed_paths are invalid")
    if any(
        item.startswith("/") or "\\" in item or ":" in item or ".." in item.split("/")
        for item in allowed
    ):
        raise ArtifactError("Architect TaskCard allowed_paths escape the repository")
    implementation = compile_implementation_report_path(task_id)
    review = compile_review_report_path(task_id)
    declared_impl = [item for item in allowed if Path(item).name.startswith("impl-report-")]
    declared_review = [item for item in allowed if Path(item).name.startswith("review-report-")]
    if declared_impl != [implementation] or declared_review != [review]:
        raise ArtifactError("Architect TaskCard report-path binding is invalid")
    relative = destination.relative_to(repo).as_posix()
    if relative in allowed:
        raise ArtifactError("Architect TaskCard cannot make itself model-writable")
    return task_id, relative


def persist_architect_taskcard(
    *,
    repo: str,
    destination: str,
    stdout: bytes,
) -> ArtifactFact:
    """Validate all untrusted stdout, then create one exact TaskCard without authorization."""
    root = Path(repo).expanduser().resolve()
    target = Path(destination).expanduser()
    if not target.is_absolute():
        raise ArtifactError("Architect TaskCard destination must be absolute")
    if not root.is_dir() or root.is_symlink():
        raise ArtifactError("Architect TaskCard repository root is unavailable")
    parent = target.parent
    if not parent.exists() or not parent.is_dir() or parent.is_symlink():
        raise ArtifactError("Architect TaskCard destination parent is unavailable")
    try:
        resolved_parent = parent.resolve(strict=True)
        resolved_parent.relative_to(root)
    except (OSError, ValueError) as exc:
        raise ArtifactError("Architect TaskCard destination escapes the repository") from exc
    resolved = resolved_parent / target.name
    if resolved.exists() or resolved.is_symlink():
        raise ArtifactError("Architect TaskCard destination already exists")

    _task_id, relative = _validated_taskcard(stdout, resolved, root)
    descriptor = -1
    try:
        descriptor = os.open(resolved, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(stdout)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            directory_fd = os.open(resolved_parent, os.O_RDONLY)
        except OSError:
            directory_fd = -1
        if directory_fd >= 0:
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    except OSError as exc:
        if descriptor >= 0:
            os.close(descriptor)
        resolved.unlink(missing_ok=True)
        raise ArtifactError("Architect TaskCard could not be persisted durably") from exc
    return ArtifactFact(relative, len(stdout), hashlib.sha256(stdout).hexdigest())
