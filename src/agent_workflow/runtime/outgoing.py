"""Store-owned outgoing intent and one conservative Stage-blind send boundary."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from .contracts import ContractError, _identifier, _sha256, _strict_text
from .ports import DecisionOutcome, RunDecision
from .transport import ResultEnvelope


class TransportSendState(str, Enum):
    PREPARED = "prepared"
    ATTEMPTING = "attempting"
    AMBIGUOUS = "ambiguous"
    SENT = "sent"


@dataclass(frozen=True, slots=True)
class OutgoingIntent:
    run_spec_sha256: str
    delivery_id: str
    envelope_sha256: str
    envelope_json: str
    route: str
    target_role: str

    def __post_init__(self) -> None:
        _sha256("run_spec_sha256", self.run_spec_sha256)
        _identifier("delivery_id", self.delivery_id)
        _sha256("envelope_sha256", self.envelope_sha256)
        _identifier("route", self.route)
        if self.target_role not in {"coder", "reviewer", "architect"}:
            raise ContractError("outgoing target_role is unsupported")
        if not isinstance(self.envelope_json, str):
            raise ContractError("outgoing envelope_json must be text")
        try:
            raw = self.envelope_json.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ContractError("outgoing envelope_json must be valid UTF-8") from exc
        if not raw or len(raw) > 256 * 1024:
            raise ContractError("outgoing envelope_json is empty or oversized")
        if hashlib.sha256(raw).hexdigest() != self.envelope_sha256:
            raise ContractError("outgoing envelope bytes do not match their SHA-256")
        envelope = ResultEnvelope.decode(raw)
        if (
            envelope.encode() != raw
            or envelope.run_spec_sha256 != self.run_spec_sha256
            or envelope.delivery_id != self.delivery_id
            or envelope.route != self.route
            or envelope.target_role != self.target_role
        ):
            raise ContractError("outgoing intent does not match its canonical result envelope")

    @classmethod
    def from_envelope(cls, envelope: ResultEnvelope) -> OutgoingIntent:
        if not isinstance(envelope, ResultEnvelope):
            raise ContractError("outgoing intent requires a ResultEnvelope")
        raw = envelope.encode()
        return cls(
            envelope.run_spec_sha256,
            envelope.delivery_id,
            hashlib.sha256(raw).hexdigest(),
            raw.decode("utf-8"),
            envelope.route,
            envelope.target_role,
        )

    @property
    def envelope_bytes(self) -> bytes:
        return self.envelope_json.encode("utf-8")

    @property
    def envelope(self) -> ResultEnvelope:
        return ResultEnvelope.decode(self.envelope_bytes)


@dataclass(frozen=True, slots=True)
class TransportSendObservation:
    run_spec_sha256: str
    delivery_id: str
    envelope_sha256: str
    attempt_id: str
    state: TransportSendState
    evidence_sha256: str

    def __post_init__(self) -> None:
        _sha256("run_spec_sha256", self.run_spec_sha256)
        _identifier("delivery_id", self.delivery_id)
        _sha256("envelope_sha256", self.envelope_sha256)
        _identifier("attempt_id", self.attempt_id)
        if not isinstance(self.state, TransportSendState) or self.state not in {
            TransportSendState.ATTEMPTING,
            TransportSendState.AMBIGUOUS,
            TransportSendState.SENT,
        }:
            raise ContractError("transport observation state is not durable")
        _sha256("evidence_sha256", self.evidence_sha256)


@dataclass(frozen=True, slots=True)
class OutgoingStatus:
    run_id: str
    sequence: int
    intent: OutgoingIntent | None
    state: TransportSendState | None
    observation: TransportSendObservation | None
    outcome: DecisionOutcome
    owner: str
    cause: str
    next_action: str

    def __post_init__(self) -> None:
        _identifier("run_id", self.run_id)
        if (
            isinstance(self.sequence, bool)
            or not isinstance(self.sequence, int)
            or self.sequence < 0
        ):
            raise ContractError("outgoing status sequence is invalid")
        if self.intent is not None and not isinstance(self.intent, OutgoingIntent):
            raise ContractError("outgoing status intent is invalid")
        if self.state is not None and not isinstance(self.state, TransportSendState):
            raise ContractError("outgoing status state is invalid")
        if self.observation is not None and not isinstance(
            self.observation, TransportSendObservation
        ):
            raise ContractError("outgoing status observation is invalid")
        if (self.intent is None) != (self.state is None):
            raise ContractError("outgoing status intent and state must be present together")
        if self.state is TransportSendState.PREPARED and self.observation is not None:
            raise ContractError("prepared outgoing status cannot have a send observation")
        if self.state not in {None, TransportSendState.PREPARED} and self.observation is None:
            raise ContractError("observed outgoing status requires an exact observation")
        if self.intent is not None and self.observation is not None and (
            self.observation.delivery_id != self.intent.delivery_id
            or self.observation.envelope_sha256 != self.intent.envelope_sha256
        ):
            raise ContractError("outgoing status observation identity drift")
        if not isinstance(self.outcome, DecisionOutcome):
            raise ContractError("outgoing status outcome is invalid")
        _strict_text("owner", self.owner, maximum=100)
        _strict_text("cause", self.cause, maximum=500)
        _strict_text("next_action", self.next_action, maximum=500)


@dataclass(frozen=True, slots=True)
class TransportSendReceipt:
    success: bool | None
    evidence_sha256: str

    def __post_init__(self) -> None:
        if self.success is not None and not isinstance(self.success, bool):
            raise ContractError("transport send success must be true, false or unknown")
        _sha256("evidence_sha256", self.evidence_sha256)


class TransportSender(Protocol):
    def send(
        self,
        *,
        delivery_id: str,
        target_role: str,
        route: str,
        envelope: bytes,
    ) -> TransportSendReceipt: ...


class _OutgoingStore(Protocol):
    def outgoing_status(self) -> OutgoingStatus: ...

    def record_send_observation(self, fact: TransportSendObservation) -> RunDecision: ...


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class OutgoingIntentDispatcher:
    def __init__(self, store: _OutgoingStore, sender: TransportSender) -> None:
        self.store, self.sender = store, sender

    def dispatch(self) -> RunDecision:
        status = self.store.outgoing_status()
        intent = status.intent
        if intent is None or status.state is None:
            raise ContractError("no exact Store-owned outgoing intent is available")
        if status.state is TransportSendState.SENT:
            return RunDecision(
                DecisionOutcome.SAFE_IDEMPOTENT_REPLAY,
                "runtime",
                "the exact outgoing intent is already recorded sent",
                "none",
                status.sequence,
            )
        if status.state in {TransportSendState.ATTEMPTING, TransportSendState.AMBIGUOUS}:
            return RunDecision(
                DecisionOutcome.AMBIGUOUS_NO_REPLAY,
                "owner",
                "the exact outgoing send attempt is ambiguous",
                "preserve exact transport evidence; do not resend automatically",
                status.sequence,
            )
        attempt_id = "send-" + _digest(intent.delivery_id + "\0" + intent.envelope_sha256)
        attempting = TransportSendObservation(
            intent.run_spec_sha256,
            intent.delivery_id,
            intent.envelope_sha256,
            attempt_id,
            TransportSendState.ATTEMPTING,
            _digest("attempting\0" + attempt_id),
        )
        self.store.record_send_observation(attempting)
        try:
            receipt = self.sender.send(
                delivery_id=intent.delivery_id,
                target_role=intent.target_role,
                route=intent.route,
                envelope=intent.envelope_bytes,
            )
        except Exception as exc:
            evidence = _digest("exception\0" + type(exc).__module__ + "." + type(exc).__qualname__)
            return self.store.record_send_observation(
                TransportSendObservation(
                    intent.run_spec_sha256,
                    intent.delivery_id,
                    intent.envelope_sha256,
                    attempt_id,
                    TransportSendState.AMBIGUOUS,
                    evidence,
                )
            )
        if not isinstance(receipt, TransportSendReceipt):
            receipt = TransportSendReceipt(None, _digest("invalid-transport-receipt"))
        state = (
            TransportSendState.SENT
            if receipt.success is True
            else TransportSendState.AMBIGUOUS
        )
        return self.store.record_send_observation(
            TransportSendObservation(
                intent.run_spec_sha256,
                intent.delivery_id,
                intent.envelope_sha256,
                attempt_id,
                state,
                receipt.evidence_sha256,
            )
        )
