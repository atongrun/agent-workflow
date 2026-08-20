"""Immutable values at the Runtime v2 package boundary."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

RUN_SPEC_FORMAT = "awf.runtime-v2.run-spec.v1"
INVOCATION_SPEC_FORMAT = "awf.runtime-v2.invocation-spec.v1"

_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_GIT_SHA_RE = re.compile(r"[0-9a-f]{40,64}")
_IDENTIFIER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]*")
_ENV_NAME_RE = re.compile(r"[^=\x00-\x1f\x7f]+")
_SENSITIVE_ENV_PARTS = ("TOKEN", "PASSWORD", "SECRET", "CREDENTIAL", "PRIVATE_KEY")
_CODER_PROVIDERS = frozenset({"codex", "opencode"})
_REVIEWER_PROVIDERS = frozenset({"codex", "opencode", "pi"})
_MAX_PROVIDER_INPUT_BYTES = 256 * 1024
_MAX_ENV_VALUE_CHARS = 32_767
_MAX_ENVIRONMENT_ITEMS = 256
_MAX_ENVIRONMENT_BYTES = 512 * 1024


class ContractError(ValueError):
    """A Runtime boundary value is malformed or insufficiently bound."""


def _strict_mapping(value: object, name: str, keys: frozenset[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractError(f"{name} must be an object")
    actual = frozenset(value)
    if actual != keys:
        missing = sorted(keys - actual)
        extra = sorted(actual - keys)
        raise ContractError(f"{name} keys mismatch: missing={missing}, extra={extra}")
    return value


def _strict_text(name: str, value: object, *, maximum: int = 512) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or len(value) > maximum:
        raise ContractError(f"{name} must be a bounded nonblank string")
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        raise ContractError(f"{name} contains a control character")
    return value


def _multiline_text(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{name} must be nonblank UTF-8 text")
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ContractError(f"{name} must be valid UTF-8 text") from exc
    if len(encoded) > _MAX_PROVIDER_INPUT_BYTES:
        raise ContractError(f"{name} exceeds the provider input bound")
    if any(
        (ord(char) < 0x20 and char not in "\t\n\r") or ord(char) == 0x7F for char in value
    ):
        raise ContractError(f"{name} contains a prohibited control character")
    return value


def _executable(value: object) -> str:
    executable = _strict_text("executable", value, maximum=4096)
    if os.path.isabs(executable):
        _absolute_path("executable", executable)
    elif any(char.isspace() for char in executable) or "/" in executable or "\\" in executable:
        raise ContractError("a relative executable must be one structured token")
    return executable


def _sha256(name: str, value: object) -> str:
    text = _strict_text(name, value, maximum=64)
    if _SHA256_RE.fullmatch(text) is None:
        raise ContractError(f"{name} must be a lowercase SHA-256")
    return text


def _identifier(name: str, value: object) -> str:
    text = _strict_text(name, value, maximum=200)
    if _IDENTIFIER_RE.fullmatch(text) is None:
        raise ContractError(f"{name} must be a canonical identifier")
    return text


def _git_sha(name: str, value: object) -> str:
    text = _strict_text(name, value, maximum=64)
    if _GIT_SHA_RE.fullmatch(text) is None:
        raise ContractError(f"{name} must be a lowercase Git object ID")
    return text


def _capacity(name: str, value: object, *, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum or value > 1000:
        raise ContractError(f"{name} must be an integer in [{minimum}, 1000]")
    return value


def _nonnegative_integer(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContractError(f"{name} must be a nonnegative integer")
    return value


def _repo_relative_path(name: str, value: object) -> str:
    text = _strict_text(name, value, maximum=1024)
    if "\\" in text or text.startswith("/"):
        raise ContractError(f"{name} must be a canonical repository-relative POSIX path")
    path = PurePosixPath(text)
    if path.as_posix() != text or text in {".", ".."} or ".." in path.parts:
        raise ContractError(f"{name} must be a canonical repository-relative POSIX path")
    return text


def _absolute_path(name: str, value: object) -> str:
    text = _strict_text(name, value, maximum=4096)
    path = Path(text)
    if not path.is_absolute() or any(part in {".", ".."} for part in path.parts):
        raise ContractError(f"{name} must be an absolute normalized local path")
    if os.path.normpath(text) != text:
        raise ContractError(f"{name} must be an absolute normalized local path")
    return text


def _workspace_path(name: str, value: object, workspace: Path) -> str:
    if isinstance(value, str) and Path(value).is_absolute():
        text = _absolute_path(name, value)
        candidate = Path(text)
    else:
        text = _repo_relative_path(name, value)
        candidate = workspace.joinpath(*PurePosixPath(text).parts)
    try:
        candidate.resolve().relative_to(workspace.resolve())
    except ValueError as exc:
        raise ContractError(f"{name} must be inside workspace") from exc
    return text


def _environment(value: object) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, Mapping):
        raise ContractError("environment must be an object")
    if len(value) > _MAX_ENVIRONMENT_ITEMS:
        raise ContractError("environment contains too many entries")
    pairs: list[tuple[str, str]] = []
    total_bytes = 0
    for raw_name, raw_value in value.items():
        name = _strict_text("environment name", raw_name, maximum=128)
        if not isinstance(raw_value, str) or len(raw_value) > _MAX_ENV_VALUE_CHARS:
            raise ContractError(f"environment[{name}] must be bounded text")
        if "\0" in raw_value:
            raise ContractError(f"environment[{name}] contains NUL")
        if _ENV_NAME_RE.fullmatch(name) is None:
            raise ContractError(f"environment name is invalid: {name}")
        if any(part in name.upper() for part in _SENSITIVE_ENV_PARTS):
            raise ContractError(f"credential-bearing environment name is forbidden: {name}")
        try:
            total_bytes += len(name.encode("utf-8")) + len(raw_value.encode("utf-8"))
        except UnicodeEncodeError as exc:
            raise ContractError(f"environment[{name}] must be valid UTF-8 text") from exc
        if total_bytes > _MAX_ENVIRONMENT_BYTES:
            raise ContractError("environment exceeds the canonical identity bound")
        pairs.append((name, raw_value))
    return tuple(sorted(pairs))


def _environment_tuple(value: object) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, tuple):
        raise ContractError("environment must be an immutable tuple")
    try:
        mapping = dict(value)
    except (TypeError, ValueError) as exc:
        raise ContractError("environment must contain name/value pairs") from exc
    normalized = _environment(mapping)
    if normalized != value:
        raise ContractError("environment must be unique and sorted")
    return normalized


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


@dataclass(frozen=True, slots=True)
class ProviderSelection:
    provider: str
    model: str

    def __post_init__(self) -> None:
        _strict_text("provider", self.provider, maximum=32)
        _strict_text("model", self.model, maximum=200)

    @classmethod
    def from_mapping(cls, value: object, name: str) -> ProviderSelection:
        mapping = _strict_mapping(value, name, frozenset({"provider", "model"}))
        return cls(provider=mapping["provider"], model=mapping["model"])

    def to_mapping(self) -> dict[str, str]:
        return {"provider": self.provider, "model": self.model}


@dataclass(frozen=True, slots=True)
class RunSpec:
    run_id: str
    task_id: str
    task_card: str
    task_card_sha256: str
    repository: str
    frozen_base: str
    task_branch: str
    state_root_sha256: str
    semantic_contract_sha256: str
    coder: ProviderSelection
    reviewer: ProviderSelection
    implement_attempts: int
    review_attempts: int
    rework_budget: int
    implement_route: str
    review_route: str
    rework_route: str
    implementation_report: str
    review_report: str
    format: str = RUN_SPEC_FORMAT

    _KEYS = frozenset(
        {
            "format",
            "run_id",
            "task_id",
            "task_card",
            "task_card_sha256",
            "repository",
            "frozen_base",
            "task_branch",
            "state_root_sha256",
            "semantic_contract_sha256",
            "coder",
            "reviewer",
            "implement_attempts",
            "review_attempts",
            "rework_budget",
            "implement_route",
            "review_route",
            "rework_route",
            "implementation_report",
            "review_report",
        }
    )

    def __post_init__(self) -> None:
        if self.format != RUN_SPEC_FORMAT:
            raise ContractError("RunSpec format is unsupported")
        _identifier("run_id", self.run_id)
        _identifier("task_id", self.task_id)
        _repo_relative_path("task_card", self.task_card)
        _sha256("task_card_sha256", self.task_card_sha256)
        _strict_text("repository", self.repository, maximum=500)
        _git_sha("frozen_base", self.frozen_base)
        _strict_text("task_branch", self.task_branch, maximum=300)
        _sha256("state_root_sha256", self.state_root_sha256)
        _sha256("semantic_contract_sha256", self.semantic_contract_sha256)
        if not isinstance(self.coder, ProviderSelection):
            raise ContractError("coder must be a ProviderSelection")
        if not isinstance(self.reviewer, ProviderSelection):
            raise ContractError("reviewer must be a ProviderSelection")
        if self.coder.provider not in _CODER_PROVIDERS:
            raise ContractError("coder provider is unsupported")
        if self.reviewer.provider not in _REVIEWER_PROVIDERS:
            raise ContractError("reviewer provider is unsupported")
        _capacity("implement_attempts", self.implement_attempts, minimum=1)
        _capacity("review_attempts", self.review_attempts, minimum=1)
        _capacity("rework_budget", self.rework_budget, minimum=0)
        routes = (
            _identifier("implement_route", self.implement_route),
            _identifier("review_route", self.review_route),
            _identifier("rework_route", self.rework_route),
        )
        if len(set(routes)) != len(routes):
            raise ContractError("implement, review, and rework routes must be distinct")
        implementation = _repo_relative_path("implementation_report", self.implementation_report)
        review = _repo_relative_path("review_report", self.review_report)
        if implementation == review:
            raise ContractError("implementation and review reports must be distinct")

    @classmethod
    def from_mapping(cls, value: object) -> RunSpec:
        mapping = _strict_mapping(value, "RunSpec", cls._KEYS)
        return cls(
            format=mapping["format"],
            run_id=mapping["run_id"],
            task_id=mapping["task_id"],
            task_card=mapping["task_card"],
            task_card_sha256=mapping["task_card_sha256"],
            repository=mapping["repository"],
            frozen_base=mapping["frozen_base"],
            task_branch=mapping["task_branch"],
            state_root_sha256=mapping["state_root_sha256"],
            semantic_contract_sha256=mapping["semantic_contract_sha256"],
            coder=ProviderSelection.from_mapping(mapping["coder"], "coder"),
            reviewer=ProviderSelection.from_mapping(mapping["reviewer"], "reviewer"),
            implement_attempts=mapping["implement_attempts"],
            review_attempts=mapping["review_attempts"],
            rework_budget=mapping["rework_budget"],
            implement_route=mapping["implement_route"],
            review_route=mapping["review_route"],
            rework_route=mapping["rework_route"],
            implementation_report=mapping["implementation_report"],
            review_report=mapping["review_report"],
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "format": self.format,
            "run_id": self.run_id,
            "task_id": self.task_id,
            "task_card": self.task_card,
            "task_card_sha256": self.task_card_sha256,
            "repository": self.repository,
            "frozen_base": self.frozen_base,
            "task_branch": self.task_branch,
            "state_root_sha256": self.state_root_sha256,
            "semantic_contract_sha256": self.semantic_contract_sha256,
            "coder": self.coder.to_mapping(),
            "reviewer": self.reviewer.to_mapping(),
            "implement_attempts": self.implement_attempts,
            "review_attempts": self.review_attempts,
            "rework_budget": self.rework_budget,
            "implement_route": self.implement_route,
            "review_route": self.review_route,
            "rework_route": self.rework_route,
            "implementation_report": self.implementation_report,
            "review_report": self.review_report,
        }

    @property
    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.to_mapping())

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes).hexdigest()


@dataclass(frozen=True, slots=True)
class InvocationSpec:
    invocation_id: str
    run_id: str
    task_id: str
    authorization_sha256: str
    role: str
    provider: str
    model: str
    executable: str
    workspace: str
    input_path: str
    input_text: str
    report_path: str
    provider_args: tuple[str, ...] = ()
    environment: tuple[tuple[str, str], ...] = ()
    format: str = INVOCATION_SPEC_FORMAT

    _KEYS = frozenset(
        {
            "format",
            "invocation_id",
            "run_id",
            "task_id",
            "authorization_sha256",
            "role",
            "provider",
            "model",
            "executable",
            "workspace",
            "input_path",
            "input_text",
            "report_path",
            "provider_args",
            "environment",
        }
    )

    def __post_init__(self) -> None:
        if self.format != INVOCATION_SPEC_FORMAT:
            raise ContractError("InvocationSpec format is unsupported")
        _identifier("invocation_id", self.invocation_id)
        _identifier("run_id", self.run_id)
        _identifier("task_id", self.task_id)
        _sha256("authorization_sha256", self.authorization_sha256)
        if self.role not in {"coder", "reviewer"}:
            raise ContractError("role is unsupported")
        allowed = _CODER_PROVIDERS if self.role == "coder" else _REVIEWER_PROVIDERS
        if self.provider not in allowed:
            raise ContractError("provider is unsupported for role")
        if self.model:
            _strict_text("model", self.model, maximum=200)
        elif self.model != "":
            raise ContractError("model must be text")
        _executable(self.executable)
        workspace = Path(_absolute_path("workspace", self.workspace))
        input_path = Path(_absolute_path("input_path", self.input_path))
        try:
            input_path.resolve().relative_to(workspace.resolve())
        except ValueError as exc:
            raise ContractError("input_path must be inside workspace") from exc
        _workspace_path("report_path", self.report_path, workspace)
        _multiline_text("input_text", self.input_text)
        if not isinstance(self.provider_args, tuple):
            raise ContractError("provider_args must be an immutable tuple")
        for index, item in enumerate(self.provider_args):
            argument = _strict_text(f"provider_args[{index}]", item, maximum=4096)
            normalized = argument.upper().replace("-", "_")
            if argument.startswith("-") and any(
                part in normalized for part in _SENSITIVE_ENV_PARTS
            ):
                raise ContractError("credential-bearing provider argument is forbidden")
        _environment_tuple(self.environment)

    @classmethod
    def from_mapping(cls, value: object) -> InvocationSpec:
        mapping = _strict_mapping(value, "InvocationSpec", cls._KEYS)
        raw_args = mapping["provider_args"]
        if not isinstance(raw_args, list):
            raise ContractError("provider_args must be an array")
        return cls(
            format=mapping["format"],
            invocation_id=mapping["invocation_id"],
            run_id=mapping["run_id"],
            task_id=mapping["task_id"],
            authorization_sha256=mapping["authorization_sha256"],
            role=mapping["role"],
            provider=mapping["provider"],
            model=mapping["model"],
            executable=mapping["executable"],
            workspace=mapping["workspace"],
            input_path=mapping["input_path"],
            input_text=mapping["input_text"],
            report_path=mapping["report_path"],
            provider_args=tuple(raw_args),
            environment=_environment(mapping["environment"]),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "format": self.format,
            "invocation_id": self.invocation_id,
            "run_id": self.run_id,
            "task_id": self.task_id,
            "authorization_sha256": self.authorization_sha256,
            "role": self.role,
            "provider": self.provider,
            "model": self.model,
            "executable": self.executable,
            "workspace": self.workspace,
            "input_path": self.input_path,
            "input_text": self.input_text,
            "report_path": self.report_path,
            "provider_args": list(self.provider_args),
            "environment": dict(self.environment),
        }

    @property
    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.to_mapping())

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes).hexdigest()


@dataclass(frozen=True, slots=True)
class RenderedInputFile:
    path: str
    content: bytes

    def __post_init__(self) -> None:
        _absolute_path("file input path", self.path)
        if not isinstance(self.content, bytes) or len(self.content) > _MAX_PROVIDER_INPUT_BYTES:
            raise ContractError("file input content must be bounded immutable bytes")

    def to_mapping(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "sha256": hashlib.sha256(self.content).hexdigest(),
            "length": len(self.content),
        }


@dataclass(frozen=True, slots=True)
class RenderedInvocation:
    executable: str
    argv: tuple[str, ...]
    cwd: str
    stdin: bytes | None = None
    environment: tuple[tuple[str, str], ...] = ()
    file_inputs: tuple[RenderedInputFile, ...] = ()

    def __post_init__(self) -> None:
        _executable(self.executable)
        if not isinstance(self.argv, tuple):
            raise ContractError("argv must be an immutable tuple")
        for index, item in enumerate(self.argv):
            _multiline_text(f"argv[{index}]", item)
        _absolute_path("cwd", self.cwd)
        if self.stdin is not None and (
            not isinstance(self.stdin, bytes) or len(self.stdin) > _MAX_PROVIDER_INPUT_BYTES
        ):
            raise ContractError("stdin must be bounded immutable bytes or None")
        _environment_tuple(self.environment)
        if not isinstance(self.file_inputs, tuple):
            raise ContractError("file_inputs must be an immutable tuple")
        if any(not isinstance(item, RenderedInputFile) for item in self.file_inputs):
            raise ContractError("file_inputs must contain RenderedInputFile values")
        if len({item.path for item in self.file_inputs}) != len(self.file_inputs):
            raise ContractError("file input paths must be unique")
        cwd = Path(self.cwd)
        for item in self.file_inputs:
            try:
                Path(item.path).resolve().relative_to(cwd.resolve())
            except ValueError as exc:
                raise ContractError("file input paths must be inside cwd") from exc

    def to_mapping(self) -> dict[str, Any]:
        stdin_identity = None
        if self.stdin is not None:
            stdin_identity = {
                "sha256": hashlib.sha256(self.stdin).hexdigest(),
                "length": len(self.stdin),
            }
        return {
            "executable": self.executable,
            "argv": list(self.argv),
            "cwd": self.cwd,
            "stdin": stdin_identity,
            "environment": dict(self.environment),
            "file_inputs": [item.to_mapping() for item in self.file_inputs],
        }

    @property
    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.to_mapping())

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes).hexdigest()
