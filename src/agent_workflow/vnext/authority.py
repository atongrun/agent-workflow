"""Single-writer VNext RunAuthority and pure serial Result acceptance."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from .contracts import (
    ArchitectDecision,
    AuthorResult,
    ImplementationResult,
    PendingOperation,
    ReviewResult,
    RoleBinding,
    RunStatus,
    Stage,
    TaskSpec,
    TerminalOutcome,
    TypedResult,
    WaitingReason,
    sha256,
)


class AuthorityError(RuntimeError):
    """A caller attempted an unauthorized Run transition."""


class AcceptanceKind(StrEnum):
    ACCEPTED = "ACCEPTED"
    IDEMPOTENT = "IDEMPOTENT"
    LATE = "LATE"
    CONFLICT = "CONFLICT"


@dataclass(frozen=True, slots=True)
class Acceptance:
    kind: AcceptanceKind
    authority: RunAuthority


@dataclass(frozen=True, slots=True)
class RunAuthority:
    run_id: str
    writer_id: str
    plan_sha256: str
    repository: str
    base_ref: str
    base_sha: str
    roles: tuple[RoleBinding, ...]
    sequence: int = 0
    status: RunStatus = RunStatus.ACTIVE
    stage: Stage = Stage.AUTHOR
    task_ordinal: int = 0
    current_task: TaskSpec | None = None
    pending_operation: PendingOperation | None = None
    attempts: tuple[tuple[str, int], ...] = ()
    rework_count: int = 0
    last_error: str = ""
    waiting_reason: WaitingReason | None = None
    terminal: TerminalOutcome | None = None
    last_operation_id: str = ""
    last_result_sha256: str = ""

    def __post_init__(self) -> None:
        if self.sequence < 0 or self.task_ordinal < 0 or self.rework_count < 0:
            raise AuthorityError("RunAuthority counters are invalid")
        if len(self.roles) != 3 or {binding.role for binding in self.roles} != {
            "architect",
            "coder",
            "reviewer",
        }:
            raise AuthorityError("RunAuthority requires exactly the three peer Role bindings")
        expected = {
            "architect": ("pi", "local"),
            "coder": ("opencode", "windows-coder"),
            "reviewer": ("codex", "local"),
        }
        if any(
            (binding.provider, binding.target) != expected[binding.role] for binding in self.roles
        ):
            raise AuthorityError("RunAuthority supports only the frozen initial topology")
        if self.status == RunStatus.ACTIVE and (self.waiting_reason or self.terminal):
            raise AuthorityError("active Run has waiting or terminal state")
        if self.status == RunStatus.WAITING and (not self.waiting_reason or self.terminal):
            raise AuthorityError("waiting Run state is invalid")
        if self.status == RunStatus.TERMINAL and (not self.terminal or self.waiting_reason):
            raise AuthorityError("terminal Run state is invalid")
        if self.pending_operation and self.pending_operation.expected_sequence != self.sequence:
            raise AuthorityError("pending operation sequence does not match RunAuthority")

    def begin(self, *, writer_id: str, input_value: object) -> RunAuthority:
        self._require_writer(writer_id)
        if self.status != RunStatus.ACTIVE or self.pending_operation is not None:
            raise AuthorityError("Run cannot begin another operation")
        attempts = dict(self.attempts)
        key = f"{self.sequence}:{self.stage.value}"
        attempt = attempts.get(key, 0) + 1
        attempts[key] = attempt
        pending = PendingOperation.derive(
            run_id=self.run_id,
            sequence=self.sequence,
            stage=self.stage,
            attempt=attempt,
            input_value=input_value,
        )
        return replace(self, pending_operation=pending, attempts=tuple(sorted(attempts.items())))

    def fail_attempt(self, *, writer_id: str, error: str) -> RunAuthority:
        """Record one compute/validation failure without changing Run, Task or Stage."""
        self._require_writer(writer_id)
        if self.pending_operation is None:
            raise AuthorityError("Run has no pending operation to fail")
        budget = 3 if self.stage == Stage.IMPLEMENT else 2
        if self.pending_operation.attempt >= budget:
            return replace(
                self,
                status=RunStatus.WAITING,
                waiting_reason=WaitingReason.BUDGET_EXHAUSTED,
                last_error=error,
                pending_operation=None,
            )
        return replace(self, last_error=error, pending_operation=None)

    def accept(
        self,
        *,
        writer_id: str,
        operation_id: str,
        input_sha256: str,
        result: TypedResult,
    ) -> Acceptance:
        self._require_writer(writer_id)
        result_digest = sha256(result_to_dict(result))
        if operation_id == self.last_operation_id:
            if result_digest == self.last_result_sha256:
                return Acceptance(AcceptanceKind.IDEMPOTENT, self)
            waiting = replace(
                self,
                status=RunStatus.WAITING,
                waiting_reason=WaitingReason.HUMAN,
                terminal=None,
                last_error="conflicting Result for accepted operation",
            )
            return Acceptance(AcceptanceKind.CONFLICT, waiting)
        pending = self.pending_operation
        if pending is None or operation_id != pending.operation_id:
            return Acceptance(AcceptanceKind.LATE, self)
        if input_sha256 != pending.input_sha256 or pending.expected_sequence != self.sequence:
            waiting = replace(
                self,
                status=RunStatus.WAITING,
                waiting_reason=WaitingReason.HUMAN,
                last_error="Result conflicts with pending operation identity",
            )
            return Acceptance(AcceptanceKind.CONFLICT, waiting)
        next_authority = self._reduce(result)
        next_authority = replace(
            next_authority,
            sequence=self.sequence + 1,
            pending_operation=None,
            last_operation_id=operation_id,
            last_result_sha256=result_digest,
        )
        return Acceptance(AcceptanceKind.ACCEPTED, next_authority)

    def wait(self, *, writer_id: str, reason: WaitingReason, error: str) -> RunAuthority:
        self._require_writer(writer_id)
        return replace(
            self,
            status=RunStatus.WAITING,
            waiting_reason=reason,
            last_error=error,
            pending_operation=None,
        )

    def resume(self, *, writer_id: str) -> RunAuthority:
        self._require_writer(writer_id)
        if self.status != RunStatus.WAITING:
            raise AuthorityError("only a waiting Run can resume")
        return replace(
            self,
            status=RunStatus.ACTIVE,
            waiting_reason=None,
            last_error="",
        )

    def stop(self, *, writer_id: str) -> RunAuthority:
        self._require_writer(writer_id)
        return replace(
            self,
            status=RunStatus.TERMINAL,
            terminal=TerminalOutcome.STOPPED,
            waiting_reason=None,
            pending_operation=None,
        )

    def observe_merge(
        self, *, writer_id: str, task_head_sha: str, fresh_base_sha: str
    ) -> RunAuthority:
        """Accept an exact merged Task head and fresh base observation."""
        self._require_writer(writer_id)
        if self.status != RunStatus.ACTIVE or self.stage != Stage.MERGE:
            raise AuthorityError("Run is not awaiting merge")
        if self.current_task is None or not task_head_sha or not fresh_base_sha:
            raise AuthorityError("merge provenance is incomplete")
        return replace(
            self,
            sequence=self.sequence + 1,
            stage=Stage.AUTHOR,
            base_sha=fresh_base_sha,
            current_task=None,
            pending_operation=None,
            attempts=(),
            rework_count=0,
            last_error="",
            last_operation_id=f"merge:{task_head_sha}",
            last_result_sha256=sha256(
                {"task_head_sha": task_head_sha, "fresh_base_sha": fresh_base_sha}
            ),
        )

    def _require_writer(self, writer_id: str) -> None:
        if writer_id != self.writer_id:
            raise AuthorityError("RunAuthority writer identity mismatch")

    def _reduce(self, result: TypedResult) -> RunAuthority:
        if self.stage == Stage.AUTHOR and isinstance(result, AuthorResult):
            if result.status == "next_task":
                if result.task is None:
                    raise AuthorityError("Author next_task has no TaskProposal")
                ordinal = self.task_ordinal + 1
                task = TaskSpec(
                    task_id=f"{self.run_id}-task-{ordinal:02d}",
                    ordinal=ordinal,
                    repository=self.repository,
                    base_ref=self.base_ref,
                    base_sha=self.base_sha,
                    task_ref=f"awf/{self.run_id}-task-{ordinal:02d}",
                    proposal=result.task,
                    roles=self.roles,
                )
                return replace(
                    self,
                    stage=Stage.IMPLEMENT,
                    task_ordinal=ordinal,
                    current_task=task,
                    rework_count=0,
                )
            if result.status == "complete":
                return replace(
                    self,
                    status=RunStatus.TERMINAL,
                    terminal=TerminalOutcome.COMPLETED,
                    last_error="",
                )
            return self._human_wait(result.reason)
        if self.stage == Stage.IMPLEMENT and isinstance(result, ImplementationResult):
            return (
                replace(self, stage=Stage.REVIEW)
                if result.status == "completed"
                else self._human_wait(result.summary)
            )
        if self.stage == Stage.REVIEW and isinstance(result, ReviewResult):
            if result.verdict == "approve":
                return replace(self, stage=Stage.DECIDE)
            if result.verdict == "request_changes":
                return replace(self, stage=Stage.IMPLEMENT, rework_count=self.rework_count + 1)
            return self._human_wait(result.blocked_reason)
        if self.stage == Stage.DECIDE and isinstance(result, ArchitectDecision):
            if result.verdict == "approve":
                return replace(self, stage=Stage.MERGE)
            if result.verdict == "request_changes":
                return replace(self, stage=Stage.IMPLEMENT, rework_count=self.rework_count + 1)
            return self._human_wait(result.rationale)
        raise AuthorityError("typed Result does not match the current Stage")

    def _human_wait(self, error: str) -> RunAuthority:
        return replace(
            self,
            status=RunStatus.WAITING,
            waiting_reason=WaitingReason.HUMAN,
            last_error=error,
        )


def result_to_dict(result: TypedResult) -> dict[str, object]:
    if isinstance(result, AuthorResult):
        if result.status == "next_task":
            assert result.task is not None
            return {
                "status": result.status,
                "task": {
                    "brief": result.task.brief,
                    "change_paths": list(result.task.change_paths),
                    "acceptance_criteria": list(result.task.acceptance_criteria),
                    "verification_argv": [list(argv) for argv in result.task.verification_argv],
                },
            }
        key = "summary" if result.status == "complete" else "reason"
        return {"status": result.status, key: getattr(result, key)}
    if isinstance(result, ImplementationResult):
        return {
            "status": result.status,
            "summary": result.summary,
            "diagnostics": result.diagnostics,
        }
    if isinstance(result, ReviewResult):
        return {
            "verdict": result.verdict,
            "findings": [
                {
                    "required_correction": finding.required_correction,
                    **({"evidence": finding.evidence} if finding.evidence else {}),
                }
                for finding in result.findings
            ],
            "blocked_reason": result.blocked_reason,
            "rationale": result.rationale,
        }
    return {"verdict": result.verdict, "rationale": result.rationale}
