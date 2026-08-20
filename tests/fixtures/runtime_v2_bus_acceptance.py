#!/usr/bin/env python3
"""Credential-safe no-model fixture for the isolated RTS-042 Bus acceptance."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable, Mapping

from agent_workflow.runtime import (
    AtomicRunStore,
    AuthorizationCommand,
    CommandEnvelope,
    DecisionOutcome,
    HandoffCommand,
    JournalAuthorization,
    LaunchIntent,
    OutgoingIntent,
    OutgoingIntentDispatcher,
    ProcessObservation,
    ProviderResult,
    ProviderSelection,
    ResultEnvelope,
    RunSpec,
    TransportSendReceipt,
    TransportSendState,
    ValidationEffect,
    WorkflowStage,
)

EVIDENCE_FORMAT = "awf.runtime-v2.bus-acceptance-evidence.v1"
COMMAND_EVENT = "control:awfv2-command-v1"
RESULT_EVENT = "control:awfv2-result-v1"
TASK_CARD = "docs/tasks/runtime-v2-rts-042-cross-machine-acceptance.md"
SEMANTIC_CONTRACT = "docs/runtime-v2-semantic-contract.md"
TASK_BRANCH = "codex/runtime-v2-rts-042-cross-machine-acceptance"
_SCOPE_RE = re.compile(r"[a-z0-9][a-z0-9-]{7,39}")
_SHA_RE = re.compile(r"[0-9a-f]{40,64}")
_DIGEST_RE = re.compile(r"[0-9a-f]{64}")


class AcceptanceError(RuntimeError):
    pass


def digest(value: str | bytes) -> str:
    raw = value if isinstance(value, bytes) else value.encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise AcceptanceError("transport payload contains a duplicate key")
        value[key] = item
    return value


def canonical_payload(raw: str) -> bytes:
    if not isinstance(raw, str) or not raw or len(raw.encode("utf-8")) > 256 * 1024:
        raise AcceptanceError("transport payload is empty or oversized")
    try:
        value = json.loads(
            raw,
            object_pairs_hook=_unique,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                AcceptanceError("transport payload contains a non-finite number")
            ),
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise AcceptanceError("transport payload is not strict JSON") from exc
    if not isinstance(value, dict):
        raise AcceptanceError("transport payload is not an object")
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode()


def validate_value(value: str, pattern: re.Pattern[str], label: str) -> str:
    if pattern.fullmatch(value) is None:
        raise AcceptanceError(f"{label} is invalid")
    return value


def state_root_binding(root: Path) -> str:
    return digest("awf-state-root-v1\0" + str(root.resolve()))


def verify_repo(repo: Path, candidate_sha: str) -> None:
    if not repo.is_dir() or repo.is_symlink():
        raise AcceptanceError("candidate repository identity is invalid")
    completed = subprocess.run(
        ["git", "-C", str(repo.resolve()), "rev-parse", "HEAD^{commit}"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        check=False,
    )
    try:
        head = completed.stdout.decode("ascii").strip()
    except UnicodeError as exc:
        raise AcceptanceError("candidate repository HEAD is not ASCII") from exc
    if completed.returncode != 0 or head != candidate_sha:
        raise AcceptanceError("candidate repository HEAD does not match the frozen SHA")


def make_spec(repo: Path, scope: str, candidate_sha: str, root_binding: str) -> RunSpec:
    validate_value(scope, _SCOPE_RE, "acceptance scope")
    validate_value(candidate_sha, _SHA_RE, "candidate SHA")
    validate_value(root_binding, _DIGEST_RE, "state-root binding")
    card = repo.resolve() / TASK_CARD
    contract = repo.resolve() / SEMANTIC_CONTRACT
    try:
        card_sha256 = digest(card.read_bytes())
        contract_sha256 = digest(contract.read_bytes())
    except OSError as exc:
        raise AcceptanceError("frozen contract input is unavailable") from exc
    return RunSpec(
        run_id=f"task-rts042-{scope}",
        task_id=f"rts042-{scope}",
        task_card=TASK_CARD,
        task_card_sha256=card_sha256,
        repository="atongrun/agent-workflow",
        frozen_base=candidate_sha,
        task_branch=TASK_BRANCH,
        state_root_sha256=root_binding,
        semantic_contract_sha256=contract_sha256,
        coder=ProviderSelection("opencode", "no-model-coder"),
        reviewer=ProviderSelection("pi", "no-model-reviewer"),
        implement_attempts=1,
        review_attempts=1,
        rework_budget=0,
        implement_route=COMMAND_EVENT,
        review_route=RESULT_EVENT,
        rework_route="control:awfv2-unused-rework-v1",
        implementation_report=f".awf/artifacts/impl-{scope}.md",
        review_report=f".awf/artifacts/review-{scope}.md",
    )


def make_command(spec: RunSpec, scope: str) -> CommandEnvelope:
    return CommandEnvelope.create(
        run_id=spec.run_id,
        task_id=spec.task_id,
        run_spec_sha256=spec.sha256,
        source_role="architect",
        target_role="coder",
        route=spec.implement_route,
        source_invocation_id=f"owner-{scope}",
        source_authorization_sha256=digest(f"owner-auth\0{scope}\0{spec.frozen_base}"),
        target_invocation_id=f"invoke-coder-{scope}",
        payload={"acceptance_scope": scope, "mode": "no-model"},
    )


def expected_child_sha256(scope: str, phase: str) -> str:
    output = digest(f"{scope}:{phase}").encode("ascii") + b"\n"
    return digest(output)


def run_child(scope: str, phase: str) -> tuple[str, str]:
    child_env = {
        key: value
        for key, value in os.environ.items()
        if key.upper() in {"SYSTEMROOT", "WINDIR", "COMSPEC", "PATH", "TEMP", "TMP", "TMPDIR"}
    }
    child_env["PYTHONIOENCODING"] = "utf-8"
    code = "import hashlib,sys; print(hashlib.sha256(sys.argv[1].encode()).hexdigest())"
    process = subprocess.Popen(
        [sys.executable, "-I", "-c", code, f"{scope}:{phase}"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=child_env,
        shell=False,
    )
    try:
        stdout, _stderr = process.communicate(timeout=10)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        process.communicate()
        raise AcceptanceError("bounded child timed out") from exc
    output_sha256 = digest(stdout)
    if process.returncode != 0 or output_sha256 != expected_child_sha256(scope, phase):
        raise AcceptanceError("bounded child result is invalid")
    return output_sha256, digest(f"rts042-child\0{scope}\0{phase}\0{process.pid}")


def transition_values(
    spec: RunSpec, command: CommandEnvelope, child_sha256: str
) -> tuple[str, str, str, str, ResultEnvelope]:
    authorization = digest(
        f"rts042-authorization\0{spec.sha256}\0{command.delivery_id}\0{child_sha256}"
    )
    result_sha256 = digest(f"rts042-result\0{authorization}\0{child_sha256}")
    artifact_sha256 = digest(f"rts042-no-model-artifact\0{command.delivery_id}")
    effect_sha256 = digest(
        f"rts042-effect\0{authorization}\0{result_sha256}\0{artifact_sha256}"
    )
    envelope = ResultEnvelope.create(
        run_id=spec.run_id,
        task_id=spec.task_id,
        run_spec_sha256=spec.sha256,
        source_role="coder",
        target_role="reviewer",
        route=spec.review_route,
        source_invocation_id=command.target_invocation_id,
        source_authorization_sha256=authorization,
        target_invocation_id=f"invoke-review-{spec.task_id.removeprefix('rts042-')}",
        causation_delivery_id=command.delivery_id,
        payload={"child_sha256": child_sha256, "effect_sha256": effect_sha256},
    )
    return authorization, result_sha256, artifact_sha256, effect_sha256, envelope


def prepare_result_store(
    root: Path,
    spec: RunSpec,
    command: CommandEnvelope,
    child_output_sha256: str,
    child_process_sha256: str,
) -> tuple[AtomicRunStore, OutgoingIntent]:
    if root.is_symlink() or state_root_binding(root) != spec.state_root_sha256:
        raise AcceptanceError("target state-root binding is invalid")
    authorization, result_sha256, artifact_sha256, effect_sha256, envelope = transition_values(
        spec, command, child_output_sha256
    )
    store = AtomicRunStore(root, spec.run_id, f"writer-{spec.task_id}")
    store.initialize(spec)
    command_fact = AuthorizationCommand(
        spec.sha256,
        command.target_invocation_id,
        authorization,
        WorkflowStage.IMPLEMENT,
        "coder",
        1,
        command.delivery_id,
        command.payload_sha256.removeprefix("sha256:"),
    )
    store.authorize(
        command_fact,
        JournalAuthorization(
            spec.sha256,
            command.target_invocation_id,
            authorization,
            digest("rts042-child-spec"),
        ),
    )
    journal = store.journal(command.target_invocation_id)
    journal.record_launch_intent(LaunchIntent(authorization, digest("rts042-child-launch")))
    process = ProcessObservation(authorization, child_process_sha256)
    journal.record_process_observation(process)
    journal.record_result(
        ProviderResult(authorization, process.process_identity_sha256, 0, result_sha256)
    )
    effect = ValidationEffect(authorization, result_sha256, artifact_sha256, effect_sha256)
    intent = OutgoingIntent.from_envelope(envelope)
    store.record_handoff(
        HandoffCommand(
            spec.sha256,
            command.target_invocation_id,
            authorization,
            envelope.delivery_id,
            envelope.payload_sha256.removeprefix("sha256:"),
            spec.review_route,
            "reviewer",
        ),
        effect,
        intent,
    )
    return store, intent


Runner = Callable[..., subprocess.CompletedProcess[bytes]]


class AgentBusSender:
    def __init__(
        self,
        bus_bin: Path,
        source_role: str,
        runner: Runner = subprocess.run,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        if not bus_bin.is_absolute() or not bus_bin.is_file():
            raise AcceptanceError("Agent Bus executable identity is invalid")
        self.bus_bin = bus_bin
        self.source_role = source_role
        self.runner = runner
        self.environment = dict(environment or os.environ)
        if self.environment.get("AGENT_BUS_AGENT") != source_role:
            raise AcceptanceError("Agent Bus source role identity is invalid")

    def run_payload(
        self, target_role: str, route: str, payload: bytes
    ) -> subprocess.CompletedProcess[bytes]:
        return self.runner(
            [
                str(self.bus_bin),
                "send",
                "--from",
                self.source_role,
                "--to",
                target_role,
                "--type",
                route,
                "--payload",
                payload.decode("utf-8"),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self.environment,
            timeout=20,
            shell=False,
            check=False,
        )

    def send(
        self, *, delivery_id: str, target_role: str, route: str, envelope: bytes
    ) -> TransportSendReceipt:
        decoded = ResultEnvelope.decode(envelope)
        if (
            decoded.delivery_id != delivery_id
            or decoded.target_role != target_role
            or decoded.route != route
            or decoded.source_role != self.source_role
        ):
            raise AcceptanceError("Agent Bus send identity drift")
        try:
            completed = self.run_payload(target_role, route, envelope)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise AcceptanceError("Agent Bus send outcome is unknown") from exc
        evidence = digest(f"bus-send\0{delivery_id}\0{digest(envelope)}\0{completed.returncode}")
        return TransportSendReceipt(completed.returncode == 0, evidence)


def write_evidence(path: Path, value: dict[str, object]) -> None:
    if path.is_symlink() or (path.parent.exists() and path.parent.is_symlink()):
        raise AcceptanceError("evidence path is redirected")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f"{path.name}.tmp-{os.getpid()}")
    with temp.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


def validate_event(args: argparse.Namespace, spec: RunSpec, role: str, event_type: str) -> None:
    if args.event_type != event_type or os.environ.get("AGENT_BUS_AGENT") != role:
        raise AcceptanceError("handler event role or route identity is invalid")
    if not str(args.event_id).isdigit() or int(args.event_id) < 1:
        raise AcceptanceError("handler event identity is invalid")
    verify_repo(args.repo, args.candidate_sha)
    if spec.frozen_base != args.candidate_sha:
        raise AcceptanceError("RunSpec candidate identity drift")


def send_command(args: argparse.Namespace) -> None:
    verify_repo(args.repo, args.candidate_sha)
    spec = make_spec(args.repo, args.scope, args.candidate_sha, args.state_root_binding)
    command = make_command(spec, args.scope)
    sender = AgentBusSender(args.bus_bin, "architect")
    try:
        completed = sender.run_payload("coder", spec.implement_route, command.encode())
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AcceptanceError("initial Agent Bus send outcome is unknown") from exc
    if completed.returncode != 0:
        raise AcceptanceError("initial Agent Bus send did not explicitly succeed")
    write_evidence(
        args.evidence,
        {
            "format": EVIDENCE_FORMAT,
            "kind": "command-sent",
            "scope": args.scope,
            "candidate_sha": args.candidate_sha,
            "run_spec_sha256": spec.sha256,
            "command_delivery_id": command.delivery_id,
            "command_envelope_sha256": digest(command.encode()),
        },
    )


def handle_command(args: argparse.Namespace) -> None:
    spec = make_spec(args.repo, args.scope, args.candidate_sha, args.state_root_binding)
    validate_event(args, spec, "coder", spec.implement_route)
    command = CommandEnvelope.decode(canonical_payload(args.payload))
    if command.encode() != make_command(spec, args.scope).encode():
        raise AcceptanceError("command envelope identity does not match the frozen acceptance")
    child_output, child_process = run_child(args.scope, "windows-command")
    store, intent = prepare_result_store(
        args.state_root, spec, command, child_output, child_process
    )
    decision = OutgoingIntentDispatcher(store, AgentBusSender(args.bus_bin, "coder")).dispatch()
    status = store.outgoing_status()
    if (
        decision.outcome is not DecisionOutcome.SAFE_CONTINUE
        or status.state is not TransportSendState.SENT
    ):
        raise AcceptanceError("result send did not reach exact sent evidence")
    write_evidence(
        args.evidence_dir / f"{args.scope}-target.json",
        {
            "format": EVIDENCE_FORMAT,
            "kind": "target-handler-completed",
            "scope": args.scope,
            "candidate_sha": args.candidate_sha,
            "run_spec_sha256": spec.sha256,
            "command_event_id": int(args.event_id),
            "command_delivery_id": command.delivery_id,
            "result_delivery_id": intent.delivery_id,
            "result_envelope_sha256": intent.envelope_sha256,
            "child_return_code": 0,
            "child_output_sha256": child_output,
            "store_sequence": status.sequence,
            "send_state": status.state.value,
        },
    )


def handle_result(args: argparse.Namespace) -> None:
    spec = make_spec(args.repo, args.scope, args.candidate_sha, args.state_root_binding)
    validate_event(args, spec, "reviewer", spec.review_route)
    command = make_command(spec, args.scope)
    result = ResultEnvelope.decode(canonical_payload(args.payload))
    expected = transition_values(
        spec, command, expected_child_sha256(args.scope, "windows-command")
    )[-1]
    if result.encode() != expected.encode():
        raise AcceptanceError("result envelope identity does not match the command causation")
    child_output, _child_process = run_child(args.scope, "mac-result")
    write_evidence(
        args.evidence_dir / f"{args.scope}-source.json",
        {
            "format": EVIDENCE_FORMAT,
            "kind": "source-handler-completed",
            "scope": args.scope,
            "candidate_sha": args.candidate_sha,
            "run_spec_sha256": spec.sha256,
            "result_event_id": int(args.event_id),
            "command_delivery_id": command.delivery_id,
            "result_delivery_id": result.delivery_id,
            "result_envelope_sha256": digest(result.encode()),
            "child_return_code": 0,
            "child_output_sha256": child_output,
        },
    )


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser()
    sub = root.add_subparsers(dest="action", required=True)

    def identity(target: argparse.ArgumentParser) -> None:
        target.add_argument("--scope", required=True)
        target.add_argument("--repo", required=True, type=Path)
        target.add_argument("--candidate-sha", required=True)
        target.add_argument("--state-root-binding", required=True)

    send = sub.add_parser("send-command")
    identity(send)
    send.add_argument("--bus-bin", required=True, type=Path)
    send.add_argument("--evidence", required=True, type=Path)

    for name in ("handle-command", "handle-result"):
        handler = sub.add_parser(name)
        identity(handler)
        handler.add_argument("--event-id", required=True)
        handler.add_argument("--event-type", required=True)
        handler.add_argument("--payload", required=True)
        handler.add_argument("--evidence-dir", required=True, type=Path)
        if name == "handle-command":
            handler.add_argument("--state-root", required=True, type=Path)
            handler.add_argument("--bus-bin", required=True, type=Path)

    return root


def main() -> int:
    try:
        args = parser().parse_args()
        if args.action == "send-command":
            send_command(args)
        elif args.action == "handle-command":
            handle_command(args)
        elif args.action == "handle-result":
            handle_result(args)
        else:
            handle_result(args)
        return 0
    except (AcceptanceError, ValueError, OSError) as exc:
        print(f"runtime-v2-bus-acceptance: {type(exc).__name__}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
