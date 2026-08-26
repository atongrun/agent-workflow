"""Trusted, non-authorizing persistence for one Pi Architect TaskCard proposal."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Mapping

from .artifact import (
    ArtifactError,
    ArtifactFact,
    compile_implementation_report_path,
    compile_review_report_path,
    parse_postflight_text,
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
_SEMANTIC_KEYS = frozenset(
    {
        "task_id",
        "objective",
        "scope",
        "change_paths",
        "constraints",
        "acceptance_criteria",
        "verification_commands",
    }
)
_PROTOCOL_MARKERS = ("<!--", "-->", "awf-reviewer-selection", "awf-postflight")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ArtifactError("Architect TaskCard postflight contains a duplicate key")
        value[key] = item
    return value


def _semantic_text(value: object, field: str, *, maximum: int = 2000) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > maximum
        or "\n" in value
        or "\r" in value
        or any(ord(char) < 0x20 or ord(char) == 0x7F for char in value)
        or any(marker in value for marker in _PROTOCOL_MARKERS)
    ):
        raise ArtifactError(f"Architect semantic {field} is invalid")
    return value


def _semantic_text_list(value: object, field: str) -> list[str]:
    if not isinstance(value, list) or not value or len(value) > 32:
        raise ArtifactError(f"Architect semantic {field} must be a non-empty array")
    result = [
        _semantic_text(item, f"{field}[{index}]", maximum=1000) for index, item in enumerate(value)
    ]
    if len(result) != len(set(result)):
        raise ArtifactError(f"Architect semantic {field} contains duplicates")
    return result


def _semantic_path(value: object, index: int, task_id: str) -> str:
    path = _semantic_text(value, f"change_paths[{index}]", maximum=1024)
    pure = PurePosixPath(path)
    if (
        path.startswith("/")
        or "\\" in path
        or ":" in path
        or pure.as_posix() != path
        or path in {".", ".."}
        or ".." in pure.parts
        or path == f"docs/tasks/{task_id}.md"
        or path.startswith(".awf/artifacts/")
        or path == ".git"
        or path.startswith(".git/")
    ):
        raise ArtifactError(f"Architect semantic change_paths[{index}] is invalid")
    return path


def parse_architect_task_semantic(raw: bytes) -> dict[str, object]:
    """Validate the closed, provider-neutral Architect semantic payload."""
    if not isinstance(raw, bytes) or not raw or len(raw) > _MAX_TASKCARD_BYTES:
        raise ArtifactError("Architect semantic output must be bounded non-empty bytes")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise ArtifactError("Architect semantic output is invalid JSON") from exc
    if not isinstance(value, dict) or set(value) != _SEMANTIC_KEYS:
        raise ArtifactError("Architect semantic output has missing or unknown fields")
    task_id = _semantic_text(value["task_id"], "task_id", maximum=200)
    if _TASK_ID.fullmatch(task_id) is None:
        raise ArtifactError("Architect semantic task_id is invalid")
    paths = value["change_paths"]
    if not isinstance(paths, list) or not paths or len(paths) > 32:
        raise ArtifactError("Architect semantic change_paths must be a non-empty array")
    change_paths = [_semantic_path(item, index, task_id) for index, item in enumerate(paths)]
    if len(change_paths) != len(set(change_paths)):
        raise ArtifactError("Architect semantic change_paths contains duplicates")
    commands = value["verification_commands"]
    if not isinstance(commands, list) or not commands or len(commands) > 16:
        raise ArtifactError("Architect semantic verification_commands must be a non-empty array")
    verified_commands: list[list[str]] = []
    for command_index, command in enumerate(commands):
        if not isinstance(command, list) or not command or len(command) > 32:
            raise ArtifactError(
                f"Architect semantic verification_commands[{command_index}] is invalid"
            )
        verified_commands.append(
            [
                _semantic_text(
                    item,
                    f"verification_commands[{command_index}][{argument_index}]",
                    maximum=1024,
                )
                for argument_index, item in enumerate(command)
            ]
        )
    return {
        "task_id": task_id,
        "objective": _semantic_text(value["objective"], "objective"),
        "scope": _semantic_text_list(value["scope"], "scope"),
        "change_paths": change_paths,
        "constraints": _semantic_text_list(value["constraints"], "constraints"),
        "acceptance_criteria": _semantic_text_list(
            value["acceptance_criteria"], "acceptance_criteria"
        ),
        "verification_commands": verified_commands,
    }


def assemble_architect_taskcard(
    semantic: Mapping[str, object],
    *,
    frozen_base: str,
    repository: str,
    base_ref: str,
    coder: Mapping[str, object],
    reviewer: Mapping[str, object],
) -> bytes:
    """Inject trusted TaskCard authority facts into a validated semantic proposal."""
    normalized = parse_architect_task_semantic(
        json.dumps(dict(semantic), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )
    if re.fullmatch(r"[0-9a-f]{40,64}", frozen_base) is None:
        raise ArtifactError("trusted frozen base is invalid")
    if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) is None:
        raise ArtifactError("trusted repository identity is invalid")
    if not isinstance(base_ref, str) or not base_ref or any(char.isspace() for char in base_ref):
        raise ArtifactError("trusted base ref is invalid")
    selections: dict[str, dict[str, str]] = {}
    for role, selection in (("coder", coder), ("reviewer", reviewer)):
        if (
            not isinstance(selection, Mapping)
            or set(selection) != {"tool", "model"}
            or not isinstance(selection["tool"], str)
            or not selection["tool"]
            or not isinstance(selection["model"], str)
        ):
            raise ArtifactError(f"trusted {role} selection is invalid")
        selections[role] = {"tool": str(selection["tool"]), "model": str(selection["model"])}
    task_id = str(normalized["task_id"])
    implementation = compile_implementation_report_path(task_id)
    review = compile_review_report_path(task_id)
    commands = list(normalized["verification_commands"])
    allowed = [*list(normalized["change_paths"]), implementation, review]

    def bullets(values: object, prefix: str) -> str:
        return "\n".join(f"{prefix} {value}" for value in values)

    selection_json = json.dumps(
        selections, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    postflight_json = json.dumps(
        {"allowed_paths": allowed, "verification_commands": commands},
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    command_text = "\n".join(json.dumps(command, ensure_ascii=False) for command in commands)
    paths_text = ", ".join(f"`{path}`" for path in normalized["change_paths"])
    raw = (
        "# Task Card\n\n## Task ID\n\n"
        f"{task_id}\n\n## Goal\n\n{normalized['objective']}\n\n## Scope\n\n"
        f"{bullets(normalized['scope'], '-')}\n\n## Out of Scope\n\n"
        "- Any change outside the declared scope and allowed paths.\n\n"
        "## Working Context (self-contained)\n\n"
        f"- **Repository**: `{repository}`\n- **Base branch**: `{base_ref}`\n"
        f"- **Task branch**: `agent/{task_id}`\n- **Frozen base**: `{frozen_base}`\n"
        f"- **Entry points & relevant files**: {paths_text}\n\n## Constraints\n\n"
        f"{bullets(normalized['constraints'], '-')}\n\n## Acceptance Criteria\n\n"
        f"{bullets(normalized['acceptance_criteria'], '- [ ]')}\n\n"
        "## Verification Commands\n\nExecute these exact argv arrays without a shell:\n\n```json\n"
        f"{command_text}\n```\n\n## Required Output Artifacts\n\n"
        f"- ImplementationReport: `{implementation}`\n- ReviewReport: `{review}`\n\n"
        "<!-- awf-reviewer-selection\n"
        f"{selection_json}\n-->\n\n<!-- awf-postflight\n{postflight_json}\n-->\n"
    ).encode("utf-8")
    if len(raw) > _MAX_TASKCARD_BYTES:
        raise ArtifactError("assembled Architect TaskCard exceeds 64 KiB")
    return raw


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
    postflight = parse_postflight_text(text, sys.executable)
    allowed = postflight.allowed_paths
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
