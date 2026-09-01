"""The two-method Local/SSH execution boundary and remote JobReceipt contract."""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass
from enum import StrEnum

from .contracts import ContractError, TaskSpec, canonical_bytes, sha256

_HEX = set("0123456789abcdef")
_ID = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")


class ExecutorError(RuntimeError):
    """One fixed executor invocation failed or returned an invalid receipt."""


class ReceiptStatus(StrEnum):
    NOT_FOUND = "NOT_FOUND"
    RUNNING = "RUNNING"
    TERMINAL = "TERMINAL"


@dataclass(frozen=True, slots=True)
class JobSpec:
    job_id: str
    operation_id: str
    task: TaskSpec
    reviewed_head_sha: str = ""
    rework_count: int = 0

    def __post_init__(self) -> None:
        if (
            not self.job_id
            or len(self.job_id) > 128
            or any(character not in _ID for character in self.job_id)
            or len(self.operation_id) > 128
            or not self.operation_id
            or any(character not in _ID for character in self.operation_id)
            or self.rework_count < 0
        ):
            raise ContractError("JobSpec identity is invalid")
        if self.rework_count and (
            len(self.reviewed_head_sha) not in (40, 64)
            or any(character not in _HEX for character in self.reviewed_head_sha)
        ):
            raise ContractError("rework JobSpec reviewed head is invalid")
        if not self.rework_count and self.reviewed_head_sha:
            raise ContractError("initial JobSpec has a reviewed head")

    @property
    def request_sha256(self) -> str:
        return sha256(asdict(self))

    def document(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class JobReceipt:
    job_id: str
    request_sha256: str
    status: ReceiptStatus
    result: dict[str, object] | None = None
    provenance: dict[str, str] | None = None
    diagnostics: str = ""

    @classmethod
    def from_bytes(cls, raw: bytes) -> JobReceipt:
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ExecutorError("executor stdout is not one JobReceipt") from exc
        if not isinstance(value, dict) or set(value) != {
            "job_id",
            "request_sha256",
            "status",
            "result",
            "provenance",
            "diagnostics",
        }:
            raise ExecutorError("executor JobReceipt fields are invalid")
        try:
            status = ReceiptStatus(value["status"])
        except (TypeError, ValueError) as exc:
            raise ExecutorError("executor JobReceipt status is invalid") from exc
        if not isinstance(value["job_id"], str) or not isinstance(value["request_sha256"], str):
            raise ExecutorError("executor JobReceipt identity is invalid")
        if value["result"] is not None and not isinstance(value["result"], dict):
            raise ExecutorError("executor JobReceipt result is invalid")
        if value["provenance"] is not None and not isinstance(value["provenance"], dict):
            raise ExecutorError("executor JobReceipt provenance is invalid")
        if not isinstance(value["diagnostics"], str):
            raise ExecutorError("executor JobReceipt diagnostics are invalid")
        return cls(
            value["job_id"],
            value["request_sha256"],
            status,
            value["result"],
            value["provenance"],
            value["diagnostics"],
        )

    def bytes(self) -> bytes:
        return canonical_bytes(asdict(self))


class LocalExecutor:
    def __init__(self, command: tuple[str, ...] = ("awf-agent",)) -> None:
        self._command = command

    def execute(self, job: JobSpec) -> JobReceipt:
        return self._invoke("execute", canonical_bytes(job.document()))

    def inspect(self, job_id: str) -> JobReceipt:
        return self._invoke("inspect", canonical_bytes({"job_id": job_id}))

    def _invoke(self, action: str, stdin: bytes) -> JobReceipt:
        try:
            completed = subprocess.run(
                [*self._command, action],
                shell=False,
                input=stdin,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
        except OSError as exc:
            raise ExecutorError("local awf-agent could not start") from exc
        if completed.returncode != 0:
            raise ExecutorError(completed.stderr.decode("utf-8", errors="replace")[:4096])
        return JobReceipt.from_bytes(completed.stdout)


class SSHExecutor:
    def __init__(self, ssh_target: str, ssh_binary: str = "ssh") -> None:
        if not ssh_target or any(character.isspace() for character in ssh_target):
            raise ContractError("SSH target is invalid")
        self._prefix = (ssh_binary, ssh_target, "awf-agent")

    def execute(self, job: JobSpec) -> JobReceipt:
        return self._invoke("execute", canonical_bytes(job.document()))

    def inspect(self, job_id: str) -> JobReceipt:
        return self._invoke("inspect", canonical_bytes({"job_id": job_id}))

    def _invoke(self, action: str, stdin: bytes) -> JobReceipt:
        try:
            completed = subprocess.run(
                [*self._prefix, action],
                shell=False,
                input=stdin,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
        except OSError as exc:
            raise ExecutorError("SSH process could not start") from exc
        if completed.returncode != 0:
            detail = completed.stderr.decode("utf-8", errors="replace")[:4096]
            raise ExecutorError(detail or "SSH awf-agent failed")
        return JobReceipt.from_bytes(completed.stdout)
