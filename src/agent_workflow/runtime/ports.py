"""Typed effect boundaries for the selected Runtime v2 Core."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from .contracts import (
    ContractError,
    InvocationSpec,
    RenderedInvocation,
    RunSpec,
    _capacity,
    _identifier,
    _nonnegative_integer,
    _sha256,
    _strict_text,
)

if TYPE_CHECKING:
    from .outgoing import OutgoingIntent, OutgoingStatus, TransportSendObservation


def _workspace_manifest(value: str) -> None:
    if not isinstance(value, str) or not value.startswith("sha256:"):
        raise ContractError("workspace_manifest_sha256 must be a prefixed SHA-256")
    _sha256("workspace_manifest_sha256", value.removeprefix("sha256:"))


class WorkflowStage(str, Enum):
    IMPLEMENT = "implement"
    REVIEW = "review"
    REWORK = "rework"
    ARCHITECT = "architect"


class TerminalOutcome(str, Enum):
    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class DecisionOutcome(str, Enum):
    SAFE_CONTINUE = "SAFE_CONTINUE"
    SAFE_IDEMPOTENT_REPLAY = "SAFE_IDEMPOTENT_REPLAY"
    SAFE_STABLE_RESEND = "SAFE_STABLE_RESEND"
    DENY_BEFORE_PROVIDER = "DENY_BEFORE_PROVIDER"
    AMBIGUOUS_NO_REPLAY = "AMBIGUOUS_NO_REPLAY"
    DENY_BEFORE_MUTATION = "DENY_BEFORE_MUTATION"
    HANDLER_FAILURE_NO_ACK = "HANDLER_FAILURE_NO_ACK"
    TERMINAL_IDEMPOTENT = "TERMINAL_IDEMPOTENT"
    TERMINAL_CONFLICT = "TERMINAL_CONFLICT"
    OWNER_DECISION_REQUIRED = "OWNER_DECISION_REQUIRED"
    EXTERNAL_OBSERVATION_UNKNOWN = "EXTERNAL_OBSERVATION_UNKNOWN"


@dataclass(frozen=True, slots=True)
class AuthorizationCommand:
    run_spec_sha256: str
    invocation_id: str
    authorization_sha256: str
    stage: WorkflowStage
    role: str
    attempt: int
    delivery_id: str
    payload_sha256: str

    def __post_init__(self) -> None:
        _sha256("run_spec_sha256", self.run_spec_sha256)
        _identifier("invocation_id", self.invocation_id)
        _sha256("authorization_sha256", self.authorization_sha256)
        if not isinstance(self.stage, WorkflowStage):
            raise ContractError("stage must be a WorkflowStage")
        if self.role not in {"architect", "coder", "reviewer"}:
            raise ContractError("role is unsupported")
        _capacity("attempt", self.attempt, minimum=1)
        _identifier("delivery_id", self.delivery_id)
        _sha256("payload_sha256", self.payload_sha256)


@dataclass(frozen=True, slots=True)
class HandoffCommand:
    run_spec_sha256: str
    source_invocation_id: str
    source_authorization_sha256: str
    delivery_id: str
    payload_sha256: str
    route: str
    target_role: str

    def __post_init__(self) -> None:
        _sha256("run_spec_sha256", self.run_spec_sha256)
        _identifier("source_invocation_id", self.source_invocation_id)
        _sha256("source_authorization_sha256", self.source_authorization_sha256)
        _identifier("delivery_id", self.delivery_id)
        _sha256("payload_sha256", self.payload_sha256)
        _identifier("route", self.route)
        if self.target_role not in {"coder", "reviewer", "architect"}:
            raise ContractError("target_role is unsupported")


@dataclass(frozen=True, slots=True)
class TerminalCommand:
    run_spec_sha256: str
    source_invocation_id: str
    source_authorization_sha256: str
    delivery_id: str
    payload_sha256: str
    outcome: TerminalOutcome
    evidence_sha256: str

    def __post_init__(self) -> None:
        _sha256("run_spec_sha256", self.run_spec_sha256)
        _identifier("source_invocation_id", self.source_invocation_id)
        _sha256("source_authorization_sha256", self.source_authorization_sha256)
        _identifier("delivery_id", self.delivery_id)
        _sha256("payload_sha256", self.payload_sha256)
        if not isinstance(self.outcome, TerminalOutcome):
            raise ContractError("outcome must be a TerminalOutcome")
        _sha256("evidence_sha256", self.evidence_sha256)


@dataclass(frozen=True, slots=True)
class StopCommand:
    run_spec_sha256: str
    run_id: str
    expected_sequence: int

    def __post_init__(self) -> None:
        _sha256("run_spec_sha256", self.run_spec_sha256)
        _identifier("run_id", self.run_id)
        _nonnegative_integer("expected_sequence", self.expected_sequence)


@dataclass(frozen=True, slots=True)
class RunDecision:
    outcome: DecisionOutcome
    owner: str
    cause: str
    next_action: str
    sequence: int

    def __post_init__(self) -> None:
        if not isinstance(self.outcome, DecisionOutcome):
            raise ContractError("outcome must be a DecisionOutcome")
        _strict_text("owner", self.owner, maximum=100)
        _strict_text("cause", self.cause, maximum=500)
        _strict_text("next_action", self.next_action, maximum=500)
        _nonnegative_integer("sequence", self.sequence)


@dataclass(frozen=True, slots=True)
class RunSnapshot:
    run_id: str
    run_spec_sha256: str
    sequence: int
    stage: WorkflowStage | None
    terminal: TerminalOutcome | None
    stopped: bool
    outcome: DecisionOutcome
    first_blocker: str | None
    owner: str
    cause: str
    next_action: str

    def __post_init__(self) -> None:
        _identifier("run_id", self.run_id)
        _sha256("run_spec_sha256", self.run_spec_sha256)
        _nonnegative_integer("sequence", self.sequence)
        if self.stage is not None and not isinstance(self.stage, WorkflowStage):
            raise ContractError("stage must be a WorkflowStage or None")
        if self.terminal is not None and not isinstance(self.terminal, TerminalOutcome):
            raise ContractError("terminal must be a TerminalOutcome or None")
        if not isinstance(self.stopped, bool):
            raise ContractError("stopped must be a boolean")
        if not isinstance(self.outcome, DecisionOutcome):
            raise ContractError("outcome must be a DecisionOutcome")
        if self.first_blocker is not None:
            _strict_text("first_blocker", self.first_blocker, maximum=500)
        _strict_text("owner", self.owner, maximum=100)
        _strict_text("cause", self.cause, maximum=500)
        _strict_text("next_action", self.next_action, maximum=500)


@dataclass(frozen=True, slots=True)
class JournalAuthorization:
    run_spec_sha256: str
    invocation_id: str
    authorization_sha256: str
    invocation_spec_sha256: str
    workspace_manifest_sha256: str = "sha256:" + "0" * 64

    def __post_init__(self) -> None:
        _sha256("run_spec_sha256", self.run_spec_sha256)
        _identifier("invocation_id", self.invocation_id)
        _sha256("authorization_sha256", self.authorization_sha256)
        _sha256("invocation_spec_sha256", self.invocation_spec_sha256)
        _workspace_manifest(self.workspace_manifest_sha256)


@dataclass(frozen=True, slots=True)
class LaunchIntent:
    authorization_sha256: str
    rendered_invocation_sha256: str

    def __post_init__(self) -> None:
        _sha256("authorization_sha256", self.authorization_sha256)
        _sha256("rendered_invocation_sha256", self.rendered_invocation_sha256)


@dataclass(frozen=True, slots=True)
class ProcessObservation:
    authorization_sha256: str
    process_identity_sha256: str

    def __post_init__(self) -> None:
        _sha256("authorization_sha256", self.authorization_sha256)
        _sha256("process_identity_sha256", self.process_identity_sha256)


@dataclass(frozen=True, slots=True)
class ProviderResult:
    authorization_sha256: str
    process_identity_sha256: str
    return_code: int
    result_sha256: str
    workspace_manifest_sha256: str = "sha256:" + "0" * 64

    def __post_init__(self) -> None:
        _sha256("authorization_sha256", self.authorization_sha256)
        _sha256("process_identity_sha256", self.process_identity_sha256)
        if isinstance(self.return_code, bool) or not isinstance(self.return_code, int):
            raise ContractError("return_code must be an integer")
        _sha256("result_sha256", self.result_sha256)
        _workspace_manifest(self.workspace_manifest_sha256)


@dataclass(frozen=True, slots=True)
class ValidationEffect:
    authorization_sha256: str
    result_sha256: str
    artifact_sha256: str
    effect_sha256: str

    def __post_init__(self) -> None:
        _sha256("authorization_sha256", self.authorization_sha256)
        _sha256("result_sha256", self.result_sha256)
        _sha256("artifact_sha256", self.artifact_sha256)
        _sha256("effect_sha256", self.effect_sha256)


@dataclass(frozen=True, slots=True)
class JournalSnapshot:
    run_spec_sha256: str
    invocation_id: str
    authorization_sha256: str
    invocation_spec_sha256: str
    workspace_manifest_sha256: str
    launch_intent: LaunchIntent | None
    process_observation: ProcessObservation | None
    result: ProviderResult | None
    validation_effect: ValidationEffect | None

    def __post_init__(self) -> None:
        _sha256("run_spec_sha256", self.run_spec_sha256)
        _identifier("invocation_id", self.invocation_id)
        _sha256("authorization_sha256", self.authorization_sha256)
        _sha256("invocation_spec_sha256", self.invocation_spec_sha256)
        _workspace_manifest(self.workspace_manifest_sha256)
        for name, value, expected in (
            ("launch_intent", self.launch_intent, LaunchIntent),
            ("process_observation", self.process_observation, ProcessObservation),
            ("result", self.result, ProviderResult),
            ("validation_effect", self.validation_effect, ValidationEffect),
        ):
            if value is not None and not isinstance(value, expected):
                raise ContractError(f"{name} has an invalid fact type")


@runtime_checkable
class RunStore(Protocol):
    def initialize(self, run_spec: RunSpec) -> RunSnapshot: ...

    def authorize(
        self, command: AuthorizationCommand, fact: JournalAuthorization
    ) -> RunDecision: ...

    def record_handoff(
        self, command: HandoffCommand, effect: ValidationEffect, intent: OutgoingIntent
    ) -> RunDecision: ...

    def record_terminal(
        self, command: TerminalCommand, effect: ValidationEffect, intent: OutgoingIntent
    ) -> RunDecision: ...

    def record_stop(self, command: StopCommand) -> RunDecision: ...

    def pending_handoff(self) -> HandoffCommand | None: ...

    def pending_outgoing(self) -> OutgoingIntent | None: ...

    def outgoing_status(self) -> OutgoingStatus: ...

    def record_send_observation(self, fact: TransportSendObservation) -> RunDecision: ...

    def journal(self, invocation_id: str) -> InvocationJournal: ...


@runtime_checkable
class InvocationJournal(Protocol):
    def record_launch_intent(self, fact: LaunchIntent) -> JournalSnapshot: ...

    def record_process_observation(self, fact: ProcessObservation) -> JournalSnapshot: ...

    def record_result(self, fact: ProviderResult) -> JournalSnapshot: ...

    def snapshot(self) -> JournalSnapshot: ...


@runtime_checkable
class StatusReader(Protocol):
    def snapshot(self, run_id: str) -> RunSnapshot: ...

    def outgoing(self, run_id: str) -> OutgoingStatus: ...


@runtime_checkable
class ProviderRenderer(Protocol):
    def render(self, spec: InvocationSpec) -> RenderedInvocation: ...
