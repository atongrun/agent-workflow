from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .artifact import (
    ArtifactError,
    PostflightContract,
    normalize_rework_feedback,
    parse_postflight_contract,
    parse_review_report,
    postflight_result,
    resolve_repo_file,
    validate_implementation_report,
    validate_postflight_paths,
    validate_secret_observation,
)
from .contracts import (
    FreshRunSpec,
    InvocationSpec,
    RenderedInvocation,
    RunSpec,
    _canonical_bytes,
    _identifier,
)
from .outgoing import OutgoingIntent
from .ports import (
    AuthorizationCommand,
    DecisionOutcome,
    HandoffCommand,
    JournalAuthorization,
    LaunchIntent,
    ProcessObservation,
    ProviderResult,
    RunSnapshot,
    StopCommand,
    TerminalCommand,
    TerminalOutcome,
    ValidationEffect,
    WorkflowStage,
)
from .renderers import ATTACH_INPUT, render_provider_invocation
from .store import AtomicRunStore, AtomicStatusReader, StoreError
from .transport import ResultEnvelope, _require_delivery_id
from .workspace import (
    WorkspaceDelta,
    WorkspaceError,
    WorkspaceSpec,
    assert_workspace_state,
    bind_environment,
    freeze_workspace,
    import_workspace_delta,
    prepare_workspace,
    restore_workspace_manifest,
    serialize_workspace_delta,
)

_IDENTITY_NEXT = "preserve files; diagnose exact run identity"
_MUTATION_NEXT = "preserve both facts for owner decision"


class ApplicationError(RuntimeError):
    def __init__(
        self,
        outcome: DecisionOutcome,
        cause: str,
        next_action: str,
        owner: str = "runtime",
    ) -> None:
        super().__init__(cause)
        self.outcome, self.owner, self.cause, self.next_action = outcome, owner, cause, next_action


def _deny_provider(cause: str) -> ApplicationError:
    return ApplicationError(DecisionOutcome.DENY_BEFORE_PROVIDER, cause, _IDENTITY_NEXT)


def _deny_mutation(cause: str) -> ApplicationError:
    return ApplicationError(DecisionOutcome.DENY_BEFORE_MUTATION, cause, _MUTATION_NEXT, "owner")


@dataclass(frozen=True, slots=True)
class ProcessResult:
    return_code: int
    stdout: bytes
    stderr: bytes

    def __post_init__(self) -> None:
        if isinstance(self.return_code, bool) or not isinstance(self.return_code, int):
            raise TypeError("return_code must be an integer")
        if not isinstance(self.stdout, bytes) or not isinstance(self.stderr, bytes):
            raise TypeError("process output must be immutable bytes")
        if len(self.stdout) + len(self.stderr) > 1024 * 1024:
            raise ValueError("provider process output exceeds the local bound")


class StartedProvider(Protocol):
    @property
    def process_identity_sha256(self) -> str: ...

    def wait(self) -> ProcessResult: ...


class ProviderLauncher(Protocol):
    def start(self, invocation: RenderedInvocation) -> StartedProvider: ...


class _SubprocessHandle:
    def __init__(
        self,
        process: subprocess.Popen[bytes],
        process_identity_sha256: str,
        stdin: bytes | None,
    ) -> None:
        self._process = process
        self._identity = process_identity_sha256
        self._stdin = stdin

    @property
    def process_identity_sha256(self) -> str:
        return self._identity

    def wait(self) -> ProcessResult:
        stdout, stderr = self._process.communicate(input=self._stdin)
        return ProcessResult(self._process.returncode, stdout, stderr)


class SubprocessProviderLauncher:
    def start(self, invocation: RenderedInvocation) -> StartedProvider:
        cwd = Path(invocation.cwd).resolve()
        for item in invocation.file_inputs:
            raw_target = Path(item.path)
            if raw_target.is_symlink():
                raise _deny_provider("provider file input is redirected")
            target = raw_target.resolve()
            try:
                target.relative_to(cwd)
            except ValueError as exc:
                raise _deny_provider("provider file input escaped the exact workspace") from exc
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(item.content)
        process = subprocess.Popen(
            [invocation.executable, *invocation.argv],
            cwd=invocation.cwd,
            env=dict(invocation.environment),
            stdin=subprocess.PIPE if invocation.stdin is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
        )
        identity = _digest(
            {
                "pid": process.pid,
                "rendered_invocation_sha256": invocation.sha256,
                "kind": "local-subprocess",
            }
        )
        return _SubprocessHandle(process, identity, invocation.stdin)


@dataclass(frozen=True, slots=True)
class PostflightObservation:
    delta_paths: tuple[str, ...]
    tracked_added_lines: tuple[tuple[str, str], ...] = ()
    untracked_contents: tuple[tuple[str, str], ...] = ()
    unreadable_untracked: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.delta_paths, tuple) or not self.delta_paths:
            raise ValueError("postflight delta_paths must be a non-empty tuple")
        for collection in (self.tracked_added_lines, self.untracked_contents):
            if not isinstance(collection, tuple) or any(
                not isinstance(item, tuple)
                or len(item) != 2
                or not all(isinstance(value, str) for value in item)
                for item in collection
            ):
                raise ValueError("postflight text observations must be immutable pairs")


@dataclass(frozen=True, slots=True)
class LocalStageRequest:
    invocation_id: str
    stage: WorkflowStage
    attempt: int
    delivery_id: str
    payload_sha256: str
    outgoing_target_invocation_id: str
    provider_executable: str
    provider_environment: tuple[tuple[str, str], ...]
    input_text: str
    provider_args: tuple[str, ...]
    source_repo: str
    trusted_repo: str
    expected_commit: str
    workspace_state_dir: str
    python_executable: str
    postflight: PostflightObservation | None = None

    def __post_init__(self) -> None:
        _require_delivery_id("delivery identity", self.delivery_id)
        _identifier("outgoing_target_invocation_id", self.outgoing_target_invocation_id)
        if not isinstance(self.stage, WorkflowStage):
            raise TypeError("stage must be a WorkflowStage")
        no_postflight = {WorkflowStage.REVIEW, WorkflowStage.ARCHITECT}
        if self.stage in no_postflight and self.postflight is not None:
            raise ValueError("review and architect do not accept coder postflight observations")
        if self.stage not in no_postflight and self.postflight is None:
            raise ValueError("coder and rework require postflight observations")
        if not Path(self.provider_executable).is_absolute():
            raise ValueError("provider executable must be absolute")
        for name, value in (
            ("source_repo", self.source_repo),
            ("trusted_repo", self.trusted_repo),
            ("workspace_state_dir", self.workspace_state_dir),
            ("python_executable", self.python_executable),
        ):
            if not Path(value).is_absolute():
                raise ValueError(f"{name} must be absolute")


def _digest(value: object) -> str:
    if isinstance(value, bytes):
        data = value
    else:
        data = _canonical_bytes(value)  # type: ignore[arg-type]
    return hashlib.sha256(data).hexdigest()


def _git(
    repo: str | Path,
    environment: tuple[tuple[str, str], ...],
    *args: str,
    input_bytes: bytes | None = None,
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-C", str(Path(repo).resolve()), *args],
        env=dict(environment),
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def _git_text(repo: str | Path, environment: tuple[tuple[str, str], ...], *args: str) -> str:
    completed = _git(repo, environment, *args)
    if completed.returncode != 0:
        raise _deny_mutation("trusted local Git observation failed")
    try:
        return completed.stdout.decode("utf-8").strip()
    except UnicodeError as exc:
        raise _deny_mutation("trusted local Git observation is not UTF-8") from exc


class LocalRuntimeApplication:
    def __init__(
        self,
        state_root: str | Path,
        writer_id: str,
        launcher: ProviderLauncher | None = None,
    ) -> None:
        self.state_root = Path(state_root).resolve()
        self.writer_id = writer_id
        self.launcher = launcher or SubprocessProviderLauncher()

    def status(self, run_id: str) -> RunSnapshot:
        return AtomicStatusReader(self.state_root, run_id).snapshot(run_id)

    def stop(self, run_spec: RunSpec | FreshRunSpec) -> RunSnapshot:
        snapshot = self.status(run_spec.run_id)
        if snapshot.stopped:
            return snapshot
        store = AtomicRunStore(self.state_root, run_spec.run_id, self.writer_id)
        store.record_stop(StopCommand(run_spec.sha256, run_spec.run_id, snapshot.sequence))
        return self.status(run_spec.run_id)

    def run(self, run_spec: RunSpec | FreshRunSpec, request: LocalStageRequest) -> RunSnapshot:
        store = AtomicRunStore(self.state_root, run_spec.run_id, self.writer_id)
        snapshot = store.initialize(run_spec)
        if snapshot.terminal is not None or snapshot.stopped:
            return snapshot
        if snapshot.stage is not request.stage:
            raise _deny_provider("local stage request does not match current Workflow authority")
        lineage = store.pending_handoff()
        if request.stage is WorkflowStage.REWORK:
            try:
                rework_payload = json.loads(request.input_text)
            except json.JSONDecodeError as exc:
                raise _deny_provider("rework input is not deterministic JSON feedback") from exc
            deterministic_feedback = json.dumps(rework_payload, indent=2, sort_keys=True)
            if (
                request.input_text != deterministic_feedback
                or lineage is None
                or _digest(rework_payload) != lineage.payload_sha256
            ):
                raise _deny_provider("rework input does not match deterministic review feedback")
        recovery = None
        try:
            recovery = store.journal(request.invocation_id).snapshot()
        except StoreError as exc:
            if exc.cause != "invocation is not authorized":
                raise
        if recovery is not None and recovery.launch_intent is not None and recovery.result is None:
            return snapshot
        card = resolve_repo_file(Path(request.trusted_repo), run_spec.task_card, "TaskCard")
        if card.is_symlink():
            raise _deny_provider("immutable TaskCard path is redirected")
        try:
            card_sha256 = hashlib.sha256(card.read_bytes()).hexdigest()
        except OSError as exc:
            raise _deny_provider("immutable TaskCard is missing or unreadable") from exc
        if card_sha256 != run_spec.task_card_sha256:
            raise _deny_provider("immutable TaskCard digest drifted")
        trusted_head = _git_text(
            request.trusted_repo, request.provider_environment, "rev-parse", "HEAD^{commit}"
        )
        if Path(request.source_repo).resolve() != Path(request.trusted_repo).resolve():
            raise _deny_provider("source and trusted repository identities differ")
        if trusted_head != request.expected_commit and (
            recovery is None or recovery.result is None
        ):
            raise _deny_provider("trusted local Git HEAD does not match the requested lineage")
        expected_manifest = None
        if recovery is not None:
            expected_manifest = (
                recovery.result.workspace_manifest_sha256
                if recovery.result is not None
                else recovery.workspace_manifest_sha256
            )
        workspace, initial_manifest = self._workspace(run_spec, request, expected_manifest)
        authorization_manifest = (
            recovery.workspace_manifest_sha256 if recovery is not None else initial_manifest
        )
        invocation = self._invocation(run_spec, request, workspace)
        authorization = _digest(
            {
                "run_spec_sha256": run_spec.sha256,
                "invocation_spec_sha256": invocation.sha256,
                "stage": request.stage.value,
                "attempt": request.attempt,
                "delivery_id": request.delivery_id,
                "payload_sha256": request.payload_sha256,
            }
        )
        command = AuthorizationCommand(
            run_spec.sha256,
            request.invocation_id,
            authorization,
            request.stage,
            "reviewer" if request.stage is WorkflowStage.REVIEW else "coder",
            request.attempt,
            request.delivery_id,
            request.payload_sha256,
        )
        store.authorize(
            command,
            JournalAuthorization(
                run_spec.sha256,
                request.invocation_id,
                authorization,
                invocation.sha256,
                authorization_manifest,
            ),
        )
        journal = store.journal(request.invocation_id)
        current = journal.snapshot()
        rendered = render_provider_invocation(invocation)
        if current.launch_intent is None:
            attached_input = self._materialize_bound_input(invocation)
            journal.record_launch_intent(LaunchIntent(authorization, rendered.sha256))
            started = self.launcher.start(rendered)
            journal.record_process_observation(
                ProcessObservation(authorization, started.process_identity_sha256)
            )
            process_result = started.wait()
            if attached_input is not None:
                attached_input.unlink()
            self._persist_review_stdout(invocation, process_result)
            result_sha256, result_manifest = self._result_fact(
                request,
                workspace,
                process_result.return_code,
                self._report_for_stage(run_spec, request.stage),
            )
            journal.record_result(
                ProviderResult(
                    authorization,
                    started.process_identity_sha256,
                    process_result.return_code,
                    result_sha256,
                    result_manifest,
                )
            )
            current = journal.snapshot()
        elif current.result is None:
            return self.status(run_spec.run_id)
        if current.result is None:
            raise AssertionError("provider result vanished after durable journal update")
        if current.result.return_code != 0:
            raise ApplicationError(
                DecisionOutcome.HANDLER_FAILURE_NO_ACK,
                "the exact provider process returned non-zero",
                "preserve the same delivery and provider evidence",
            )
        try:
            expected_result, expected_manifest = self._result_fact(
                request,
                workspace,
                current.result.return_code,
                self._report_for_stage(run_spec, request.stage),
            )
        except WorkspaceError as exc:
            raise _deny_mutation("durable workspace failed exact result revalidation") from exc
        if current.result.result_sha256 != expected_result:
            raise _deny_mutation(
                "durable provider result no longer matches its workspace or Artifact"
            )
        if current.result.workspace_manifest_sha256 != expected_manifest:
            raise _deny_mutation("durable provider workspace manifest drifted")
        try:
            if request.stage is WorkflowStage.REVIEW:
                self._finish_review(store, run_spec, request, command, workspace)
            else:
                self._finish_coder(store, run_spec, request, command, workspace)
        except ArtifactError as exc:
            raise ApplicationError(
                DecisionOutcome.HANDLER_FAILURE_NO_ACK,
                "provider Artifact or frozen postflight contract is invalid",
                "record failure/ambiguity and preserve the same delivery evidence",
            ) from exc
        except WorkspaceError as exc:
            raise _deny_mutation("isolated or trusted workspace identity failed closed") from exc
        return self.status(run_spec.run_id)

    @staticmethod
    def _materialize_bound_input(invocation: InvocationSpec) -> Path | None:
        if invocation.provider != "opencode" or invocation.provider_args != (ATTACH_INPUT,):
            return None
        target = Path(invocation.input_path)
        if target.is_symlink():
            raise _deny_provider("provider input path is redirected")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(invocation.input_text, encoding="utf-8", newline="\n")
        return target

    def _workspace(
        self,
        run_spec: RunSpec,
        request: LocalStageRequest,
        expected_manifest: str | None,
    ) -> tuple[str, str]:
        root = Path(request.workspace_state_dir).resolve() / run_spec.run_id
        root.mkdir(parents=True, exist_ok=True)
        prefix = f"{request.invocation_id}-"
        matches = sorted(
            child for child in root.iterdir() if child.is_dir() and child.name.startswith(prefix)
        )
        if len(matches) > 1:
            raise _deny_provider("multiple workspaces claim the same invocation identity")
        if not matches:
            prepared = prepare_workspace(
                WorkspaceSpec(
                    request.source_repo,
                    request.expected_commit,
                    str(root),
                    prefix,
                    request.provider_environment,
                )
            )
            return prepared.path, prepared.manifest_sha256
        path = matches[0]
        if path.is_symlink():
            raise _deny_provider("workspace identity is redirected")
        if expected_manifest is None:
            raise _deny_provider("orphan workspace has no durable recovery identity")
        restore_workspace_manifest(str(path), expected_manifest, request.provider_environment)
        assert_workspace_state(str(path), request.expected_commit, request.provider_environment)
        return str(path), expected_manifest

    def _invocation(
        self, run_spec: RunSpec | FreshRunSpec, request: LocalStageRequest, workspace: str
    ) -> InvocationSpec:
        role = {
            WorkflowStage.REVIEW: "reviewer",
            WorkflowStage.ARCHITECT: "architect",
        }.get(request.stage, "coder")
        if role == "architect":
            if not isinstance(run_spec, FreshRunSpec):
                raise _deny_provider("architect Stage requires a fresh RunSpec v2")
            selection = run_spec.architect
        else:
            selection = run_spec.reviewer if role == "reviewer" else run_spec.coder
        report = self._report_for_stage(run_spec, request.stage)
        input_path = Path(workspace) / ".awf" / f"runtime-input-{request.invocation_id}.md"
        return InvocationSpec(
            invocation_id=request.invocation_id,
            run_id=run_spec.run_id,
            task_id=run_spec.task_id,
            authorization_sha256=_digest(
                {
                    "run_spec_sha256": run_spec.sha256,
                    "invocation_id": request.invocation_id,
                    "delivery_id": request.delivery_id,
                    "payload_sha256": request.payload_sha256,
                }
            ),
            role=role,
            provider=selection.provider,
            model=selection.model,
            executable=request.provider_executable,
            workspace=workspace,
            input_path=str(input_path),
            input_text=request.input_text,
            report_path=str(Path(workspace) / report),
            provider_args=request.provider_args,
            environment=bind_environment(dict(request.provider_environment)),
        )

    @staticmethod
    def _persist_review_stdout(invocation: InvocationSpec, result: ProcessResult) -> None:
        if invocation.role not in {"reviewer", "architect"} or not result.stdout:
            return
        if invocation.provider != "pi":
            return
        path = Path(invocation.report_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(result.stdout)

    @staticmethod
    def _report_for_stage(
        run_spec: RunSpec | FreshRunSpec, stage: WorkflowStage
    ) -> str:
        if stage is WorkflowStage.ARCHITECT:
            if not isinstance(run_spec, FreshRunSpec):
                raise _deny_provider("architect Stage requires FreshRunSpec")
            return run_spec.decision_report
        return (
            run_spec.review_report
            if stage is WorkflowStage.REVIEW
            else run_spec.implementation_report
        )

    def _result_fact(
        self,
        request: LocalStageRequest,
        workspace: str,
        return_code: int,
        report_name: str,
    ) -> tuple[str, str]:
        report = Path(workspace) / report_name
        raw = report.read_bytes() if report.is_file() else b""
        value: dict[str, object] = {
            "return_code": return_code,
            "artifact_sha256": hashlib.sha256(raw).hexdigest(),
            "artifact_size": len(raw),
        }
        if request.stage in {WorkflowStage.IMPLEMENT, WorkflowStage.REWORK} and return_code == 0:
            assert_workspace_state(workspace, request.expected_commit, request.provider_environment)
            delta = serialize_workspace_delta(workspace, request.provider_environment)
            value["workspace_delta_sha256"] = delta.identity_sha256
            manifest = self._restore_result_index(workspace, request.provider_environment)
        else:
            manifest = freeze_workspace(workspace, request.provider_environment)
        return _digest(value), manifest

    @staticmethod
    def _restore_result_index(workspace: str, environment: tuple[tuple[str, str], ...]) -> str:
        reset = _git(workspace, environment, "reset", "--mixed", "HEAD")
        if reset.returncode != 0:
            raise _deny_mutation("isolated workspace index restore failed")
        return freeze_workspace(workspace, environment)

    def _finish_coder(
        self,
        store: AtomicRunStore,
        run_spec: RunSpec | FreshRunSpec,
        request: LocalStageRequest,
        command: AuthorizationCommand,
        workspace: str,
    ) -> None:
        assert request.postflight is not None
        card = Path(request.trusted_repo) / run_spec.task_card
        contract = parse_postflight_contract(card, request.python_executable)
        report = Path(workspace) / run_spec.implementation_report
        fact = validate_implementation_report(report, run_spec.implementation_report)
        self._verification(contract, workspace, request.provider_environment)
        delta = serialize_workspace_delta(workspace, request.provider_environment)
        actual_paths = self._delta_paths(workspace, request.provider_environment)
        if actual_paths != request.postflight.delta_paths:
            raise _deny_mutation(
                "postflight path observation does not match the exact workspace delta"
            )
        validate_postflight_paths(contract, actual_paths)
        secret = validate_secret_observation(
            request.postflight.tracked_added_lines,
            request.postflight.untracked_contents,
            request.postflight.unreadable_untracked,
        )
        diff_check = _git(workspace, request.provider_environment, "diff", "HEAD", "--check")
        postflight = postflight_result(actual_paths, secret, diff_check.returncode)
        result = store.journal(command.invocation_id).snapshot().result
        assert result is not None
        manifest = self._restore_result_index(workspace, request.provider_environment)
        if manifest != result.workspace_manifest_sha256:
            raise _deny_mutation("validated workspace did not restore its result identity")
        commit = self._import_and_commit(request, delta)
        effect_sha256 = _digest(
            {
                "artifact_sha256": fact.sha256,
                "postflight_sha256": postflight.observation_sha256,
                "workspace_delta_sha256": delta.identity_sha256,
                "trusted_commit": commit,
            }
        )
        effect = ValidationEffect(
            command.authorization_sha256,
            result.result_sha256,
            fact.sha256,
            effect_sha256,
        )
        payload = {
            "source_invocation_id": command.invocation_id,
            "effect_sha256": effect_sha256,
        }
        outgoing = ResultEnvelope.create(
            run_id=run_spec.run_id,
            task_id=run_spec.task_id,
            run_spec_sha256=run_spec.sha256,
            source_role="coder",
            target_role="reviewer",
            route=run_spec.review_route,
            source_invocation_id=command.invocation_id,
            source_authorization_sha256=command.authorization_sha256,
            target_invocation_id=request.outgoing_target_invocation_id,
            causation_delivery_id=request.delivery_id,
            payload=payload,
        )
        store.record_handoff(
            HandoffCommand(
                run_spec.sha256,
                command.invocation_id,
                command.authorization_sha256,
                outgoing.delivery_id,
                outgoing.payload_sha256.removeprefix("sha256:"),
                run_spec.review_route,
                "reviewer",
            ),
            effect,
            OutgoingIntent.from_envelope(outgoing),
        )

    def _finish_review(
        self,
        store: AtomicRunStore,
        run_spec: RunSpec | FreshRunSpec,
        request: LocalStageRequest,
        command: AuthorizationCommand,
        workspace: str,
    ) -> None:
        report_path = Path(workspace) / run_spec.review_report
        validated = parse_review_report(report_path, run_spec.review_report)
        trusted, environment = request.trusted_repo, request.provider_environment
        head = _git_text(trusted, environment, "rev-parse", "HEAD")
        tree = _git_text(trusted, environment, "rev-parse", "HEAD^{tree}")
        workspace_tree = _git_text(workspace, environment, "rev-parse", "HEAD^{tree}")
        if head != request.expected_commit or tree != workspace_tree:
            raise _deny_mutation("review result no longer matches the trusted Git lineage")
        trusted_report = resolve_repo_file(
            Path(request.trusted_repo), run_spec.review_report, "ReviewReport"
        )
        trusted_report.parent.mkdir(parents=True, exist_ok=True)
        trusted_report.write_bytes(report_path.read_bytes())
        effect_sha256 = _digest(
            {
                "artifact_sha256": validated.artifact.sha256,
                "canonical_sha256": validated.review.canonical_sha256,
                "trusted_commit": head,
                "trusted_tree": tree,
            }
        )
        result = store.journal(command.invocation_id).snapshot().result
        assert result is not None
        effect = ValidationEffect(
            command.authorization_sha256,
            result.result_sha256,
            validated.artifact.sha256,
            effect_sha256,
        )
        payload = validated.review.as_payload()
        verdict = payload["verdict"]
        if verdict == "REQUEST_CHANGES":
            rework_payload = json.loads(normalize_rework_feedback(payload))
            outgoing = ResultEnvelope.create(
                run_id=run_spec.run_id,
                task_id=run_spec.task_id,
                run_spec_sha256=run_spec.sha256,
                source_role="reviewer",
                target_role="coder",
                route=run_spec.rework_route,
                source_invocation_id=command.invocation_id,
                source_authorization_sha256=command.authorization_sha256,
                target_invocation_id=request.outgoing_target_invocation_id,
                causation_delivery_id=request.delivery_id,
                payload=rework_payload,
            )
            store.record_handoff(
                HandoffCommand(
                    run_spec.sha256,
                    command.invocation_id,
                    command.authorization_sha256,
                    outgoing.delivery_id,
                    outgoing.payload_sha256.removeprefix("sha256:"),
                    run_spec.rework_route,
                    "coder",
                ),
                effect,
                OutgoingIntent.from_envelope(outgoing),
            )
            return
        terminal = TerminalOutcome.COMPLETED if verdict == "PASS" else TerminalOutcome.BLOCKED
        outgoing = ResultEnvelope.create(
            run_id=run_spec.run_id,
            task_id=run_spec.task_id,
            run_spec_sha256=run_spec.sha256,
            source_role="reviewer",
            target_role="architect",
            route=f"result:{terminal.value}",
            source_invocation_id=command.invocation_id,
            source_authorization_sha256=command.authorization_sha256,
            target_invocation_id=request.outgoing_target_invocation_id,
            causation_delivery_id=request.delivery_id,
            payload=payload,
        )
        store.record_terminal(
            TerminalCommand(
                run_spec.sha256,
                command.invocation_id,
                command.authorization_sha256,
                outgoing.delivery_id,
                outgoing.payload_sha256.removeprefix("sha256:"),
                terminal,
                effect_sha256,
            ),
            effect,
            OutgoingIntent.from_envelope(outgoing),
        )

    @staticmethod
    def _verification(
        contract: PostflightContract,
        workspace: str,
        environment: tuple[tuple[str, str], ...],
    ) -> None:
        for argv in contract.verification_commands:
            completed = subprocess.run(
                list(argv),
                cwd=workspace,
                env=dict(environment),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
            )
            if completed.returncode != 0:
                raise ApplicationError(
                    DecisionOutcome.HANDLER_FAILURE_NO_ACK,
                    "frozen postflight verification failed",
                    "preserve the same delivery and verification evidence",
                )

    @staticmethod
    def _delta_paths(workspace: str, environment: tuple[tuple[str, str], ...]) -> tuple[str, ...]:
        completed = _git(workspace, environment, "diff", "--cached", "--name-only", "-z", "HEAD")
        if completed.returncode != 0:
            raise _deny_mutation("workspace delta path observation failed")
        try:
            paths = tuple(item.decode("utf-8") for item in completed.stdout.split(b"\0") if item)
        except UnicodeError as exc:
            raise _deny_mutation("workspace delta path is not UTF-8") from exc
        return paths

    @staticmethod
    def _import_and_commit(request: LocalStageRequest, delta: WorkspaceDelta) -> str:
        head_tree = _git_text(
            request.trusted_repo, request.provider_environment, "rev-parse", "HEAD^{tree}"
        )
        index_tree = _git_text(request.trusted_repo, request.provider_environment, "write-tree")
        if head_tree == delta.model_tree:
            return _git_text(
                request.trusted_repo, request.provider_environment, "rev-parse", "HEAD"
            )
        if head_tree != delta.base_tree:
            raise _deny_mutation("trusted repository base tree drifted before import")
        if index_tree == delta.base_tree:
            imported = import_workspace_delta(
                delta, request.trusted_repo, request.provider_environment
            )
            if imported != delta.model_tree:
                raise AssertionError("trusted import returned a conflicting tree")
        elif index_tree != delta.model_tree:
            raise _deny_mutation("trusted repository index drifted before commit")
        completed = _git(
            request.trusted_repo,
            request.provider_environment,
            "-c",
            "user.name=Runtime V2 Local Application",
            "-c",
            "user.email=runtime-v2@example.invalid",
            "commit",
            "--no-gpg-sign",
            "-m",
            f"Record exact local effect for {request.invocation_id}",
        )
        if completed.returncode != 0:
            raise _deny_mutation("trusted local commit failed")
        commit = _git_text(request.trusted_repo, request.provider_environment, "rev-parse", "HEAD")
        tree = _git_text(
            request.trusted_repo, request.provider_environment, "rev-parse", "HEAD^{tree}"
        )
        if tree != delta.model_tree:
            raise _deny_mutation("trusted commit does not bind the verified model tree")
        return commit
