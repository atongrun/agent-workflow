"""Fresh-only compilation and local pointer boundary for one Runtime v2 TaskCard."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from agent_workflow.node import NodeProfile

from .contracts import FreshRunSpec, ModelSelection, RoleBinding, _canonical_bytes

READINESS_REQUEST_TYPE = "control:awf-runtime-v2-readiness-v1"
READINESS_RESULT_TYPE = "control:awf-runtime-v2-readiness-result-v1"
COMMAND_TYPE = "task:awf-runtime-v2-command-v1"
RESULT_TYPE = "result:awf-runtime-v2-result-v1"
ACTIVE_RUN_FORMAT = "awf.runtime-v2.active-run-pointer.v1"
REQUIRED_BUS_CAPABILITY = "agent-bus.listen.on-argv.v1"

_TASK_ID = re.compile(
    r"(?m)^## Task ID[ \t]*\r?\n(?:[ \t]*\r?\n)*([A-Za-z0-9][A-Za-z0-9._-]*)[ \t]*$"
)
_TASK_BRANCH = re.compile(r"(?m)^- \*\*Task branch\*\*: `([^`]+)`\s*$")


class SingleCardError(RuntimeError):
    """Fresh single-card compilation or pointer validation failed closed."""


@dataclass(frozen=True, slots=True)
class ReadinessFact:
    nonce: str
    expires_at: int
    binding: RoleBinding
    source_commit: str
    tool_executable: str
    tool_version_sha256: str
    bus_executable: str
    bus_provenance_sha256: str
    bus_capabilities: tuple[str, ...]

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[0-9a-f]{32}", self.nonce):
            raise SingleCardError("readiness nonce is invalid")
        if isinstance(self.expires_at, bool) or not isinstance(self.expires_at, int):
            raise SingleCardError("readiness expiry is invalid")
        if REQUIRED_BUS_CAPABILITY not in self.bus_capabilities:
            raise SingleCardError("Agent Bus structured argv capability is absent")
        if not re.fullmatch(r"[0-9a-f]{40,64}", self.source_commit):
            raise SingleCardError("readiness source commit is invalid")
        for name, value in (
            ("tool executable", self.tool_executable),
            ("bus executable", self.bus_executable),
        ):
            if not value or not Path(value).is_absolute():
                raise SingleCardError(f"readiness {name} is not an absolute path")
        for name, value in (
            ("tool version", self.tool_version_sha256),
            ("bus provenance", self.bus_provenance_sha256),
        ):
            if not re.fullmatch(r"[0-9a-f]{64}", value):
                raise SingleCardError(f"readiness {name} digest is invalid")


def role_binding_from_profile(profile: NodeProfile) -> RoleBinding:
    model = str(profile.values.get("model", ""))
    selection = ModelSelection("explicit", model) if model else ModelSelection("tool-default", "")
    return RoleBinding(
        role=profile.role,
        agent_tool=str(profile.values["tool"]),
        model_selection=selection,
        profile=str(profile.path.resolve()),
        profile_sha256=profile.digest.removeprefix("sha256:"),
        workspace=str(profile.repo),
    )


def _git(repo: Path, *args: str, input_bytes: bytes | None = None) -> bytes:
    completed = subprocess.run(
        ["git", "--no-optional-locks", "-C", str(repo), *args],
        input=input_bytes,
        capture_output=True,
        check=False,
    )
    if completed.returncode:
        raise SingleCardError("trusted Git observation failed during fresh compilation")
    return completed.stdout


def _state_root_sha256(path: Path) -> str:
    return hashlib.sha256(("awf-state-root-v1\0" + str(path.resolve())).encode()).hexdigest()


def compile_fresh_run_spec(
    *,
    repo: str | Path,
    card: str | Path,
    repository: str,
    state_root: str | Path,
    bindings: Mapping[str, RoleBinding],
    rework_budget: int = 1,
) -> FreshRunSpec:
    """Compile only committed canonical Git bytes after all readiness facts are known."""
    root = Path(repo).resolve()
    card_path = Path(card)
    if card_path.is_absolute():
        try:
            relative = card_path.resolve().relative_to(root).as_posix()
        except ValueError as exc:
            raise SingleCardError("TaskCard escapes the repository") from exc
    else:
        relative = card_path.as_posix()
    if relative.startswith("../") or "\\" in relative:
        raise SingleCardError("TaskCard path is not repository-relative")
    base = _git(root, "rev-parse", "HEAD^{commit}").decode("ascii").strip()
    committed = _git(root, "show", f"{base}:{relative}")
    try:
        working = (root / relative).read_bytes()
    except OSError as exc:
        raise SingleCardError("committed TaskCard is unavailable in the working tree") from exc
    if working != committed:
        raise SingleCardError("TaskCard working bytes differ from the committed frozen bytes")
    try:
        text = committed.decode("utf-8")
    except UnicodeError as exc:
        raise SingleCardError("TaskCard is not strict UTF-8") from exc
    task_match = _TASK_ID.search(text)
    if task_match is None:
        raise SingleCardError("TaskCard has no canonical Task ID")
    task_id = task_match.group(1)
    branch_match = _TASK_BRANCH.search(text)
    branch = branch_match.group(1) if branch_match else f"codex/{task_id}"
    if set(bindings) != {"architect", "coder", "reviewer"}:
        raise SingleCardError("fresh compilation requires exact Architect/Coder/Reviewer bindings")
    for role, binding in bindings.items():
        if binding.role != role:
            raise SingleCardError(f"fresh {role} binding identity drifted")
    semantic_path = "docs/plans/runtime-v2-development-plan.md"
    semantic = _git(root, "show", f"{base}:{semantic_path}")
    resolved_state = Path(state_root).expanduser().resolve()
    return FreshRunSpec(
        run_id=f"fresh-{task_id}-{base[:12]}",
        task_id=task_id,
        task_card=relative,
        task_card_sha256=hashlib.sha256(committed).hexdigest(),
        repository=repository,
        frozen_base=base,
        task_branch=branch,
        state_root_sha256=_state_root_sha256(resolved_state),
        semantic_contract_sha256=hashlib.sha256(semantic).hexdigest(),
        architect=bindings["architect"],
        coder=bindings["coder"],
        reviewer=bindings["reviewer"],
        implement_attempts=1,
        review_attempts=2,
        rework_budget=rework_budget,
        implement_route="task:awf-runtime-v2-implement-v1",
        review_route="task:awf-runtime-v2-review-v1",
        rework_route="task:awf-runtime-v2-rework-v1",
        architect_route="decision:awf-runtime-v2-architect-v1",
        implementation_report=f".awf/artifacts/impl-report-{task_id}.md",
        review_report=f".awf/artifacts/review-report-{task_id}.md",
        decision_report=f".awf/artifacts/decision-{task_id}.md",
    )


def active_run_path(repo: str | Path) -> Path:
    return Path(repo).resolve() / ".awf" / "active-run.json"


def write_active_run(repo: str | Path, spec: FreshRunSpec, authority_path: Path) -> Path:
    path = active_run_path(repo)
    value = {
        "format": ACTIVE_RUN_FORMAT,
        "run_id": spec.run_id,
        "run_spec_sha256": spec.sha256,
        "state_root_sha256": spec.state_root_sha256,
        "authority_path": str(authority_path.resolve()),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{secrets.token_hex(8)}")
    descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(_canonical_bytes(value) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def read_active_run(repo: str | Path) -> dict[str, str] | None:
    """Read only the fresh pointer; never scan or interpret legacy RunLedger state."""
    path = active_run_path(repo)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    keys = {
        "format",
        "run_id",
        "run_spec_sha256",
        "state_root_sha256",
        "authority_path",
    }
    if not isinstance(value, dict) or set(value) != keys or value["format"] != ACTIVE_RUN_FORMAT:
        return None
    authority = Path(str(value["authority_path"]))
    if not authority.is_absolute() or not authority.is_file():
        return None
    try:
        envelope = json.loads(authority.read_text(encoding="utf-8"))
        payload = envelope["payload"]
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError):
        return None
    if (
        not isinstance(payload, dict)
        or payload.get("run_id") != value["run_id"]
        or payload.get("run_spec_sha256") != value["run_spec_sha256"]
        or payload.get("state_root_sha256") != value["state_root_sha256"]
    ):
        return None
    return {key: str(item) for key, item in value.items()}
