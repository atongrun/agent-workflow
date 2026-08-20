from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

_POSTFLIGHT_RE = re.compile(r"<!--\s*awf-postflight\s*\n(.*?)\n\s*-->", re.DOTALL)
_IMPLEMENTATION_REPORT_RE = re.compile(
    r"<!--\s*awf-implementation-report\s*(?:\n\s*)?(\{.*?\})\s*-->", re.DOTALL
)
_REVIEW_REPORT_RE = re.compile(
    r"<!--\s*awf-review-report\s*(?:\n\s*)?(\{.*?\})(?:\s*\n\s*|\s*)-->", re.DOTALL
)
_INLINE_REVIEW_REPORT_RE = re.compile(r"<!--\s*awf-review-report\s+(\{.*?\})\s*-->", re.DOTALL)
_REVIEW_REPORT_FENCED_RE = re.compile(r"```json\s*\n?(.*?)\n?```", re.DOTALL)
_DIFF_BODY_RE = re.compile(
    r"(?m)^(?:diff --git |@@ -|--- a/|\+\+\+ b/)|```(?:diff|patch)\s*$", re.IGNORECASE
)
_TASK_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_ARTIFACT_ROOT = ".awf/artifacts/"
_REVIEW_REPORT_MAX_BYTES = 16 * 1024
_REVIEW_REPORT_KEYS = {"verdict", "deterministic_failures", "blocked_reason"}
_REVIEW_VERDICTS = {"PASS", "REQUEST_CHANGES", "BLOCKED"}

_DENY_PREFIXES = tuple(
    ".venv/ venv/ env/ __pycache__/ node_modules/ dist/ build/ coverage/ htmlcov/".split()
)
_DENY_EXACT = ("Thumbs.db", ".DS_Store", ".coverage", "coverage.xml")
_DENY_SUFFIXES = tuple(".swp .swo .swn .bak .orig .pyc .pyo .log .pid .egg-info".split())
_SECRET_DETECTORS = (
    ("private-key", re.compile(r"-----BEGIN\s+(?:\S+\s+)?PRIVATE\s+KEY-----")),
    ("credential-url", re.compile(r"https?://[^/:@\s]+:[^/@\s]+@")),
    ("github-token", re.compile(r"gh[puosr]_[A-Za-z0-9_]{36,}")),
    ("openai-key", re.compile(r"sk-[A-Za-z0-9]{20,}")),
    ("aws-access-key", re.compile(r"AKIA[0-9A-Z]{16}")),
)


class ArtifactError(RuntimeError):
    pass


@dataclass(frozen=True)
class StageArtifactContract:
    task_id: str
    implementation_report_path: str


@dataclass(frozen=True)
class RunArtifactContract:
    task_id: str
    taskcard_path: str
    allowed_paths: tuple[str, ...]
    implementation_report_path: str
    review_report_path: str


@dataclass(frozen=True)
class PostflightContract:
    allowed_paths: tuple[str, ...]
    verification_commands: tuple[tuple[str, ...], ...]


@dataclass(frozen=True)
class ArtifactFact:
    path: str
    size: int
    sha256: str


@dataclass(frozen=True)
class NormalizedReviewReport:
    payload_json: str
    canonical_sha256: str

    def as_payload(self) -> dict[str, object]:
        value = json.loads(self.payload_json)
        assert isinstance(value, dict)
        return value


@dataclass(frozen=True)
class ValidatedReviewArtifact:
    artifact: ArtifactFact
    review: NormalizedReviewReport


@dataclass(frozen=True)
class PostflightResult:
    delta_paths: tuple[str, ...]
    observation_sha256: str


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(key)
        result[key] = value
    return result


def _validate_repo_relative_path(path: str, *, field: str, artifact_only: bool = False) -> None:
    if not isinstance(path, str) or not path:
        raise ArtifactError(f"{field} is required")
    if "\\" in path:
        raise ArtifactError(f"{field} must use forward slashes")
    if path.startswith("/") or ":" in path:
        raise ArtifactError(f"{field} must be a repo-relative path")
    if ".." in path.split("/"):
        raise ArtifactError(f"{field} must not contain parent traversal")
    if artifact_only and not path.startswith(_ARTIFACT_ROOT):
        raise ArtifactError(f"{field} must be under {_ARTIFACT_ROOT}")


def compile_implementation_report_path(task_id: str) -> str:
    if not isinstance(task_id, str) or not _TASK_ID_RE.fullmatch(task_id):
        raise ArtifactError("task_id cannot compile a safe implementation report path")
    return f"{_ARTIFACT_ROOT}impl-report-{task_id}.md"


def compile_review_report_path(task_id: str) -> str:
    if not isinstance(task_id, str) or not _TASK_ID_RE.fullmatch(task_id):
        raise ArtifactError("task_id cannot compile a safe review report path")
    return f"{_ARTIFACT_ROOT}review-report-{task_id}.md"


def _taskcard_payload(card_path: Path) -> dict[str, object]:
    try:
        text = Path(card_path).read_text(encoding="utf-8")
    except OSError as exc:
        raise ArtifactError("TaskCard is unreadable") from exc
    match = _POSTFLIGHT_RE.search(text)
    if match is None:
        raise ArtifactError("TaskCard has no awf-postflight contract")
    try:
        value = json.loads(match.group(1), object_pairs_hook=_unique_json_object)
    except ValueError as exc:
        raise ArtifactError("TaskCard awf-postflight contract is invalid JSON") from exc
    if not isinstance(value, dict):
        raise ArtifactError("TaskCard awf-postflight contract must be a JSON object")
    return value


def taskcard_allowed_paths(card_path: Path) -> tuple[str, ...]:
    value = _taskcard_payload(card_path).get("allowed_paths")
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ArtifactError("TaskCard allowed_paths must be an array of strings")
    return tuple(value)


def _validate_taskcard_binding(card_path: Path, required_report_path: str) -> None:
    allowed_paths = taskcard_allowed_paths(card_path)
    declared = [path for path in allowed_paths if Path(path).name.startswith("impl-report-")]
    if required_report_path not in allowed_paths or declared != [required_report_path]:
        raise ArtifactError(
            "TaskCard allowed_paths implementation report does not match delivery.report: "
            f"TaskCard={declared!r}, delivery.report={required_report_path!r}"
        )


def compile_stage_artifact_contract(
    *, card_path: Path, task_id: str, requested_report_path: str
) -> StageArtifactContract:
    compiled = compile_implementation_report_path(task_id)
    requested = requested_report_path or compiled
    _validate_repo_relative_path(requested, field="dispatch --report", artifact_only=True)
    _validate_taskcard_binding(Path(card_path), requested)
    return StageArtifactContract(task_id=task_id, implementation_report_path=requested)


def validate_stage_artifact_contract(
    *, card_path: Path, task_id: str, required_report_path: str
) -> StageArtifactContract:
    return compile_stage_artifact_contract(
        card_path=card_path,
        task_id=task_id,
        requested_report_path=required_report_path,
    )


def compile_run_artifact_contract(
    *,
    repo: Path,
    card_path: Path,
    task_id: str,
    implementation_report_path: str,
    review_report_path: str,
) -> RunArtifactContract:
    repo = Path(repo).resolve()
    card_path = Path(card_path).resolve()
    try:
        taskcard_path = card_path.relative_to(repo).as_posix()
    except ValueError as exc:
        raise ArtifactError("TaskCard must be inside the target repository") from exc
    _validate_repo_relative_path(taskcard_path, field="TaskCard")
    allowed_paths = taskcard_allowed_paths(card_path)
    if not allowed_paths or len(allowed_paths) != len(set(allowed_paths)):
        raise ArtifactError("TaskCard allowed_paths must be non-empty and unique")
    for path in allowed_paths:
        _validate_repo_relative_path(path, field="TaskCard allowed_paths")
    if taskcard_path in allowed_paths:
        raise ArtifactError("frozen TaskCard must not be model-writable in allowed_paths")

    _validate_repo_relative_path(
        implementation_report_path, field="RunManifest ImplementationReport", artifact_only=True
    )
    _validate_repo_relative_path(
        review_report_path, field="RunManifest ReviewReport", artifact_only=True
    )
    if implementation_report_path != compile_implementation_report_path(task_id):
        raise ArtifactError(
            "RunManifest ImplementationReport does not match compiled task identity"
        )
    if review_report_path != compile_review_report_path(task_id):
        raise ArtifactError("RunManifest ReviewReport does not match compiled task identity")
    declared_implementation = [
        path for path in allowed_paths if Path(path).name.startswith("impl-report-")
    ]
    declared_review = [
        path for path in allowed_paths if Path(path).name.startswith("review-report-")
    ]
    if declared_implementation != [implementation_report_path]:
        raise ArtifactError(
            "TaskCard allowed_paths ImplementationReport binding does not match RunManifest"
        )
    if declared_review != [review_report_path]:
        raise ArtifactError(
            "TaskCard allowed_paths ReviewReport binding does not match RunManifest"
        )
    return RunArtifactContract(
        task_id=task_id,
        taskcard_path=taskcard_path,
        allowed_paths=allowed_paths,
        implementation_report_path=implementation_report_path,
        review_report_path=review_report_path,
    )


def parse_postflight_contract(card_path: Path, python_executable: str) -> PostflightContract:
    data = _taskcard_payload(card_path)
    extra = set(data) - {"allowed_paths", "verification_commands"}
    if extra:
        raise ArtifactError(f"unexpected awf-postflight keys: {', '.join(sorted(extra))}")
    raw_paths = data.get("allowed_paths", [])
    if not isinstance(raw_paths, list) or not raw_paths:
        raise ArtifactError("awf-postflight allowed_paths must be a non-empty array")
    paths: list[str] = []
    for path in raw_paths:
        if not isinstance(path, str) or not path.strip():
            raise ArtifactError(f"invalid allowed_path entry: {path!r}")
        _validate_repo_relative_path(path, field="allowed path")
        if path in paths:
            raise ArtifactError(f"duplicate allowed path: {path!r}")
        paths.append(path)
    raw_commands = data.get("verification_commands", [])
    if not isinstance(raw_commands, list) or not raw_commands:
        raise ArtifactError("awf-postflight verification_commands must be a non-empty array")
    commands: list[tuple[str, ...]] = []
    for index, command in enumerate(raw_commands):
        if not isinstance(command, list) or not command:
            raise ArtifactError(
                f"verification_commands[{index}] must be a non-empty array of strings"
            )
        if not all(isinstance(item, str) for item in command):
            raise ArtifactError(f"verification_commands[{index}] must contain only strings")
        if command[0] == "":
            raise ArtifactError(f"verification_commands[{index}] has an empty executable")
        argv = list(command)
        if argv[0] == "{python}":
            argv[0] = python_executable
        commands.append(tuple(argv))
    return PostflightContract(tuple(paths), tuple(commands))


def resolve_repo_file(repo: Path, relative_path: str, label: str) -> Path:
    _validate_repo_relative_path(relative_path, field=f"{label} path")
    repo_root = Path(repo).resolve()
    resolved = (repo_root / relative_path).resolve()
    if resolved == repo_root or repo_root not in resolved.parents:
        raise ArtifactError(f"{label} path escapes the repository")
    return resolved


def resolve_review_report_path(repo: Path, report_path: str, implementation_report: str) -> Path:
    if not report_path:
        raise ArtifactError("--review-report is required")
    resolved = resolve_repo_file(repo, report_path, "ReviewReport")
    implementation_path = Path(implementation_report)
    if not implementation_path.is_absolute():
        implementation_path = Path(repo).resolve() / implementation_path
    if resolved == implementation_path.resolve():
        raise ArtifactError("ReviewReport path must be distinct from ImplementationReport path")
    return resolved


def artifact_fact(path: Path, relative_path: str | None = None) -> ArtifactFact:
    source = Path(path)
    try:
        raw = source.read_bytes()
    except OSError as exc:
        raise ArtifactError("Artifact is missing or unreadable") from exc
    bound_path = relative_path or source.name
    _validate_repo_relative_path(bound_path, field="Artifact path")
    return ArtifactFact(bound_path, len(raw), hashlib.sha256(raw).hexdigest())


def validate_implementation_report(path: Path, relative_path: str | None = None) -> ArtifactFact:
    if not str(path):
        raise ArtifactError(
            "--report is required; ImplementationReport must exist before commit or review"
        )
    source = Path(path)
    if not source.is_file():
        raise ArtifactError(f"ImplementationReport not found: {path}")
    try:
        raw = source.read_bytes()
        content = raw.decode("utf-8")
    except (OSError, UnicodeError) as exc:
        raise ArtifactError("ImplementationReport is unreadable") from exc
    if not content.strip() or "\x00" in content:
        raise ArtifactError("ImplementationReport is empty or contains NUL")
    envelope = _IMPLEMENTATION_REPORT_RE.findall(content)
    if envelope:
        if len(envelope) != 1:
            raise ArtifactError("ImplementationReport must contain exactly one machine envelope")
        try:
            value = json.loads(envelope[0], object_pairs_hook=_unique_json_object)
        except ValueError as exc:
            raise ArtifactError("ImplementationReport machine envelope is malformed") from exc
        expected = {"summary", "changed_files", "commands", "tests", "source_revision"}
        if not isinstance(value, dict) or set(value) != expected:
            raise ArtifactError(
                "ImplementationReport machine envelope has missing or unknown fields"
            )
    bound_path = relative_path or source.name
    _validate_repo_relative_path(bound_path, field="Artifact path")
    return ArtifactFact(bound_path, len(raw), hashlib.sha256(raw).hexdigest())


def normalize_review_envelope(path: Path) -> None:
    source = Path(path)
    try:
        markdown = source.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return
    matches = list(_INLINE_REVIEW_REPORT_RE.finditer(markdown))
    if len(matches) != 1:
        return
    match = matches[0]
    if "\n" in markdown[match.start() : match.end()].split("{", 1)[0]:
        return
    try:
        machine = json.loads(match.group(1), object_pairs_hook=_unique_json_object)
    except ValueError:
        return
    if not isinstance(machine, dict):
        return
    canonical = (
        "<!-- awf-review-report\n"
        + json.dumps(machine, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n-->"
    )
    updated = markdown[: match.start()] + canonical + markdown[match.end() :]
    if updated != markdown:
        source.write_text(updated, encoding="utf-8", newline="\n")


def _review_failure(item: object, index: int) -> dict[str, object]:
    if not isinstance(item, dict) or set(item) != {"evidence", "required_correction"}:
        raise ArtifactError(f"deterministic_failures[{index}] has invalid fields")
    correction = item["required_correction"]
    evidence = item["evidence"]
    if not isinstance(correction, str) or not correction.strip():
        raise ArtifactError(f"deterministic_failures[{index}] requires a correction")
    if not isinstance(evidence, dict) or not isinstance(evidence.get("kind"), str):
        raise ArtifactError(f"deterministic_failures[{index}] requires structured evidence")
    kind = evidence["kind"]
    if kind == "criterion":
        expected = {"kind", "criterion"}
        valid = isinstance(evidence.get("criterion"), str) and bool(evidence["criterion"].strip())
    elif kind == "command":
        expected = {"kind", "command", "result"}
        valid = all(
            isinstance(evidence.get(key), str) and bool(evidence[key].strip())
            for key in ("command", "result")
        )
    elif kind == "file_line":
        expected = {"kind", "file", "line"}
        file_name = evidence.get("file")
        line = evidence.get("line")
        valid = (
            isinstance(file_name, str)
            and bool(file_name.strip())
            and not file_name.startswith("/")
            and "\\" not in file_name
            and ".." not in file_name.split("/")
            and isinstance(line, int)
            and not isinstance(line, bool)
            and line > 0
        )
    else:
        raise ArtifactError(f"deterministic_failures[{index}] has unknown evidence kind")
    if set(evidence) != expected or not valid:
        raise ArtifactError(f"deterministic_failures[{index}] lacks precise evidence")
    return {"evidence": dict(evidence), "required_correction": correction.strip()}


def _normalize_review(data: dict[str, object], markdown: str) -> NormalizedReviewReport:
    verdict = data["verdict"]
    if not isinstance(verdict, str) or verdict not in _REVIEW_VERDICTS:
        raise ArtifactError(
            "ReviewReport verdict must be exactly PASS, REQUEST_CHANGES, or BLOCKED"
        )
    failures = data["deterministic_failures"]
    if not isinstance(failures, list):
        raise ArtifactError("ReviewReport deterministic_failures must be an array")
    normalized_failures = [_review_failure(item, i) for i, item in enumerate(failures)]
    blocked_reason = data["blocked_reason"]
    if verdict == "PASS" and blocked_reason is None:
        blocked_reason = ""
    elif not isinstance(blocked_reason, str):
        raise ArtifactError("ReviewReport blocked_reason must be a string")
    blocked_reason = blocked_reason.strip()
    if verdict == "PASS" and normalized_failures:
        raise ArtifactError("PASS ReviewReport cannot contain deterministic failures")
    if verdict == "REQUEST_CHANGES" and not normalized_failures:
        raise ArtifactError("REQUEST_CHANGES requires deterministic failure evidence")
    if verdict == "BLOCKED" and not blocked_reason:
        raise ArtifactError("BLOCKED requires an escalation reason")
    if verdict != "BLOCKED" and blocked_reason:
        raise ArtifactError("blocked_reason is only valid for BLOCKED")
    payload = {
        "format": "awf.review-report.v1",
        "verdict": verdict,
        "deterministic_failures": normalized_failures,
        "blocked_reason": blocked_reason,
        "markdown": markdown,
    }
    encoded = json.dumps(payload).encode("utf-8")
    if len(encoded) > _REVIEW_REPORT_MAX_BYTES:
        raise ArtifactError("normalized ReviewReport exceeds 16 KiB")
    return NormalizedReviewReport(encoded.decode("utf-8"), hashlib.sha256(encoded).hexdigest())


def _review_machine(markdown: str, *, embedded: bool) -> dict[str, object]:
    blocks = _REVIEW_REPORT_RE.findall(markdown)
    if len(blocks) == 1:
        source = blocks[0]
    elif len(blocks) == 0:
        fenced = _REVIEW_REPORT_FENCED_RE.findall(markdown)
        if len(fenced) != 1:
            prefix = "embedded " if embedded else ""
            raise ArtifactError(
                f"{prefix}ReviewReport must contain exactly one awf-review-report object"
            )
        try:
            wrapped = json.loads(fenced[0], object_pairs_hook=_unique_json_object)
        except ValueError as exc:
            raise ArtifactError(
                "ReviewReport machine object is malformed or contains duplicate fields"
            ) from exc
        if not isinstance(wrapped, dict) or set(wrapped) != {"awf-review-report"}:
            raise ArtifactError("ReviewReport machine object has missing or unknown fields")
        data = wrapped["awf-review-report"]
        if not isinstance(data, dict):
            raise ArtifactError("ReviewReport machine object is malformed")
        return data
    else:
        raise ArtifactError("ReviewReport must contain exactly one awf-review-report object")
    try:
        data = json.loads(source, object_pairs_hook=_unique_json_object)
    except ValueError as exc:
        raise ArtifactError(
            "ReviewReport machine object is malformed or contains duplicate fields"
        ) from exc
    if not isinstance(data, dict):
        raise ArtifactError("ReviewReport machine object is malformed")
    return data


def parse_review_report(path: Path, relative_path: str | None = None) -> ValidatedReviewArtifact:
    source = Path(path)
    try:
        raw = source.read_bytes()
        markdown = raw.decode("utf-8")
    except (OSError, UnicodeError) as exc:
        raise ArtifactError(f"ReviewReport is missing or unreadable: {path}") from exc
    if not markdown.strip():
        raise ArtifactError("ReviewReport is empty")
    if _DIFF_BODY_RE.search(markdown):
        raise ArtifactError("ReviewReport must not contain full diff or patch bodies")
    label = scan_secret_text(markdown)
    if label:
        raise ArtifactError(f"ReviewReport contains prohibited {label} material")
    data = _review_machine(markdown, embedded=False)
    if set(data) != _REVIEW_REPORT_KEYS:
        raise ArtifactError("ReviewReport machine object has missing or unknown fields")
    review = _normalize_review(data, markdown)
    bound_path = relative_path or source.name
    _validate_repo_relative_path(bound_path, field="Artifact path")
    fact = ArtifactFact(bound_path, len(raw), hashlib.sha256(raw).hexdigest())
    return ValidatedReviewArtifact(fact, review)


def validate_embedded_review_report(data: object) -> NormalizedReviewReport:
    expected = {"format", "verdict", "deterministic_failures", "blocked_reason", "markdown"}
    if not isinstance(data, dict) or set(data) != expected:
        raise ArtifactError("embedded ReviewReport has missing or unknown fields")
    if data.get("format") != "awf.review-report.v1":
        raise ArtifactError("embedded ReviewReport format is unsupported")
    markdown = data.get("markdown")
    if not isinstance(markdown, str) or not markdown.strip():
        raise ArtifactError("embedded ReviewReport markdown is missing")
    if _DIFF_BODY_RE.search(markdown):
        raise ArtifactError("embedded ReviewReport must not contain full diff or patch bodies")
    label = scan_secret_text(markdown)
    if label:
        raise ArtifactError(f"embedded ReviewReport contains prohibited {label} material")
    machine = _review_machine(markdown, embedded=True)
    if set(machine) != _REVIEW_REPORT_KEYS:
        raise ArtifactError("embedded ReviewReport machine object has missing or unknown fields")
    normalized = _normalize_review(machine, markdown)
    if normalized.as_payload() != data:
        raise ArtifactError("embedded ReviewReport does not match its normalized machine object")
    return normalized


def normalize_rework_feedback(data: object) -> str:
    if not isinstance(data, dict) or data.get("format") != "awf.review-report.v1":
        raise ArtifactError("review feedback has an invalid format")
    verdict, failures = data.get("verdict"), data.get("deterministic_failures")
    if verdict != "REQUEST_CHANGES" or not isinstance(failures, list) or not failures:
        raise ArtifactError("rework requires REQUEST_CHANGES with deterministic failures")
    blocked_reason = data.get("blocked_reason")
    if not isinstance(blocked_reason, str) or blocked_reason:
        raise ArtifactError("REQUEST_CHANGES feedback cannot contain a blocked reason")
    normalized = [_review_failure(item, index) for index, item in enumerate(failures)]
    text = json.dumps(
        {"verdict": verdict, "deterministic_failures": normalized, "blocked_reason": ""},
        indent=2,
        sort_keys=True,
    )
    label = scan_secret_text(text)
    if label:
        raise ArtifactError(f"review feedback contains prohibited {label} material")
    return text


def path_is_denied(path: str) -> bool:
    basename = os.path.basename(path)
    if basename == ".env" or (
        basename.startswith(".env.")
        and basename not in (".env.example", ".env.template", ".env.sample")
    ):
        return True
    components = path.split("/")
    if any(prefix.rstrip("/") in components for prefix in _DENY_PREFIXES):
        return True
    return basename in _DENY_EXACT or path.endswith(_DENY_SUFFIXES) or ".egg-info/" in path


def validate_postflight_paths(
    contract: PostflightContract, delta_paths: tuple[str, ...]
) -> tuple[str, ...]:
    if not delta_paths:
        raise ArtifactError("postflight: no changes detected after model execution")
    offending = sorted(path for path in delta_paths if path not in set(contract.allowed_paths))
    if offending:
        raise ArtifactError(
            "postflight: changed path(s) not in allowed_paths:\n  " + "\n  ".join(offending)
        )
    denied = sorted(path for path in delta_paths if path_is_denied(path))
    if denied:
        raise ArtifactError("postflight: artifact denylist violation:\n  " + "\n  ".join(denied))
    return delta_paths


def scan_secret_text(text: str) -> str | None:
    for label, pattern in _SECRET_DETECTORS:
        if pattern.search(text):
            return label
    return None


def validate_secret_observation(
    tracked_added_lines: tuple[tuple[str, str], ...],
    untracked_contents: tuple[tuple[str, str], ...],
    unreadable_untracked: tuple[str, ...] = (),
) -> str:
    for path, text in tracked_added_lines:
        label = scan_secret_text(text)
        if label:
            raise ArtifactError(f"postflight secret scan: {label} in {path}")
    for path, text in untracked_contents:
        label = scan_secret_text(text)
        if label:
            raise ArtifactError(f"postflight secret scan: {label} in untracked file {path}")
    if unreadable_untracked:
        raise ArtifactError(
            f"postflight secret scan: unreadable-file in untracked file {unreadable_untracked[0]}"
        )
    summary = {
        "tracked": [
            (path, hashlib.sha256(text.encode("utf-8")).hexdigest())
            for path, text in tracked_added_lines
        ],
        "untracked": [
            (path, hashlib.sha256(text.encode("utf-8")).hexdigest())
            for path, text in untracked_contents
        ],
    }
    return hashlib.sha256(
        json.dumps(summary, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def postflight_result(
    delta_paths: tuple[str, ...], secret_observation_sha256: str, diff_check_returncode: int
) -> PostflightResult:
    if diff_check_returncode != 0:
        raise ArtifactError("postflight: git diff HEAD --check found whitespace errors")
    payload = {
        "delta_paths": delta_paths,
        "secret_observation_sha256": secret_observation_sha256,
        "diff_check_returncode": diff_check_returncode,
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return PostflightResult(delta_paths, digest)
