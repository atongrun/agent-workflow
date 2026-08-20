from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from .contracts import ContractError, RunSpec, _identifier, _sha256
from .ports import (
    DecisionOutcome,
    HandoffCommand,
    RunSnapshot,
    TerminalCommand,
    WorkflowStage,
)

ENVELOPE_FORMAT = "awf.runtime-v2.command-result-envelope.v1"
_MAX_ENVELOPE_BYTES = 256 * 1024
_MAX_JSON_DEPTH = 32
_MAX_JSON_NODES = 8192
_DELIVERY_RE = re.compile(r"awfv2:[0-9a-f]{64}")
_ROLE_PAIRS = frozenset(
    {
        ("architect", "coder"),
        ("coder", "reviewer"),
        ("reviewer", "coder"),
        ("reviewer", "architect"),
    }
)
_COMMON_KEYS = frozenset(
    {
        "format",
        "kind",
        "delivery_id",
        "run_id",
        "task_id",
        "run_spec_sha256",
        "source_role",
        "target_role",
        "route",
        "source_invocation_id",
        "source_authorization_sha256",
        "target_invocation_id",
        "payload_sha256",
        "payload",
    }
)
_RESULT_KEYS = _COMMON_KEYS | {"causation_delivery_id"}


class TransportError(ContractError):
    outcome = DecisionOutcome.DENY_BEFORE_PROVIDER
    owner = "sender"
    next_action = "correct the exact envelope identity and resend only those bytes"

    def __init__(self, cause: str) -> None:
        self.cause = cause
        super().__init__(cause)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise TransportError("envelope JSON contains a duplicate key")
        value[key] = item
    return value


def _reject_constant(value: str) -> None:
    raise TransportError(f"envelope JSON contains a non-finite number: {value}")


def _json_shape(value: object, depth: int = 0) -> int:
    if depth > _MAX_JSON_DEPTH:
        raise TransportError("envelope JSON exceeds the nesting bound")
    if value is None or isinstance(value, bool) or isinstance(value, int):
        return 1
    if isinstance(value, float):
        raise TransportError("envelope JSON numbers must be integers")
    if isinstance(value, str):
        try:
            value.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise TransportError("envelope JSON text is not valid UTF-8") from exc
        if any((ord(char) < 0x20 and char not in "\t\n\r") or ord(char) == 0x7F for char in value):
            raise TransportError("envelope JSON text contains a prohibited control character")
        return 1
    if isinstance(value, list):
        count = 1 + sum(_json_shape(item, depth + 1) for item in value)
    elif isinstance(value, Mapping):
        count = 1
        for key, item in value.items():
            if not isinstance(key, str):
                raise TransportError("envelope JSON object keys must be text")
            count += _json_shape(key, depth + 1) + _json_shape(item, depth + 1)
    else:
        raise TransportError("envelope payload contains a non-JSON value")
    if count > _MAX_JSON_NODES:
        raise TransportError("envelope JSON exceeds the node bound")
    return count


def _canonical_json(value: object) -> bytes:
    _json_shape(value)
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise TransportError("envelope payload is not canonical JSON") from exc
    if len(encoded) > _MAX_ENVELOPE_BYTES:
        raise TransportError("envelope JSON exceeds the size bound")
    return encoded


def _payload_bytes(payload: object) -> bytes:
    if not isinstance(payload, Mapping):
        raise TransportError("envelope payload must be a JSON object")
    return _canonical_json(payload)


def _payload_value(payload_bytes: bytes) -> dict[str, Any]:
    if not isinstance(payload_bytes, bytes):
        raise TransportError("envelope payload identity must be immutable bytes")
    try:
        value = json.loads(
            payload_bytes.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except TransportError:
        raise
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise TransportError("envelope payload identity is not strict UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise TransportError("envelope payload must be a JSON object")
    return value


def _validate_payload_bytes(payload_bytes: bytes) -> None:
    if _payload_bytes(_payload_value(payload_bytes)) != payload_bytes:
        raise TransportError("envelope payload identity is not canonical JSON")


def _payload_sha256(payload_bytes: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload_bytes).hexdigest()


def _load(raw: bytes, keys: frozenset[str], kind: str) -> dict[str, Any]:
    if not isinstance(raw, bytes) or not raw or len(raw) > _MAX_ENVELOPE_BYTES:
        raise TransportError("envelope must be bounded non-empty bytes")
    try:
        text = raw.decode("utf-8")
        value = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except TransportError:
        raise
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise TransportError("envelope is not strict UTF-8 JSON") from exc
    _json_shape(value)
    if not isinstance(value, dict) or frozenset(value) != keys:
        raise TransportError("envelope has missing or unknown fields")
    if value.get("format") != ENVELOPE_FORMAT or value.get("kind") != kind:
        raise TransportError("envelope format or kind is unsupported")
    return value


def _identity_fields(
    *,
    kind: str,
    run_id: str,
    task_id: str,
    run_spec_sha256: str,
    source_role: str,
    target_role: str,
    route: str,
    source_invocation_id: str,
    source_authorization_sha256: str,
    target_invocation_id: str,
    payload_sha256: str,
    causation_delivery_id: str | None,
) -> dict[str, object]:
    fields: dict[str, object] = {
        "format": "awf.runtime-v2.delivery.v1",
        "kind": kind,
        "run_id": run_id,
        "task_id": task_id,
        "run_spec_sha256": run_spec_sha256,
        "source_role": source_role,
        "target_role": target_role,
        "route": route,
        "source_invocation_id": source_invocation_id,
        "source_authorization_sha256": source_authorization_sha256,
        "target_invocation_id": target_invocation_id,
        "payload_sha256": payload_sha256,
    }
    if causation_delivery_id is not None:
        fields["causation_delivery_id"] = causation_delivery_id
    return fields


def _delivery_id(**identity: object) -> str:
    return "awfv2:" + hashlib.sha256(_canonical_json(identity)).hexdigest()


def _require_delivery_id(name: str, value: object) -> str:
    if not isinstance(value, str) or _DELIVERY_RE.fullmatch(value) is None:
        raise TransportError(f"{name} is malformed")
    return value


def _validate_identity(
    *,
    kind: str,
    delivery_id: str,
    run_id: str,
    task_id: str,
    run_spec_sha256: str,
    source_role: str,
    target_role: str,
    route: str,
    source_invocation_id: str,
    source_authorization_sha256: str,
    target_invocation_id: str,
    payload_bytes: bytes,
    causation_delivery_id: str | None,
) -> None:
    _identifier("run_id", run_id)
    _identifier("task_id", task_id)
    _sha256("run_spec_sha256", run_spec_sha256)
    _identifier("route", route)
    _identifier("source_invocation_id", source_invocation_id)
    _sha256("source_authorization_sha256", source_authorization_sha256)
    _identifier("target_invocation_id", target_invocation_id)
    if (source_role, target_role) not in _ROLE_PAIRS:
        raise TransportError("envelope role pair is unsupported")
    _require_delivery_id("delivery identity", delivery_id)
    if causation_delivery_id is not None:
        _require_delivery_id("result causation identity", causation_delivery_id)
    payload_sha256 = _payload_sha256(payload_bytes)
    expected = _delivery_id(
        **_identity_fields(
            kind=kind,
            run_id=run_id,
            task_id=task_id,
            run_spec_sha256=run_spec_sha256,
            source_role=source_role,
            target_role=target_role,
            route=route,
            source_invocation_id=source_invocation_id,
            source_authorization_sha256=source_authorization_sha256,
            target_invocation_id=target_invocation_id,
            payload_sha256=payload_sha256,
            causation_delivery_id=causation_delivery_id,
        )
    )
    if delivery_id != expected:
        raise TransportError("delivery identity does not match the canonical envelope")


@dataclass(frozen=True, slots=True)
class CommandEnvelope:
    delivery_id: str
    run_id: str
    task_id: str
    run_spec_sha256: str
    source_role: str
    target_role: str
    route: str
    source_invocation_id: str
    source_authorization_sha256: str
    target_invocation_id: str
    payload_bytes: bytes

    def __post_init__(self) -> None:
        _validate_payload_bytes(self.payload_bytes)
        _validate_identity(kind="command", causation_delivery_id=None, **self._identity())

    def _identity(self) -> dict[str, object]:
        return {
            "delivery_id": self.delivery_id,
            "run_id": self.run_id,
            "task_id": self.task_id,
            "run_spec_sha256": self.run_spec_sha256,
            "source_role": self.source_role,
            "target_role": self.target_role,
            "route": self.route,
            "source_invocation_id": self.source_invocation_id,
            "source_authorization_sha256": self.source_authorization_sha256,
            "target_invocation_id": self.target_invocation_id,
            "payload_bytes": self.payload_bytes,
        }

    @classmethod
    def create(cls, *, payload: object, **identity: object) -> CommandEnvelope:
        payload_bytes = _payload_bytes(payload)
        payload_sha256 = _payload_sha256(payload_bytes)
        delivery_id = _delivery_id(
            **_identity_fields(
                kind="command",
                payload_sha256=payload_sha256,
                causation_delivery_id=None,
                **identity,
            )
        )
        return cls(delivery_id, payload_bytes=payload_bytes, **identity)

    @classmethod
    def decode(cls, raw: bytes) -> CommandEnvelope:
        value = _load(raw, _COMMON_KEYS, "command")
        payload = value.pop("payload")
        payload_sha256 = value.pop("payload_sha256")
        value.pop("format")
        value.pop("kind")
        envelope = cls(payload_bytes=_payload_bytes(payload), **value)
        if payload_sha256 != envelope.payload_sha256 or envelope.encode() != raw:
            raise TransportError("command payload hash or canonical encoding is invalid")
        return envelope

    @property
    def payload(self) -> dict[str, Any]:
        return _payload_value(self.payload_bytes)

    @property
    def payload_sha256(self) -> str:
        return _payload_sha256(self.payload_bytes)

    def encode(self) -> bytes:
        return _canonical_json(
            {
                "format": ENVELOPE_FORMAT,
                "kind": "command",
                **{key: value for key, value in self._identity().items() if key != "payload_bytes"},
                "payload_sha256": self.payload_sha256,
                "payload": self.payload,
            }
        )


@dataclass(frozen=True, slots=True)
class ResultEnvelope:
    delivery_id: str
    causation_delivery_id: str
    run_id: str
    task_id: str
    run_spec_sha256: str
    source_role: str
    target_role: str
    route: str
    source_invocation_id: str
    source_authorization_sha256: str
    target_invocation_id: str
    payload_bytes: bytes

    def __post_init__(self) -> None:
        _validate_payload_bytes(self.payload_bytes)
        _validate_identity(kind="result", **self._identity())

    def _identity(self) -> dict[str, object]:
        return {
            "delivery_id": self.delivery_id,
            "causation_delivery_id": self.causation_delivery_id,
            "run_id": self.run_id,
            "task_id": self.task_id,
            "run_spec_sha256": self.run_spec_sha256,
            "source_role": self.source_role,
            "target_role": self.target_role,
            "route": self.route,
            "source_invocation_id": self.source_invocation_id,
            "source_authorization_sha256": self.source_authorization_sha256,
            "target_invocation_id": self.target_invocation_id,
            "payload_bytes": self.payload_bytes,
        }

    @classmethod
    def create(cls, *, payload: object, **identity: object) -> ResultEnvelope:
        payload_bytes = _payload_bytes(payload)
        payload_sha256 = _payload_sha256(payload_bytes)
        delivery_id = _delivery_id(
            **_identity_fields(kind="result", payload_sha256=payload_sha256, **identity)
        )
        return cls(delivery_id, payload_bytes=payload_bytes, **identity)

    @classmethod
    def decode(cls, raw: bytes) -> ResultEnvelope:
        value = _load(raw, _RESULT_KEYS, "result")
        payload = value.pop("payload")
        payload_sha256 = value.pop("payload_sha256")
        value.pop("format")
        value.pop("kind")
        envelope = cls(payload_bytes=_payload_bytes(payload), **value)
        if payload_sha256 != envelope.payload_sha256 or envelope.encode() != raw:
            raise TransportError("result payload hash or canonical encoding is invalid")
        return envelope

    @property
    def payload(self) -> dict[str, Any]:
        return _payload_value(self.payload_bytes)

    @property
    def payload_sha256(self) -> str:
        return _payload_sha256(self.payload_bytes)

    def encode(self) -> bytes:
        return _canonical_json(
            {
                "format": ENVELOPE_FORMAT,
                "kind": "result",
                **{key: value for key, value in self._identity().items() if key != "payload_bytes"},
                "payload_sha256": self.payload_sha256,
                "payload": self.payload,
            }
        )


class _LocalRequest(Protocol):
    invocation_id: str
    stage: WorkflowStage
    delivery_id: str
    payload_sha256: str


class _LocalApplication(Protocol):
    state_root: Any
    writer_id: str

    def run(self, run_spec: RunSpec, request: Any) -> RunSnapshot: ...


class LocalTransportBoundary:
    def __init__(self, application: _LocalApplication) -> None:
        self.application = application

    def accept(
        self,
        run_spec: RunSpec,
        request: _LocalRequest,
        raw: bytes,
        *,
        expected_causation_delivery_id: str | None = None,
    ) -> RunSnapshot:
        expected = {
            WorkflowStage.IMPLEMENT: (
                CommandEnvelope,
                "architect",
                "coder",
                run_spec.implement_route,
            ),
            WorkflowStage.REVIEW: (ResultEnvelope, "coder", "reviewer", run_spec.review_route),
            WorkflowStage.REWORK: (ResultEnvelope, "reviewer", "coder", run_spec.rework_route),
        }
        try:
            envelope_type, source_role, target_role, route = expected[request.stage]
        except (KeyError, TypeError) as exc:
            raise TransportError("local request Stage is unsupported") from exc
        envelope = envelope_type.decode(raw)
        mismatch = (
            envelope.run_id != run_spec.run_id
            or envelope.task_id != run_spec.task_id
            or envelope.run_spec_sha256 != run_spec.sha256
            or envelope.source_role != source_role
            or envelope.target_role != target_role
            or envelope.route != route
            or envelope.target_invocation_id != request.invocation_id
            or envelope.delivery_id != request.delivery_id
            or envelope.payload_sha256.removeprefix("sha256:") != request.payload_sha256
        )
        if isinstance(envelope, ResultEnvelope):
            from .store import AtomicRunStore

            mismatch = mismatch or (
                expected_causation_delivery_id is None
                or envelope.causation_delivery_id != expected_causation_delivery_id
            )
            incoming = AtomicRunStore(
                self.application.state_root,
                run_spec.run_id,
                self.application.writer_id,
            ).pending_handoff()
            mismatch = (
                mismatch
                or incoming is None
                or (
                    incoming.delivery_id != envelope.delivery_id
                    or incoming.payload_sha256 != envelope.payload_sha256.removeprefix("sha256:")
                    or incoming.route != envelope.route
                    or incoming.target_role != envelope.target_role
                    or incoming.source_invocation_id != envelope.source_invocation_id
                    or incoming.source_authorization_sha256 != envelope.source_authorization_sha256
                )
            )
        if mismatch:
            raise TransportError("envelope does not match the exact local application input")
        return self.application.run(run_spec, request)

    @staticmethod
    def prepare_result(
        run_spec: RunSpec,
        intent: HandoffCommand | TerminalCommand,
        *,
        source_role: str,
        target_role: str,
        route: str,
        target_invocation_id: str,
        causation_delivery_id: str,
        payload: object,
    ) -> ResultEnvelope:
        envelope = ResultEnvelope.create(
            run_id=run_spec.run_id,
            task_id=run_spec.task_id,
            run_spec_sha256=run_spec.sha256,
            source_role=source_role,
            target_role=target_role,
            route=route,
            source_invocation_id=intent.source_invocation_id,
            source_authorization_sha256=intent.source_authorization_sha256,
            target_invocation_id=target_invocation_id,
            causation_delivery_id=causation_delivery_id,
            payload=payload,
        )
        if (
            intent.run_spec_sha256 != run_spec.sha256
            or intent.delivery_id != envelope.delivery_id
            or intent.payload_sha256 != envelope.payload_sha256.removeprefix("sha256:")
            or isinstance(intent, HandoffCommand)
            and (intent.route != route or intent.target_role != target_role)
            or isinstance(intent, TerminalCommand)
            and target_role != "architect"
        ):
            raise TransportError("outgoing result does not match the exact Store-owned intent")
        return envelope
