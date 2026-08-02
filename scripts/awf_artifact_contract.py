"""Machine-owned implementation artifact contract for production Workflow stages."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

_POSTFLIGHT_RE = re.compile(r"<!--\s*awf-postflight\s*\n(.*?)\n\s*-->", re.DOTALL)
_TASK_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_ARTIFACT_ROOT = ".awf/artifacts/"


class ArtifactContractError(RuntimeError):
    """The compiled stage artifact identity disagrees with a supplied contract."""


@dataclass(frozen=True)
class StageArtifactContract:
    task_id: str
    implementation_report_path: str


def compile_implementation_report_path(task_id: str) -> str:
    """Compile the only valid ImplementationReport path for a task stage."""
    if not isinstance(task_id, str) or not _TASK_ID_RE.fullmatch(task_id):
        raise ArtifactContractError("task_id cannot compile a safe implementation report path")
    return f"{_ARTIFACT_ROOT}impl-report-{task_id}.md"


def _validate_repo_relative_artifact_path(path: str, *, field: str) -> None:
    if not isinstance(path, str) or not path:
        raise ArtifactContractError(f"{field} is required")
    if "\\" in path:
        raise ArtifactContractError(f"{field} must use forward slashes")
    if path.startswith("/") or ":" in path:
        raise ArtifactContractError(f"{field} must be a repo-relative path")
    if ".." in path.split("/"):
        raise ArtifactContractError(f"{field} must not contain parent traversal")
    if not path.startswith(_ARTIFACT_ROOT):
        raise ArtifactContractError(f"{field} must be under {_ARTIFACT_ROOT}")


def _taskcard_allowed_paths(card_path: Path) -> list[str]:
    try:
        text = Path(card_path).read_text(encoding="utf-8")
    except OSError as exc:
        raise ArtifactContractError("TaskCard is unreadable") from exc
    match = _POSTFLIGHT_RE.search(text)
    if match is None:
        raise ArtifactContractError("TaskCard has no awf-postflight contract")
    try:
        value = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise ArtifactContractError("TaskCard awf-postflight contract is invalid JSON") from exc
    allowed_paths = value.get("allowed_paths") if isinstance(value, dict) else None
    if not isinstance(allowed_paths, list) or not all(
        isinstance(item, str) for item in allowed_paths
    ):
        raise ArtifactContractError("TaskCard allowed_paths must be an array of strings")
    return allowed_paths


def _validate_taskcard_binding(card_path: Path, required_report_path: str) -> None:
    allowed_paths = _taskcard_allowed_paths(card_path)
    declared_reports = [
        path for path in allowed_paths if Path(path).name.startswith("impl-report-")
    ]
    if required_report_path not in allowed_paths or declared_reports != [required_report_path]:
        raise ArtifactContractError(
            "TaskCard allowed_paths implementation report does not match delivery.report: "
            f"TaskCard={declared_reports!r}, delivery.report={required_report_path!r}"
        )


def compile_stage_artifact_contract(
    *,
    card_path: Path,
    task_id: str,
    requested_report_path: str,
) -> StageArtifactContract:
    """Compile and validate a dispatch-stage artifact contract before side effects."""
    compiled = compile_implementation_report_path(task_id)
    requested = requested_report_path or compiled
    _validate_repo_relative_artifact_path(requested, field="dispatch --report")
    if requested != compiled:
        raise ArtifactContractError(
            "dispatch --report does not match the machine-compiled implementation report path: "
            f"requested={requested!r}, compiled={compiled!r}"
        )
    _validate_taskcard_binding(Path(card_path), compiled)
    return StageArtifactContract(task_id=task_id, implementation_report_path=compiled)


def validate_stage_artifact_contract(
    *,
    card_path: Path,
    task_id: str,
    required_report_path: str,
) -> StageArtifactContract:
    """Validate a received delivery against the same machine-owned stage contract."""
    compiled = compile_implementation_report_path(task_id)
    _validate_repo_relative_artifact_path(required_report_path, field="delivery.report")
    if required_report_path != compiled:
        raise ArtifactContractError(
            "delivery.report does not match the machine-compiled implementation report path: "
            f"delivery.report={required_report_path!r}, compiled={compiled!r}"
        )
    _validate_taskcard_binding(Path(card_path), required_report_path)
    return StageArtifactContract(task_id=task_id, implementation_report_path=compiled)
