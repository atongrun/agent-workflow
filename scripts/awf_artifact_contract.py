"""Owner-bound implementation artifact contract for production Workflow stages."""

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


@dataclass(frozen=True)
class RunArtifactContract:
    """The complete immutable TaskCard/report binding checked by plan lint."""

    task_id: str
    taskcard_path: str
    allowed_paths: tuple[str, ...]
    implementation_report_path: str
    review_report_path: str


def compile_implementation_report_path(task_id: str) -> str:
    """Compile the only valid ImplementationReport path for a task stage."""
    if not isinstance(task_id, str) or not _TASK_ID_RE.fullmatch(task_id):
        raise ArtifactContractError("task_id cannot compile a safe implementation report path")
    return f"{_ARTIFACT_ROOT}impl-report-{task_id}.md"


def compile_review_report_path(task_id: str) -> str:
    """Compile the only valid ReviewReport path for a task run."""
    if not isinstance(task_id, str) or not _TASK_ID_RE.fullmatch(task_id):
        raise ArtifactContractError("task_id cannot compile a safe review report path")
    return f"{_ARTIFACT_ROOT}review-report-{task_id}.md"


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


def _validate_allowed_path(path: str) -> None:
    if not path or "\\" in path or path.startswith("/") or ":" in path:
        raise ArtifactContractError("TaskCard allowed_paths must be repo-relative paths")
    if ".." in path.split("/"):
        raise ArtifactContractError("TaskCard allowed_paths must not contain parent traversal")


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
    """Compile or accept the owner-bound report path before dispatch side effects."""
    compiled = compile_implementation_report_path(task_id)
    requested = requested_report_path or compiled
    _validate_repo_relative_artifact_path(requested, field="dispatch --report")
    _validate_taskcard_binding(Path(card_path), requested)
    return StageArtifactContract(task_id=task_id, implementation_report_path=requested)


def validate_stage_artifact_contract(
    *,
    card_path: Path,
    task_id: str,
    required_report_path: str,
) -> StageArtifactContract:
    """Validate a received delivery against the same owner/Card-bound stage contract."""
    compile_implementation_report_path(task_id)
    _validate_repo_relative_artifact_path(required_report_path, field="delivery.report")
    _validate_taskcard_binding(Path(card_path), required_report_path)
    return StageArtifactContract(task_id=task_id, implementation_report_path=required_report_path)


def compile_run_artifact_contract(
    *,
    repo: Path,
    card_path: Path,
    task_id: str,
    implementation_report_path: str,
    review_report_path: str,
) -> RunArtifactContract:
    """Lint the complete frozen TaskCard/report contract without mutating the repository."""
    repo = Path(repo).resolve()
    card_path = Path(card_path).resolve()
    try:
        taskcard_path = card_path.relative_to(repo).as_posix()
    except ValueError as exc:
        raise ArtifactContractError("TaskCard must be inside the target repository") from exc
    _validate_allowed_path(taskcard_path)
    allowed_paths = _taskcard_allowed_paths(card_path)
    if not allowed_paths or len(allowed_paths) != len(set(allowed_paths)):
        raise ArtifactContractError("TaskCard allowed_paths must be non-empty and unique")
    for path in allowed_paths:
        _validate_allowed_path(path)
    if taskcard_path in allowed_paths:
        raise ArtifactContractError("frozen TaskCard must not be model-writable in allowed_paths")

    expected_implementation = compile_implementation_report_path(task_id)
    expected_review = compile_review_report_path(task_id)
    _validate_repo_relative_artifact_path(
        implementation_report_path, field="RunManifest ImplementationReport"
    )
    _validate_repo_relative_artifact_path(review_report_path, field="RunManifest ReviewReport")
    if implementation_report_path != expected_implementation:
        raise ArtifactContractError(
            "RunManifest ImplementationReport does not match compiled task identity"
        )
    if review_report_path != expected_review:
        raise ArtifactContractError(
            "RunManifest ReviewReport does not match compiled task identity"
        )
    declared_implementation = [
        path for path in allowed_paths if Path(path).name.startswith("impl-report-")
    ]
    declared_review = [
        path for path in allowed_paths if Path(path).name.startswith("review-report-")
    ]
    if declared_implementation != [implementation_report_path]:
        raise ArtifactContractError(
            "TaskCard allowed_paths ImplementationReport binding does not match RunManifest"
        )
    if declared_review != [review_report_path]:
        raise ArtifactContractError(
            "TaskCard allowed_paths ReviewReport binding does not match RunManifest"
        )
    return RunArtifactContract(
        task_id=task_id,
        taskcard_path=taskcard_path,
        allowed_paths=tuple(allowed_paths),
        implementation_report_path=implementation_report_path,
        review_report_path=review_report_path,
    )
