"""Small durable facts for the Architect-owned Plan happy path.

This module is deliberately not an execution engine.  The existing operations
dispatcher and role handlers continue to own TaskCard execution, review,
rework, Git publication and handler-success/ACK behavior.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Mapping

from agent_workflow.state_root import state_root_binding

PLAN_RUN_FORMAT = "awf.plan-run.v1"
PLAN_FACT_FORMAT = "awf.plan-fact.v1"
ROLE_BINDING_FORMAT = "awf.plan-role-binding.v1"
COMPLETED_CARD_FORMAT = "awf.completed-card-fact.v1"
PLAN_START_TYPE = "task:awf-plan-start-v1"

_SHA256 = re.compile(r"[0-9a-f]{64}")
_GIT_OID = re.compile(r"[0-9a-f]{40,64}")
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,199}")
_FROZEN_BASE = re.compile(r"(?m)^- \*\*Frozen base\*\*: `([0-9a-f]{40,64})`(?:\s+[^\r\n]*)?$")
_SELECTION = re.compile(r"<!--\s*awf-reviewer-selection\s*\n(.*?)\n\s*-->", re.DOTALL)
_DECISION = re.compile(r"(?mi)^\*\*Verdict:\*\*\s*(approve|request_changes|reject|escalate)\s*$")
_DECISION_PRESENTATION = re.compile(
    r"(?ix)^(?:"
    r"verdict\s*:\s*(approve|request_changes|reject|escalate)"
    r"|\*\*\s*verdict\s*:\s*(approve|request_changes|reject|escalate)\s*\*\*"
    r"|\*\*\s*verdict\s*:\s*\*\*\s*(approve|request_changes|reject|escalate)"
    r"|\*\*\s*verdict\s*\*\*\s*:\s*(approve|request_changes|reject|escalate)"
    r")$"
)
_DECISION_LABEL = re.compile(r"(?i)^(?:\*\*\s*)?verdict\b")
_DECISION_CODE_VALUE = re.compile(
    r"(?i)(:\s*(?:\*\*\s*)?)`(approve|request_changes|reject|escalate)`"
    r"(?=\s*(?:\*\*)?\s*$)"
)
_DECISION_TRUSTED_GATE_PRESENTATION = re.compile(
    r"(?i)^\*\*\s*verdict\s*:\s*(approve|request_changes|reject|escalate)\s*\*\*"
    r"\s*(?:→|->)\s*trusted-merge-gate\s*$"
)
_DECISION_FINAL_MERGE_PRESENTATION = re.compile(
    r"(?i)(?:^|[.!?]\s+)decision\s+final\s*:\s*\*\*\s*(approve)"
    r"\s*(?:→|->)\s*merge\s*\*\*"
    r"\s*[.;]?\s*$"
)
_DECISION_FINAL_MERGE_LABEL = re.compile(r"(?i)(?:^|[.!?]\s+)decision\s+final\s*:")
_DECISION_INLINE_PRESENTATION = re.compile(
    r"(?i)(?:^|[.!?]\s+)verdict\s*:?\s*(?:"
    r"\*\*(approve|request_changes|reject|escalate)\*\*"
    r"|`(approve|request_changes|reject|escalate)`"
    r")\s+is\s+final\s*[.;]?\s*$"
)
_DECISION_INLINE_LABEL = re.compile(r"(?i)(?:^|[.!?]\s+)verdict\s*:?\s*(?:\*\*|`)")
_CLOSED_NEXT = frozenset({"MILESTONE_COMPLETE", "BLOCKED"})


class PlanLoopError(RuntimeError):
    """A Plan fact, Architect output, or durable PlanRun is unsafe."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _canonical(value: Mapping[str, object]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _digest(value: Mapping[str, object]) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _git(repo: Path, *args: str, binary: bool = False) -> str | bytes:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PlanLoopError("trusted Git observation failed") from exc
    if result.returncode:
        raise PlanLoopError("trusted Git observation failed")
    if binary:
        return result.stdout
    try:
        return result.stdout.decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise PlanLoopError("trusted Git observation is not UTF-8") from exc


def _repo_relative(repo: Path, path: Path) -> str:
    try:
        relative = path.resolve(strict=True).relative_to(repo.resolve(strict=True)).as_posix()
    except (OSError, ValueError) as exc:
        raise PlanLoopError("Plan must be a regular file inside the repository") from exc
    pure = PurePosixPath(relative)
    if relative in {"", "."} or ".." in pure.parts or path.is_symlink() or not path.is_file():
        raise PlanLoopError("Plan must be a regular tracked repository file")
    return relative


@dataclass(frozen=True, slots=True)
class ArchitectBinding:
    profile: str
    profile_sha256: str
    workspace: str
    tool: str
    model_mode: str
    model_ref: str

    def __post_init__(self) -> None:
        if not self.profile or not self.workspace or self.tool not in {"pi", "opencode", "codex"}:
            raise PlanLoopError("Architect binding must name one exact supported profile/workspace")
        if (
            not self.profile_sha256.startswith("sha256:")
            or _SHA256.fullmatch(self.profile_sha256.removeprefix("sha256:")) is None
        ):
            raise PlanLoopError("Architect profile digest is invalid")
        if self.model_mode not in {"tool-default", "explicit"}:
            raise PlanLoopError("Architect model-selection mode is invalid")
        if (self.model_mode == "tool-default" and self.model_ref) or (
            self.model_mode == "explicit" and not self.model_ref
        ):
            raise PlanLoopError("Architect model-selection reference is inconsistent")

    @property
    def model(self) -> str:
        return self.model_ref if self.model_mode == "explicit" else ""

    def to_mapping(self) -> dict[str, object]:
        return {
            "format": ROLE_BINDING_FORMAT,
            "profile": self.profile,
            "profile_sha256": self.profile_sha256,
            "workspace": self.workspace,
            "tool": self.tool,
            "model_selection": {"mode": self.model_mode, "ref": self.model_ref},
        }

    @classmethod
    def from_mapping(cls, value: object) -> ArchitectBinding:
        if not isinstance(value, Mapping) or set(value) != {
            "format",
            "profile",
            "profile_sha256",
            "workspace",
            "tool",
            "model_selection",
        }:
            raise PlanLoopError("Architect RoleBinding is malformed")
        selection = value["model_selection"]
        if not isinstance(selection, Mapping) or set(selection) != {"mode", "ref"}:
            raise PlanLoopError("Architect model selection is malformed")
        if value["format"] != ROLE_BINDING_FORMAT:
            raise PlanLoopError("Architect RoleBinding format is unsupported")
        return cls(
            profile=str(value["profile"]),
            profile_sha256=str(value["profile_sha256"]),
            workspace=str(value["workspace"]),
            tool=str(value["tool"]),
            model_mode=str(selection["mode"]),
            model_ref=str(selection["ref"]),
        )


@dataclass(frozen=True, slots=True)
class PlanFact:
    repository: str
    upstream_remote: str
    base_ref: str
    path: str
    commit: str
    blob_oid: str
    blob_sha256: str
    main_sha: str

    def __post_init__(self) -> None:
        if not self.repository or not self.upstream_remote or not self.base_ref:
            raise PlanLoopError("Plan repository/main binding is incomplete")
        if any(
            _GIT_OID.fullmatch(value) is None
            for value in (self.commit, self.blob_oid, self.main_sha)
        ):
            raise PlanLoopError("Plan Git identity is invalid")
        if _SHA256.fullmatch(self.blob_sha256) is None:
            raise PlanLoopError("Plan content digest is invalid")
        pure = PurePosixPath(self.path)
        if self.path.startswith("/") or "\\" in self.path or ".." in pure.parts:
            raise PlanLoopError("Plan path is not canonical repository-relative POSIX")

    @property
    def identity(self) -> str:
        return _digest(self.to_mapping())

    def to_mapping(self) -> dict[str, object]:
        return {
            "format": PLAN_FACT_FORMAT,
            "repository": self.repository,
            "upstream_remote": self.upstream_remote,
            "base_ref": self.base_ref,
            "path": self.path,
            "commit": self.commit,
            "blob_oid": self.blob_oid,
            "blob_sha256": self.blob_sha256,
            "main_sha": self.main_sha,
        }

    @classmethod
    def from_mapping(cls, value: object) -> PlanFact:
        keys = {
            "format",
            "repository",
            "upstream_remote",
            "base_ref",
            "path",
            "commit",
            "blob_oid",
            "blob_sha256",
            "main_sha",
        }
        if (
            not isinstance(value, Mapping)
            or set(value) != keys
            or value["format"] != PLAN_FACT_FORMAT
        ):
            raise PlanLoopError("PlanFact is malformed or unsupported")
        return cls(**{key: str(value[key]) for key in keys if key != "format"})


def architect_binding(machine: object) -> ArchitectBinding:
    """Project the already validated Phase 5-01 machine binding."""
    profiles = tuple(getattr(machine, "profiles", ()))
    profile = next((item for item in profiles if getattr(item, "role", "") == "architect"), None)
    if profile is None:
        raise PlanLoopError("machine configuration has no Architect RoleBinding")
    try:
        value = json.loads(Path(machine.config_path).read_text(encoding="utf-8"))
        binding = value["roles"]["architect"]
        selection = binding["model_selection"]
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise PlanLoopError("machine Architect RoleBinding is unreadable") from exc
    projected = ArchitectBinding(
        profile=str(binding["profile"]),
        profile_sha256=str(binding["profile_sha256"]),
        workspace=str(binding["workspace"]),
        tool=str(binding["tool"]),
        model_mode=str(selection["mode"]),
        model_ref=str(selection["ref"]),
    )
    if (
        projected.profile_sha256 != profile.digest
        or Path(projected.workspace).resolve() != profile.repo
        or projected.tool != profile.values.get("tool")
        or projected.model != profile.values.get("model", "")
    ):
        raise PlanLoopError("machine Architect RoleBinding drifted")
    return projected


def compile_plan_fact(repo: Path, plan: Path, binding: ArchitectBinding) -> tuple[PlanFact, bytes]:
    """Bind exact committed Plan bytes and a freshly observed upstream main."""
    root = repo.resolve(strict=True)
    relative = _repo_relative(root, plan if plan.is_absolute() else root / plan)
    commit = str(_git(root, "rev-parse", "HEAD^{commit}"))
    tracked = str(_git(root, "ls-files", "--error-unmatch", "--", relative))
    if tracked != relative:
        raise PlanLoopError("Plan is not tracked at the current commit")
    if subprocess.run(
        ["git", "-C", str(root), "diff", "--quiet", "HEAD", "--", relative],
        check=False,
        timeout=30,
    ).returncode:
        raise PlanLoopError("Plan working-tree bytes differ from the committed Plan")
    blob_oid = str(_git(root, "rev-parse", f"{commit}:{relative}"))
    raw = _git(root, "cat-file", "blob", blob_oid, binary=True)
    if not isinstance(raw, bytes):
        raise PlanLoopError("exact committed Plan blob bytes are unavailable")

    profile_values = _profile_values(binding.profile)
    upstream_remote = str(profile_values.get("upstream_remote", "upstream"))
    base_ref = str(profile_values.get("base_ref", "main"))
    repository = str(profile_values.get("upstream_repo", ""))
    ref = f"refs/remotes/{upstream_remote}/{base_ref}"
    _git(root, "fetch", "--no-tags", upstream_remote, f"+refs/heads/{base_ref}:{ref}")
    main_sha = str(_git(root, "rev-parse", f"{ref}^{{commit}}"))
    if subprocess.run(
        ["git", "-C", str(root), "merge-base", "--is-ancestor", commit, main_sha],
        check=False,
        timeout=30,
    ).returncode:
        raise PlanLoopError("committed Plan is not contained in the freshly observed upstream main")
    return (
        PlanFact(
            repository=repository,
            upstream_remote=upstream_remote,
            base_ref=base_ref,
            path=relative,
            commit=commit,
            blob_oid=blob_oid,
            blob_sha256=hashlib.sha256(raw).hexdigest(),
            main_sha=main_sha,
        ),
        raw,
    )


def _profile_values(profile_path: str) -> dict[str, object]:
    try:
        value = json.loads(Path(profile_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PlanLoopError("Architect profile is unavailable") from exc
    if not isinstance(value, dict):
        raise PlanLoopError("Architect profile is malformed")
    return value


def plan_run_id(plan: PlanFact) -> str:
    return f"plan-{plan.identity[:24]}"


def plan_start_payload(
    plan: PlanFact,
    binding: ArchitectBinding,
    *,
    mode: str,
    coder_tool: str,
    coder_model: str,
    reviewer_tool: str,
    reviewer_model: str,
) -> dict[str, object]:
    if mode not in {"one-card", "milestone"}:
        raise PlanLoopError("PlanRun mode is unsupported")
    if coder_tool not in {"opencode", "pi", "codex"} or reviewer_tool not in {
        "opencode",
        "pi",
        "codex",
    }:
        raise PlanLoopError("PlanRun execution selection is unsupported")
    base = {
        "run_id": plan_run_id(plan),
        "mode": mode,
        "plan": plan.to_mapping(),
        "architect": binding.to_mapping(),
        "coder": {"tool": coder_tool, "model": coder_model},
        "reviewer": {"tool": reviewer_tool, "model": reviewer_model},
    }
    payload_sha256 = _digest(base)
    return {
        **base,
        "awf_payload_sha256": payload_sha256,
        "awf_delivery_id": f"awf-plan:{payload_sha256}",
    }


def validate_plan_start_payload(value: object) -> dict[str, object]:
    keys = {
        "run_id",
        "mode",
        "plan",
        "architect",
        "coder",
        "reviewer",
        "awf_payload_sha256",
        "awf_delivery_id",
    }
    if not isinstance(value, Mapping) or set(value) != keys:
        raise PlanLoopError("Plan start payload is malformed")
    base = {key: value[key] for key in keys if not key.startswith("awf_")}
    digest = _digest(base)
    if value["awf_payload_sha256"] != digest or value["awf_delivery_id"] != f"awf-plan:{digest}":
        raise PlanLoopError("Plan start payload identity is invalid")
    plan = PlanFact.from_mapping(value["plan"])
    binding = ArchitectBinding.from_mapping(value["architect"])
    if value["run_id"] != plan_run_id(plan) or value["mode"] not in {"one-card", "milestone"}:
        raise PlanLoopError("Plan start run identity is invalid")
    for role in ("coder", "reviewer"):
        selection = value[role]
        if not isinstance(selection, Mapping) or set(selection) != {"tool", "model"}:
            raise PlanLoopError(f"Plan start {role} selection is malformed")
    if value["coder"]["tool"] not in {"opencode", "pi", "codex"} or value["reviewer"][
        "tool"
    ] not in {
        "opencode",
        "pi",
        "codex",
    }:
        raise PlanLoopError("Plan start provider selection is unsupported")
    return {**dict(value), "plan_fact": plan, "architect_binding": binding}


class PlanRunStore:
    """One minimal atomic Plan/Architect/card/completion record."""

    def __init__(self, state_root: Path, run_id: str):
        if _SAFE_ID.fullmatch(run_id) is None:
            raise PlanLoopError("PlanRun ID is unsafe")
        self.state_root = state_root.resolve()
        self.run_id = run_id
        self.directory = self.state_root / "plan-runs" / run_id
        self.path = self.directory / "run.json"
        self.completed_directory = self.directory / "completed-cards"

    def _envelope(self, body: Mapping[str, object]) -> dict[str, object]:
        return {"body": dict(body), "sha256": _digest(body)}

    def _write(self, body: Mapping[str, object]) -> dict[str, object]:
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{os.getpid()}.{time.time_ns()}.tmp")
        envelope = self._envelope(body)
        try:
            with temporary.open("x", encoding="utf-8", newline="\n") as handle:
                json.dump(envelope, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            raise PlanLoopError("PlanRun could not be persisted") from exc
        return dict(body)

    def load(self) -> dict[str, object]:
        try:
            envelope = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise PlanLoopError("PlanRun is unavailable or unreadable") from exc
        if not isinstance(envelope, dict) or set(envelope) != {"body", "sha256"}:
            raise PlanLoopError("PlanRun envelope is malformed")
        body = envelope["body"]
        if not isinstance(body, dict) or envelope["sha256"] != _digest(body):
            raise PlanLoopError("PlanRun checksum is invalid")
        if (
            body.get("format") != PLAN_RUN_FORMAT
            or body.get("run_id") != self.run_id
            or body.get("state_root_sha256") != state_root_binding(self.state_root)
        ):
            raise PlanLoopError("PlanRun identity is invalid")
        PlanFact.from_mapping(body.get("plan"))
        ArchitectBinding.from_mapping(body.get("architect"))
        return body

    def create(self, payload: Mapping[str, object], *, repo: Path) -> dict[str, object]:
        parsed = validate_plan_start_payload(payload)
        if self.path.exists():
            existing = self.load()
            if existing.get("start_payload_sha256") != payload["awf_payload_sha256"]:
                raise PlanLoopError("PlanRun already exists with different start authority")
            return existing
        body: dict[str, object] = {
            "format": PLAN_RUN_FORMAT,
            "run_id": self.run_id,
            "state_root_sha256": state_root_binding(self.state_root),
            "repo": str(repo.resolve()),
            "mode": payload["mode"],
            "plan": parsed["plan_fact"].to_mapping(),
            "architect": parsed["architect_binding"].to_mapping(),
            "coder": dict(payload["coder"]),
            "reviewer": dict(payload["reviewer"]),
            "status": "start_prepared",
            "start_payload_sha256": payload["awf_payload_sha256"],
            "current_card": None,
            "last_completion": None,
            "architect_invocation": None,
            "preflight": None,
            "stop_requested": False,
            "stop_reason": "",
            "created_at": _utc_now(),
            "updated_at": _utc_now(),
        }
        return self._write(body)

    def update(self, **changes: object) -> dict[str, object]:
        body = self.load()
        allowed = {
            "status",
            "current_card",
            "last_completion",
            "architect_invocation",
            "preflight",
            "stop_requested",
            "stop_reason",
        }
        if set(changes) - allowed:
            raise PlanLoopError("PlanRun update contains an unsupported field")
        updated = {**body, **changes, "updated_at": _utc_now()}
        return self._write(updated)

    def persist_completion(self, fact: Mapping[str, object]) -> Path:
        """Create one immutable CompletedCardFact; this is not an execution journal."""
        value = dict(fact)
        card = value.get("card")
        task_id = card.get("task_id") if isinstance(card, Mapping) else None
        digest = value.get("sha256")
        unsigned = {key: item for key, item in value.items() if key != "sha256"}
        if (
            value.get("format") != COMPLETED_CARD_FORMAT
            or value.get("plan_run_id") != self.run_id
            or not isinstance(task_id, str)
            or _SAFE_ID.fullmatch(task_id) is None
            or digest != _digest(unsigned)
        ):
            raise PlanLoopError("CompletedCardFact is malformed")
        self.completed_directory.mkdir(parents=True, exist_ok=True)
        destination = self.completed_directory / f"{task_id}.json"
        encoded = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if destination.exists():
            try:
                existing = destination.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                raise PlanLoopError("CompletedCardFact is unreadable") from exc
            if existing != encoded:
                raise PlanLoopError(
                    "CompletedCardFact identity already exists with different facts"
                )
            return destination
        try:
            with destination.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError:
            return self.persist_completion(value)
        except OSError as exc:
            raise PlanLoopError("CompletedCardFact could not be persisted") from exc
        return destination

    def completions(self) -> tuple[dict[str, object], ...]:
        values: list[dict[str, object]] = []
        for path in self.completed_directory.glob("*.json"):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise PlanLoopError("CompletedCardFact is unreadable") from exc
            if not isinstance(value, dict):
                raise PlanLoopError("CompletedCardFact is malformed")
            card = value.get("card")
            task_id = card.get("task_id") if isinstance(card, Mapping) else None
            digest = value.get("sha256")
            unsigned = {key: item for key, item in value.items() if key != "sha256"}
            if (
                value.get("format") != COMPLETED_CARD_FORMAT
                or value.get("plan_run_id") != self.run_id
                or not isinstance(task_id, str)
                or path.name != f"{task_id}.json"
                or digest != _digest(unsigned)
            ):
                raise PlanLoopError("CompletedCardFact is malformed")
            values.append(value)
        return tuple(sorted(values, key=lambda value: str(value.get("completed_at", ""))))


def find_plan_run(
    state_root: Path, *, branch: str = "", repo: Path | None = None
) -> PlanRunStore | None:
    root = state_root.resolve() / "plan-runs"
    matches: list[tuple[str, PlanRunStore]] = []
    for path in root.glob("*/run.json"):
        store = PlanRunStore(state_root, path.parent.name)
        try:
            body = store.load()
        except PlanLoopError:
            continue
        if repo is not None and Path(str(body.get("repo", ""))).resolve() != repo.resolve():
            continue
        card = body.get("current_card")
        completion = body.get("last_completion")
        completion_card = completion.get("card") if isinstance(completion, dict) else None
        if branch and not (
            (isinstance(card, dict) and card.get("branch") == branch)
            or (isinstance(completion_card, dict) and completion_card.get("branch") == branch)
        ):
            continue
        matches.append((str(body.get("updated_at", "")), store))
    if not matches:
        return None
    return sorted(matches, key=lambda item: item[0])[-1][1]


def validate_taskcard_binding(
    raw: bytes,
    *,
    frozen_base: str,
    coder: Mapping[str, object],
    reviewer: Mapping[str, object],
) -> tuple[str, str]:
    """Validate the Plan-specific facts layered over Phase 5-01 persistence."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PlanLoopError("Architect TaskCard is not UTF-8") from exc
    bases = _FROZEN_BASE.findall(text)
    if bases != [frozen_base]:
        raise PlanLoopError("Architect TaskCard does not bind the exact fresh upstream main")
    matches = _SELECTION.findall(text)
    if len(matches) != 1:
        raise PlanLoopError("Architect TaskCard requires one reviewer-selection block")
    try:
        selection = json.loads(matches[0])
    except json.JSONDecodeError as exc:
        raise PlanLoopError("Architect TaskCard reviewer selection is invalid JSON") from exc
    expected = {"coder": dict(coder), "reviewer": dict(reviewer)}
    if selection != expected:
        raise PlanLoopError("Architect TaskCard execution selection drifted")
    task = re.search(
        r"(?m)^## Task ID\s*\n\s*`?([A-Za-z0-9][A-Za-z0-9._-]*)`?\s*$",
        text,
    )
    branch = re.search(r"(?m)^- \*\*Task branch\*\*: `([^`]+)`\s*$", text)
    if task is None or branch is None or branch.group(1).rsplit("/", 1)[-1] != task.group(1):
        raise PlanLoopError("Architect TaskCard task/branch identity is invalid")
    return task.group(1), branch.group(1)


def architect_context(
    *,
    plan: PlanFact,
    plan_bytes: bytes,
    architect: ArchitectBinding,
    coder: Mapping[str, object],
    reviewer: Mapping[str, object],
    last_completion: Mapping[str, object] | None = None,
    fresh_main: str | None = None,
) -> str:
    try:
        plan_text = plan_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PlanLoopError("committed Plan is not UTF-8") from exc
    observed_main = fresh_main or plan.main_sha
    if _GIT_OID.fullmatch(observed_main) is None:
        raise PlanLoopError("fresh upstream main is invalid")
    facts: dict[str, object] = {
        "plan": plan.to_mapping(),
        "architect": architect.to_mapping(),
        "fresh_main": observed_main,
        "coder": dict(coder),
        "reviewer": dict(reviewer),
    }
    if last_completion is not None:
        facts["last_completed_card"] = dict(last_completion)
    return (
        "# Trusted ArchitectContext\n\n"
        "Use only these exact facts and the committed Plan. Reason silently. Output only one raw "
        "JSON object with no Markdown, code fence, introduction, or trailing text. The object must "
        "contain exactly these fields: `task_id` (safe string), `objective` (string), `scope` "
        "(non-empty string array), `change_paths` (non-empty repository-relative POSIX path "
        "array), `constraints` (non-empty string array), `acceptance_criteria` (non-empty string "
        "array), and `verification_commands` (non-empty array of non-empty argv string arrays). "
        "Do not include a branch, frozen base, provider selection, report path, postflight block, "
        "or any other authority field; trusted AWF code injects those after validation. Do not "
        "include the generated TaskCard path, `.git`, or `.awf/artifacts` in change_paths.\n\n"
        "## Durable facts\n\n```json\n"
        + json.dumps(facts, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n```\n\n## Exact committed Plan\n\n"
        + plan_text
    )


def next_architect_context(
    *,
    plan: PlanFact,
    plan_bytes: bytes,
    fresh_main: str,
    last_completion: Mapping[str, object],
    coder: Mapping[str, object],
    reviewer: Mapping[str, object],
    completed_task_ids: tuple[str, ...],
) -> str:
    """Compose the closed Phase 5-03 decision context from durable facts only."""
    try:
        plan_text = plan_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PlanLoopError("committed Plan is not UTF-8") from exc
    if _GIT_OID.fullmatch(fresh_main) is None:
        raise PlanLoopError("fresh upstream main is invalid")
    if last_completion.get("format") != COMPLETED_CARD_FORMAT:
        raise PlanLoopError("last CompletedCardFact is invalid")
    if any(_SAFE_ID.fullmatch(value) is None for value in completed_task_ids):
        raise PlanLoopError("completed TaskCard identity is invalid")
    facts = {
        "plan": plan.to_mapping(),
        "fresh_main": fresh_main,
        "last_completed_card": dict(last_completion),
        "milestone": {
            "completed_count": len(completed_task_ids),
            "completed_task_ids": list(completed_task_ids),
            "coder": dict(coder),
            "reviewer": dict(reviewer),
        },
    }
    return (
        "# Trusted next ArchitectContext\n\n"
        "Use only the durable facts, exact committed Plan and read-only repository at fresh_main. "
        "Reason silently: never print repository verification, analysis, a summary, or an "
        "introduction before the closed outcome. Return exactly one closed outcome. If Plan work "
        "remains, return only one raw JSON object with exactly these fields: `task_id`, "
        "`objective`, `scope`, `change_paths`, `constraints`, `acceptance_criteria`, and "
        "`verification_commands`. Use the same closed semantic types as the first Architect call: "
        "strings, non-empty string arrays, repository-relative POSIX change paths, and non-empty "
        "argv string arrays. Do not add Markdown, a code fence, an outcome label, or authority "
        "fields; trusted AWF code assembles the TaskCard. If the Plan milestone is fully complete, "
        "stdout must contain only the single line "
        "`MILESTONE_COMPLETE`, with no text before or after it. If facts prevent a safe next "
        "decision, return "
        "`BLOCKED` on the first line and a non-empty reason on following lines. Do not "
        "pre-generate later cards.\n\n"
        "## Durable facts\n\n```json\n"
        + json.dumps(facts, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n```\n\n## Exact committed Plan\n\n"
        + plan_text
    )


def _normalize_decision_syntax(text: str) -> str:
    """Canonicalize bounded Markdown presentation around one explicit verdict line."""
    normalized = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        while len(line) >= 2 and line.startswith("`") and line.endswith("`"):
            line = line[1:-1].strip()
        line = _DECISION_CODE_VALUE.sub(lambda match: match.group(1) + match.group(2), line)
        gate_match = _DECISION_TRUSTED_GATE_PRESENTATION.fullmatch(line)
        if gate_match is not None:
            normalized.append(f"**Verdict:** {gate_match.group(1).lower()}")
            continue
        final_merge_labels = list(_DECISION_FINAL_MERGE_LABEL.finditer(line))
        final_merge_matches = list(_DECISION_FINAL_MERGE_PRESENTATION.finditer(line))
        if len(final_merge_labels) != len(final_merge_matches):
            raise PlanLoopError("Architect Decision requires exactly one closed verdict")
        if final_merge_matches:
            prefix = line[: final_merge_matches[0].start()]
            if prefix.strip():
                normalized.extend(_normalize_decision_syntax(prefix).splitlines())
            for final_merge_match in final_merge_matches:
                normalized.append(f"**Verdict:** {final_merge_match.group(1).lower()}")
            continue
        match = _DECISION_PRESENTATION.fullmatch(line)
        if match is not None:
            verdict = next(value for value in match.groups() if value is not None)
            normalized.append(f"**Verdict:** {verdict.lower()}")
            continue
        labels = list(_DECISION_INLINE_LABEL.finditer(line))
        matches = list(_DECISION_INLINE_PRESENTATION.finditer(line))
        if len(labels) != len(matches) or (_DECISION_LABEL.match(line) is not None and not matches):
            raise PlanLoopError("Architect Decision requires exactly one closed verdict")
        if not matches:
            normalized.append(raw_line)
            continue
        for match in matches:
            verdict = next(value for value in match.groups() if value is not None)
            normalized.append(f"**Verdict:** {verdict.lower()}")
    return "\n".join(normalized)


def parse_decision(raw: bytes) -> dict[str, object]:
    if not raw or len(raw) > 64 * 1024:
        raise PlanLoopError("Architect Decision is missing or oversized")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PlanLoopError("Architect Decision is not UTF-8") from exc
    verdicts = _DECISION.findall(_normalize_decision_syntax(text))
    if len(verdicts) != 1:
        raise PlanLoopError("Architect Decision requires exactly one closed verdict")
    return {
        "verdict": verdicts[0].lower(),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
    }


def parse_next_output(raw: bytes) -> tuple[str, str]:
    """Return the Phase 5-03 closed outcome without scheduling anything."""
    if not raw or len(raw) > 64 * 1024:
        raise PlanLoopError("Architect next output is missing or oversized")
    try:
        text = raw.decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise PlanLoopError("Architect next output is not UTF-8") from exc
    first, _, rest = text.partition("\n")
    if first in _CLOSED_NEXT:
        if first == "MILESTONE_COMPLETE" and rest.strip():
            raise PlanLoopError("MILESTONE_COMPLETE must be the complete Architect output")
        if first == "BLOCKED" and not rest.strip():
            raise PlanLoopError("BLOCKED requires a non-empty reason")
        return first, rest.strip()
    return "NEXT_TASK_CARD", text


def completed_card_fact(
    *,
    run: Mapping[str, object],
    card: Mapping[str, object],
    decision: Mapping[str, object],
    ci: Mapping[str, object],
    merge: Mapping[str, object],
) -> dict[str, object]:
    if decision.get("verdict") != "approve" or ci.get("conclusion") != "SUCCESS":
        raise PlanLoopError("CompletedCardFact requires Architect approve and green CI")
    if merge.get("state") != "MERGED" or not _GIT_OID.fullmatch(str(merge.get("commit", ""))):
        raise PlanLoopError("CompletedCardFact requires an exact observed merge")
    fact: dict[str, object] = {
        "format": COMPLETED_CARD_FORMAT,
        "plan_run_id": run["run_id"],
        "plan": run["plan"],
        "architect": run["architect"],
        "card": dict(card),
        "decision": dict(decision),
        "ci": dict(ci),
        "merge": dict(merge),
        "completed_at": _utc_now(),
    }
    fact["sha256"] = _digest(fact)
    return fact


def plan_status_lines(run: Mapping[str, object]) -> tuple[str, ...]:
    """Render only durable PlanRun facts; never refresh or mutate them."""
    plan = run.get("plan")
    plan_value = plan if isinstance(plan, Mapping) else {}
    card = run.get("current_card")
    card_value = card if isinstance(card, Mapping) else {}
    completion = run.get("last_completion")
    completion_value = completion if isinstance(completion, Mapping) else {}
    completed_card = completion_value.get("card")
    completed_value = completed_card if isinstance(completed_card, Mapping) else {}
    preflight = run.get("preflight")
    preflight_value = preflight if isinstance(preflight, Mapping) else {}
    authoring = preflight_value.get("authoring")
    authoring_value = authoring if isinstance(authoring, Mapping) else {}
    remote = preflight_value.get("remote_dispatch")
    remote_value = remote if isinstance(remote, Mapping) else {}
    deep = remote_value.get("deep")
    deep_value = deep if isinstance(deep, Mapping) else {}
    merge = completion_value.get("merge")
    merge_value = merge if isinstance(merge, Mapping) else {}
    return (
        f"plan_run={run.get('run_id', '')} status={run.get('status', 'unknown')}",
        f"plan={plan_value.get('path', '')}@{plan_value.get('commit', '')} "
        f"main={plan_value.get('main_sha', '')}",
        f"current_card={card_value.get('task_id', 'none')} branch={card_value.get('branch', '')}",
        f"completed_card={completed_value.get('task_id', 'none')} "
        f"merge={merge_value.get('commit', '')}",
        f"preflight: authoring={authoring_value.get('status', 'not_recorded')} "
        f"remote_dispatch={remote_value.get('status', 'not_recorded')} "
        f"deep_current={deep_value.get('current', 'not_recorded')}",
        f"stop_requested={run.get('stop_requested', False)}",
        f"first_blocker={run.get('stop_reason') or 'none'}",
    )
