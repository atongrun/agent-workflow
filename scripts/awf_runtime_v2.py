#!/usr/bin/env python3
"""Installed structured-argv handlers for the fresh Runtime v2 single-card path."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from agent_workflow import node
from agent_workflow.runtime.single_card import (
    READINESS_RESULT_TYPE,
    RESULT_TYPE,
    role_binding_from_profile,
)
from agent_workflow.runtime.transport import ResultEnvelope
from agent_workflow.runtime.worker import (
    WorkerError,
    execute_worker_command,
    mark_worker_result_sent,
)


class HandlerError(RuntimeError):
    pass


def _payload(raw: str) -> dict[str, object]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HandlerError("payload is not valid JSON") from exc
    if not isinstance(value, dict):
        raise HandlerError("payload must be an object")
    return value


def _profile(path: str, expected_sha256: str):
    profile = node.load_installed_profile(path) or node.load_profile(path)
    if profile.digest.removeprefix("sha256:") != expected_sha256:
        raise HandlerError("listener profile digest drifted")
    return profile


def _send(bus: str, *, from_role: str, to_role: str, event_type: str, payload: dict) -> None:
    result = subprocess.run(
        [
            bus,
            "send",
            "--from",
            from_role,
            "--to",
            to_role,
            "--type",
            event_type,
            "--payload",
            json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
        ],
        check=False,
        stdin=subprocess.DEVNULL,
    )
    if result.returncode:
        raise HandlerError("Agent Bus result send failed; input remains unACKed")


def _atomic_bytes(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != raw:
            raise HandlerError("durable handler inbox conflicts")
        return
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        with temporary.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def readiness_request(args: argparse.Namespace) -> None:
    profile = _profile(args.profile, args.profile_sha256)
    payload = _payload(args.payload_json)
    required = {"nonce", "expires_at", "source_commit", "binding"}
    if set(payload) != required:
        raise HandlerError("readiness request fields are invalid")
    binding = role_binding_from_profile(profile)
    if payload["binding"] != binding.to_mapping():
        raise HandlerError("readiness requested binding does not match this listener")
    source_commit = str(payload["source_commit"])
    observed = subprocess.run(
        [
            "git",
            "--no-optional-locks",
            "-C",
            str(profile.repo),
            "cat-file",
            "-e",
            f"{source_commit}^{{commit}}",
        ],
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if observed.returncode:
        raise HandlerError("role workspace lacks the requested source commit; refresh it manually")
    readiness = node._local_readiness(profile)
    result = {
        "nonce": payload["nonce"],
        "expires_at": payload["expires_at"],
        "binding": binding.to_mapping(),
        "source_commit": source_commit,
        "tool_executable": readiness.tool_executable,
        "tool_version_sha256": readiness.tool_version_sha256,
        "bus_executable": readiness.bus_executable,
        "bus_provenance_sha256": readiness.bus_provenance_sha256,
        "bus_capabilities": list(readiness.bus_capabilities),
    }
    _send(
        readiness.bus_executable,
        from_role=profile.role,
        to_role="architect",
        event_type=READINESS_RESULT_TYPE,
        payload=result,
    )


def readiness_result(args: argparse.Namespace) -> None:
    payload = _payload(args.payload_json)
    nonce = str(payload.get("nonce", ""))
    binding = payload.get("binding")
    role = str(binding.get("role", "")) if isinstance(binding, dict) else ""
    if not nonce or role not in {"coder", "reviewer"}:
        raise HandlerError("readiness result identity is invalid")
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    _atomic_bytes(Path(args.state_root) / "runtime-v2" / "readiness" / nonce / f"{role}.json", raw)


def command(args: argparse.Namespace) -> None:
    profile = _profile(args.profile, args.profile_sha256)
    payload = _payload(args.payload_json)
    if set(payload) != {"envelope"} or not isinstance(payload["envelope"], str):
        raise HandlerError("worker command payload is invalid")
    try:
        result = execute_worker_command(
            envelope_bytes=payload["envelope"].encode("utf-8"),
            local_binding=role_binding_from_profile(profile),
            state_root=args.state_root,
            python_executable=sys.executable,
        )
    except WorkerError as exc:
        raise HandlerError(str(exc)) from exc
    readiness = node._local_readiness(profile)
    _send(
        readiness.bus_executable,
        from_role=profile.role,
        to_role="architect",
        event_type=RESULT_TYPE,
        payload={"envelope": result.envelope.encode().decode("utf-8")},
    )
    mark_worker_result_sent(result.journal_path, result.envelope)


def result(args: argparse.Namespace) -> None:
    payload = _payload(args.payload_json)
    if set(payload) != {"envelope"} or not isinstance(payload["envelope"], str):
        raise HandlerError("source result payload is invalid")
    envelope = ResultEnvelope.decode(payload["envelope"].encode("utf-8"))
    raw = envelope.encode()
    path = (
        Path(args.state_root)
        / "runtime-v2"
        / "inbox"
        / envelope.run_id
        / f"{envelope.delivery_id.removeprefix('awfv2:')}.json"
    )
    _atomic_bytes(path, raw)


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(prog="awf_runtime_v2")
    value.add_argument(
        "command", choices=("readiness-request", "readiness-result", "command", "result")
    )
    value.add_argument("--payload-json", required=True)
    value.add_argument("--profile", default="")
    value.add_argument("--profile-sha256", default="")
    value.add_argument("--state-root", required=True)
    return value


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    handlers = {
        "readiness-request": readiness_request,
        "readiness-result": readiness_result,
        "command": command,
        "result": result,
    }
    try:
        handlers[args.command](args)
    except (HandlerError, node.NodeError, OSError, ValueError) as exc:
        print(f"awf_runtime_v2: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
