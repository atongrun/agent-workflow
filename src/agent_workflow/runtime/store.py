from __future__ import annotations

import contextlib
import copy
import dataclasses
import hashlib
import json
import os
import secrets
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from .contracts import ContractError, RunSpec, _canonical_bytes, _identifier, _sha256
from .ports import (
    AuthorizationCommand,
    DecisionOutcome,
    HandoffCommand,
    InvocationJournal,
    JournalAuthorization,
    JournalSnapshot,
    LaunchIntent,
    ProcessObservation,
    ProviderResult,
    RunDecision,
    RunSnapshot,
    TerminalCommand,
    TerminalOutcome,
    ValidationEffect,
    WorkflowStage,
)

AUTHORITY_FORMAT = "awf.runtime-v2.atomic-authority.v1"
LOCK_FORMAT = "awf.runtime-v2.atomic-writer-lock.v1"
SCHEMA_VERSION = 1
_PAYLOAD_KEYS = frozenset(
    "schema_version run_spec run_spec_sha256 run_id state_root_sha256 writer_id "
    "sequence events journals".split()
)
_JOURNAL_KEYS = frozenset(
    "authorization launch_intent process_observation result validation_effect".split()
)
_Result = tuple[DecisionOutcome, str, str]
_TransformResult = tuple[dict[str, Any], _Result | None]
_Payload = dict[str, Any] | None


class StoreError(RuntimeError):
    def __init__(
        self, outcome: DecisionOutcome, cause: str, next_action: str, *, owner: str = "runtime"
    ) -> None:
        super().__init__(cause)
        self.outcome = outcome
        self.owner, self.cause, self.next_action = owner, cause, next_action


class WriterBusy(StoreError):
    def __init__(self, cause: str = "exact writer lock is active") -> None:
        super().__init__(
            DecisionOutcome.AMBIGUOUS_NO_REPLAY, cause, "preserve writer evidence", owner="owner"
        )


@dataclass(frozen=True, slots=True)
class _Authority:
    payload: dict[str, Any]
    run_spec: RunSpec
    stage: WorkflowStage
    terminal: TerminalCommand | None
    authorizations: dict[str, tuple[AuthorizationCommand, JournalAuthorization]]
    journals: dict[str, JournalSnapshot]


def _deny(cause: str) -> StoreError:
    return StoreError(
        DecisionOutcome.DENY_BEFORE_PROVIDER, cause, "preserve files; diagnose exact run identity"
    )


def _bind_paths(owner: Any, state_root: Path | str, run_id: str) -> None:
    candidate = Path(state_root).expanduser()
    if candidate.is_symlink():
        raise _deny("state root must not be a symbolic link")
    owner.state_root, owner.run_id = candidate.resolve(), _identifier("run_id", run_id)
    owner.run_dir = owner.state_root / "runtime-v2" / "runs" / owner.run_id
    owner.path = owner.run_dir / "authority.json"
    owner.lock_path = owner.run_dir / "authority.lock"


def _guard_path(state_root: Path, path: Path) -> None:
    try:
        relative = path.relative_to(state_root)
    except ValueError as exc:
        raise _deny("Runtime path escapes the selected state root") from exc
    current = state_root
    for part in relative.parts:
        current /= part
        if current.is_symlink() or (current.exists() and current.resolve() != current):
            raise _deny("Runtime path must not traverse a symbolic link or reparse point")


def _strict_object(value: object, name: str, keys: frozenset[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or frozenset(value) != keys:
        raise _deny(f"{name} fields are invalid")
    return value


def _data(value: object) -> Any:
    if dataclasses.is_dataclass(value):
        return {f.name: _data(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return [_data(item) for item in value]
    return value


def _load_json(text: str, name: str) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate key {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(text, object_pairs_hook=reject_duplicates)
    except (json.JSONDecodeError, UnicodeError, ValueError) as exc:
        raise _deny(f"cannot parse {name}: {exc}") from exc
    if not isinstance(value, dict):
        raise _deny(f"{name} is not a JSON object")
    return value


def _restore(cls: type[Any], value: object) -> Any:
    data = dict(
        _strict_object(
            value,
            cls.__name__,
            frozenset(field.name for field in dataclasses.fields(cls)),
        )
    )
    try:
        if cls is AuthorizationCommand:
            data["stage"] = WorkflowStage(data["stage"])
        elif cls is TerminalCommand:
            data["outcome"] = TerminalOutcome(data["outcome"])
        return cls(**data)
    except (ContractError, TypeError, ValueError) as exc:
        raise _deny(f"{cls.__name__} is invalid: {exc}") from exc


def _decode_journal(invocation_id: str, value: object) -> JournalSnapshot:
    data = _strict_object(value, f"journal {invocation_id}", _JOURNAL_KEYS)
    authorization = _restore(JournalAuthorization, data["authorization"])
    types = {
        "launch_intent": LaunchIntent,
        "process_observation": ProcessObservation,
        "result": ProviderResult,
        "validation_effect": ValidationEffect,
    }
    facts = {
        name: None if data[name] is None else _restore(cls, data[name])
        for name, cls in types.items()
    }
    launch, process, result, effect = (facts[name] for name in types)
    if authorization.invocation_id != invocation_id:
        raise _deny(f"journal {invocation_id} identity drift")
    if process is not None and launch is None:
        raise _deny(f"journal {invocation_id} process precedes launch intent")
    if result is not None and process is None:
        raise _deny(f"journal {invocation_id} result precedes process observation")
    if effect is not None and result is None:
        raise _deny(f"journal {invocation_id} validation precedes result")
    for fact in (launch, process, result, effect):
        if fact is not None and fact.authorization_sha256 != authorization.authorization_sha256:
            raise _deny(f"journal {invocation_id} authorization drift")
    if result is not None and result.process_identity_sha256 != process.process_identity_sha256:
        raise _deny(f"journal {invocation_id} process identity drift")
    if effect is not None and effect.result_sha256 != result.result_sha256:
        raise _deny(f"journal {invocation_id} result identity drift")
    return JournalSnapshot(*dataclasses.astuple(authorization), launch, process, result, effect)


def _capacity(spec: RunSpec, stage: WorkflowStage) -> int:
    if stage is WorkflowStage.REWORK:
        return spec.rework_budget
    return spec.review_attempts if stage is WorkflowStage.REVIEW else spec.implement_attempts


def _next_stage(spec: RunSpec, stage: WorkflowStage, command: HandoffCommand) -> WorkflowStage:
    if stage in {WorkflowStage.IMPLEMENT, WorkflowStage.REWORK}:
        if command.route == spec.review_route and command.target_role == "reviewer":
            return WorkflowStage.REVIEW
    elif command.route == spec.rework_route and command.target_role == "coder":
        return WorkflowStage.REWORK
    raise _deny("handoff route or target is illegal for the current Workflow Stage")


def _validate_payload(payload: object) -> _Authority:
    data = _strict_object(payload, "authority payload", _PAYLOAD_KEYS)
    if data["schema_version"] != SCHEMA_VERSION:
        raise StoreError(
            DecisionOutcome.OWNER_DECISION_REQUIRED,
            "authority schema is unsupported",
            "preserve program and state evidence; use only a compatible schema",
            owner="owner",
        )
    try:
        spec = RunSpec.from_mapping(data["run_spec"])
        _sha256("run_spec_sha256", data["run_spec_sha256"])
        _identifier("run_id", data["run_id"])
        _sha256("state_root_sha256", data["state_root_sha256"])
        _identifier("writer_id", data["writer_id"])
    except (TypeError, ValueError) as exc:
        raise _deny(f"authority identity is invalid: {exc}") from exc
    if spec.sha256 != data["run_spec_sha256"] or spec.run_id != data["run_id"]:
        raise _deny("authority RunSpec binding drift")
    sequence = data["sequence"]
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
        raise _deny("authority sequence is invalid")
    if not isinstance(data["events"], list) or not isinstance(data["journals"], Mapping):
        raise _deny("authority events or journals are invalid")
    journals = {
        invocation_id: _decode_journal(invocation_id, value)
        for invocation_id, value in data["journals"].items()
        if isinstance(invocation_id, str)
    }
    if len(journals) != len(data["journals"]):
        raise _deny("journal identifiers are invalid")

    stage = WorkflowStage.IMPLEMENT
    terminal: TerminalCommand | None = None
    authorizations: dict[str, tuple[AuthorizationCommand, JournalAuthorization]] = {}
    counts = {item: 0 for item in WorkflowStage}
    deliveries: set[str] = set()
    handed_off: set[str] = set()
    for raw_event in data["events"]:
        if terminal is not None:
            raise _deny("authority contains an event after terminal")
        if not isinstance(raw_event, Mapping):
            raise _deny("authority event is invalid")
        kind = raw_event.get("kind")
        if kind == "authorization":
            event = _strict_object(
                raw_event, "authorization event", frozenset({"kind", "command", "fact"})
            )
            command = _restore(AuthorizationCommand, event["command"])
            fact = _restore(JournalAuthorization, event["fact"])
            if command.invocation_id in authorizations or command.delivery_id in deliveries:
                raise _deny("authorization identity is reused")
            if command.stage is not stage:
                raise _deny("authorization Stage does not match current authority")
            expected_role = "reviewer" if stage is WorkflowStage.REVIEW else "coder"
            if command.role != expected_role:
                raise _deny("authorization role does not match current Stage")
            counts[stage] += 1
            if counts[stage] > _capacity(spec, stage) or command.attempt != counts[stage]:
                raise _deny("authorization capacity is exhausted")
            if (
                command.run_spec_sha256 != spec.sha256
                or fact.run_spec_sha256 != spec.sha256
                or command.invocation_id != fact.invocation_id
                or command.authorization_sha256 != fact.authorization_sha256
            ):
                raise _deny("authorization command and journal binding drift")
            journal = journals.get(command.invocation_id)
            if journal is None or (
                journal.run_spec_sha256,
                journal.invocation_id,
                journal.authorization_sha256,
                journal.invocation_spec_sha256,
            ) != (
                fact.run_spec_sha256,
                fact.invocation_id,
                fact.authorization_sha256,
                fact.invocation_spec_sha256,
            ):
                raise _deny("authorization journal is absent or conflicting")
            authorizations[command.invocation_id] = (command, fact)
            deliveries.add(command.delivery_id)
        elif kind == "handoff":
            event = _strict_object(
                raw_event, "handoff event", frozenset({"kind", "command", "effect"})
            )
            command = _restore(HandoffCommand, event["command"])
            effect = _restore(ValidationEffect, event["effect"])
            source = authorizations.get(command.source_invocation_id)
            journal = journals.get(command.source_invocation_id)
            if source is None or journal is None or journal.result is None:
                raise _deny("handoff source authorization or result is absent")
            if command.delivery_id in deliveries or command.source_invocation_id in handed_off:
                raise _deny("handoff identity is reused")
            if stage is WorkflowStage.REVIEW and counts[WorkflowStage.REWORK] >= spec.rework_budget:
                raise _deny("rework capacity is exhausted")
            if (
                source[0].stage is not stage
                or command.run_spec_sha256 != spec.sha256
                or command.source_authorization_sha256 != source[0].authorization_sha256
                or journal.validation_effect != effect
            ):
                raise _deny("handoff lineage or validation drift")
            stage = _next_stage(spec, stage, command)
            handed_off.add(command.source_invocation_id)
            deliveries.add(command.delivery_id)
        elif kind == "terminal":
            event = _strict_object(
                raw_event, "terminal event", frozenset({"kind", "command", "effect"})
            )
            command = _restore(TerminalCommand, event["command"])
            effect = _restore(ValidationEffect, event["effect"])
            source = authorizations.get(command.source_invocation_id)
            journal = journals.get(command.source_invocation_id)
            if source is None or journal is None or journal.result is None:
                raise _deny("terminal source authorization or result is absent")
            if (
                command.delivery_id in deliveries
                or command.source_invocation_id in handed_off
                or stage is not WorkflowStage.REVIEW
            ):
                raise _deny("terminal delivery or Stage is invalid")
            if command.outcome not in {TerminalOutcome.COMPLETED, TerminalOutcome.BLOCKED}:
                raise _deny("terminal outcome has no owner in this Store")
            if (
                source[0].stage is not WorkflowStage.REVIEW
                or command.run_spec_sha256 != spec.sha256
                or command.source_authorization_sha256 != source[0].authorization_sha256
                or journal.validation_effect != effect
            ):
                raise _deny("terminal lineage or validation drift")
            terminal = command
            deliveries.add(command.delivery_id)
        else:
            raise _deny("authority event kind is unknown")
    if set(journals) != set(authorizations):
        raise _deny("journal and authorization identities differ")
    observations = sum(
        value[key] is not None
        for value in data["journals"].values()
        for key in ("launch_intent", "process_observation", "result")
    )
    if sequence != 1 + len(data["events"]) + observations:
        raise _deny("authority sequence does not match durable transitions")
    return _Authority(dict(data), spec, stage, terminal, authorizations, journals)


def _read_authority(state_root: Path, path: Path) -> _Authority:
    _guard_path(state_root, path)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise StoreError(
            DecisionOutcome.EXTERNAL_OBSERVATION_UNKNOWN,
            "authority file is absent",
            "inspect the exact run and state-root identity",
            owner="owner",
        ) from exc
    envelope = _strict_object(
        _load_json(text, path.name),
        "authority envelope",
        frozenset({"format", "payload", "checksum"}),
    )
    payload = envelope["payload"]
    if (
        envelope["format"] != AUTHORITY_FORMAT
        or not isinstance(payload, Mapping)
        or envelope["checksum"] != hashlib.sha256(_canonical_bytes(payload)).hexdigest()
    ):
        raise _deny("authority envelope checksum or format is invalid")
    return _validate_payload(payload)


def _state_root_sha256(path: Path) -> str:
    return hashlib.sha256(("awf-state-root-v1\0" + str(path)).encode()).hexdigest()


def _snapshot(authority: _Authority, *, lock_active: bool = False) -> RunSnapshot:
    spec = authority.run_spec
    sequence = authority.payload["sequence"]
    blocker = None
    owner = "runtime"
    outcome = DecisionOutcome.SAFE_CONTINUE
    if authority.terminal is not None:
        outcome = DecisionOutcome.TERMINAL_IDEMPOTENT
        cause = "run is terminal"
        action = "none"
    elif lock_active:
        blocker = "exact writer lock is active"
        owner = "owner"
        outcome = DecisionOutcome.AMBIGUOUS_NO_REPLAY
        cause = "a local authority mutation may be in flight or ambiguous"
        action = "preserve exact writer/process evidence for owner decision"
    else:
        closed = {
            event["command"]["source_invocation_id"]
            for event in authority.payload["events"]
            if event["kind"] in {"handoff", "terminal"}
        }
        current = [
            item
            for item in authority.authorizations.values()
            if item[0].stage is authority.stage and item[0].invocation_id not in closed
        ]
        if not current:
            cause = f"{authority.stage.value} authorization is required"
            action = f"authorize one exact {authority.stage.value} invocation"
        else:
            journal = authority.journals[current[-1][0].invocation_id]
            if journal.launch_intent is None:
                cause = "the invocation is authorized and has no launch intent"
                action = "launch the exact authorized provider once"
            elif journal.result is None:
                blocker = "provider outcome is ambiguous"
                owner = "owner"
                outcome = DecisionOutcome.AMBIGUOUS_NO_REPLAY
                cause = "launch/process evidence exists without a trusted result"
                action = "preserve exact process/workspace/evidence for owner decision"
            else:
                cause = "an exact durable provider result awaits validation"
                action = "validate the exact durable result without provider replay"
    terminal = None if authority.terminal is None else authority.terminal.outcome
    return RunSnapshot(
        spec.run_id,
        spec.sha256,
        sequence,
        authority.stage,
        terminal,
        outcome,
        blocker,
        owner,
        cause,
        action,
    )


def _decision(outcome: DecisionOutcome, cause: str, next_action: str, sequence: int) -> RunDecision:
    return RunDecision(outcome, "runtime", cause, next_action, sequence)


class AtomicRunStore:
    def __init__(self, state_root: Path | str, run_id: str, writer_id: str) -> None:
        _bind_paths(self, state_root, run_id)
        self.writer_id = _identifier("writer_id", writer_id)

    def _verify_binding(self, authority: _Authority) -> None:
        payload = authority.payload
        if (
            payload["run_id"] != self.run_id
            or payload["state_root_sha256"] != _state_root_sha256(self.state_root)
            or payload["writer_id"] != self.writer_id
        ):
            raise _deny("run, state-root, or writer identity drift")

    def _read(self) -> _Authority:
        authority = _read_authority(self.state_root, self.path)
        self._verify_binding(authority)
        return authority

    @contextlib.contextmanager
    def _writer_lock(self) -> Iterator[bytes]:
        _guard_path(self.state_root, self.run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        _guard_path(self.state_root, self.run_dir)
        _guard_path(self.state_root, self.path)
        _guard_path(self.state_root, self.lock_path)
        lock = {"format": LOCK_FORMAT, "writer_id": self.writer_id, "nonce": secrets.token_hex(16)}
        token = _canonical_bytes(lock)
        try:
            descriptor = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            raise WriterBusy() from exc
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(token)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            yield token
        finally:
            try:
                current = self.lock_path.read_bytes()
            except FileNotFoundError as exc:
                raise WriterBusy("exact writer lock disappeared before release") from exc
            if current != token:
                raise WriterBusy("exact writer lock changed before release")
            self.lock_path.unlink()

    def _write(self, payload: dict[str, Any], token: bytes) -> None:
        if self.lock_path.read_bytes() != token:
            raise WriterBusy("exact writer lock changed before authority replacement")
        envelope = {
            "format": AUTHORITY_FORMAT,
            "payload": payload,
            "checksum": hashlib.sha256(_canonical_bytes(payload)).hexdigest(),
        }
        temporary = self.path.with_name(f".{self.path.name}.tmp-{secrets.token_hex(16)}")
        descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(_canonical_bytes(envelope) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        if self.lock_path.read_bytes() != token:
            raise WriterBusy("exact writer lock changed before authority replacement")
        os.replace(temporary, self.path)
        if hasattr(os, "O_DIRECTORY"):
            directory = os.open(self.run_dir, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)

    def _transaction(
        self,
        transform: Callable[[dict[str, Any] | None, _Authority | None], _TransformResult],
    ) -> tuple[_Authority, _Result | None]:
        with self._writer_lock() as token:
            current = self._read() if self.path.exists() else None
            payload = None if current is None else copy.deepcopy(current.payload)
            updated, result = transform(payload, current)
            if current is not None and updated == current.payload:
                return current, result
            updated["sequence"] = 1 if current is None else current.payload["sequence"] + 1
            authority = _validate_payload(updated)
            self._verify_binding(authority)
            try:
                self._write(updated, token)
            except OSError as exc:
                raise WriterBusy("authority replacement outcome is ambiguous") from exc
            return authority, result

    def initialize(self, run_spec: RunSpec) -> RunSnapshot:
        if not isinstance(run_spec, RunSpec):
            raise _deny("initialize requires an immutable RunSpec")
        if run_spec.run_id != self.run_id:
            raise _deny("RunSpec run identity drift")
        if run_spec.state_root_sha256 != _state_root_sha256(self.state_root):
            raise _deny("RunSpec state-root binding drift")

        def transform(payload: _Payload, authority: _Authority | None) -> _TransformResult:
            if authority is not None:
                if authority.run_spec != run_spec:
                    raise _deny("immutable RunSpec drift")
                return authority.payload, None
            return (
                {
                    "schema_version": SCHEMA_VERSION,
                    "run_spec": run_spec.to_mapping(),
                    "run_spec_sha256": run_spec.sha256,
                    "run_id": self.run_id,
                    "state_root_sha256": run_spec.state_root_sha256,
                    "writer_id": self.writer_id,
                    "sequence": 0,
                    "events": [],
                    "journals": {},
                },
                None,
            )

        authority, _ = self._transaction(transform)
        return _snapshot(authority)

    def authorize(self, command: AuthorizationCommand, fact: JournalAuthorization) -> RunDecision:
        def transform(payload: _Payload, authority: _Authority | None) -> _TransformResult:
            if payload is None or authority is None:
                raise _deny("RunStore must be initialized before authorization")
            existing = authority.authorizations.get(command.invocation_id)
            if existing is not None:
                if existing == (command, fact):
                    return payload, (
                        DecisionOutcome.SAFE_IDEMPOTENT_REPLAY,
                        "exact authorization is already durable",
                        "use the exact authorized journal",
                    )
                raise _deny("invocation authorization identity conflicts")
            event = {"kind": "authorization", "command": _data(command), "fact": _data(fact)}
            payload["events"].append(event)
            payload["journals"][command.invocation_id] = {
                "authorization": _data(fact),
                "launch_intent": None,
                "process_observation": None,
                "result": None,
                "validation_effect": None,
            }
            return payload, (
                DecisionOutcome.SAFE_CONTINUE,
                "authorization and journal identity are durable",
                "launch the exact authorized provider once",
            )

        authority, result = self._transaction(transform)
        assert result is not None
        return _decision(*result, authority.payload["sequence"])

    def journal(self, invocation_id: str) -> InvocationJournal:
        invocation_id = _identifier("invocation_id", invocation_id)
        if invocation_id not in self._read().authorizations:
            raise _deny("invocation is not authorized")
        return AtomicInvocationJournal(self, invocation_id)

    def _record_effect(
        self,
        kind: str,
        command: HandoffCommand | TerminalCommand,
        effect: ValidationEffect,
    ) -> RunDecision:
        def transform(payload: _Payload, authority: _Authority | None) -> _TransformResult:
            if payload is None or authority is None:
                raise _deny("RunStore is absent")
            encoded = {"kind": kind, "command": _data(command), "effect": _data(effect)}
            for event in payload["events"]:
                same = event["kind"] == kind and (
                    kind == "terminal" or event["command"]["delivery_id"] == command.delivery_id
                )
                if same and event == encoded:
                    outcome = (
                        DecisionOutcome.TERMINAL_IDEMPOTENT
                        if kind == "terminal"
                        else DecisionOutcome.SAFE_STABLE_RESEND
                    )
                    action = "none" if kind == "terminal" else "resend the exact handoff"
                    return payload, (outcome, f"exact {kind} is already durable", action)
                if same and kind == "terminal":
                    raise StoreError(
                        DecisionOutcome.TERMINAL_CONFLICT,
                        "terminal replay conflicts with current authority",
                        "preserve the current terminal and conflicting evidence",
                        owner="owner",
                    )
                if same:
                    raise _deny("handoff delivery identity conflicts")
            journal = payload["journals"].get(command.source_invocation_id)
            if journal is None or journal["result"] is None:
                raise _deny(f"{kind} source result is absent")
            if effect.result_sha256 != journal["result"]["result_sha256"]:
                raise _deny(f"{kind} validation result identity drift")
            journal["validation_effect"] = _data(effect)
            payload["events"].append(encoded)
            cause = f"validation and {kind} are durable"
            action = "none" if kind == "terminal" else "send the exact bound handoff"
            return payload, (DecisionOutcome.SAFE_CONTINUE, cause, action)

        authority, result = self._transaction(transform)
        assert result is not None
        return _decision(*result, authority.payload["sequence"])

    def record_handoff(self, command: HandoffCommand, effect: ValidationEffect) -> RunDecision:
        return self._record_effect("handoff", command, effect)

    def record_terminal(self, command: TerminalCommand, effect: ValidationEffect) -> RunDecision:
        return self._record_effect("terminal", command, effect)

    def _record_journal_fact(self, invocation_id: str, field: str, fact: object) -> JournalSnapshot:
        def transform(payload: _Payload, authority: _Authority | None) -> _TransformResult:
            if payload is None or authority is None:
                raise _deny("journal mutation is not legal for current authority")
            journal = payload["journals"].get(invocation_id)
            if journal is None:
                raise _deny("authorized journal is absent")
            if fact.authorization_sha256 != journal["authorization"]["authorization_sha256"]:
                raise _deny("journal fact authorization identity drift")
            expected_previous = {
                "launch_intent": None,
                "process_observation": "launch_intent",
                "result": "process_observation",
            }[field]
            if expected_previous is not None and journal[expected_previous] is None:
                raise _deny(f"journal {field} precedes {expected_previous}")
            encoded = _data(fact)
            if journal[field] is not None:
                if journal[field] == encoded:
                    return payload, None
                raise _deny(f"journal {field} identity conflicts")
            if authority.terminal is not None:
                raise _deny("new journal fact is illegal after terminal")
            journal[field] = encoded
            return payload, None

        authority, _ = self._transaction(transform)
        return authority.journals[invocation_id]


class AtomicInvocationJournal:
    def __init__(self, store: AtomicRunStore, invocation_id: str) -> None:
        self._store = store
        self._invocation_id = invocation_id

    def record_launch_intent(self, fact: LaunchIntent) -> JournalSnapshot:
        return self._store._record_journal_fact(self._invocation_id, "launch_intent", fact)

    def record_process_observation(self, fact: ProcessObservation) -> JournalSnapshot:
        return self._store._record_journal_fact(self._invocation_id, "process_observation", fact)

    def record_result(self, fact: ProviderResult) -> JournalSnapshot:
        return self._store._record_journal_fact(self._invocation_id, "result", fact)

    def snapshot(self) -> JournalSnapshot:
        authority = self._store._read()
        try:
            return authority.journals[self._invocation_id]
        except KeyError as exc:
            raise _deny("authorized journal is absent") from exc


class AtomicStatusReader:
    def __init__(self, state_root: Path | str, run_id: str) -> None:
        _bind_paths(self, state_root, run_id)

    def snapshot(self, run_id: str) -> RunSnapshot:
        if _identifier("run_id", run_id) != self.run_id:
            raise _deny("status run identity drift")
        authority = _read_authority(self.state_root, self.path)
        if authority.payload["run_id"] != self.run_id or authority.payload[
            "state_root_sha256"
        ] != _state_root_sha256(self.state_root):
            raise _deny("status run or state-root identity drift")
        _guard_path(self.state_root, self.lock_path)
        return _snapshot(authority, lock_active=self.lock_path.exists())
