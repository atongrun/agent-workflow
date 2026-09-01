"""Strict VNext workflow identities and typed provider Results."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Any, Callable

_SHA_RE = re.compile(r"[0-9a-f]{40,64}")
_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_ROLES = {"architect", "coder", "reviewer"}


class ContractError(ValueError):
    """A correctness-critical typed boundary is invalid."""


class Stage(StrEnum):
    AUTHOR = "AUTHOR"
    IMPLEMENT = "IMPLEMENT"
    REVIEW = "REVIEW"
    DECIDE = "DECIDE"
    MERGE = "MERGE"


class RunStatus(StrEnum):
    ACTIVE = "ACTIVE"
    WAITING = "WAITING"
    TERMINAL = "TERMINAL"


class WaitingReason(StrEnum):
    PROVIDER = "PROVIDER"
    SSH = "SSH"
    EXTERNAL_READ = "EXTERNAL_READ"
    HUMAN = "HUMAN"
    EFFECT_RECONCILIATION = "EFFECT_RECONCILIATION"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"


class TerminalOutcome(StrEnum):
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"
    STOPPED = "STOPPED"


def canonical_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def sha256(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _text(value: object, field: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()) or "\x00" in value:
        raise ContractError(f"{field} is invalid")
    return value


def _keys(value: dict[str, Any], required: set[str], field: str) -> None:
    if set(value) != required:
        raise ContractError(f"{field} fields are invalid")


def _object(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ContractError(f"{field} is not an object")
    return value


def _pairs_without_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ContractError("typed Result contains a duplicate field")
        value[key] = item
    return value


def one_json_object(raw: bytes) -> dict[str, Any]:
    """Decode exactly one UTF-8 JSON object, never a candidate embedded in prose."""
    if not isinstance(raw, bytes) or not raw or len(raw) > 1024 * 1024:
        raise ContractError("typed Result bytes are invalid")
    try:
        text = raw.decode("utf-8")
        value = json.loads(text, object_pairs_hook=_pairs_without_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError("typed Result is not exactly one JSON value") from exc
    return _object(value, "typed Result")


@dataclass(frozen=True, slots=True)
class RoleBinding:
    role: str
    provider: str
    target: str

    def __post_init__(self) -> None:
        if self.role not in _ROLES:
            raise ContractError("Role binding role is invalid")
        for field, value in (("provider", self.provider), ("target", self.target)):
            if not isinstance(value, str) or not _ID_RE.fullmatch(value):
                raise ContractError(f"Role binding {field} is invalid")


@dataclass(frozen=True, slots=True)
class TaskProposal:
    brief: str
    change_paths: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]
    verification_argv: tuple[tuple[str, ...], ...]

    def __post_init__(self) -> None:
        _text(self.brief, "TaskProposal brief")
        if not self.change_paths or len(set(self.change_paths)) != len(self.change_paths):
            raise ContractError("TaskProposal change_paths are invalid")
        for raw in self.change_paths:
            path = PurePosixPath(_text(raw, "TaskProposal change path"))
            if path.is_absolute() or ".." in path.parts or path.as_posix() in {"", "."}:
                raise ContractError("TaskProposal change path escapes the repository")
        if not self.acceptance_criteria:
            raise ContractError("TaskProposal acceptance_criteria are empty")
        for criterion in self.acceptance_criteria:
            _text(criterion, "TaskProposal acceptance criterion")
        if not self.verification_argv:
            raise ContractError("TaskProposal verification_argv are empty")
        for argv in self.verification_argv:
            if not argv:
                raise ContractError("TaskProposal verification argv is empty")
            for token in argv:
                _text(token, "TaskProposal verification argv token")

    @classmethod
    def from_dict(cls, value: object) -> TaskProposal:
        item = _object(value, "TaskProposal")
        _keys(
            item,
            {"brief", "change_paths", "acceptance_criteria", "verification_argv"},
            "TaskProposal",
        )
        for field in ("change_paths", "acceptance_criteria", "verification_argv"):
            if not isinstance(item[field], list):
                raise ContractError(f"TaskProposal {field} is invalid")
        argv = item["verification_argv"]
        if not all(isinstance(command, list) for command in argv):
            raise ContractError("TaskProposal verification_argv are invalid")
        return cls(
            brief=item["brief"],
            change_paths=tuple(item["change_paths"]),
            acceptance_criteria=tuple(item["acceptance_criteria"]),
            verification_argv=tuple(tuple(command) for command in argv),
        )


@dataclass(frozen=True, slots=True)
class TaskSpec:
    task_id: str
    ordinal: int
    repository: str
    base_ref: str
    base_sha: str
    task_ref: str
    proposal: TaskProposal
    roles: tuple[RoleBinding, ...]

    def __post_init__(self) -> None:
        if not _ID_RE.fullmatch(self.task_id) or self.ordinal < 1:
            raise ContractError("Task authority identity is invalid")
        _text(self.repository, "Task repository")
        _text(self.base_ref, "Task base ref")
        _text(self.task_ref, "Task ref")
        if not _SHA_RE.fullmatch(self.base_sha):
            raise ContractError("Task base SHA is invalid")
        if len(self.roles) != 3 or {binding.role for binding in self.roles} != _ROLES:
            raise ContractError("Task Role bindings must contain exactly the three peer Roles")

    @property
    def identity_sha256(self) -> str:
        return sha256(asdict(self))


@dataclass(frozen=True, slots=True)
class AuthorResult:
    status: str
    task: TaskProposal | None = None
    summary: str = ""
    reason: str = ""

    @classmethod
    def from_dict(cls, value: object) -> AuthorResult:
        item = _object(value, "AuthorResult")
        status = item.get("status")
        fields = {
            "next_task": {"status", "task"},
            "complete": {"status", "summary"},
            "blocked": {"status", "reason"},
        }
        if status not in fields:
            raise ContractError("AuthorResult status is invalid")
        _keys(item, fields[status], "AuthorResult")
        if status == "next_task":
            return cls(status=status, task=TaskProposal.from_dict(item["task"]))
        if status == "complete":
            return cls(status=status, summary=_text(item["summary"], "AuthorResult summary"))
        return cls(status=status, reason=_text(item["reason"], "AuthorResult reason"))


@dataclass(frozen=True, slots=True)
class ImplementationResult:
    status: str
    summary: str
    diagnostics: str

    @classmethod
    def from_dict(cls, value: object) -> ImplementationResult:
        item = _object(value, "ImplementationResult")
        _keys(item, {"status", "summary", "diagnostics"}, "ImplementationResult")
        if item["status"] not in {"completed", "blocked"}:
            raise ContractError("ImplementationResult status is invalid")
        return cls(
            status=item["status"],
            summary=_text(item["summary"], "ImplementationResult summary"),
            diagnostics=_text(
                item["diagnostics"], "ImplementationResult diagnostics", allow_empty=True
            ),
        )


@dataclass(frozen=True, slots=True)
class ReviewFinding:
    required_correction: str
    evidence: str = ""

    @classmethod
    def from_dict(cls, value: object) -> ReviewFinding:
        item = _object(value, "Review finding")
        if set(item) not in ({"required_correction"}, {"required_correction", "evidence"}):
            raise ContractError("Review finding fields are invalid")
        return cls(
            required_correction=_text(
                item["required_correction"], "Review finding required_correction"
            ),
            evidence=_text(item.get("evidence", ""), "Review finding evidence", allow_empty=True),
        )


@dataclass(frozen=True, slots=True)
class ReviewResult:
    verdict: str
    findings: tuple[ReviewFinding, ...]
    blocked_reason: str
    rationale: str

    @classmethod
    def from_dict(cls, value: object) -> ReviewResult:
        item = _object(value, "ReviewResult")
        _keys(
            item,
            {"verdict", "findings", "blocked_reason", "rationale"},
            "ReviewResult",
        )
        verdict = item["verdict"]
        if verdict not in {"approve", "request_changes", "blocked"}:
            raise ContractError("ReviewResult verdict is invalid")
        if not isinstance(item["findings"], list):
            raise ContractError("ReviewResult findings are invalid")
        findings = tuple(ReviewFinding.from_dict(value) for value in item["findings"])
        blocked_reason = _text(
            item["blocked_reason"], "ReviewResult blocked_reason", allow_empty=True
        )
        rationale = _text(item["rationale"], "ReviewResult rationale", allow_empty=True)
        if verdict == "request_changes" and not findings:
            raise ContractError("request_changes requires at least one finding")
        if verdict != "request_changes" and findings:
            raise ContractError("only request_changes may contain findings")
        if verdict == "blocked" and not blocked_reason:
            raise ContractError("blocked ReviewResult requires blocked_reason")
        if verdict != "blocked" and blocked_reason:
            raise ContractError("non-blocked ReviewResult has blocked_reason")
        return cls(verdict, findings, blocked_reason, rationale)


@dataclass(frozen=True, slots=True)
class ArchitectDecision:
    verdict: str
    rationale: str

    @classmethod
    def from_dict(cls, value: object) -> ArchitectDecision:
        item = _object(value, "ArchitectDecision")
        _keys(item, {"verdict", "rationale"}, "ArchitectDecision")
        if item["verdict"] not in {"approve", "request_changes", "reject", "escalate"}:
            raise ContractError("ArchitectDecision verdict is invalid")
        return cls(item["verdict"], _text(item["rationale"], "ArchitectDecision rationale"))


TypedResult = AuthorResult | ImplementationResult | ReviewResult | ArchitectDecision


_PARSERS: dict[str, Callable[[object], TypedResult]] = {
    "author": AuthorResult.from_dict,
    "implement": ImplementationResult.from_dict,
    "review": ReviewResult.from_dict,
    "decide": ArchitectDecision.from_dict,
}


def parse_typed_result(kind: str, raw: bytes) -> TypedResult:
    try:
        parser = _PARSERS[kind]
    except KeyError as exc:
        raise ContractError("typed Result kind is invalid") from exc
    return parser(one_json_object(raw))


@dataclass(frozen=True, slots=True)
class PendingOperation:
    operation_id: str
    input_sha256: str
    expected_sequence: int
    stage: Stage
    attempt: int

    @classmethod
    def derive(
        cls, *, run_id: str, sequence: int, stage: Stage, attempt: int, input_value: object
    ) -> PendingOperation:
        if not _ID_RE.fullmatch(run_id) or sequence < 0 or attempt < 1:
            raise ContractError("pending operation identity is invalid")
        input_digest = sha256(input_value)
        operation_id = sha256(
            {
                "run_id": run_id,
                "sequence": sequence,
                "stage": stage.value,
                "attempt": attempt,
                "input_sha256": input_digest,
            }
        )
        return cls(operation_id, input_digest, sequence, stage, attempt)
