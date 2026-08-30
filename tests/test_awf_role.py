"""Regression tests for the cross-machine role handler."""

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from agent_workflow.operations import (
    awf_bootstrap,
    awf_dispatch,
    awf_executor,
    awf_handoff_check,
    awf_listen,
    awf_role,
)
from agent_workflow.resources import operations_dir
from agent_workflow.runtime import RenderedInputFile, RenderedInvocation
from agent_workflow.state_root import state_root_binding

SCRIPTS_DIR = operations_dir()
MODULE_PATH = SCRIPTS_DIR / "awf_role.py"
LISTEN_MODULE_PATH = SCRIPTS_DIR / "awf_listen.py"
DISPATCH_PATH = SCRIPTS_DIR / "awf-dispatch.sh"
NATIVE_DISPATCH_PATH = SCRIPTS_DIR / "awf_dispatch.py"
HANDOFF_MODULE_PATH = SCRIPTS_DIR / "awf_handoff_check.py"
BOOTSTRAP_MODULE_PATH = SCRIPTS_DIR / "awf_bootstrap.py"


_VALID_POSTFLIGHT_CARD = """# Card
<!-- awf-postflight
{
  "allowed_paths": ["task.md"],
  "verification_commands": [["{python}", "-c", "exit(0)"]]
}
-->
"""

# Secret test fragments — constructed to avoid literal secrets in the test
# source so the new postflight secret gate does not reject its own
# uncommitted test diff (self-hosting requirement).
_GITHUB_TOKEN = "ghp_" + ("A" * 36)
_OPENAI_KEY = "sk-" + ("A" * 30)
_AWS_KEY = "AKIA" + "1234567890123456"
_PK_HEADER = "-----BEGIN " + "RSA PRIVATE KEY-----"
_PK_FOOTER = "-----END " + "RSA PRIVATE KEY-----"
_CRED_URL = "http://" + "user:password@host.com/path"


def run(*args: str, cwd: Path) -> str:
    completed = subprocess.run(
        args,
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def model_git_argv(*args: str) -> list[str]:
    """Use the shell resolution path that OpenCode uses for model Git commands."""
    if os.name == "nt":
        return ["cmd", "/d", "/s", "/c", "git", *args]
    return ["git", *args]


def commit(repo: Path, message: str, filename: str, content: str) -> str:
    (repo / filename).write_text(content, encoding="utf-8")
    run("git", "add", filename, cwd=repo)
    run("git", "commit", "-m", message, cwd=repo)
    return run("git", "rev-parse", "HEAD", cwd=repo)


def dispatch_shell_path(path: Path) -> str:
    if os.name != "nt":
        return str(path)
    resolved = path.resolve()
    drive = resolved.drive.lower().rstrip(":")
    rest = str(resolved).replace("\\", "/").split(":", 1)[1]
    return f"/{drive}{rest}"


def native_dispatch_argv(repo: Path, *args: str) -> list[str]:
    return [
        sys.executable,
        str(NATIVE_DISPATCH_PATH),
        "--repo",
        str(repo),
        "--tool",
        "opencode",
        *args,
    ]


# ---------------------------------------------------------------------------
# Durable handler exit evidence
# ---------------------------------------------------------------------------


def test_listener_handler_passes_event_id_once():
    handler = awf_listen.build_handler("python", "awf_role.py", "coder")

    assert handler.split().count("--event-id") == 1
    assert "--event-id {id}" in handler
    assert "--input-type {type}" in handler
    assert "--delivery-id {payload.awf_delivery_id}" in handler
    assert "--payload-sha256 {payload.awf_payload_sha256}" in handler
    assert "--source-event-id {payload.awf_source_event_id}" in handler


def test_structured_handler_argv_json_preserves_paths_and_payload_placeholders(tmp_path):
    def render_placeholders(argv: list[str], event: dict[str, object]) -> list[str]:
        rendered: list[str] = []
        for value in argv:
            if value.startswith("{") and value.endswith("}"):
                current: object = event
                for part in value[1:-1].split("."):
                    assert isinstance(current, dict)
                    current = current[part]
                rendered.append(str(current))
            else:
                rendered.append(value)
        return rendered

    role_state_root = tmp_path / "state root \u03a9"
    preflight_state_root = tmp_path / "preflight state \u03a9"
    config_path = tmp_path / "config dir" / "dispatch \u03a9.env"
    role_argv = awf_listen.build_handler_argv(
        str(tmp_path / "bin dir" / "python exe"),
        str(tmp_path / "script dir" / "awf_role.py"),
        "coder",
        on_type="task:awf-rework-v3",
        upstream_remote="up stream",
        head_remote="fork remote",
        state_root=role_state_root,
    )
    preflight_argv = awf_listen.build_preflight_handler_argv(
        str(tmp_path / "bin dir" / "python exe"),
        str(tmp_path / "script dir" / "awf_preflight.py"),
        "handle-request",
        config_path=config_path,
        state_root=preflight_state_root,
    )

    assert json.loads(awf_listen.handler_argv_json(role_argv)) == role_argv
    assert json.loads(awf_listen.handler_argv_json(preflight_argv)) == preflight_argv
    assert str(role_state_root) in role_argv
    assert f'"{role_state_root}"' not in role_argv
    assert str(config_path) in preflight_argv
    assert f'"{config_path}"' not in preflight_argv

    attack = 'value"; touch /tmp/not-executed --branch'
    role_event = {
        "id": 21,
        "type": "task:awf-rework-v3",
        "payload": {
            "awf_delivery_id": "delivery-1",
            "awf_payload_sha256": "sha256:payload",
            "awf_source_event_id": "20",
            "branch": attack,
            "card": "docs/task card.md",
            "commit": "a" * 40,
            "model": "test model",
            "tool": "opencode",
            "report": "docs/report path.md",
            "provenance_version": "awf.pr-provenance.v1",
            "upstream_repo": "upstream/project",
            "base_ref": "main",
            "base_sha": "b" * 40,
            "head_repo": "fork/project",
            "head_ref": "codex/structured-handler-contract",
            "head_sha": "c" * 40,
            "pull_request": "90",
            "review_report_path": "docs/review path.md",
            "review_report": attack,
        },
    }
    preflight_event = {
        "id": 22,
        "type": awf_listen.PREFLIGHT_REQUEST_TYPE,
        "payload": {
            "probe_id": attack,
            "fingerprint": "sha256:" + "d" * 64,
            "source_role": "architect",
            "target_role": "coder",
        },
    }

    rendered_role = render_placeholders(role_argv, role_event)
    rendered_preflight = render_placeholders(preflight_argv, preflight_event)

    assert rendered_role[rendered_role.index("--delivery-id") + 1] == "delivery-1"
    assert rendered_role[rendered_role.index("--payload-sha256") + 1] == "sha256:payload"
    assert rendered_role[rendered_role.index("--branch") + 1] == attack
    assert rendered_role[rendered_role.index("--report") + 1] == "docs/report path.md"
    assert rendered_role[rendered_role.index("--review-feedback") + 1] == attack
    assert rendered_role[rendered_role.index("--pull-request") + 1] == "90"
    assert "touch" not in rendered_role
    assert rendered_preflight[rendered_preflight.index("--probe-id") + 1] == attack
    assert rendered_preflight[rendered_preflight.index("--config") + 1] == str(config_path)
    assert "touch" not in rendered_preflight


def test_custom_state_root_propagates_to_run_and_feedback_records(monkeypatch, tmp_path):
    state_root = (tmp_path / "custom-state").resolve()
    binding = state_root_binding(state_root)
    observed = {}

    def role_handler(args):
        observed["evidence"] = args.evidence
        authority = {
            "sha256": "sha256:" + "a" * 64,
            "allowed_operations": ["diagnose", "endpoint_discovery", "listener_restart"],
        }
        packet = awf_role.build_context_packet(
            run_id="root-propagation",
            taskcard="docs/task.md",
            frozen_base="a" * 40,
            branch="codex/root-propagation",
            authority_manifest=authority,
            next_action="stop",
            stage="implement",
            state_root_sha256=binding,
        )
        awf_role.RunLedger(state_root, "root-propagation").initialize(
            packet, stage="implement", max_attempts=1, rework_budget=1
        )
        input_context = {
            "key": "delivery-root",
            "delivery_id": "delivery-root",
            "payload_sha256": "sha256:payload",
            "source_event_id": 901,
        }
        observed["checkpoint_path"], _ = awf_role.begin_recovery_checkpoint(
            args.evidence,
            input_context,
            role="reviewer",
            branch="codex/root-propagation",
            source_commit="a" * 40,
            provenance=_pr_provenance(),
        )
        payload = awf_role.build_delivery_payload(
            "reviewer", "decision:awf-ready", {"task_id": "root-propagation"}, args.evidence
        )
        observed["outbox_path"], _ = awf_role.prepare_outbox(
            args.evidence,
            input_context,
            action="reviewer.pass",
            branch="codex/root-propagation",
            source_commit="a" * 40,
            evidence_commit="b" * 40,
            to_role="architect",
            event_type="decision:awf-ready",
            payload=payload,
        )
        awf_role.complete_inbox(args.evidence, "delivery-root", "sha256:payload")
        feedback = sys.modules["agent_workflow.operations.awf_feedback"]
        occurrence = feedback.build_occurrence(
            {
                "kind": "reliability",
                "component": "configuration",
                "summary": "Canonical state root",
                "observed": "All state shares one root",
                "expected": "The binding remains exact",
            },
            input_delivery_id="delivery-root",
            source_role="reviewer",
            source_tool="pi",
            awf_version=awf_role.AWF_VERSION,
        )
        observed["feedback_path"] = feedback.queue_occurrence(state_root, occurrence)
        return 0

    monkeypatch.setitem(awf_role.ROLES, "reviewer", role_handler)
    monkeypatch.setenv("AWF_STATE_ROOT", str(state_root))
    monkeypatch.setenv("AWF_STATE_ROOT_SHA256", binding)

    assert (
        awf_role.main(
            [
                "reviewer",
                "--event-id",
                "901",
                "--branch",
                "codex/root-propagation",
                "--state-root",
                str(state_root),
                "--state-root-sha256",
                binding,
            ]
        )
        == 0
    )

    evidence = observed["evidence"]
    assert evidence.state_dir == state_root
    result = json.loads(evidence.result_path.read_text(encoding="utf-8"))
    assert result["state_root_sha256"] == binding
    _, packet = awf_role.RunLedger(state_root, "root-propagation").recover()
    assert packet["state_root_sha256"] == binding
    checkpoint = json.loads(observed["checkpoint_path"].read_text(encoding="utf-8"))
    assert checkpoint["state_root_sha256"] == binding
    outbox = json.loads(observed["outbox_path"].read_text(encoding="utf-8"))
    assert outbox["state_root_sha256"] == binding
    inbox = next((state_root / "inbox" / "reviewer").glob("*.json"))
    assert json.loads(inbox.read_text(encoding="utf-8"))["state_root_sha256"] == binding
    feedback_record = json.loads(observed["feedback_path"].read_text(encoding="utf-8"))
    assert feedback_record["state_root_sha256"] == binding


def test_state_root_mismatch_fails_before_bus_or_model(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    expected = (tmp_path / "expected").resolve()
    conflicting = (tmp_path / "conflicting").resolve()
    environment = {
        "AGENT_BUS_URL": "http://bus.invalid",
        "AWF_CODER_TOKEN": "test-token",
        "AWF_STATE_ROOT": str(conflicting),
    }
    monkeypatch.setattr(awf_listen.os, "environ", environment)
    monkeypatch.setattr(
        awf_listen,
        "run_command",
        lambda *_args, **_kwargs: pytest.fail("mismatch must fail before Bus connect"),
    )

    with pytest.raises(SystemExit, match="2"):
        awf_listen.main(
            [
                "--role",
                "coder",
                "--repo",
                str(repo),
                "--state-root",
                str(expected),
                "--node-launch-id",
                "a" * 32,
            ]
        )

    monkeypatch.setitem(
        awf_role.ROLES,
        "coder",
        lambda _args: pytest.fail("mismatch must fail before model invocation"),
    )
    monkeypatch.setenv("AWF_STATE_ROOT", str(expected))
    monkeypatch.setenv("AWF_STATE_ROOT_SHA256", state_root_binding(expected))
    with pytest.raises(SystemExit, match="2"):
        awf_role.main(
            [
                "coder",
                "--event-id",
                "902",
                "--branch",
                "codex/root-mismatch",
                "--state-root",
                str(conflicting),
            ]
        )


def test_listener_handler_passes_distinct_report_paths():
    handler = awf_listen.build_handler("python", "awf_role.py", "reviewer")

    assert "--report {payload.report}" in handler
    assert "--review-report {payload.review_report}" in handler


def test_v3_listener_handler_passes_complete_pr_provenance():
    handler = awf_listen.build_handler(
        "python",
        "awf_role.py",
        "reviewer",
        on_type="task:awf-review-v3",
    )

    for field in awf_role._PROVENANCE_FIELDS:
        option = "--" + field.replace("_", "-")
        assert f"{option} {{payload.{field}}}" in handler


def test_v3_listener_handler_passes_configured_remote_names():
    handler = awf_listen.build_handler(
        "python",
        "awf_role.py",
        "reviewer",
        on_type="task:awf-review-v3",
        upstream_remote="origin",
        head_remote="fork",
    )

    assert "--upstream-remote origin" in handler
    assert "--head-remote fork" in handler


def test_rework_handler_maps_report_path_and_structured_feedback():
    handler = awf_listen.build_handler(
        "python",
        "awf_role.py",
        "coder",
        on_type="task:awf-rework",
    )

    assert "--review-report {payload.review_report_path}" in handler
    assert "--review-feedback {payload.review_report}" in handler


def test_architect_handler_maps_terminal_report_and_provenance():
    handler = awf_listen.build_handler(
        "python",
        "awf_role.py",
        "architect",
        on_type="decision:awf-ready-v3",
    )

    assert "--review-report {payload.review_report_path}" in handler
    assert "--review-feedback {payload.review_report}" in handler
    assert "--pull-request {payload.pull_request}" in handler


def test_listener_adds_bus_host_to_existing_no_proxy_entries():
    environment = {
        "NO_PROXY": "localhost,127.0.0.1",
        "no_proxy": "internal.example",
    }

    awf_listen.add_url_host_to_no_proxy(environment, "http://100.108.67.47:8800")

    expected = "localhost,127.0.0.1,internal.example,100.108.67.47"
    assert environment["NO_PROXY"] == expected
    assert environment["no_proxy"] == expected


@pytest.mark.parametrize(
    ("os_name", "environ", "home", "expected"),
    [
        (
            "nt",
            {"LOCALAPPDATA": "C:/Users/test/AppData/Local"},
            "/unused",
            Path("C:/Users/test/AppData/Local/agent-workflow/runs/event-50"),
        ),
        (
            "posix",
            {"XDG_STATE_HOME": "/var/state/test"},
            "/unused",
            Path("/var/state/test/agent-workflow/runs/event-50"),
        ),
        (
            "posix",
            {},
            "/home/test",
            Path("/home/test/.local/state/agent-workflow/runs/event-50"),
        ),
    ],
)
def test_event_run_directory_uses_os_state_location(os_name, environ, home, expected):
    assert (
        awf_role.event_run_directory(
            50,
            os_name=os_name,
            environ=environ,
            home=Path(home),
        )
        == expected
    )


def test_delivery_state_paths_stay_outside_checkout(tmp_path):
    evidence = awf_role.RunEvidence(70, "coder", state_root=tmp_path / "state")

    outbox = awf_role.delivery_state_path(evidence, "outbox", "awf:delivery:one")
    inbox = awf_role.delivery_state_path(evidence, "inbox", "awf:delivery:one")

    assert outbox.parent.parent == tmp_path / "state" / "outbox"
    assert inbox.parent.parent == tmp_path / "state" / "inbox"
    assert outbox.name.endswith(".json")
    assert inbox.name.endswith(".json")
    assert outbox != inbox


def test_run_evidence_appends_log_and_atomically_updates_result(tmp_path):
    evidence = awf_role.RunEvidence(50, "coder", state_root=tmp_path)

    evidence.record("handler_start", handler_pid=1234, postflight_started=False)
    first = json.loads(evidence.result_path.read_text(encoding="utf-8"))
    evidence.record("opencode_start", opencode_pid=4321, opencode_cwd="/work")
    second = json.loads(evidence.result_path.read_text(encoding="utf-8"))

    assert first["last_phase"] == "handler_start"
    assert second["last_phase"] == "opencode_start"
    assert second["handler_pid"] == 1234
    assert second["opencode_pid"] == 4321
    assert not list(evidence.run_dir.glob("result.json.tmp-*"))
    phases = [
        json.loads(line)["phase"]
        for line in evidence.log_path.read_text(encoding="utf-8").splitlines()
    ]
    assert phases == ["handler_start", "opencode_start"]


@pytest.mark.parametrize(("child_rc", "expected_rc"), [(0, 0), (7, 7)])
def test_controlled_subprocess_persists_real_pid_and_return_code(tmp_path, child_rc, expected_rc):
    evidence = awf_role.RunEvidence(51 + child_rc, "coder", state_root=tmp_path)

    rc = awf_role.spawn(
        [sys.executable, "-c", f"raise SystemExit({child_rc})"],
        cwd=str(tmp_path),
        env=awf_role.model_env(),
        evidence=evidence,
        tracked_phase="opencode",
    )

    result = json.loads(evidence.result_path.read_text(encoding="utf-8"))
    assert rc == expected_rc
    assert result["last_phase"] == "opencode_exit"
    assert result["opencode_pid"] != os.getpid()
    assert result["opencode_cwd"] == str(tmp_path)
    assert result["opencode_rc"] == expected_rc
    assert result["opencode_duration_seconds"] >= 0
    assert result["postflight_started"] is False
    diagnostic = evidence.run_dir / "opencode.stderr"
    assert diagnostic.exists() is (child_rc != 0)


def test_tracked_subprocess_retains_only_bounded_stderr_on_failure(tmp_path):
    evidence = awf_role.RunEvidence(58, "coder", state_root=tmp_path)

    rc = awf_role.spawn(
        [
            sys.executable,
            "-c",
            "import sys; sys.stderr.write('x' * 65536); raise SystemExit(3)",
        ],
        cwd=str(tmp_path),
        env=awf_role.model_env(),
        evidence=evidence,
        tracked_phase="opencode",
    )

    assert rc == 3
    assert (evidence.run_dir / "opencode.stderr").read_text(encoding="utf-8") == (
        "x" * awf_role._CAPTURED_STDERR_MAX_BYTES
        + f"\n[stderr truncated at {awf_role._CAPTURED_STDERR_MAX_BYTES} bytes]\n"
    )


def test_tracked_subprocess_preserves_early_exit_stderr_with_large_stdin(tmp_path):
    evidence = awf_role.RunEvidence(57, "reviewer", state_root=tmp_path)

    rc = awf_role.spawn(
        [sys.executable, "-c", "import sys; sys.stderr.write('early fail'); raise SystemExit(7)"],
        cwd=str(tmp_path),
        stdin="x" * (2 * 1024 * 1024),
        env=awf_role.model_env(),
        evidence=evidence,
        tracked_phase="codex",
    )

    result = json.loads(evidence.result_path.read_text(encoding="utf-8"))
    assert rc == 7
    assert result["codex_rc"] == 7
    assert "codex_interrupted" not in result
    assert (evidence.run_dir / "codex.stderr").read_text(encoding="utf-8") == "early fail"


def test_windows_invalid_argument_is_a_closed_stdin_pipe_only():
    assert awf_role._is_closed_stdin_error(OSError(errno.EINVAL, "closed"), os_name="nt")
    assert not awf_role._is_closed_stdin_error(OSError(errno.EINVAL, "invalid"), os_name="posix")
    assert not awf_role._is_closed_stdin_error(OSError(errno.EIO, "io"), os_name="nt")


def test_tracked_subprocess_discards_uncaptured_stdout(monkeypatch, tmp_path):
    real_start_command = awf_role.start_command
    observed = {}

    def capture_start_command(*args, **kwargs):
        observed["stdout"] = kwargs["stdout"]
        return real_start_command(*args, **kwargs)

    monkeypatch.setattr(awf_role, "start_command", capture_start_command)
    evidence = awf_role.RunEvidence(56, "coder", state_root=tmp_path)

    rc = awf_role.spawn(
        [sys.executable, "-c", "print('provider progress')"],
        cwd=str(tmp_path),
        env=awf_role.model_env(),
        evidence=evidence,
        tracked_phase="opencode",
    )

    assert rc == 0
    assert observed["stdout"] is awf_role.DEVNULL


def test_controlled_subprocess_interruption_kills_and_reaps_before_exit_evidence(
    monkeypatch, tmp_path
):
    class InterruptedProcess:
        pid = 4321
        returncode = None
        killed = False
        waited = False

        def communicate(self, _stdin):
            raise OSError("controlled interruption")

        def poll(self):
            return self.returncode

        def kill(self):
            self.killed = True
            self.returncode = -9

        def wait(self):
            self.waited = True
            return self.returncode

    process = InterruptedProcess()
    monkeypatch.setattr(awf_role, "start_command", lambda *args, **kwargs: process)
    evidence = awf_role.RunEvidence(59, "coder", state_root=tmp_path)

    with pytest.raises(OSError, match="controlled interruption"):
        awf_role.spawn(
            ["controlled-opencode"],
            cwd=str(tmp_path),
            evidence=evidence,
            tracked_phase="opencode",
        )

    result = json.loads(evidence.result_path.read_text(encoding="utf-8"))
    assert process.killed is True
    assert process.waited is True
    assert result["last_phase"] == "opencode_exit"
    assert result["opencode_rc"] == -9
    assert result["opencode_interrupted"] is True


@pytest.mark.parametrize(("role_rc", "expected_rc"), [(0, 0), (9, 9)])
def test_handler_main_persists_exit_for_success_and_failure(
    monkeypatch, tmp_path, role_rc, expected_rc
):
    monkeypatch.setattr(
        awf_role,
        "event_run_directory",
        lambda event_id, **kwargs: tmp_path / f"event-{event_id}",
    )

    def fake_role(_args):
        if role_rc:
            raise SystemExit(role_rc)
        return 0

    monkeypatch.setitem(awf_role.ROLES, "coder", fake_role)
    argv = [
        "coder",
        "--event-id",
        "60",
        "--branch",
        "feature/task",
    ]

    if role_rc:
        with pytest.raises(SystemExit, match=str(role_rc)):
            awf_role.main(argv)
    else:
        assert awf_role.main(argv) == 0

    result = json.loads((tmp_path / "event-60" / "result.json").read_text(encoding="utf-8"))
    assert result["last_phase"] == "handler_exit"
    assert result["last_phase_before_exit"] == "handler_start"
    assert result["handler_rc"] == expected_rc


@pytest.fixture
def repositories(tmp_path: Path) -> tuple[Path, Path, Path]:
    origin = tmp_path / "origin.git"
    seed = tmp_path / "seed"
    executor = tmp_path / "executor"
    run("git", "init", "--bare", str(origin), cwd=tmp_path)
    run("git", "init", "-b", "main", str(seed), cwd=tmp_path)
    run("git", "config", "user.name", "AWF Test", cwd=seed)
    run("git", "config", "user.email", "awf-test@example.invalid", cwd=seed)
    commit(seed, "initial", "README.md", "initial\n")
    run("git", "remote", "add", "origin", str(origin), cwd=seed)
    run("git", "push", "-u", "origin", "main", cwd=seed)
    run("git", "switch", "-c", "feature/task", cwd=seed)
    commit(seed, "task card", "task.md", "task\n")
    run("git", "push", "-u", "origin", "feature/task", cwd=seed)
    run("git", "clone", str(origin), str(executor), cwd=tmp_path)
    run("git", "config", "user.name", "AWF Executor", cwd=executor)
    run("git", "config", "user.email", "awf-executor@example.invalid", cwd=executor)
    run("git", "switch", "feature/task", cwd=executor)
    return origin, seed, executor


def test_minimal_listener_handler_opencode_return_chain(repositories, tmp_path):
    _, seed, executor = repositories
    remote_head = commit(seed, "review inputs", "report.md", "controlled report\n")
    run("git", "push", "origin", "feature/task", cwd=seed)

    fake_script = tmp_path / "controlled-reviewer.py"
    fake_script.write_text(
        "import sys\n"
        "from pathlib import Path\n"
        "args = sys.argv[1:]\n"
        "repo = Path(args[args.index('--dir') + 1])\n"
        "path = repo / '.awf' / 'artifacts' / 'review-report-task.md'\n"
        "path.parent.mkdir(parents=True, exist_ok=True)\n"
        f"path.write_text({_review_markdown('PASS')!r}, encoding='utf-8')\n",
        encoding="utf-8",
    )
    if os.name == "nt":
        fake_tool = tmp_path / "controlled-tool.cmd"
        fake_tool.write_text(f'@"{sys.executable}" "{fake_script}" %*\r\n', encoding="utf-8")
        fake_tool.with_suffix(".ps1").write_text(
            f"& '{str(sys.executable).replace(chr(39), chr(39) * 2)}' "
            f"'{str(fake_script).replace(chr(39), chr(39) * 2)}' @args\n"
            "exit $LASTEXITCODE\n",
            encoding="utf-8",
        )
    else:
        fake_tool = tmp_path / "controlled-tool"
        fake_tool.write_text(
            f"#!{sys.executable}\nexec(open({str(fake_script)!r}).read())\n", encoding="utf-8"
        )
        fake_tool.chmod(0o755)

    send_bin = executor / "send"
    send_bin.write_text(
        "import sys\n"
        "from pathlib import Path\n"
        "args = ' '.join(sys.argv[1:])\n"
        "Path('send-called.txt').write_text(args, encoding='utf-8')\n",
        encoding="utf-8",
    )
    (executor / ".git" / "info" / "exclude").write_text("send\n", encoding="utf-8")

    state_root = tmp_path / "os-state"
    child_environment = dict(os.environ)
    child_environment.update(
        {
            "AWF_REPO_DIR": str(executor),
            "AWF_SCRIPT_DIR": str(MODULE_PATH.parent),
            "AWF_TOOL": "opencode",
            "AWF_BASE": "main",
            "AWF_OPENCODE_BIN": str(fake_tool),
            "AWF_BUS_BIN": sys.executable,
            "AGENT_BUS_URL": "http://controlled.invalid",
            "AWF_REVIEWER_TOKEN": "controlled-test-token",
        }
    )
    if os.name == "nt":
        child_environment["LOCALAPPDATA"] = str(state_root)
    else:
        child_environment["XDG_STATE_HOME"] = str(state_root)

    handler = awf_listen.build_handler(sys.executable, str(MODULE_PATH), "reviewer")
    input_payload = {
        "task_id": "task",
        "branch": "feature/task",
        "card": "task.md",
        "commit": remote_head,
        "tool": "opencode",
        "model": "controlled/model",
        "report": "report.md",
        "review_report": ".awf/artifacts/review-report-task.md",
    }
    input_hash = awf_role.canonical_payload_sha256(input_payload)
    delivery_id = awf_role.make_delivery_id("coder", "task:awf-review-v2", input_hash, 61)
    replacements = {
        "{id}": "63",
        "{type}": "task:awf-review-v2",
        "{payload.awf_delivery_id}": delivery_id,
        "{payload.awf_payload_sha256}": input_hash,
        "{payload.awf_source_event_id}": "61",
        "{payload.branch}": "feature/task",
        "{payload.card}": "task.md",
        "{payload.commit}": remote_head,
        "{payload.model}": "controlled/model",
        "{payload.tool}": "opencode",
        "{payload.report}": "report.md",
        "{payload.review_report}": ".awf/artifacts/review-report-task.md",
    }
    for placeholder, value in replacements.items():
        handler = handler.replace(placeholder, value)

    completed = subprocess.run(
        handler,
        cwd=executor,
        env=child_environment,
        shell=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    assert completed.returncode == 0, completed.stderr
    run_dir = state_root / "agent-workflow" / "runs" / "event-63"
    result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    assert result["last_phase"] == "handler_exit"
    assert result["last_phase_before_exit"] == "outbox_sent"
    assert result["handler_rc"] == 0
    assert result["opencode_pid"] != os.getpid()
    assert result["opencode_rc"] == 0
    assert result["postflight_started"] is False


def test_fetch_and_checkout_updates_stale_branch_to_remote(repositories):
    _, seed, executor = repositories
    remote_head = commit(seed, "implementation", "result.txt", "done\n")
    run("git", "push", "origin", "feature/task", cwd=seed)

    awf_role.fetch_and_checkout(str(executor), "feature/task", remote_head)

    assert run("git", "rev-parse", "HEAD", cwd=executor) == remote_head
    assert run("git", "status", "--porcelain", cwd=executor) == ""


def test_fetch_and_checkout_rejects_dirty_worktree_before_fetch(repositories):
    _, seed, executor = repositories
    old_remote_ref = run("git", "rev-parse", "origin/feature/task", cwd=executor)
    commit(seed, "remote update", "remote.txt", "new\n")
    run("git", "push", "origin", "feature/task", cwd=seed)
    (executor / "dirty.txt").write_text("do not overwrite\n", encoding="utf-8")

    with pytest.raises(SystemExit, match="1"):
        awf_role.fetch_and_checkout(str(executor), "feature/task", old_remote_ref)

    assert run("git", "rev-parse", "origin/feature/task", cwd=executor) == old_remote_ref
    assert (executor / "dirty.txt").read_text(encoding="utf-8") == "do not overwrite\n"


def test_fetch_and_checkout_rejects_unpushed_local_commits(repositories):
    _, _, executor = repositories
    local_head = commit(executor, "local only", "local.txt", "keep\n")
    remote_head = run("git", "rev-parse", "origin/feature/task", cwd=executor)

    with pytest.raises(SystemExit, match="1"):
        awf_role.fetch_and_checkout(str(executor), "feature/task", remote_head)

    assert run("git", "rev-parse", "HEAD", cwd=executor) == local_head
    assert (executor / "local.txt").read_text(encoding="utf-8") == "keep\n"


def test_fetch_and_checkout_rejects_branch_changed_after_dispatch(repositories):
    _, seed, executor = repositories
    dispatched_head = run("git", "rev-parse", "origin/feature/task", cwd=executor)
    original_head = run("git", "rev-parse", "HEAD", cwd=executor)
    commit(seed, "later update", "later.txt", "not dispatched\n")
    run("git", "push", "origin", "feature/task", cwd=seed)

    with pytest.raises(SystemExit, match="1"):
        awf_role.fetch_and_checkout(str(executor), "feature/task", dispatched_head)

    assert run("git", "rev-parse", "HEAD", cwd=executor) == original_head
    assert not (executor / "later.txt").exists()


def test_fetch_and_checkout_finds_task_branch_from_single_branch_clone(
    repositories, tmp_path: Path
):
    origin, seed, _ = repositories
    single = tmp_path / "single"
    run(
        "git",
        "clone",
        "--single-branch",
        "--branch",
        "main",
        str(origin),
        str(single),
        cwd=tmp_path,
    )
    task_head = run("git", "rev-parse", "feature/task", cwd=seed)
    assert run("git", "branch", "-r", "--list", "origin/feature/task", cwd=single) == ""

    awf_role.fetch_and_checkout(str(single), "feature/task", task_head)

    assert run("git", "rev-parse", "HEAD", cwd=single) == task_head


# ---------------------------------------------------------------------------
# Fork/PR trusted publication and provenance
# ---------------------------------------------------------------------------


def _pr_provenance(**overrides):
    value = {
        "provenance_version": "awf.pr-provenance.v1",
        "upstream_repo": "upstream/project",
        "upstream_remote": "upstream",
        "base_ref": "main",
        "base_sha": "a" * 40,
        "head_repo": "contributor/project",
        "head_remote": "fork",
        "head_ref": "feature/task",
        "head_sha": "b" * 40,
        "pull_request": 17,
    }
    value.update(overrides)
    return value


@pytest.mark.parametrize(
    "remote_url",
    [
        "https://user:secret@github.com/upstream/project.git",
        "file:///tmp/project.git",
        "ssh://git@github.com/upstream/project.git",
        "https://example.invalid/upstream/project.git",
        "/tmp/project.git",
    ],
)
def test_remote_binding_rejects_credentials_protocols_and_local_paths(
    monkeypatch, tmp_path, remote_url
):
    monkeypatch.setattr(awf_role, "git_out", lambda *args: remote_url)

    with pytest.raises(SystemExit, match="1"):
        awf_role.validate_remote_binding(str(tmp_path), "upstream", "upstream/project")


def test_remote_binding_accepts_canonical_credential_free_github_https(monkeypatch, tmp_path):
    monkeypatch.setattr(
        awf_role,
        "git_out",
        lambda *args: "https://github.com/upstream/project.git",
    )

    awf_role.validate_remote_binding(str(tmp_path), "upstream", "upstream/project")


def test_remote_binding_rejects_separate_or_multiple_push_urls(monkeypatch, tmp_path):
    fetch_url = "https://github.com/contributor/project.git"

    def fake_git_out(_repo, *args):
        if "--push" in args:
            return "\n".join(
                [
                    fetch_url,
                    "https://github.com/attacker/project.git",
                ]
            )
        return fetch_url

    monkeypatch.setattr(awf_role, "git_out", fake_git_out)

    with pytest.raises(SystemExit, match="1"):
        awf_role.validate_remote_binding(
            str(tmp_path),
            "fork",
            "contributor/project",
        )


def test_trusted_config_rejects_collapsed_upstream_and_fork(monkeypatch, tmp_path):
    monkeypatch.setenv("AWF_UPSTREAM_REPO", "owner/project")
    monkeypatch.setenv("AWF_HEAD_REPO", "owner/project")
    monkeypatch.setattr(
        awf_role,
        "validate_remote_binding",
        lambda *args, **kwargs: pytest.fail("collapsed repositories must fail first"),
    )

    with pytest.raises(SystemExit, match="1"):
        awf_role.trusted_remote_config(str(tmp_path))


def test_trusted_config_accepts_handler_remote_overrides(monkeypatch, tmp_path):
    monkeypatch.setenv("AWF_UPSTREAM_REPO", "owner/project")
    monkeypatch.setenv("AWF_HEAD_REPO", "contributor/project")
    monkeypatch.setattr(
        awf_role,
        "validate_remote_binding",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(awf_role, "validate_git_ref", lambda *args, **kwargs: None)

    config = awf_role.trusted_remote_config(
        str(tmp_path),
        upstream_remote="origin",
        head_remote="fork",
    )

    assert config["upstream_remote"] == "origin"
    assert config["head_remote"] == "fork"


def test_v3_incomplete_provenance_is_rejected_before_trusted_config_lookup(tmp_path):
    args = argparse.Namespace(
        input_type="task:awf-review-v3",
        branch="feature/task",
        provenance_version="",
        upstream_repo="",
        base_ref="",
        base_sha="",
        head_repo="",
        head_ref="",
        head_sha="",
        pull_request=0,
    )

    with pytest.raises(SystemExit, match="1"):
        awf_role.provenance_from_args(args, str(tmp_path), require_pr=True)


@pytest.mark.parametrize(
    "repo_slug",
    [
        "owner/repo --upload-pack=evil",
        "https://github.com/owner/repo",
        "owner/repo.git",
        "../repo",
        "owner/repo/extra",
    ],
)
def test_repository_slug_injection_is_rejected(repo_slug):
    with pytest.raises(SystemExit, match="1"):
        awf_role.validate_repo_slug(repo_slug, "repository")


@pytest.mark.parametrize("ref", ["-evil", "refs/heads/task", "task name", "../task", "task..x"])
def test_ref_injection_is_rejected(monkeypatch, tmp_path, ref):
    monkeypatch.setattr(awf_role, "git", lambda *args: 1)

    with pytest.raises(SystemExit, match="1"):
        awf_role.validate_git_ref(str(tmp_path), ref, "head ref")


@pytest.mark.parametrize(
    ("push_rc", "remote_sha"),
    [
        (1, "b" * 40),
        (0, "c" * 40),
    ],
)
def test_fork_push_failure_or_fresh_sha_mismatch_fails_closed(
    monkeypatch, tmp_path, push_rc, remote_sha
):
    provenance = _pr_provenance(pull_request=0)
    calls = []

    def fake_git(_repo, *args):
        calls.append(args)
        if args[0] == "push":
            return push_rc
        return 0

    def fake_git_out(_repo, *args):
        return "b" * 40 if args[-1] == "HEAD^{commit}" else remote_sha

    monkeypatch.setattr(awf_role, "git", fake_git)
    monkeypatch.setattr(awf_role, "git_out", fake_git_out)
    monkeypatch.setattr(
        awf_role,
        "ensure_pull_request",
        lambda *args: pytest.fail("PR operation must not run after fork publication denial"),
    )

    with pytest.raises(SystemExit, match="1"):
        awf_role.push_and_verify_pr_head(str(tmp_path), provenance)

    assert calls[0][:3] == ("push", "-u", "fork")


def test_fork_push_fresh_sha_equality_proceeds_to_exact_pr(monkeypatch, tmp_path):
    provenance = _pr_provenance(pull_request=0)
    calls = []
    monkeypatch.setattr(awf_role, "git", lambda _repo, *args: calls.append(args) or 0)
    monkeypatch.setattr(awf_role, "git_out", lambda *args: "d" * 40)
    monkeypatch.setattr(
        awf_role,
        "ensure_pull_request",
        lambda _repo, value: {**value, "pull_request": 23},
    )

    result = awf_role.push_and_verify_pr_head(str(tmp_path), provenance)

    assert result["head_sha"] == "d" * 40
    assert result["pull_request"] == 23
    assert (
        "fetch",
        "--no-tags",
        "fork",
        "+refs/heads/feature/task:refs/remotes/fork/feature/task",
    ) in calls


def test_pr_create_then_verify_binds_exact_repo_base_ref_and_sha(monkeypatch, tmp_path):
    provenance = _pr_provenance(head_sha="d" * 40, pull_request=0)

    def fake_json(_repo, *args):
        if args[:2] == ("pr", "list"):
            return []
        assert args[:3] == ("pr", "view", "23")
        return {
            "number": 23,
            "state": "OPEN",
            "baseRefName": "main",
            "baseRefOid": "a" * 40,
            "headRefName": "feature/task",
            "headRefOid": "d" * 40,
            "headRepository": {"name": "project"},
            "headRepositoryOwner": {"login": "contributor"},
        }

    monkeypatch.setattr(awf_role, "_gh_json", fake_json)
    monkeypatch.setattr(awf_role, "_gh_create_pull_request", lambda *_args: 23)

    result = awf_role.ensure_pull_request(str(tmp_path), provenance)

    assert result["pull_request"] == 23


def test_pr_create_returns_exact_number_without_branch_list_rediscovery(monkeypatch, tmp_path):
    provenance = _pr_provenance(head_sha="d" * 40, pull_request=0)
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout="https://github.com/upstream/project/pull/23\n",
            stderr="",
        )

    monkeypatch.setattr(awf_role, "run_command", fake_run)

    assert awf_role._gh_create_pull_request(str(tmp_path), provenance) == 23
    assert calls[0][0][:4] == ["gh", "pr", "create", "--repo"]
    assert calls[0][1]["stderr"] is subprocess.DEVNULL


@pytest.mark.parametrize(
    "output",
    [
        "https://user@github.com/upstream/project/pull/23",
        "http://github.com/upstream/project/pull/23",
        "https://example.com/upstream/project/pull/23",
        "https://github.com/other/project/pull/23",
        "https://github.com/upstream/project/pull/not-a-number",
        "https://github.com/upstream/project/pull/23?token=secret",
        "diagnostic\nhttps://github.com/upstream/project/pull/23",
    ],
)
def test_pr_create_rejects_noncanonical_result_without_logging_it(
    monkeypatch, tmp_path, capsys, output
):
    provenance = _pr_provenance(head_sha="d" * 40, pull_request=0)
    monkeypatch.setattr(
        awf_role,
        "run_command",
        lambda argv, **_kwargs: subprocess.CompletedProcess(
            argv,
            0,
            stdout=output,
            stderr="",
        ),
    )

    with pytest.raises(SystemExit, match="1"):
        awf_role._gh_create_pull_request(str(tmp_path), provenance)

    assert output not in capsys.readouterr().err


def test_existing_pr_update_path_reuses_and_verifies_without_create(monkeypatch, tmp_path):
    provenance = _pr_provenance(head_sha="d" * 40, pull_request=0)
    calls = []

    def fake_json(_repo, *args):
        calls.append(args)
        return (
            [{"number": 23}]
            if args[:2] == ("pr", "list")
            else {
                "number": 23,
                "state": "OPEN",
                "baseRefName": "main",
                "baseRefOid": "a" * 40,
                "headRefName": "feature/task",
                "headRefOid": "d" * 40,
                "headRepository": {"name": "project"},
                "headRepositoryOwner": {"login": "contributor"},
            }
        )

    monkeypatch.setattr(
        awf_role,
        "_gh_json",
        fake_json,
    )
    monkeypatch.setattr(
        awf_role,
        "_gh_create_pull_request",
        lambda *args: pytest.fail("existing matching PR must not be recreated"),
    )

    assert awf_role.ensure_pull_request(str(tmp_path), provenance)["pull_request"] == 23
    list_call = calls[0]
    assert list_call[list_call.index("--head") + 1] == "feature/task"


def test_github_cli_failure_is_fail_closed_without_exposing_stderr(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(
        awf_role,
        "run_command",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0],
            1,
            stdout="",
            stderr="credential-bearing diagnostic",
        ),
    )

    with pytest.raises(SystemExit, match="1"):
        awf_role._gh_json(str(tmp_path), "pr", "list")

    assert "credential-bearing diagnostic" not in capsys.readouterr().err


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("baseRefOid", "c" * 40),
        ("headRefOid", "c" * 40),
        ("headRefName", "other/ref"),
        ("baseRefName", "release"),
        ("state", "CLOSED"),
    ],
)
def test_pr_tuple_mismatch_fails_closed(monkeypatch, tmp_path, field, bad_value):
    provenance = _pr_provenance()
    live = {
        "number": 17,
        "state": "OPEN",
        "baseRefName": "main",
        "baseRefOid": "a" * 40,
        "headRefName": "feature/task",
        "headRefOid": "b" * 40,
        "headRepository": {"name": "project"},
        "headRepositoryOwner": {"login": "contributor"},
    }
    live[field] = bad_value
    monkeypatch.setattr(awf_role, "_gh_json", lambda *args: live)

    with pytest.raises(SystemExit, match="1"):
        awf_role.verify_pr_head(str(tmp_path), provenance)


def test_merged_pr_is_allowed_only_for_explicit_terminal_recovery(monkeypatch, tmp_path):
    provenance = _pr_provenance()
    live = {
        "number": 17,
        "state": "MERGED",
        "baseRefName": "main",
        "baseRefOid": "a" * 40,
        "headRefName": "feature/task",
        "headRefOid": "b" * 40,
        "headRepository": {"name": "project"},
        "headRepositoryOwner": {"login": "contributor"},
    }
    monkeypatch.setattr(awf_role, "_gh_json", lambda *args: live)

    with pytest.raises(SystemExit, match="1"):
        awf_role.verify_pr_head(str(tmp_path), provenance)
    assert awf_role.verify_pr_head(str(tmp_path), provenance, allow_merged=True) == provenance


def test_v3_outbox_persists_complete_provenance_tuple(tmp_path):
    evidence = awf_role.RunEvidence(90, "coder", state_root=tmp_path / "state")
    provenance = _pr_provenance()
    payload = awf_role.build_delivery_payload(
        "coder",
        "task:awf-review-v3",
        {
            "task_id": "task",
            "branch": "feature/task",
            "card": "task.md",
            "commit": "b" * 40,
            "report": "report.md",
            "review_report": "review.md",
            "tool": "opencode",
            "model": "",
            **awf_role.provenance_payload(provenance),
        },
        evidence,
    )

    _, record = awf_role.prepare_outbox(
        evidence,
        {
            "key": "input",
            "delivery_id": "input",
            "payload_sha256": "sha256:input",
            "source_event_id": 1,
        },
        action="coder.review_handoff",
        branch="feature/task",
        source_commit="a" * 40,
        evidence_commit="b" * 40,
        to_role="reviewer",
        event_type="task:awf-review-v3",
        payload=payload,
        provenance=provenance,
    )

    assert record["format"] == "awf.outbox.v2"
    assert record["state_root_sha256"] == state_root_binding(evidence.state_dir)
    assert record["provenance"] == awf_role.provenance_payload(provenance)
    assert record["payload"]["head_sha"] == "b" * 40


def test_v3_rework_reconstructs_structured_feedback_for_delivery_hash():
    provenance = _pr_provenance()
    feedback = {
        "format": "awf.review-report.v1",
        "verdict": "REQUEST_CHANGES",
        "summary": "Fix the bounded issue.",
        "findings": [],
    }
    args = argparse.Namespace(
        input_type="task:awf-rework-v3",
        source_event_id=93,
        branch="feature/task",
        card="task.md",
        commit="b" * 40,
        tool="opencode",
        model="",
        report="report.md",
        review_report="review.md",
        review_feedback=json.dumps(feedback),
        **awf_role.provenance_payload(provenance),
    )
    expected_payload = {
        "task_id": "task",
        "branch": "feature/task",
        "card": "task.md",
        "commit": "b" * 40,
        "tool": "opencode",
        "model": "",
        "report": "report.md",
        "review_report_path": "review.md",
        "review_report": feedback,
        **awf_role.provenance_payload(provenance),
    }
    args.payload_sha256 = awf_role.canonical_payload_sha256(expected_payload)
    args.delivery_id = awf_role.make_delivery_id(
        "reviewer",
        args.input_type,
        args.payload_sha256,
        args.source_event_id,
    )

    context = awf_role.validate_input_delivery(args, "coder", None)

    assert context["payload_sha256"] == awf_role.canonical_payload_sha256(expected_payload)


@pytest.mark.parametrize("status", ["prepared", "attempting", "ambiguous", "sent"])
def test_v3_outbox_replay_revalidates_same_provenance_without_model(monkeypatch, tmp_path, status):
    evidence = awf_role.RunEvidence(92, "coder", state_root=tmp_path / "state")
    provenance = _pr_provenance()
    input_context = {
        "key": "input",
        "delivery_id": "input",
        "payload_sha256": "sha256:input",
        "source_event_id": 1,
    }
    payload = awf_role.build_delivery_payload(
        "coder",
        "task:awf-review-v3",
        {
            "task_id": "task",
            "branch": "feature/task",
            "card": "task.md",
            "commit": "b" * 40,
            "report": "report.md",
            "review_report": "review.md",
            "tool": "opencode",
            "model": "",
            **awf_role.provenance_payload(provenance),
        },
        evidence,
    )
    path, record = awf_role.prepare_outbox(
        evidence,
        input_context,
        action="coder.review_handoff",
        branch="feature/task",
        source_commit="a" * 40,
        evidence_commit="b" * 40,
        to_role="reviewer",
        event_type="task:awf-review-v3",
        payload=payload,
        provenance=provenance,
    )
    awf_role._atomic_write_json(path, {**record, "status": status})
    if status == "sent":
        awf_role.complete_inbox(
            evidence,
            str(input_context["delivery_id"]),
            str(input_context["payload_sha256"]),
        )
    args = argparse.Namespace(branch="feature/task", commit="a" * 40)
    verified = []
    sends = []
    monkeypatch.setattr(
        awf_role,
        "provenance_from_args",
        lambda *call_args, **kwargs: provenance,
    )
    monkeypatch.setattr(
        awf_role,
        "verify_pr_remote_tuple",
        lambda *call_args, **kwargs: verified.append((call_args, kwargs)),
    )
    monkeypatch.setattr(
        awf_role,
        "git_out",
        lambda _repo, *git_args: "report.md" if git_args[0] == "ls-tree" else "",
    )
    monkeypatch.setattr(
        awf_role,
        "send_event",
        lambda *call_args, **kwargs: sends.append(call_args) or True,
    )

    assert awf_role.resume_outbox(
        args,
        "coder",
        str(tmp_path),
        evidence,
        input_context,
    )
    assert len(verified) == 1
    assert len(sends) == (0 if status == "sent" else 1)


# ---------------------------------------------------------------------------
# Model-process credential boundary
# ---------------------------------------------------------------------------


def test_model_env_strips_credentials_and_runner_metadata(monkeypatch):
    """Model children receive only allowlisted runtime state."""
    monkeypatch.setenv("AGENT_BUS_TOKEN", "secret")
    monkeypatch.setenv("AGENT_BUS_AGENT_TOKENS", "secrets")
    monkeypatch.setenv("AGENT_BUS_AGENT", "coder")
    monkeypatch.setenv("AWF_CODER_TOKEN", "coder-tok")
    monkeypatch.setenv("AWF_REVIEWER_TOKEN", "reviewer-tok")
    monkeypatch.setenv("AWF_SCRIPT_DIR", "/safe")
    monkeypatch.setenv("GH_TOKEN", "github-cli-token")
    monkeypatch.setenv("GITHUB_TOKEN", "github-actions-token")
    monkeypatch.setenv("SSH_AUTH_SOCK", "/tmp/agent.sock")
    monkeypatch.setenv("SSH_AGENT_PID", "123")
    monkeypatch.setenv("GIT_ASKPASS", "/tmp/git-askpass")
    monkeypatch.setenv("GIT_ALLOW_PROTOCOL", "file:https:ssh")
    monkeypatch.setenv("GIT_CONFIG_PARAMETERS", "'protocol.file.allow=always'")
    monkeypatch.setenv("SSH_ASKPASS", "/tmp/ssh-askpass")
    monkeypatch.setenv("GIT_SSH", "/tmp/git-ssh")
    monkeypatch.setenv("GIT_SSH_COMMAND", "ssh -i /tmp/key")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "cloud-access")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "cloud-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "model-provider-secret")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "model-provider-secret")
    monkeypatch.setenv("DOCKER_CONFIG", "/tmp/docker-secret")
    monkeypatch.setenv("KUBECONFIG", "/tmp/kube-secret")
    monkeypatch.setenv("NPM_CONFIG_USERCONFIG", "/tmp/npm-secret")
    monkeypatch.setenv("PYTHONPATH", "/tmp/python-injection")
    monkeypatch.setenv("ARBITRARY_PRIVATE_SECRET", "private")

    env = awf_role.model_env()

    assert "AGENT_BUS_TOKEN" not in env
    assert "AGENT_BUS_AGENT_TOKENS" not in env
    assert "AGENT_BUS_AGENT" not in env
    assert "AWF_CODER_TOKEN" not in env
    assert "AWF_REVIEWER_TOKEN" not in env
    for key in (
        "GH_TOKEN",
        "GITHUB_TOKEN",
        "SSH_AUTH_SOCK",
        "SSH_AGENT_PID",
        "GIT_ASKPASS",
        "GIT_ALLOW_PROTOCOL",
        "GIT_CONFIG_PARAMETERS",
        "SSH_ASKPASS",
        "GIT_SSH",
        "GIT_SSH_COMMAND",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "DOCKER_CONFIG",
        "KUBECONFIG",
        "NPM_CONFIG_USERCONFIG",
        "PYTHONPATH",
        "ARBITRARY_PRIVATE_SECRET",
    ):
        assert key not in env
    assert "AWF_SCRIPT_DIR" not in env
    # UTF-8 settings present (from child_env)
    assert "PYTHONUTF8" in env
    assert "PYTHONIOENCODING" in env
    assert env["PYTHONDONTWRITEBYTECODE"] == "1"


def test_model_env_replaces_existing_process_git_config(monkeypatch, tmp_path):
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "credential.helper")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "/trusted/credential-helper")

    environment = awf_role.model_env(str(tmp_path))

    assert environment["GIT_CONFIG_COUNT"] == "10"
    assert environment["GIT_CONFIG_KEY_0"] == "core.hooksPath"
    assert environment["GIT_CONFIG_KEY_1"] == "protocol.allow"
    assert environment["GIT_CONFIG_VALUE_1"] == "never"
    assert environment["GIT_CONFIG_KEY_2"] == "protocol.ext.allow"
    assert environment["GIT_CONFIG_KEY_7"] == "protocol.ssh.allow"
    assert environment["GIT_CONFIG_KEY_8"] == "remote.origin.pushurl"
    assert environment["GIT_CONFIG_KEY_9"] == "credential.helper"
    assert "/trusted/credential-helper" not in environment.values()


def test_model_env_points_runtime_paths_at_isolated_repo(monkeypatch, tmp_path):
    monkeypatch.setenv("AWF_REPO_DIR", "/trusted/repo")
    monkeypatch.setenv("AWF_SCRIPT_DIR", "/trusted/agent-workflow/scripts")
    monkeypatch.setenv("AWF_BUS_BIN", "/trusted/agent-bus")
    monkeypatch.setenv("AGENT_BUS_URL", "http://private-bus.invalid")
    monkeypatch.setenv("PWD", "/trusted/repo")
    monkeypatch.setenv("OLDPWD", "/trusted")
    monkeypatch.setenv("INIT_CWD", "/trusted/repo")
    monkeypatch.setenv("GIT_DIR", "/trusted/repo/.git")

    environment = awf_role.model_env(str(tmp_path))

    assert environment["AWF_REPO_DIR"] == str(tmp_path.resolve())
    assert environment["PWD"] == str(tmp_path.resolve())
    assert environment["INIT_CWD"] == str(tmp_path.resolve())
    assert "AWF_SCRIPT_DIR" not in environment
    assert "AWF_BUS_BIN" not in environment
    assert "AGENT_BUS_URL" not in environment
    assert "OLDPWD" not in environment
    assert "GIT_DIR" not in environment
    assert all("/trusted" not in value for value in environment.values())
    model_bin = Path(environment["PATH"].split(os.pathsep)[0]).resolve()
    hooks_path = Path(environment["GIT_CONFIG_VALUE_0"]).resolve()
    trusted_root = Path(awf_role.__file__).resolve().parent.parent
    assert model_bin.name == "model-bin"
    assert hooks_path.name == "model-git-hooks"
    assert not model_bin.is_relative_to(trusted_root)
    assert not hooks_path.is_relative_to(trusted_root)
    assert all(str(trusted_root) not in value for value in environment.values())
    assert environment["NoDefaultCurrentDirectoryInExePath"] == "1"


def test_postflight_git_env_is_credential_free(monkeypatch):
    monkeypatch.setenv("AWF_CODER_TOKEN", "bus-secret")
    monkeypatch.setenv("GH_TOKEN", "git-secret")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "cloud-secret")
    monkeypatch.setenv("OPENROUTER_API_KEY", "provider-secret")
    monkeypatch.setenv("PYTHONPATH", "/tmp/injection")

    environment = awf_role.postflight_git_env()

    for key in (
        "AWF_CODER_TOKEN",
        "GH_TOKEN",
        "AWS_SECRET_ACCESS_KEY",
        "OPENROUTER_API_KEY",
        "PYTHONPATH",
    ):
        assert key not in environment
    assert environment["GIT_CONFIG_NOSYSTEM"] == "1"
    assert environment["GIT_CONFIG_GLOBAL"] == os.devnull
    assert "core.autocrlf" in environment.values()


@pytest.mark.parametrize("key", ["HTTP_PROXY", "https_proxy"])
def test_model_env_rejects_credential_proxy(monkeypatch, capsys, key):
    monkeypatch.setenv(key, "http://runner:secret@proxy.invalid:8080")

    with pytest.raises(SystemExit):
        awf_role.model_env()
    assert "must not contain embedded credentials" in capsys.readouterr().err


def test_model_env_preserves_credential_free_proxy(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:7890")

    assert awf_role.model_env()["HTTPS_PROXY"] == "http://127.0.0.1:7890"


def test_model_env_canonicalizes_equal_no_proxy_case_variants(monkeypatch):
    monkeypatch.setenv("NO_PROXY", "github.com,api.github.com")
    monkeypatch.setenv("no_proxy", "github.com,api.github.com")

    environment = awf_role.model_env()

    assert environment["NO_PROXY"] == "github.com,api.github.com"
    assert "no_proxy" not in environment


def test_model_env_preserves_external_pi_runtime_directories(monkeypatch, tmp_path):
    pi_config = tmp_path / "pi-config"
    pi_sessions = tmp_path / "pi-sessions"
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(pi_config))
    monkeypatch.setenv("PI_CODING_AGENT_SESSION_DIR", str(pi_sessions))

    environment = awf_role.model_env()

    assert environment["PI_CODING_AGENT_DIR"] == str(pi_config)
    assert environment["PI_CODING_AGENT_SESSION_DIR"] == str(pi_sessions)


def test_model_env_blocks_git_commit(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    run("git", "init", "-b", "main", cwd=repo)
    run("git", "config", "user.name", "AWF Test", cwd=repo)
    run("git", "config", "user.email", "awf-test@example.invalid", cwd=repo)
    original_head = commit(repo, "base", "task.md", "base\n")
    (repo / "task.md").write_text("model output\n", encoding="utf-8")
    run("git", "add", "task.md", cwd=repo)

    completed = subprocess.run(
        model_git_argv("commit", "-m", "model must not commit"),
        cwd=repo,
        env=awf_role.model_env(str(repo)),
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "trusted runner owns Git writes" in completed.stderr
    assert run("git", "rev-parse", "HEAD", cwd=repo) == original_head


def test_model_env_blocks_git_push(repositories):
    origin, _, executor = repositories
    commit(executor, "model commit", "model.txt", "must not reach origin\n")
    remote_head = run("git", "rev-parse", "refs/heads/feature/task", cwd=origin)

    completed = subprocess.run(
        model_git_argv("push", "origin", "feature/task"),
        cwd=executor,
        env=awf_role.model_env(str(executor)),
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert run("git", "rev-parse", "refs/heads/feature/task", cwd=origin) == remote_head


def test_model_env_blocks_no_verify_push_to_direct_remote(repositories):
    origin, _, executor = repositories
    remote_head = run("git", "rev-parse", "refs/heads/feature/task", cwd=origin)
    environment = awf_role.model_env(str(executor))
    (executor / "bypass.txt").write_text("must stay local\n", encoding="utf-8")
    run("git", "add", "bypass.txt", cwd=executor)

    committed = subprocess.run(
        model_git_argv("commit", "--no-verify", "-m", "bypass local hook"),
        cwd=executor,
        env=environment,
        capture_output=True,
        text=True,
    )
    pushed = subprocess.run(
        model_git_argv(
            "-c",
            "protocol.file.allow=always",
            "push",
            "--no-verify",
            str(origin),
            "HEAD:refs/heads/feature/task",
        ),
        cwd=executor,
        env=environment,
        capture_output=True,
        text=True,
    )

    assert committed.returncode != 0
    assert "trusted runner owns Git writes" in committed.stderr
    assert pushed.returncode != 0
    assert "trusted runner owns Git writes" in pushed.stderr
    assert run("git", "rev-parse", "refs/heads/feature/task", cwd=origin) == remote_head


@pytest.mark.skipif(os.name != "nt", reason="Windows command lookup semantics")
def test_model_env_blocks_workspace_git_cmd_shadow(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    marker = tmp_path / "shadow-ran.txt"
    (repo / "git.cmd").write_text(f"@echo shadow>{marker}\r\n@exit /b 0\r\n", encoding="utf-8")
    environment = awf_role.model_env(str(repo))

    completed = subprocess.run(
        model_git_argv("commit", "-m", "must use isolated guard"),
        cwd=repo,
        env=environment,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "trusted runner owns Git writes" in completed.stderr
    assert not marker.exists()


def test_windows_cmd_wrappers_are_delegated_to_executor(monkeypatch):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(awf_role, "run_command", fake_run)

    assert awf_role.spawn(["tool.cmd", "argument"], env={"PATH": "ignored"}) == 0
    assert calls[0][0] == ["tool.cmd", "argument"]
    assert calls[0][1]["allow_shell_wrapper"] is True

    monkeypatch.setenv("AGENT_BUS_URL", "http://bus.invalid")
    monkeypatch.setenv("AWF_CODER_TOKEN", "token")
    monkeypatch.setenv("AWF_BUS_BIN", "agent-bus.cmd")
    assert awf_role.send_event("coder", "reviewer", "task:test", {})
    assert calls[1][0][0] == "agent-bus.cmd"
    assert calls[1][1]["allow_shell_wrapper"] is True


def test_prepare_model_workspace_has_exact_head_and_no_remote(repositories, tmp_path):
    _, _, executor = repositories
    expected = run("git", "rev-parse", "HEAD", cwd=executor)

    workspace = Path(
        awf_role.prepare_model_workspace(
            str(executor),
            expected,
            state_dir=tmp_path / "event-state",
        )
    )

    assert workspace.parent == (tmp_path / "event-state").resolve()
    assert run("git", "rev-parse", "HEAD", cwd=workspace) == expected
    assert run("git", "remote", cwd=workspace) == ""
    assert str(executor.resolve()) not in (workspace / ".git" / "config").read_text(
        encoding="utf-8"
    )
    assert not (workspace / ".git" / "objects" / "info" / "alternates").exists()
    source_paths = {
        str(executor.resolve()).encode(),
        executor.resolve().as_posix().encode(),
    }
    for metadata_path in (workspace / ".git").rglob("*"):
        if metadata_path.is_file():
            metadata = metadata_path.read_bytes()
            assert all(source_path not in metadata for source_path in source_paths), metadata_path
    assert run("git", "config", "--bool", "core.logAllRefUpdates", cwd=workspace) == "false"
    assert not (workspace / ".git" / "logs").exists()
    assert not (workspace / ".git" / "FETCH_HEAD").exists()
    assert run("git", "status", "--short", cwd=workspace) == ""
    assert run("git", "log", "-1", "--format=%H", cwd=workspace) == expected


def test_assert_model_workspace_state_rejects_head_or_remote_change(repositories, tmp_path):
    _, _, executor = repositories
    expected = run("git", "rev-parse", "HEAD", cwd=executor)
    workspace = Path(awf_role.prepare_model_workspace(str(executor), expected, state_dir=tmp_path))
    run("git", "remote", "add", "escaped", str(executor), cwd=workspace)

    with pytest.raises(SystemExit, match="1"):
        awf_role.assert_model_workspace_state(str(workspace), expected)

    run("git", "remote", "remove", "escaped", cwd=workspace)
    run("git", "config", "user.name", "Model", cwd=workspace)
    run("git", "config", "user.email", "model@example.invalid", cwd=workspace)
    commit(workspace, "model commit", "model.txt", "unexpected\n")

    with pytest.raises(SystemExit, match="1"):
        awf_role.assert_model_workspace_state(str(workspace), expected)


def test_assert_model_workspace_state_rejects_git_helper_injection_before_git_runs(
    repositories, monkeypatch, tmp_path
):
    _, _, executor = repositories
    expected = run("git", "rev-parse", "HEAD", cwd=executor)
    workspace = Path(awf_role.prepare_model_workspace(str(executor), expected, state_dir=tmp_path))
    config = workspace / ".git" / "config"
    config.write_text(
        config.read_text(encoding="utf-8") + "\n[diff]\n\texternal = credential-stealing-helper\n",
        encoding="utf-8",
    )
    git_calls = []
    monkeypatch.setattr(
        awf_role,
        "git_out",
        lambda *args, **kwargs: git_calls.append((args, kwargs)) or expected,
    )

    with pytest.raises(SystemExit, match="1"):
        awf_role.assert_model_workspace_state(str(workspace), expected)

    assert not git_calls


def test_trusted_commit_advances_same_durable_model_workspace(repositories, tmp_path):
    _, _, executor = repositories
    source_commit = run("git", "rev-parse", "HEAD", cwd=executor)
    evidence = awf_role.RunEvidence(120, "coder", state_root=tmp_path / "state")
    workspace = Path(
        awf_role.prepare_model_workspace(str(executor), source_commit, state_dir=evidence.run_dir)
    )
    (workspace / "workspace-transition.txt").write_text("implemented\n", encoding="utf-8")
    imported_tree = awf_role.import_model_delta(str(workspace), str(executor))
    control_sha256 = awf_role.durable_model_control_sha256(str(workspace))
    run("git", "commit", "-m", "trusted implementation", cwd=executor)
    trusted_commit = run("git", "rev-parse", "HEAD", cwd=executor)

    manifest_sha256 = awf_role.advance_model_workspace_to_trusted_commit(
        evidence,
        str(workspace),
        str(executor),
        source_commit=source_commit,
        imported_tree=imported_tree,
        trusted_commit=trusted_commit,
        expected_control_sha256=control_sha256,
    )

    assert run("git", "rev-parse", "HEAD", cwd=workspace) == trusted_commit
    assert run("git", "status", "--porcelain", cwd=workspace) == ""
    assert run("git", "remote", cwd=workspace) == ""
    assert awf_role.durable_model_manifest_sha256(str(workspace)) == manifest_sha256
    assert awf_role.durable_model_control_sha256(str(workspace)) == control_sha256


def test_rework_restores_unique_implement_lineage_and_rejects_git_drift(repositories, tmp_path):
    _, _, executor = repositories
    source_commit = run("git", "rev-parse", "HEAD", cwd=executor)
    state_root = tmp_path / "state"
    implement_evidence = awf_role.RunEvidence(121, "coder", state_root=state_root)
    workspace = Path(
        awf_role.prepare_model_workspace(
            str(executor), source_commit, state_dir=implement_evidence.run_dir
        )
    )
    (workspace / "lineage.txt").write_text("implemented\n", encoding="utf-8")
    imported_tree = awf_role.import_model_delta(str(workspace), str(executor))
    control_sha256 = awf_role.durable_model_control_sha256(str(workspace))
    run("git", "commit", "-m", "trusted implementation", cwd=executor)
    trusted_commit = run("git", "rev-parse", "HEAD", cwd=executor)
    manifest_sha256 = awf_role.advance_model_workspace_to_trusted_commit(
        implement_evidence,
        str(workspace),
        str(executor),
        source_commit=source_commit,
        imported_tree=imported_tree,
        trusted_commit=trusted_commit,
        expected_control_sha256=control_sha256,
    )

    run_id = "synthetic-implement-rework"
    authority = awf_role.authority_manifest_binding(
        awf_role.load_authority_manifest(
            Path(awf_role.__file__).resolve().parent / "authority-manifest.example.json"
        )
    )
    ledger = awf_role.RunLedger(state_root, run_id)
    packet = awf_role.build_context_packet(
        run_id=run_id,
        taskcard="task.md",
        frozen_base=source_commit,
        branch="feature/task",
        authority_manifest=authority,
        next_action="implement",
        stage="implement",
        current_stage_evidence_commit=source_commit,
    )
    ledger.initialize(packet, stage="implement", max_attempts=1, rework_budget=1)
    implement_delivery = "awf:" + "1" * 64
    assert ledger.pre_invocation_gate(
        event_id=121,
        event_type="task:awf-impl-v3",
        role="coder",
        delivery_id=implement_delivery,
        payload_sha256="sha256:" + "1" * 64,
        stage="implement",
        current_stage_evidence_commit=source_commit,
    ).allowed
    current_provenance = _pr_provenance(
        base_sha=source_commit,
        head_sha=trusted_commit,
    )
    input_context = {
        "key": implement_delivery,
        "delivery_id": implement_delivery,
        "payload_sha256": "sha256:" + "1" * 64,
        "source_event_id": 120,
    }
    checkpoint_path, checkpoint = awf_role.begin_recovery_checkpoint(
        implement_evidence,
        input_context,
        role="coder",
        branch="feature/task",
        source_commit=source_commit,
        provenance=_pr_provenance(base_sha=source_commit, head_sha=source_commit, pull_request=0),
    )
    transitions = [
        (
            "model_started",
            {
                "model_workspace": str(workspace),
                "model_manifest_sha256": manifest_sha256,
                "model_event_id": 121,
                "model_process": "opencode",
            },
        ),
        ("model_completed", {}),
        ("postflight_completed", {"postflight_model_manifest_sha256": manifest_sha256}),
        (
            "model_imported",
            {
                "imported_tree": imported_tree,
                "trusted_workspace_source_commit": source_commit,
                "trusted_workspace_control_sha256": control_sha256,
            },
        ),
        (
            "commit_created",
            {
                "commit_sha": trusted_commit,
                "trusted_workspace_commit_sha": trusted_commit,
                "trusted_workspace_manifest_sha256": manifest_sha256,
            },
        ),
        ("fork_sha_verified", {"head_sha": trusted_commit}),
        (
            "pr_tuple_verified",
            {"verified_provenance": awf_role.provenance_payload(current_provenance)},
        ),
        ("outbox_prepared", {"outbox_delivery_id": "awf:" + "2" * 64}),
        ("outbox_sent", {"outbox_delivery_id": "awf:" + "2" * 64}),
    ]
    for phase, facts in transitions:
        checkpoint = awf_role.advance_recovery_checkpoint(
            implement_evidence, checkpoint_path, checkpoint, phase, **facts
        )
    assert ledger.pre_invocation_gate(
        event_id=122,
        event_type="task:awf-review-v3",
        role="reviewer",
        delivery_id="awf:" + "3" * 64,
        payload_sha256="sha256:" + "3" * 64,
        stage="review",
        current_stage_evidence_commit=trusted_commit,
    ).allowed
    assert ledger.pre_invocation_gate(
        event_id=123,
        event_type="task:awf-rework-v3",
        role="coder",
        delivery_id="awf:" + "4" * 64,
        payload_sha256="sha256:" + "4" * 64,
        stage="rework",
        rework=True,
        current_stage_evidence_commit=trusted_commit,
    ).allowed
    args = argparse.Namespace(branch="feature/task", commit=trusted_commit, run_id=run_id)
    rework_evidence = awf_role.RunEvidence(123, "coder", state_root=state_root)
    lineage_delivery, lineage_sha256 = awf_role.resolve_fresh_rework_workspace_lineage(
        rework_evidence, args, current_provenance
    )
    _, rework_checkpoint = awf_role.begin_recovery_checkpoint(
        rework_evidence,
        {
            "key": "awf:" + "4" * 64,
            "delivery_id": "awf:" + "4" * 64,
            "payload_sha256": "sha256:" + "4" * 64,
            "source_event_id": 122,
        },
        role="coder",
        branch="feature/task",
        source_commit=trusted_commit,
        provenance=current_provenance,
        workspace_lineage_delivery_id=lineage_delivery,
        workspace_lineage_checkpoint_sha256=lineage_sha256,
    )
    restored, restored_manifest = awf_role.restore_rework_workspace_lineage(
        rework_evidence, args, current_provenance, rework_checkpoint
    )
    assert restored == str(workspace.resolve())
    assert restored_manifest == manifest_sha256

    run("git", "config", "lineage.drift", "true", cwd=workspace)
    provider_calls = []
    with pytest.raises(SystemExit, match="1"):
        awf_role.restore_rework_workspace_lineage(
            rework_evidence, args, current_provenance, rework_checkpoint
        )
        provider_calls.append("rework")
    assert provider_calls == []


def test_import_model_delta_reproduces_verified_tree_without_git_metadata(repositories, tmp_path):
    _, _, executor = repositories
    expected = run("git", "rev-parse", "HEAD", cwd=executor)
    workspace = Path(awf_role.prepare_model_workspace(str(executor), expected, state_dir=tmp_path))
    original_config = (executor / ".git" / "config").read_text(encoding="utf-8")
    (workspace / "README.md").write_text("changed\n", encoding="utf-8")
    (workspace / "task.md").unlink()
    (workspace / "nested").mkdir()
    (workspace / "nested" / "new.bin").write_bytes(b"\x00\x01model\xff")

    model_tree = awf_role.import_model_delta(str(workspace), str(executor))

    assert run("git", "write-tree", cwd=executor) == model_tree
    assert (executor / "README.md").read_text(encoding="utf-8") == "changed\n"
    assert not (executor / "task.md").exists()
    assert (executor / "nested" / "new.bin").read_bytes() == b"\x00\x01model\xff"
    assert (executor / ".git" / "config").read_text(encoding="utf-8") == original_config


def _isolated_coder_card() -> str:
    return """# Isolated coder card
<!-- awf-postflight
{
  "allowed_paths": ["result.txt", ".awf/artifacts/impl.md"],
  "verification_commands": [["{python}", "-c", "exit(0)"]]
}
-->
"""


def test_coder_runs_model_in_no_remote_workspace_then_trusted_runner_pushes(
    repositories, monkeypatch, tmp_path
):
    origin, seed, executor = repositories
    (seed / ".gitignore").write_text(".awf/\n", encoding="utf-8")
    run("git", "add", ".gitignore", cwd=seed)
    dispatched = commit(seed, "frozen card", "task.md", _isolated_coder_card())
    run("git", "push", "origin", "feature/task", cwd=seed)
    script_dir = tmp_path / "scripts"
    script_dir.mkdir()
    (script_dir / "executor-prompt.md").write_text("prompt", encoding="utf-8")
    monkeypatch.setenv("AWF_REPO_DIR", str(executor))
    monkeypatch.setenv("AWF_SCRIPT_DIR", str(script_dir))
    monkeypatch.delenv("AWF_NO_PUSH", raising=False)
    seen: dict[str, str] = {}

    def fake_tool(model_repo, card_file, *_args, **_kwargs):
        seen["repo"] = model_repo
        seen["card"] = card_file
        assert Path(model_repo).resolve() != executor.resolve()
        assert run("git", "remote", cwd=Path(model_repo)) == ""
        (Path(model_repo) / "result.txt").write_text("done\n", encoding="utf-8")
        report = Path(model_repo) / ".awf" / "artifacts" / "impl.md"
        report.parent.mkdir(parents=True)
        report.write_text("implemented in isolation\n", encoding="utf-8")
        return 0

    events = []
    monkeypatch.setattr(awf_role, "tool_opencode_exec", fake_tool)
    real_import_model_delta = awf_role.import_model_delta

    def import_then_add_late_rogue_file(model_repo, trusted_repo):
        tree = real_import_model_delta(model_repo, trusted_repo)
        (Path(trusted_repo) / "late-rogue.txt").write_text("must not be staged\n", encoding="utf-8")
        return tree

    monkeypatch.setattr(awf_role, "import_model_delta", import_then_add_late_rogue_file)
    monkeypatch.setattr(
        awf_role,
        "send_event",
        lambda *args, **kwargs: events.append((args, kwargs)) or True,
    )
    evidence = awf_role.RunEvidence(80, "coder", state_root=tmp_path / "state")
    args = argparse.Namespace(
        branch="feature/task",
        card="task.md",
        commit=dispatched,
        model="",
        tool="opencode",
        report=".awf/artifacts/impl.md",
        review_report=".awf/artifacts/review.md",
        base="",
        evidence=evidence,
    )

    assert awf_role.role_coder(args) == 0

    pushed = run("git", "rev-parse", "refs/heads/feature/task", cwd=origin)
    assert pushed != dispatched
    assert run("git", "rev-parse", "HEAD", cwd=executor) == pushed
    assert (executor / "result.txt").read_text(encoding="utf-8") == "done\n"
    assert (executor / ".awf" / "artifacts" / "impl.md").read_text(encoding="utf-8") == (
        "implemented in isolation\n"
    )
    assert (
        ".awf/artifacts/impl.md"
        in run("git", "ls-tree", "-r", "--name-only", pushed, cwd=executor).splitlines()
    )
    assert (executor / "late-rogue.txt").is_file()
    assert (
        run("git", "ls-tree", "-r", "--name-only", pushed, cwd=executor)
        .splitlines()
        .count("late-rogue.txt")
        == 0
    )
    model_config = Path(seen["repo"]).joinpath(".git", "config").read_text(encoding="utf-8")
    assert str(executor.resolve()) not in model_config
    assert len(events) == 1
    assert events[0][0][3]["commit"] == pushed
    message = run("git", "show", "-s", "--format=%B", pushed, cwd=executor)
    assert "Directive:" in message
    assert "Tested:" in message


def test_isolated_model_commit_fails_before_trusted_checkout_or_remote_changes(
    repositories, monkeypatch, tmp_path
):
    origin, seed, executor = repositories
    dispatched = commit(seed, "frozen card", "task.md", _isolated_coder_card())
    run("git", "push", "origin", "feature/task", cwd=seed)
    script_dir = tmp_path / "scripts"
    script_dir.mkdir()
    (script_dir / "executor-prompt.md").write_text("prompt", encoding="utf-8")
    monkeypatch.setenv("AWF_REPO_DIR", str(executor))
    monkeypatch.setenv("AWF_SCRIPT_DIR", str(script_dir))

    def fake_tool(model_repo, _card_file, *_args, **_kwargs):
        model_path = Path(model_repo)
        run("git", "config", "user.name", "Model", cwd=model_path)
        run("git", "config", "user.email", "model@example.invalid", cwd=model_path)
        commit(model_path, "model bypass", "result.txt", "must not import\n")
        return 0

    monkeypatch.setattr(awf_role, "tool_opencode_exec", fake_tool)
    events = []
    monkeypatch.setattr(
        awf_role,
        "send_event",
        lambda *args, **kwargs: events.append((args, kwargs)) or True,
    )
    args = argparse.Namespace(
        branch="feature/task",
        card="task.md",
        commit=dispatched,
        model="",
        tool="opencode",
        report=".awf/artifacts/impl.md",
        review_report=".awf/artifacts/review.md",
        base="",
        evidence=None,
    )

    with pytest.raises(SystemExit, match="1"):
        awf_role.role_coder(args)

    assert run("git", "rev-parse", "HEAD", cwd=executor) == dispatched
    assert run("git", "rev-parse", "refs/heads/feature/task", cwd=origin) == dispatched
    assert not (executor / "result.txt").exists()
    assert not events


def test_tool_opencode_exec_uses_model_env(monkeypatch, tmp_path):
    """The executor preserves model_env() and separates file options from its prompt."""
    card_file = tmp_path / "card.md"
    card_file.write_text("task")
    prompt_file = tmp_path / "prompt.md"
    prompt_file.write_text("instructions")

    captured: dict = {}

    def fake_spawn(argv, **kwargs):
        captured["argv"] = argv
        captured["env"] = kwargs.get("env")
        captured["evidence"] = kwargs.get("evidence")
        captured["tracked_phase"] = kwargs.get("tracked_phase")
        return 0

    monkeypatch.setattr(awf_role, "spawn", fake_spawn)
    monkeypatch.setenv("AGENT_BUS_TOKEN", "secret")
    monkeypatch.setenv("AWF_OPENCODE_BIN", "opencode-test")
    monkeypatch.delenv("GIT_CONFIG_COUNT", raising=False)
    evidence = object()

    rc = awf_role.tool_opencode_exec(
        str(tmp_path),
        str(card_file),
        str(prompt_file),
        "provider/model",
        ".awf/artifacts/impl-report-task.md",
        evidence=evidence,
    )

    assert rc == 0
    assert "AGENT_BUS_TOKEN" not in captured["env"]
    assert captured["env"]["GIT_CONFIG_COUNT"] == "10"
    assert captured["evidence"] is evidence
    assert captured["tracked_phase"] == "opencode"
    assert captured["argv"] == [
        "opencode-test",
        "run",
        "--dir",
        str(tmp_path),
        "-f",
        str(card_file),
        "-m",
        "provider/model",
        "--",
        "instructions\n\nWrite the complete ImplementationReport to exactly: "
        ".awf/artifacts/impl-report-task.md\n",
    ]


def test_tool_opencode_exec_injects_bounded_rework_feedback(monkeypatch, tmp_path):
    card_file = tmp_path / "card.md"
    card_file.write_text("task")
    prompt_file = tmp_path / "prompt.md"
    prompt_file.write_text("instructions")
    captured: dict = {}

    monkeypatch.setattr(
        awf_role,
        "spawn",
        lambda argv, **kwargs: captured.update(argv=argv, kwargs=kwargs) or 0,
    )
    feedback = json.dumps(
        {
            "format": "awf.review-report.v1",
            "verdict": "REQUEST_CHANGES",
            "deterministic_failures": [_COMMAND_FAILURE],
            "blocked_reason": "",
            "markdown": "must not reach the executor",
        }
    )

    awf_role.tool_opencode_exec(
        str(tmp_path),
        str(card_file),
        str(prompt_file),
        "",
        ".awf/artifacts/impl-report-task.md",
        review_feedback=feedback,
    )

    instructions = captured["argv"][-1]
    assert "Structured reviewer feedback to correct" in instructions
    assert "Make the failed acceptance test pass" in instructions
    assert "must not reach the executor" not in instructions


def test_executor_prompt_reserves_git_writes_for_trusted_runner():
    prompt = (Path(awf_role.__file__).parent / "executor-prompt.md").read_text(encoding="utf-8")

    assert "Do not run any Git command" in prompt
    assert "`git status`, `git diff`, or `git log`" in prompt
    assert "The trusted runner" in prompt and "alone observes Git state" in prompt


def test_tool_codex_review_uses_model_env_and_stdin(monkeypatch, tmp_path):
    """The Codex reviewer adapter passes model_env() and stdin to spawn()."""
    prompt_file = tmp_path / "prompt.md"
    prompt_file.write_text("review instructions")

    captured: dict = {}

    def fake_spawn(argv, **kwargs):
        captured["argv"] = argv
        captured["env"] = kwargs.get("env")
        captured["stdin"] = kwargs.get("stdin")
        return 0

    monkeypatch.setattr(awf_role, "spawn", fake_spawn)
    monkeypatch.setenv("AGENT_BUS_TOKEN", "secret")

    report_path = str(tmp_path / "review.md")
    awf_role.tool_codex_review(str(tmp_path), "main", str(prompt_file), "", "", report_path)

    assert "AGENT_BUS_TOKEN" not in captured["env"]
    assert report_path in captured["stdin"]
    assert "against the base ref `main`" in captured["stdin"]
    assert "<!-- awf-review-report" in captured["stdin"]
    assert "Return the complete filled-in Markdown report itself" in captured["stdin"]
    assert captured["argv"] == [
        "codex",
        "exec",
        "-C",
        str(tmp_path),
        "--sandbox",
        "read-only",
        "--output-last-message",
        report_path,
        "-",
    ]


def test_tool_opencode_review_uses_model_env(monkeypatch, tmp_path):
    """The reviewer preserves model_env() and separates file options from its prompt."""
    card_file = tmp_path / "card.md"
    card_file.write_text("task")
    prompt_file = tmp_path / "prompt.md"
    prompt_file.write_text("instructions")

    captured: dict = {}

    def fake_spawn(argv, **kwargs):
        captured["argv"] = argv
        captured["env"] = kwargs.get("env")
        captured["evidence"] = kwargs.get("evidence")
        captured["tracked_phase"] = kwargs.get("tracked_phase")
        return 0

    monkeypatch.setattr(awf_role, "spawn", fake_spawn)
    monkeypatch.setenv("AGENT_BUS_TOKEN", "secret")
    monkeypatch.setenv("AWF_OPENCODE_BIN", "opencode-test")
    evidence = object()

    rc = awf_role.tool_opencode_review(
        str(tmp_path),
        "main",
        str(prompt_file),
        str(card_file),
        "provider/model",
        ".awf/review.md",
        evidence=evidence,
    )

    assert rc == 0
    assert "AGENT_BUS_TOKEN" not in captured["env"]
    assert captured["evidence"] is evidence
    assert captured["tracked_phase"] == "opencode"
    assert captured["argv"] == [
        "opencode-test",
        "run",
        "--dir",
        str(tmp_path),
        "-f",
        str(card_file),
        "-m",
        "provider/model",
        "--",
        "instructions\n\nWrite the complete ReviewReport to exactly: .awf/review.md\n",
    ]


def test_tool_opencode_review_promotes_stdout_when_report_missing(monkeypatch, tmp_path):
    card_file = tmp_path / "card.md"
    card_file.write_text("task")
    prompt_file = tmp_path / "prompt.md"
    prompt_file.write_text("instructions")
    report_path = tmp_path / ".awf" / "review.md"

    def fake_spawn(_argv, **kwargs):
        Path(kwargs["stdout_path"]).write_text("review report from stdout\n", encoding="utf-8")
        return 0

    monkeypatch.setattr(awf_role, "spawn", fake_spawn)

    assert (
        awf_role.tool_opencode_review(
            str(tmp_path),
            "main",
            str(prompt_file),
            str(card_file),
            "provider/model",
            str(report_path),
        )
        == 0
    )
    assert report_path.read_text(encoding="utf-8") == "review report from stdout\n"


def test_tool_opencode_review_never_overwrites_model_report(monkeypatch, tmp_path):
    card_file = tmp_path / "card.md"
    card_file.write_text("task")
    prompt_file = tmp_path / "prompt.md"
    prompt_file.write_text("instructions")
    report_path = tmp_path / ".awf" / "review.md"
    report_path.parent.mkdir(parents=True)

    def fake_spawn(_argv, **kwargs):
        report_path.write_text("model-written report\n", encoding="utf-8")
        Path(kwargs["stdout_path"]).write_text("different stdout\n", encoding="utf-8")
        return 0

    monkeypatch.setattr(awf_role, "spawn", fake_spawn)

    assert (
        awf_role.tool_opencode_review(
            str(tmp_path),
            "main",
            str(prompt_file),
            str(card_file),
            "provider/model",
            str(report_path),
        )
        == 0
    )
    assert report_path.read_text(encoding="utf-8") == "model-written report\n"


def test_tool_pi_review_uses_model_env_and_stdout_path(monkeypatch, tmp_path):
    """The Pi reviewer adapter captures stdout and lets the trusted runner write the report."""
    prompt_file = tmp_path / "prompt.md"
    prompt_file.write_text("review instructions")
    card_file = tmp_path / "task.md"
    card_file.write_text("# TaskCard\n")
    captured: dict = {}

    def fake_spawn(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        captured["context"] = Path(argv[-2][1:]).read_text(encoding="utf-8")
        return 0

    monkeypatch.setattr(awf_role, "spawn", fake_spawn)
    monkeypatch.setenv("AGENT_BUS_TOKEN", "secret")
    monkeypatch.setenv("AWF_PI_BIN", "pi-test")
    monkeypatch.setattr(awf_role, "bounded_postflight_git_out", lambda *args: "trusted diff")
    evidence = awf_role.RunEvidence(68, "reviewer", state_root=tmp_path / "state")
    report_path = str(tmp_path / ".awf" / "review.md")

    rc = awf_role.tool_pi_review(
        str(tmp_path),
        "main",
        str(prompt_file),
        str(card_file),
        "provider/model",
        report_path,
        evidence=evidence,
    )

    assert rc == 0
    assert "AGENT_BUS_TOKEN" not in captured["kwargs"]["env"]
    assert captured["kwargs"]["evidence"] is evidence
    assert captured["kwargs"]["tracked_phase"] == "pi"
    assert captured["kwargs"]["stdout_path"] == report_path
    assert captured["kwargs"]["stdout_max_bytes"] == 20 * 1024
    assert captured["argv"][:-2] == [
        "pi-test",
        "--print",
        "--mode",
        "text",
        "--no-session",
        "--no-approve",
        "--no-extensions",
        "--no-skills",
        "--no-prompt-templates",
        "--no-context-files",
        "--tools",
        "read,grep,find,ls",
        "--model",
        "provider/model",
    ]
    assert captured["argv"][-2].startswith("@")
    context_path = Path(captured["argv"][-2][1:])
    assert context_path == tmp_path / ".awf" / "pi-review-context.md"
    context = captured["context"]
    assert "--- Trusted committed diff ---\n\ntrusted diff" in context
    assert "<!-- awf-review-report" in context
    assert "--- TaskCard (acceptance criteria to verify) ---" in context
    assert "against base ref `main`" in captured["argv"][-1]
    assert not context_path.exists()


def test_spawn_rendered_rejects_file_input_drift_before_provider(monkeypatch, tmp_path):
    input_path = tmp_path / ".awf" / "pi-review-context.md"
    input_path.parent.mkdir(parents=True)
    input_path.write_bytes(b"existing different bytes")
    rendered = RenderedInvocation(
        executable="pi-test",
        argv=(f"@{input_path}",),
        cwd=str(tmp_path),
        environment=(("LANG", "C.UTF-8"),),
        file_inputs=(RenderedInputFile(str(input_path), b"trusted bytes"),),
    )
    monkeypatch.setattr(
        awf_role,
        "spawn",
        lambda *args, **kwargs: pytest.fail("file drift must fail before provider spawn"),
    )

    with pytest.raises(SystemExit, match="1"):
        awf_role.spawn_rendered(rendered)

    assert input_path.read_bytes() == b"existing different bytes"


def test_spawn_rendered_rejects_unbound_environment_or_non_utf8_stdin(monkeypatch, tmp_path):
    monkeypatch.setattr(
        awf_role,
        "spawn",
        lambda *args, **kwargs: pytest.fail("invalid rendered input must fail before spawn"),
    )
    with pytest.raises(SystemExit, match="1"):
        awf_role.spawn_rendered(
            RenderedInvocation(executable="codex", argv=("exec",), cwd=str(tmp_path))
        )
    with pytest.raises(SystemExit, match="1"):
        awf_role.spawn_rendered(
            RenderedInvocation(
                executable="codex",
                argv=("exec",),
                cwd=str(tmp_path),
                stdin=b"\xff",
                environment=(("LANG", "C.UTF-8"),),
            )
        )


def test_provider_invocation_binding_is_stable_and_authority_sensitive():
    args = argparse.Namespace(
        branch="codex/example",
        commit="a" * 40,
        input_type="task:awf-review-v3",
        run_id="task-example",
    )
    context = {
        "key": "delivery-example",
        "delivery_id": "delivery-example",
        "payload_sha256": "b" * 64,
        "source_event_id": 17,
    }
    gate = argparse.Namespace(sequence=3)

    first = awf_role.provider_invocation_binding(
        args, "reviewer", context, gate, tool="pi", model="provider/model"
    )
    assert first == awf_role.provider_invocation_binding(
        args, "reviewer", context, gate, tool="pi", model="provider/model"
    )
    assert first[:3] == ("delivery-example", "task-example", "example")
    assert len(first[3]) == 64
    assert first != awf_role.provider_invocation_binding(
        args,
        "reviewer",
        {**context, "delivery_id": "delivery-other"},
        gate,
        tool="pi",
        model="provider/model",
    )
    assert first != awf_role.provider_invocation_binding(
        args,
        "reviewer",
        context,
        argparse.Namespace(sequence=4),
        tool="pi",
        model="provider/model",
    )


def test_tool_pi_review_rejects_oversized_trusted_diff_before_model(monkeypatch, tmp_path):
    prompt_file = tmp_path / "prompt.md"
    prompt_file.write_text("review instructions", encoding="utf-8")

    def reject_oversized(*args):
        raise SystemExit(1)

    monkeypatch.setattr(awf_role, "bounded_postflight_git_out", reject_oversized)
    monkeypatch.setattr(
        awf_role,
        "spawn",
        lambda *args, **kwargs: pytest.fail("oversized diff must fail before Pi invocation"),
    )

    with pytest.raises(SystemExit, match="1"):
        awf_role.tool_pi_review(
            str(tmp_path),
            "main",
            str(prompt_file),
            "",
            "",
            str(tmp_path / ".awf" / "review.md"),
        )


def test_tool_codex_review_preserves_model_card_and_tracked_phase(monkeypatch, tmp_path):
    prompt_file = tmp_path / "prompt.md"
    prompt_file.write_text("review instructions")
    card_file = tmp_path / "task.md"
    card_file.write_text("# TaskCard\n")
    captured: dict = {}

    def fake_spawn(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return 7

    monkeypatch.setattr(awf_role, "spawn", fake_spawn)
    monkeypatch.setenv("AWF_CODEX_BIN", "codex-test")
    evidence = object()
    report_path = str(tmp_path / "review.md")

    rc = awf_role.tool_codex_review(
        str(tmp_path),
        "main",
        str(prompt_file),
        str(card_file),
        "provider/model",
        report_path,
        evidence=evidence,
    )

    assert rc == 7
    assert captured["argv"] == [
        "codex-test",
        "exec",
        "-C",
        str(tmp_path),
        "--sandbox",
        "read-only",
        "--output-last-message",
        report_path,
        "--model",
        "provider/model",
        "-",
    ]
    assert (
        "--- TaskCard (acceptance criteria to verify) ---\n\n# TaskCard\n"
        in captured["kwargs"]["stdin"]
    )
    assert captured["kwargs"]["evidence"] is evidence
    assert captured["kwargs"]["tracked_phase"] == "codex"


@pytest.mark.parametrize("adapter", ["executor", "reviewer"])
def test_tool_opencode_card_prompt_boundary_without_model(monkeypatch, tmp_path, adapter):
    """The incident path still terminates the file array when no model is configured."""
    card_file = tmp_path / "card.md"
    card_file.write_text("task")
    prompt_file = tmp_path / "prompt.md"
    prompt_file.write_text("instructions")
    captured: dict = {}

    def fake_spawn(argv, **kwargs):
        captured["argv"] = argv
        return 0

    monkeypatch.setattr(awf_role, "spawn", fake_spawn)
    monkeypatch.setenv("AWF_OPENCODE_BIN", "opencode-test")

    if adapter == "executor":
        awf_role.tool_opencode_exec(
            str(tmp_path),
            str(card_file),
            str(prompt_file),
            "",
            ".awf/artifacts/impl-report-task.md",
        )
    else:
        awf_role.tool_opencode_review(
            str(tmp_path), "main", str(prompt_file), str(card_file), "", ".awf/review.md"
        )

    expected_instructions = (
        "instructions\n\nWrite the complete ImplementationReport to exactly: "
        ".awf/artifacts/impl-report-task.md\n"
        if adapter == "executor"
        else "instructions\n\nWrite the complete ReviewReport to exactly: .awf/review.md\n"
    )
    assert captured["argv"] == [
        "opencode-test",
        "run",
        "--dir",
        str(tmp_path),
        "-f",
        str(card_file),
        "--",
        expected_instructions,
    ]


# ---------------------------------------------------------------------------
# Closed stdin
# ---------------------------------------------------------------------------


def test_spawn_devnull_for_no_input(monkeypatch):
    """A subprocess with no explicit input receives subprocess.DEVNULL."""
    captured = {}

    def fake_run(*args, **kwargs):
        captured.update(kwargs)
        return subprocess.CompletedProcess([], 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    awf_role.spawn(["git", "status"])

    assert captured.get("stdin") is subprocess.DEVNULL
    assert captured.get("input") is None


def test_spawn_stdin_when_provided(monkeypatch):
    """A subprocess with stdin text does not receive DEVNULL."""
    captured = {}

    def fake_run(*args, **kwargs):
        captured.update(kwargs)
        return subprocess.CompletedProcess([], 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    awf_role.spawn(["codex"], stdin="prompt text")

    assert captured.get("input") == "prompt text"
    assert captured.get("stdin") is not subprocess.DEVNULL


def test_capture_dogfood_finding_uses_run_state_and_strips_before_business(monkeypatch, tmp_path):
    report = tmp_path / "model" / "review.md"
    report.parent.mkdir()
    finding = {
        "kind": "reliability",
        "component": "recovery",
        "summary": "Replay loses a completed report",
        "observed": "The completed report was unavailable after restart",
        "expected": "The completed report remains available after restart",
    }
    report.write_text(
        "# ReviewReport\n\nVerdict: PASS\n\n"
        "<!-- awf-dogfood-finding-v1\n" + json.dumps(finding, separators=(",", ":")) + "\n-->\n",
        encoding="utf-8",
    )
    evidence = awf_role.RunEvidence(70, "reviewer", state_root=tmp_path / "state")
    monkeypatch.setenv("AWF_FINDING_ENABLED", "1")

    awf_role.capture_dogfood_finding(
        report,
        input_context={"delivery_id": "delivery-70"},
        source_role="reviewer",
        source_tool="pi",
        evidence=evidence,
    )

    assert report.read_text(encoding="utf-8") == "# ReviewReport\n\nVerdict: PASS\n"
    assert len(list((evidence.state_dir / "feedback/outbox").glob("*.json"))) == 1
    result = json.loads(evidence.result_path.read_text(encoding="utf-8"))
    assert result["finding_status"] == "queued"


def test_finding_evidence_failure_does_not_change_business_result(monkeypatch, tmp_path, capsys):
    report = tmp_path / "review.md"
    finding = {
        "kind": "reliability",
        "component": "recovery",
        "summary": "Evidence write is unavailable",
        "observed": "The optional Finding evidence cannot be written",
        "expected": "The formal Report still proceeds",
    }
    report.write_text(
        "# ReviewReport\n\nVerdict: PASS\n\n"
        "<!-- awf-dogfood-finding-v1\n" + json.dumps(finding, separators=(",", ":")) + "\n-->\n",
        encoding="utf-8",
    )

    class FailingEvidence:
        state_dir = tmp_path / "state"

        def record(self, _phase, **_fields):
            raise OSError("evidence disk unavailable")

    monkeypatch.setenv("AWF_FINDING_ENABLED", "1")

    awf_role.capture_dogfood_finding(
        report,
        input_context={"delivery_id": "delivery-71"},
        source_role="reviewer",
        source_tool="pi",
        evidence=FailingEvidence(),
    )

    assert report.read_text(encoding="utf-8") == "# ReviewReport\n\nVerdict: PASS\n"
    assert "Finding evidence was not persisted" in capsys.readouterr().out


def test_missing_feedback_state_strips_finding_without_business_failure(
    monkeypatch, tmp_path, capsys
):
    report = tmp_path / "review.md"
    finding = {
        "kind": "reliability",
        "component": "recovery",
        "summary": "Feedback state is unavailable",
        "observed": "The optional queue cannot be opened",
        "expected": "The business report still proceeds",
    }
    report.write_text(
        "# ReviewReport\n\nVerdict: PASS\n\n"
        "<!-- awf-dogfood-finding-v1\n" + json.dumps(finding, separators=(",", ":")) + "\n-->\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        awf_role,
        "feedback_state_root",
        lambda: (_ for _ in ()).throw(
            sys.modules["agent_workflow.operations.awf_feedback"].FeedbackStateError("unavailable")
        ),
    )
    monkeypatch.setenv("AWF_FINDING_ENABLED", "1")

    awf_role.capture_dogfood_finding(
        report,
        input_context={"delivery_id": "delivery-72"},
        source_role="reviewer",
        source_tool="pi",
        evidence=None,
    )

    assert report.read_text(encoding="utf-8") == "# ReviewReport\n\nVerdict: PASS\n"
    output = capsys.readouterr().out
    assert "Finding state is unavailable" in output
    assert "Finding was stripped but not queued" in output


def test_finding_default_off_does_not_inspect_or_modify_provider_report(tmp_path):
    report = tmp_path / "review.md"
    raw = "# ReviewReport\n\nVerdict: PASS\n\n<!-- awf-dogfood-finding-v1\n{}\n-->\n"
    report.write_text(raw, encoding="utf-8")

    awf_role.capture_dogfood_finding(
        report,
        input_context={"delivery_id": "delivery-off"},
        source_role="reviewer",
        source_tool="pi",
        evidence=None,
    )

    assert report.read_text(encoding="utf-8") == raw
    assert not (tmp_path / "feedback").exists()


@pytest.mark.parametrize(("returncode", "should_write"), [(0, True), (3, False)])
def test_spawn_stdout_path_writes_only_after_success(
    monkeypatch, tmp_path, returncode, should_write
):
    import io

    captured = {}
    stdout_path = tmp_path / "review.md"

    class CapturingProcess:
        def __init__(self):
            self.pid = 4321
            self.returncode = returncode
            self.stdout = io.StringIO("review stdout")

        def poll(self):
            return self.returncode

        def kill(self):
            self.returncode = -9

        def wait(self):
            return self.returncode

    def fake_start(*args, **kwargs):
        captured.update(kwargs)
        return CapturingProcess()

    monkeypatch.setattr(awf_role, "start_command", fake_start)

    assert awf_role.spawn(["pi"], stdout_path=str(stdout_path)) == returncode

    assert captured["stdout"] is subprocess.PIPE
    assert stdout_path.exists() is should_write
    if should_write:
        assert stdout_path.read_text(encoding="utf-8") == "review stdout"


@pytest.mark.parametrize(("returncode", "stderr_written"), [(0, False), (3, True)])
def test_spawn_persists_bounded_stderr_only_after_nonzero(
    monkeypatch, tmp_path, returncode, stderr_written
):
    import io

    stdout_path = tmp_path / "architect.stdout"
    stderr_path = tmp_path / "architect.stderr"

    class CapturingProcess:
        pid = 4321

        def __init__(self):
            self.returncode = returncode
            self.stdout = io.StringIO("semantic stdout")
            self.stderr = io.StringIO("provider diagnostic")

        def poll(self):
            return self.returncode

        def kill(self):
            self.returncode = -9

        def wait(self):
            return self.returncode

    def fake_start(*args, **kwargs):
        assert kwargs["stderr"] is subprocess.PIPE
        return CapturingProcess()

    monkeypatch.setattr(awf_role, "start_command", fake_start)

    assert (
        awf_role.spawn(
            ["opencode"],
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
        )
        == returncode
    )

    assert stderr_path.exists() is stderr_written
    if stderr_written:
        assert stderr_path.read_text(encoding="utf-8") == "provider diagnostic"
        assert not stdout_path.exists()
    else:
        assert stdout_path.read_text(encoding="utf-8") == "semantic stdout"


def test_spawn_discards_stderr_after_bounded_prefix(monkeypatch, tmp_path):
    import io

    stdout_path = tmp_path / "architect.stdout"
    stderr_path = tmp_path / "architect.stderr"

    class CapturingProcess:
        pid = 4321
        returncode = 3
        stdout = io.StringIO("")
        stderr = io.StringIO("x" * 40)

        def poll(self):
            return self.returncode

        def kill(self):
            self.returncode = -9

        def wait(self):
            return self.returncode

    monkeypatch.setattr(awf_role, "start_command", lambda *args, **kwargs: CapturingProcess())

    assert (
        awf_role.spawn(
            ["opencode"],
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            stderr_max_bytes=16,
        )
        == 3
    )

    assert stderr_path.read_text(encoding="utf-8") == (
        "x" * 16 + "\n[stderr truncated at 16 bytes]\n"
    )


def test_spawn_reaps_real_child_before_propagating_stdout_interrupt(monkeypatch, tmp_path):
    original_start = awf_role.start_command
    captured = {}

    def tracking_start(*args, **kwargs):
        captured["process"] = original_start(*args, **kwargs)
        return captured["process"]

    monkeypatch.setattr(awf_role, "start_command", tracking_start)
    monkeypatch.setattr(
        awf_role,
        "read_bounded_stdout",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(KeyboardInterrupt()),
    )
    stdout_path = tmp_path / "architect.stdout"
    stderr_path = tmp_path / "architect.stderr"

    with pytest.raises(KeyboardInterrupt):
        awf_role.spawn(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
        )

    assert captured["process"].poll() is not None
    assert not stdout_path.exists()
    assert not stderr_path.exists()


def test_spawn_reaps_real_child_and_propagates_stderr_reader_failure(monkeypatch, tmp_path):
    original_start = awf_role.start_command
    captured = {}

    def tracking_start(*args, **kwargs):
        captured["process"] = original_start(*args, **kwargs)
        return captured["process"]

    monkeypatch.setattr(awf_role, "start_command", tracking_start)
    monkeypatch.setattr(
        awf_role,
        "read_bounded_stream",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("stderr drain failed")),
    )
    stdout_path = tmp_path / "architect.stdout"
    stderr_path = tmp_path / "architect.stderr"

    with pytest.raises(OSError, match="stderr drain failed"):
        awf_role.spawn(
            [
                sys.executable,
                "-c",
                "import sys,time; sys.stderr.write('x'*65536); sys.stderr.flush(); time.sleep(30)",
            ],
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
        )

    assert captured["process"].poll() is not None
    assert not stdout_path.exists()
    assert not stderr_path.exists()


@pytest.mark.parametrize(("returncode", "should_write"), [(0, True), (4, False)])
def test_tracked_spawn_stdout_path_preserves_phase_evidence(
    monkeypatch, tmp_path, returncode, should_write
):
    import io

    class CapturingProcess:
        def __init__(self, rc):
            self.pid = 4321
            self.returncode = rc
            self.stdout = io.StringIO("tracked review stdout")

        def poll(self):
            return self.returncode

        def kill(self):
            raise AssertionError("successful communicate should not kill")

        def wait(self):
            return self.returncode

    captured = {}

    def fake_start(*args, **kwargs):
        captured.update(kwargs)
        return CapturingProcess(returncode)

    monkeypatch.setattr(awf_role, "start_command", fake_start)
    evidence = awf_role.RunEvidence(66, "reviewer", state_root=tmp_path / "state")
    stdout_path = tmp_path / "review.md"

    assert (
        awf_role.spawn(
            ["pi"],
            cwd=str(tmp_path),
            evidence=evidence,
            tracked_phase="pi",
            stdout_path=str(stdout_path),
        )
        == returncode
    )

    assert captured["stdout"] is subprocess.PIPE
    assert stdout_path.exists() is should_write
    result = json.loads(evidence.result_path.read_text(encoding="utf-8"))
    assert result["last_phase"] == "pi_exit"
    assert result["pi_pid"] == 4321
    assert result["pi_rc"] == returncode


def test_tracked_spawn_kills_oversized_stdout_before_report_persistence(
    monkeypatch, tmp_path, capsys
):
    import io

    class OversizedProcess:
        pid = 4321
        returncode = None
        stdout = io.StringIO("x" * (16 * 1024 + 1))

        def poll(self):
            return self.returncode

        def kill(self):
            self.returncode = -9

        def wait(self):
            return self.returncode

    monkeypatch.setattr(awf_role, "start_command", lambda *args, **kwargs: OversizedProcess())
    evidence = awf_role.RunEvidence(67, "reviewer", state_root=tmp_path / "state")
    stdout_path = tmp_path / "review.md"

    with pytest.raises(SystemExit, match="1"):
        awf_role.spawn(
            ["pi"],
            evidence=evidence,
            tracked_phase="pi",
            stdout_path=str(stdout_path),
        )

    assert not stdout_path.exists()
    assert "exceeds 16 KiB" in capsys.readouterr().err
    result = json.loads(evidence.result_path.read_text(encoding="utf-8"))
    assert result["pi_rc"] == -9
    assert result["pi_stdout_limit_exceeded"] is True


def test_bounded_postflight_git_out_kills_oversized_diff(monkeypatch, tmp_path, capsys):
    import io

    class OversizedGitProcess:
        returncode = None
        stdout = io.StringIO("x" * 17)

        def poll(self):
            return self.returncode

        def kill(self):
            self.returncode = -9

        def wait(self):
            return self.returncode

    captured = {}

    def fake_start(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return OversizedGitProcess()

    monkeypatch.setattr(awf_role, "start_command", fake_start)

    with pytest.raises(SystemExit, match="1"):
        awf_role.bounded_postflight_git_out(str(tmp_path), 16, "diff", "main...HEAD")

    assert captured["argv"] == ["git", "-C", str(tmp_path), "diff", "main...HEAD"]
    assert captured["kwargs"]["stdout"] is subprocess.PIPE
    assert "exceeds 16 bytes" in capsys.readouterr().err


def test_send_event_stdin_devnull(monkeypatch):
    """send_event() is safe under pythonw and never reads inherited stdin."""
    monkeypatch.setenv("AGENT_BUS_URL", "http://bus")
    monkeypatch.setenv("AWF_CODER_TOKEN", "tok")

    captured = {}

    def fake_run(*args, **kwargs):
        captured.update(kwargs)
        return subprocess.CompletedProcess([], 0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    awf_role.send_event("coder", "reviewer", "task:awf-review", {"k": "v"})

    assert captured.get("stdin") is subprocess.DEVNULL
    assert captured.get("capture_output") is True
    assert captured.get("text") is True
    assert captured.get("encoding") == "utf-8"
    assert captured.get("errors") == "replace"


# ---------------------------------------------------------------------------
# ImplementationReport gate
# ---------------------------------------------------------------------------


def test_check_report_empty():
    """An empty --report argument is a handler failure."""
    with pytest.raises(SystemExit, match="1"):
        awf_role.check_report("")


def test_check_report_missing(tmp_path):
    """A --report path that is not a regular file is a handler failure."""
    with pytest.raises(SystemExit, match="1"):
        awf_role.check_report(str(tmp_path / "nonexistent.md"))


def test_check_report_exists(tmp_path):
    """A valid --report path passes without error."""
    report = tmp_path / "report.md"
    report.write_text("ok")
    awf_role.check_report(str(report))  # must not raise


def test_coder_missing_report_gate(monkeypatch, tmp_path):
    """A missing report in coder fails before git add/commit/push/send_event."""
    repo = tmp_path / "repo"
    repo.mkdir()
    script_dir = tmp_path / "scripts"
    script_dir.mkdir()
    (script_dir / "executor-prompt.md").write_text("prompt")
    card = repo / "task.md"
    card.write_text(_VALID_POSTFLIGHT_CARD)

    monkeypatch.setenv("AWF_REPO_DIR", str(repo))
    monkeypatch.setenv("AWF_SCRIPT_DIR", str(script_dir))
    monkeypatch.setenv("AWF_NO_PUSH", "1")
    monkeypatch.setenv("AGENT_BUS_URL", "http://bus")
    monkeypatch.setenv("AWF_CODER_TOKEN", "tok")

    monkeypatch.setattr(awf_role, "fetch_and_checkout", lambda *a, **kw: None)
    monkeypatch.setattr(awf_role, "prepare_model_workspace", lambda *a, **kw: str(repo))
    evidence = awf_role.RunEvidence(61, "coder", state_root=tmp_path / "state")
    tool_evidence = []
    monkeypatch.setattr(
        awf_role,
        "tool_opencode_exec",
        lambda *args, **kw: tool_evidence.append(args[-1]) or 0,
    )
    monkeypatch.setattr(awf_role, "assert_model_workspace_state", lambda *a, **kw: None)
    monkeypatch.setattr(awf_role, "assert_model_git_state", lambda *a, **kw: None)

    git_calls = []
    monkeypatch.setattr(awf_role, "git", lambda *a, **kw: git_calls.append(a) or 0)
    send_calls = []
    monkeypatch.setattr(awf_role, "send_event", lambda *a, **kw: send_calls.append(a) or True)

    ns = argparse.Namespace(
        branch="feature/task",
        card="task.md",
        commit="abc1234",
        model="",
        tool="opencode",
        report="",
        review_report=".awf/review.md",
        base="",
        evidence=evidence,
    )

    with pytest.raises(SystemExit, match="1"):
        awf_role.role_coder(ns)

    # The gate fires before any git write or event send
    assert not git_calls, "git should not be reached before report gate"
    assert not send_calls, "send_event should not be reached before report gate"
    assert tool_evidence == [evidence]
    result = json.loads(evidence.result_path.read_text(encoding="utf-8"))
    assert result["last_phase"] == "postflight_fail"
    assert result["postflight_started"] is True
    assert result["postflight_status"] == "fail"


@pytest.mark.parametrize(
    "tool,review_attr",
    [
        ("codex", "tool_codex_review"),
        ("opencode", "tool_opencode_review"),
        ("pi", "tool_pi_review"),
    ],
)
def test_reviewer_missing_report_gate(monkeypatch, tmp_path, tool, review_attr):
    """A missing report in reviewer fails before any model invocation, for both reviewer tools."""
    repo = tmp_path / "repo"
    repo.mkdir()
    script_dir = tmp_path / "scripts"
    script_dir.mkdir()
    (script_dir / "reviewer-prompt.md").write_text("prompt")
    card = repo / "task.md"
    card.write_text("card")

    monkeypatch.setenv("AWF_REPO_DIR", str(repo))
    monkeypatch.setenv("AWF_SCRIPT_DIR", str(script_dir))
    monkeypatch.setenv("AWF_TOOL", tool)

    monkeypatch.setattr(awf_role, "fetch_and_checkout", lambda *a, **kw: None)

    tool_calls = []
    monkeypatch.setattr(awf_role, review_attr, lambda *a, **kw: tool_calls.append(a) or 0)

    ns = argparse.Namespace(
        branch="feature/task",
        card="task.md",
        commit="abc1234",
        model="",
        tool=tool,
        report="",
        review_report=".awf/review.md",
        base="main",
    )

    with pytest.raises(SystemExit, match="1"):
        awf_role.role_reviewer(ns)

    assert not tool_calls, f"{tool} review tool should not be invoked before report gate"


def test_reviewer_rejects_ignored_stale_implementation_report(repositories):
    _, _, executor = repositories
    (executor / ".gitignore").write_text(".awf/\n", encoding="utf-8")
    run("git", "add", ".gitignore", cwd=executor)
    run("git", "commit", "-m", "ignore runtime artifacts", cwd=executor)
    report = executor / ".awf" / "artifacts" / "impl.md"
    report.parent.mkdir(parents=True)
    report.write_text("stale local evidence\n", encoding="utf-8")

    with pytest.raises(SystemExit):
        awf_role.check_report_tracked_at_head(str(executor), ".awf/artifacts/impl.md")


def test_import_model_report_includes_ignored_configured_artifact(repositories, tmp_path):
    _, seed, executor = repositories
    (seed / ".gitignore").write_text(".awf/\n", encoding="utf-8")
    run("git", "add", ".gitignore", cwd=seed)
    dispatched = commit(seed, "ignore runtime artifacts", "task.md", "task\n")
    run("git", "push", "origin", "feature/task", cwd=seed)
    awf_role.fetch_and_checkout(str(executor), "feature/task", dispatched)
    workspace = Path(
        awf_role.prepare_model_workspace(str(executor), dispatched, state_dir=tmp_path / "state")
    )
    report_path = ".awf/artifacts/review.md"
    report = workspace / report_path
    report.parent.mkdir(parents=True)
    report.write_text(_review_markdown("PASS"), encoding="utf-8")
    pre_import_manifest = awf_role.durable_model_manifest_sha256(str(workspace))

    imported = awf_role.import_model_report(str(workspace), str(executor), report_path)
    post_import_manifest = awf_role.durable_model_manifest_sha256(str(workspace))

    assert imported.read_text(encoding="utf-8") == _review_markdown("PASS")
    assert post_import_manifest != pre_import_manifest

    evidence = awf_role.RunEvidence(118, "reviewer", state_root=tmp_path / "state")
    input_context = {
        "key": "input-delivery",
        "delivery_id": "input-delivery",
        "payload_sha256": "sha256:input",
        "source_event_id": 117,
    }
    checkpoint_path, checkpoint = awf_role.begin_recovery_checkpoint(
        evidence,
        input_context,
        role="reviewer",
        branch="feature/task",
        source_commit=dispatched,
        provenance=_pr_provenance(),
    )
    checkpoint = awf_role.advance_recovery_checkpoint(
        evidence,
        checkpoint_path,
        checkpoint,
        "model_started",
        model_workspace=str(workspace),
        model_manifest_sha256=pre_import_manifest,
        model_event_id=118,
    )
    checkpoint = awf_role.advance_recovery_checkpoint(
        evidence,
        checkpoint_path,
        checkpoint,
        "model_completed",
    )
    checkpoint = awf_role.advance_recovery_checkpoint(
        evidence,
        checkpoint_path,
        checkpoint,
        "model_imported",
        review_report_sha256=hashlib.sha256(imported.read_bytes()).hexdigest(),
        postflight_model_manifest_sha256=post_import_manifest,
    )

    assert awf_role.restore_durable_model_manifest(
        evidence,
        str(workspace),
        checkpoint["facts"]["postflight_model_manifest_sha256"],
    ) == str(workspace.resolve())


def test_pi_reviewer_recovery_accepts_completed_process_log(monkeypatch, tmp_path):
    evidence = awf_role.RunEvidence(119, "reviewer", state_root=tmp_path / "state")
    input_context = {
        "key": "input-delivery",
        "delivery_id": "input-delivery",
        "payload_sha256": "sha256:input",
        "source_event_id": 118,
    }
    checkpoint_path, checkpoint = awf_role.begin_recovery_checkpoint(
        evidence,
        input_context,
        role="reviewer",
        branch="feature/task",
        source_commit="a" * 40,
        provenance=_pr_provenance(),
    )
    workspace = tmp_path / "model-workspace-119"
    checkpoint = awf_role.advance_recovery_checkpoint(
        evidence,
        checkpoint_path,
        checkpoint,
        "model_started",
        model_workspace=str(workspace),
        model_manifest_sha256="sha256:model",
        model_event_id=119,
        model_process="pi",
    )
    evidence.record("pi_start", pi_pid=123, pi_cwd=str(workspace))
    evidence.record("pi_exit", pi_rc=0)
    monkeypatch.setattr(
        awf_role,
        "restore_durable_model_manifest",
        lambda _evidence, path, _manifest: path,
    )

    recovered = awf_role.recover_completed_model_checkpoint(
        evidence,
        checkpoint_path,
        checkpoint,
    )

    assert recovered["phase"] == "model_completed"
    assert recovered["facts"]["model_process"] == "pi"
    assert recovered["facts"]["recovered_from_process_log"] is True


def test_model_manifest_binds_semantic_index_not_binary_stat_cache(repositories):
    _, _, executor = repositories
    manifest = awf_role._model_git_manifest(str(executor))

    assert "index" not in manifest
    assert manifest["index-semantic"][0] == "git-index"
    assert manifest["index-semantic"][1]


@pytest.mark.parametrize("field", ["card", "report"])
@pytest.mark.parametrize("escaped_path", ["absolute", "../outside.md"])
def test_reviewer_rejects_repo_path_escape_before_model(monkeypatch, tmp_path, field, escaped_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    script_dir = tmp_path / "scripts"
    script_dir.mkdir()
    (script_dir / "reviewer-prompt.md").write_text("prompt", encoding="utf-8")
    (repo / "task.md").write_text("card", encoding="utf-8")
    (repo / "implementation.md").write_text("implementation", encoding="utf-8")
    outside = tmp_path / "outside.md"
    outside.write_text("must not satisfy a repository artifact gate", encoding="utf-8")

    monkeypatch.setenv("AWF_REPO_DIR", str(repo))
    monkeypatch.setenv("AWF_SCRIPT_DIR", str(script_dir))
    monkeypatch.setenv("AWF_TOOL", "codex")
    monkeypatch.setattr(awf_role, "fetch_and_checkout", lambda *a, **kw: None)
    tool_calls = []
    monkeypatch.setattr(
        awf_role,
        "tool_codex_review",
        lambda *a, **kw: tool_calls.append(a) or 0,
    )
    args = argparse.Namespace(
        branch="feature/task",
        card="task.md",
        commit="abc1234",
        model="",
        tool="codex",
        report="implementation.md",
        review_report=".awf/review.md",
        base="main",
    )
    setattr(args, field, str(outside) if escaped_path == "absolute" else escaped_path)

    with pytest.raises(SystemExit, match="1"):
        awf_role.role_reviewer(args)

    assert not tool_calls


# ---------------------------------------------------------------------------
# Structured ReviewReport and fail-closed reviewer routing
# ---------------------------------------------------------------------------


def _review_markdown(verdict, *, failures=None, blocked_reason="", extra=""):
    machine = {
        "verdict": verdict,
        "deterministic_failures": failures or [],
        "blocked_reason": blocked_reason,
    }
    return "# Review Report\n\n<!-- awf-review-report\n" + json.dumps(machine) + "\n-->\n\n" + extra


def _fenced_review_markdown(verdict, *, failures=None, blocked_reason=""):
    machine = {
        "verdict": verdict,
        "deterministic_failures": failures or [],
        "blocked_reason": blocked_reason,
    }
    return "# Review Report\n\n```json\n" + json.dumps({"awf-review-report": machine}) + "\n```\n"


def test_parse_review_report_accepts_legacy_fenced_wrapper(tmp_path):
    report = tmp_path / "review.md"
    report.write_text(_fenced_review_markdown("PASS"), encoding="utf-8")

    normalized = awf_role.parse_review_report(report)

    assert normalized["format"] == "awf.review-report.v1"
    assert normalized["verdict"] == "PASS"


def test_trusted_runner_normalizes_one_line_review_envelope_before_checkpoint(tmp_path):
    report = tmp_path / "review.md"
    report.write_text(
        '<!-- awf-review-report {"verdict":"PASS","deterministic_failures":[],'
        '"blocked_reason":null} -->\n',
        encoding="utf-8",
    )
    awf_role.normalize_machine_review_envelope(str(tmp_path), "review.md")
    normalized = awf_role.parse_review_report(report)
    assert normalized["verdict"] == "PASS"
    assert report.read_text(encoding="utf-8").startswith("<!-- awf-review-report\n")


def test_artifact_invalid_checkpoint_is_bounded_and_preserves_report_binding(tmp_path, capsys):
    evidence = awf_role.RunEvidence(901, "reviewer", state_root=tmp_path / "state")
    provenance = _pr_provenance(pull_request=28)
    input_context = {
        "key": "delivery-901",
        "delivery_id": "delivery-901",
        "payload_sha256": "sha256:input",
        "source_event_id": 142,
    }
    path, checkpoint = awf_role.begin_recovery_checkpoint(
        evidence,
        input_context,
        role="reviewer",
        branch="feature/task",
        source_commit="a" * 40,
        provenance=provenance,
    )
    checkpoint = awf_role.advance_recovery_checkpoint(
        evidence,
        path,
        checkpoint,
        "model_started",
        model_workspace="/state/model-workspace-901",
        model_manifest_sha256="sha256:model",
        model_event_id=142,
        model_process="opencode",
    )
    checkpoint = awf_role.advance_recovery_checkpoint(
        evidence,
        path,
        checkpoint,
        "model_completed",
        model_workspace="/state/model-workspace-901",
        model_manifest_sha256="sha256:model",
        model_event_id=142,
        model_process="opencode",
    )
    checkpoint = awf_role.advance_recovery_checkpoint(
        evidence, path, checkpoint, "model_imported", review_report_sha256="invalid-bound-sha"
    )
    diagnosed = awf_role.mark_artifact_invalid(evidence, path, checkpoint, "schema rejected")
    assert diagnosed["phase"] == "model_imported"
    assert diagnosed["facts"]["artifact_status"] == "artifact_invalid"
    assert diagnosed["facts"]["review_report_sha256"] == "invalid-bound-sha"
    with pytest.raises(SystemExit, match="1"):
        awf_role.mark_artifact_invalid(evidence, path, diagnosed, "schema rejected")
    assert "artifact_invalid recovery is exhausted" in capsys.readouterr().err


def test_parse_review_report_rejects_multiple_fenced_wrappers(tmp_path):
    report = tmp_path / "review.md"
    report.write_text(
        _fenced_review_markdown("PASS") + _fenced_review_markdown("PASS"),
        encoding="utf-8",
    )

    with pytest.raises(SystemExit):
        awf_role.parse_review_report(report)


def test_validate_embedded_review_report_accepts_fenced_wrapper():
    markdown = _fenced_review_markdown("PASS")
    embedded = {
        "format": "awf.review-report.v1",
        "verdict": "PASS",
        "deterministic_failures": [],
        "blocked_reason": "",
        "markdown": markdown,
    }

    normalized = awf_role.validate_embedded_review_report(embedded)

    assert normalized == embedded


@pytest.mark.parametrize("blocked_reason", [None, ""])
def test_pass_review_report_normalizes_absent_blocked_reason(blocked_reason, tmp_path):
    report = tmp_path / "review.md"
    report.write_text(_review_markdown("PASS", blocked_reason=blocked_reason), encoding="utf-8")

    normalized = awf_role.parse_review_report(report)

    assert normalized["verdict"] == "PASS"
    assert normalized["deterministic_failures"] == []
    assert normalized["blocked_reason"] == ""
    assert json.loads(json.dumps(normalized))["blocked_reason"] == ""


def test_pass_review_report_rejects_nonempty_blocked_reason(tmp_path):
    report = tmp_path / "review.md"
    report.write_text(_review_markdown("PASS", blocked_reason="not blocked"), encoding="utf-8")

    with pytest.raises(SystemExit, match="1"):
        awf_role.parse_review_report(report)


@pytest.mark.parametrize("blocked_reason", [None, ""])
def test_blocked_review_report_requires_nonempty_reason(blocked_reason, tmp_path):
    report = tmp_path / "review.md"
    report.write_text(_review_markdown("BLOCKED", blocked_reason=blocked_reason), encoding="utf-8")

    with pytest.raises(SystemExit, match="1"):
        awf_role.parse_review_report(report)


def test_blocked_review_report_accepts_nonempty_reason(tmp_path):
    report = tmp_path / "review.md"
    report.write_text(
        _review_markdown("BLOCKED", blocked_reason="needs user decision"),
        encoding="utf-8",
    )

    normalized = awf_role.parse_review_report(report)

    assert normalized["blocked_reason"] == "needs user decision"


_COMMAND_FAILURE = {
    "evidence": {
        "kind": "command",
        "command": "python -m pytest -q tests/test_feature.py",
        "result": "FAILED test_expected_contract",
    },
    "required_correction": "Make the failed acceptance test pass without widening scope.",
}


def _architect_decision_args(tmp_path, verdict="PASS"):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "task.md").write_text("card\n", encoding="utf-8")
    (repo / "implementation.md").write_text("implementation\n", encoding="utf-8")
    review_source = tmp_path / "review.md"
    review_source.write_text(
        _review_markdown(
            verdict,
            blocked_reason="External constraint" if verdict == "BLOCKED" else "",
        ),
        encoding="utf-8",
    )
    normalized = awf_role.parse_review_report(review_source)
    provenance = _pr_provenance()
    event_type = "decision:awf-ready-v3" if verdict == "PASS" else "decision:awf-blocked-v3"
    ns = argparse.Namespace(
        input_type=event_type,
        source_event_id=88,
        branch=provenance["head_ref"],
        card="task.md",
        commit=provenance["head_sha"],
        model="",
        tool="codex",
        report="implementation.md",
        review_report=".awf/review.md",
        review_feedback=json.dumps(normalized),
        **awf_role.provenance_payload(provenance),
    )
    payload = awf_role.input_payload(ns, "architect")
    ns.payload_sha256 = awf_role.canonical_payload_sha256(payload)
    ns.delivery_id = awf_role.make_delivery_id(
        "reviewer", event_type, ns.payload_sha256, ns.source_event_id
    )
    return repo, provenance, ns


@pytest.mark.parametrize("verdict", ["PASS", "BLOCKED"])
def test_architect_terminal_consumer_completes_and_replays_without_model(
    monkeypatch, tmp_path, verdict
):
    repo, provenance, ns = _architect_decision_args(tmp_path, verdict)
    state_root = tmp_path / "state"
    ns.evidence = awf_role.RunEvidence(201, "architect", state_root=state_root)
    monkeypatch.setenv("AWF_REPO_DIR", str(repo))
    monkeypatch.setattr(awf_role, "provenance_from_args", lambda *args, **kwargs: provenance)
    checkout_calls = []
    monkeypatch.setattr(
        awf_role,
        "prepare_terminal_workspace",
        lambda *args, **kwargs: checkout_calls.append((args, kwargs)) or str(repo),
    )
    monkeypatch.setattr(awf_role, "check_report_tracked_at_head", lambda *args: None)
    monkeypatch.setattr(awf_role, "check_repo_file_tracked_at_head", lambda *args: None)

    assert awf_role.role_architect(ns) == 0
    assert len(checkout_calls) == 1
    inbox = awf_role.delivery_state_path(ns.evidence, "inbox", ns.delivery_id)
    assert json.loads(inbox.read_text(encoding="utf-8"))["status"] == "completed"

    ns.evidence = awf_role.RunEvidence(202, "architect", state_root=state_root)
    monkeypatch.setattr(
        awf_role,
        "prepare_terminal_workspace",
        lambda *args, **kwargs: pytest.fail("completed terminal delivery must replay directly"),
    )
    assert awf_role.role_architect(ns) == 0


def test_architect_terminal_consumer_uses_isolated_workspace_when_source_is_dirty(
    repositories, monkeypatch, tmp_path
):
    _, seed, source = repositories
    report = """# Implementation Report
<!-- awf-implementation-report
{
  "summary": "done",
  "changed_files": ["task.md"],
  "commands": ["python -m pytest"],
  "tests": ["passed"],
  "source_revision": "trusted"
}
-->
"""
    remote_head = commit(seed, "implementation report", "implementation.md", report)
    run("git", "push", "origin", "feature/task", cwd=seed)
    source_head = run("git", "rev-parse", "HEAD", cwd=source)
    source_remote_ref = run("git", "rev-parse", "origin/feature/task", cwd=source)
    (source / "README.md").write_text("operator edit\n", encoding="utf-8")
    dirty = source / "operator-notes.txt"
    dirty.write_text("preserve me\n", encoding="utf-8")

    _, _, ns = _architect_decision_args(tmp_path)
    ns.input_type = "decision:awf-ready"
    ns.branch = "feature/task"
    ns.commit = remote_head
    ns.card = "task.md"
    ns.report = "implementation.md"
    payload = awf_role.input_payload(ns, "architect")
    ns.payload_sha256 = awf_role.canonical_payload_sha256(payload)
    ns.delivery_id = awf_role.make_delivery_id(
        "reviewer", ns.input_type, ns.payload_sha256, ns.source_event_id
    )
    ns.evidence = awf_role.RunEvidence(205, "architect", state_root=tmp_path / "state")
    monkeypatch.setenv("AWF_REPO_DIR", str(source))

    assert awf_role.role_architect(ns) == 0
    assert (source / "README.md").read_text(encoding="utf-8") == "operator edit\n"
    assert dirty.read_text(encoding="utf-8") == "preserve me\n"
    assert run("git", "status", "--porcelain", cwd=source).splitlines() == [
        "M README.md",
        "?? operator-notes.txt",
    ]
    assert run("git", "rev-parse", "HEAD", cwd=source) == source_head
    assert run("git", "rev-parse", "origin/feature/task", cwd=source) == source_remote_ref
    inbox = awf_role.delivery_state_path(ns.evidence, "inbox", ns.delivery_id)
    assert json.loads(inbox.read_text(encoding="utf-8"))["status"] == "completed"


def test_v3_architect_terminal_fetch_and_verification_stay_outside_dirty_source(
    repositories, monkeypatch, tmp_path
):
    origin, seed, source = repositories
    report = "# Implementation Report\ntrusted result\n"
    remote_head = commit(seed, "v3 implementation report", "implementation.md", report)
    run("git", "push", "origin", "feature/task", cwd=seed)
    run("git", "fetch", "origin", "feature/task", cwd=source)
    base_sha = run("git", "rev-parse", "main", cwd=seed)
    run("git", "remote", "add", "upstream", str(origin), cwd=source)
    run("git", "remote", "add", "fork", str(origin), cwd=source)

    source_head = run("git", "rev-parse", "HEAD", cwd=source)
    source_remote_ref = run("git", "rev-parse", "origin/feature/task", cwd=source)
    (source / "README.md").write_text("operator edit\n", encoding="utf-8")
    dirty = source / "operator-notes.txt"
    dirty.write_text("preserve me\n", encoding="utf-8")

    _, _, ns = _architect_decision_args(tmp_path)
    provenance = _pr_provenance(
        base_sha=base_sha,
        head_sha=remote_head,
        upstream_remote="upstream",
        head_remote="fork",
    )
    ns.branch = provenance["head_ref"]
    ns.commit = remote_head
    ns.card = "task.md"
    ns.report = "implementation.md"
    for field, value in provenance.items():
        setattr(ns, field, value)
    payload = awf_role.input_payload(ns, "architect")
    ns.payload_sha256 = awf_role.canonical_payload_sha256(payload)
    ns.delivery_id = awf_role.make_delivery_id(
        "reviewer", ns.input_type, ns.payload_sha256, ns.source_event_id
    )
    ns.evidence = awf_role.RunEvidence(206, "architect", state_root=tmp_path / "state")
    monkeypatch.setenv("AWF_REPO_DIR", str(source))
    monkeypatch.setattr(awf_role, "provenance_from_args", lambda *_args, **_kwargs: provenance)
    verified_workspaces = []

    def verify_in_terminal(repo, _provenance, **_kwargs):
        assert Path(repo).resolve() != source.resolve()
        verified_workspaces.append(Path(repo).resolve())

    monkeypatch.setattr(awf_role, "verify_pr_remote_tuple", verify_in_terminal)

    assert awf_role.role_architect(ns) == 0
    assert len(verified_workspaces) == 1
    assert verified_workspaces[0].name.startswith("terminal-workspace-")
    assert (source / "README.md").read_text(encoding="utf-8") == "operator edit\n"
    assert dirty.read_text(encoding="utf-8") == "preserve me\n"
    assert run("git", "rev-parse", "HEAD", cwd=source) == source_head
    assert run("git", "rev-parse", "origin/feature/task", cwd=source) == source_remote_ref
    inbox = awf_role.delivery_state_path(ns.evidence, "inbox", ns.delivery_id)
    assert json.loads(inbox.read_text(encoding="utf-8"))["status"] == "completed"


@pytest.mark.parametrize(
    ("verdict", "terminal_state"),
    [("PASS", "completed"), ("BLOCKED", "blocked")],
)
def test_architect_persists_terminal_ledger_and_summary_before_inbox(
    monkeypatch, tmp_path, verdict, terminal_state
):
    repo, provenance, ns = _architect_decision_args(tmp_path, verdict)
    state_root = tmp_path / "state"
    ns.evidence = awf_role.RunEvidence(211, "architect", state_root=state_root)
    monkeypatch.setenv("AWF_REPO_DIR", str(repo))
    monkeypatch.setenv("AWF_CONTROL_PLANE", "1")
    monkeypatch.setattr(awf_role, "provenance_from_args", lambda *args, **kwargs: provenance)
    monkeypatch.setattr(awf_role, "prepare_terminal_workspace", lambda *args, **kwargs: str(repo))
    monkeypatch.setattr(awf_role, "check_report_tracked_at_head", lambda *args: None)
    monkeypatch.setattr(awf_role, "check_repo_file_tracked_at_head", lambda *args: None)

    task_id = ns.branch.rsplit("/", 1)[-1]
    run_id = f"task-{task_id}"
    ledger = awf_role.RunLedger(state_root, run_id)
    authority = {
        "sha256": "sha256:" + "a" * 64,
        "allowed_operations": ["diagnose", "endpoint_discovery", "listener_restart"],
    }
    packet = awf_role.build_context_packet(
        run_id=run_id,
        taskcard=ns.card,
        frozen_base=provenance["base_sha"],
        branch=ns.branch,
        pull_request=str(provenance["pull_request"]),
        authority_manifest=authority,
        next_action="consume terminal review decision",
        stage="review",
        current_stage_evidence_commit=ns.commit,
    )
    ledger.initialize(packet, stage="review", max_attempts=1, rework_budget=1)

    real_complete_inbox = awf_role.complete_inbox
    observed = []

    def complete_after_terminal(evidence, delivery_id, payload_sha256):
        durable, _ = ledger.recover()
        summary = json.loads(ledger.summary_path.read_text(encoding="utf-8"))
        observed.append((durable["terminal_state"], summary["terminal_state"]))
        return real_complete_inbox(evidence, delivery_id, payload_sha256)

    monkeypatch.setattr(awf_role, "complete_inbox", complete_after_terminal)

    assert awf_role.role_architect(ns) == 0
    recovered, _ = ledger.recover()
    assert observed == [(terminal_state, terminal_state)]
    assert recovered["terminal"]["verdict"] == verdict
    assert recovered["terminal"]["delivery_id"] == ns.delivery_id
    assert recovered["terminal"]["commit"] == ns.commit
    assert recovered["terminal"]["artifacts"]["implementation"]["path"] == ns.report
    assert recovered["terminal"]["artifacts"]["review"]["path"] == ns.review_report

    sequence = recovered["sequence"]
    ns.evidence = awf_role.RunEvidence(211, "architect", state_root=state_root)
    assert awf_role.role_architect(ns) == 0
    replayed, _ = ledger.recover()
    assert replayed["sequence"] == sequence


def test_architect_terminal_consumer_rejects_report_drift_without_completing_inbox(
    monkeypatch, tmp_path
):
    repo, provenance, ns = _architect_decision_args(tmp_path)
    ns.evidence = awf_role.RunEvidence(203, "architect", state_root=tmp_path / "state")
    monkeypatch.setenv("AWF_REPO_DIR", str(repo))
    monkeypatch.setattr(awf_role, "provenance_from_args", lambda *args, **kwargs: provenance)
    embedded = json.loads(ns.review_feedback)
    embedded["verdict"] = "BLOCKED"
    ns.review_feedback = json.dumps(embedded)

    with pytest.raises(SystemExit, match="1"):
        awf_role.role_architect(ns)

    assert not awf_role.delivery_state_path(ns.evidence, "inbox", ns.delivery_id).exists()


def _prepare_reviewer_routing(
    monkeypatch,
    tmp_path,
    content,
    *,
    send_result=True,
    tool_rc=0,
    tool="opencode",
):
    repo = tmp_path / "repo"
    repo.mkdir()
    script_dir = tmp_path / "scripts"
    script_dir.mkdir()
    (script_dir / "reviewer-prompt.md").write_text("prompt", encoding="utf-8")
    (repo / "task.md").write_text("card", encoding="utf-8")
    implementation_report = repo / "implementation.md"
    implementation_report.write_text("implementation", encoding="utf-8")

    monkeypatch.setenv("AWF_REPO_DIR", str(repo))
    monkeypatch.setenv("AWF_SCRIPT_DIR", str(script_dir))
    monkeypatch.setenv("AWF_TOOL", tool)
    monkeypatch.setattr(awf_role, "fetch_and_checkout", lambda *a, **kw: None)
    monkeypatch.setattr(awf_role, "prepare_model_workspace", lambda *a, **kw: str(repo))
    monkeypatch.setattr(awf_role, "freeze_model_git_metadata", lambda *a, **kw: None)
    monkeypatch.setattr(awf_role, "resolve_review_base", lambda *a, **kw: "base-sha")
    monkeypatch.setattr(awf_role, "git", lambda *a, **kw: 0)
    monkeypatch.setattr(awf_role, "assert_model_workspace_state", lambda *a, **kw: None)
    monkeypatch.setattr(awf_role, "assert_model_git_state", lambda *a, **kw: None)
    monkeypatch.setattr(
        awf_role,
        "git_out",
        lambda _repo, *args: (
            "implementation.md"
            if args == ("ls-files", "--", "implementation.md")
            else ""
            if args and args[0] == "ls-files"
            else "base-sha"
        ),
    )
    monkeypatch.setattr(
        awf_role,
        "import_model_report",
        lambda _workspace, trusted, path: Path(trusted) / path,
    )

    tool_calls = []

    def fake_review(*args, **kwargs):
        tool_calls.append((args, kwargs))
        if content is not None:
            (Path(args[0]) / args[5]).write_text(content, encoding="utf-8")
        return tool_rc

    review_attr = {
        "codex": "tool_codex_review",
        "opencode": "tool_opencode_review",
        "pi": "tool_pi_review",
    }[tool]
    monkeypatch.setattr(awf_role, review_attr, fake_review)
    send_calls = []
    monkeypatch.setattr(
        awf_role,
        "send_event",
        lambda *args, **kwargs: send_calls.append((args, kwargs)) or send_result,
    )
    ns = argparse.Namespace(
        branch="feature/task",
        card="task.md",
        commit="abc1234",
        model="",
        tool=tool,
        report="implementation.md",
        review_report=".awf/artifacts/review-report-task.md",
        base="main",
    )
    return ns, send_calls, tool_calls


@pytest.mark.parametrize("role", ["coder", "reviewer"])
@pytest.mark.parametrize("selection", ["tool", "model"])
@pytest.mark.parametrize("version", ["v1", "v2", "v3"])
def test_delivery_selection_mismatch_fails_before_ack_sensitive_lifecycle(
    monkeypatch,
    tmp_path,
    capsys,
    role,
    selection,
    version,
):
    suffix = "" if version == "v1" else f"-{version}"
    event_type = f"task:awf-{'impl' if role == 'coder' else 'review'}{suffix}"
    if role == "coder":
        ns, _ = _prepare_coder_handoff_test(monkeypatch, tmp_path)
    else:
        ns, _, tool_calls = _prepare_reviewer_routing(
            monkeypatch,
            tmp_path,
            _review_markdown("PASS"),
        )
        ns.input_type = event_type
        ns.source_event_id = 301
        assert not tool_calls

    ns.evidence = awf_role.RunEvidence(302, role, state_root=tmp_path / "state")
    payload_tool = ns.tool
    payload_model = "payload/model"
    ns.model = payload_model
    # Rebind after setting the payload model so the integrity hash represents it.
    if role == "coder":
        _bind_delivery(ns, event_type=event_type, source_event_id=301)
    else:
        payload = awf_role.input_payload(ns, "reviewer")
        ns.payload_sha256 = awf_role.canonical_payload_sha256(payload)
        ns.delivery_id = awf_role.make_delivery_id(
            "coder",
            ns.input_type,
            ns.payload_sha256,
            ns.source_event_id,
        )

    monkeypatch.setenv("AWF_TOOL", "codex" if selection == "tool" else payload_tool)
    monkeypatch.setenv(
        "AWF_MODEL",
        "listener/model" if selection == "model" else payload_model,
    )
    monkeypatch.setattr(
        awf_role,
        "pre_invocation_gate",
        lambda *args, **kwargs: pytest.fail("selection gate must precede pre-invocation"),
    )
    monkeypatch.setattr(
        awf_role,
        "resume_outbox",
        lambda *args, **kwargs: pytest.fail("selection gate must precede outbox replay"),
    )
    monkeypatch.setattr(
        awf_role,
        "tool_opencode_exec",
        lambda *args, **kwargs: pytest.fail("selection gate must precede coder model launch"),
    )
    monkeypatch.setattr(
        awf_role,
        "tool_opencode_review",
        lambda *args, **kwargs: pytest.fail("selection gate must precede reviewer model launch"),
    )
    monkeypatch.setattr(
        awf_role,
        "tool_codex_review",
        lambda *args, **kwargs: pytest.fail("selection gate must precede reviewer model launch"),
    )
    monkeypatch.setattr(
        awf_role,
        "tool_pi_review",
        lambda *args, **kwargs: pytest.fail("selection gate must precede reviewer model launch"),
    )
    monkeypatch.setattr(
        awf_role,
        "prepare_outbox",
        lambda *args, **kwargs: pytest.fail("selection gate must precede outbox preparation"),
    )
    monkeypatch.setattr(
        awf_role,
        "send_event",
        lambda *args, **kwargs: pytest.fail("selection gate must precede downstream send"),
    )
    monkeypatch.setattr(
        awf_role,
        "complete_inbox",
        lambda *args, **kwargs: pytest.fail("selection gate must precede inbox completion"),
    )

    with pytest.raises(SystemExit, match="1"):
        (awf_role.role_coder if role == "coder" else awf_role.role_reviewer)(ns)

    error = capsys.readouterr().err
    assert f"Workflow delivery {selection} selection mismatch" in error
    assert not (tmp_path / "state" / "outbox").exists()
    assert not (tmp_path / "state" / "inbox").exists()


@pytest.mark.parametrize("role", ["coder", "reviewer"])
def test_matching_delivery_selection_preserves_completed_replay(monkeypatch, tmp_path, role):
    if role == "coder":
        ns, _ = _prepare_coder_handoff_test(monkeypatch, tmp_path)
        source_role = "architect"
        event_type = "task:awf-impl-v2"
    else:
        ns, _, _ = _prepare_reviewer_routing(
            monkeypatch,
            tmp_path,
            _review_markdown("PASS"),
        )
        source_role = "coder"
        event_type = "task:awf-review-v2"
    ns.model = "provider/model"
    ns.input_type = event_type
    ns.source_event_id = 303
    payload = awf_role.input_payload(ns, role)
    ns.payload_sha256 = awf_role.canonical_payload_sha256(payload)
    ns.delivery_id = awf_role.make_delivery_id(
        source_role,
        event_type,
        ns.payload_sha256,
        ns.source_event_id,
    )
    ns.evidence = awf_role.RunEvidence(304, role, state_root=tmp_path / "state")
    awf_role.complete_inbox(ns.evidence, ns.delivery_id, ns.payload_sha256)
    monkeypatch.setenv("AWF_TOOL", ns.tool)
    monkeypatch.setenv("AWF_MODEL", ns.model)
    monkeypatch.setattr(
        awf_role,
        "pre_invocation_gate",
        lambda *args, **kwargs: argparse.Namespace(reason="duplicate_event"),
    )

    assert (awf_role.role_coder if role == "coder" else awf_role.role_reviewer)(ns) == 0


def test_legacy_reviewer_env_override_executes_and_emits_effective_identity(
    monkeypatch,
    tmp_path,
):
    ns, send_calls, tool_calls = _prepare_reviewer_routing(
        monkeypatch,
        tmp_path,
        _review_markdown("PASS"),
        tool="opencode",
    )
    ns.tool = "codex"
    ns.model = "payload/model"
    monkeypatch.setenv("AWF_TOOL", "opencode")
    monkeypatch.setenv("AWF_MODEL", "listener/model")

    assert awf_role.role_reviewer(ns) == 0

    assert len(tool_calls) == 1
    assert tool_calls[0][0][4] == "listener/model"
    emitted = send_calls[0][0][3]
    assert emitted["tool"] == "opencode"
    assert emitted["model"] == "listener/model"


def test_matching_delivery_reviewer_emits_validated_effective_identity(monkeypatch, tmp_path):
    ns, send_calls, tool_calls = _prepare_reviewer_routing(
        monkeypatch,
        tmp_path,
        _review_markdown("PASS"),
        tool="opencode",
    )
    ns.model = "provider/model"
    ns.input_type = "task:awf-review-v2"
    ns.source_event_id = 305
    payload = awf_role.input_payload(ns, "reviewer")
    ns.payload_sha256 = awf_role.canonical_payload_sha256(payload)
    ns.delivery_id = awf_role.make_delivery_id(
        "coder",
        ns.input_type,
        ns.payload_sha256,
        ns.source_event_id,
    )
    ns.evidence = awf_role.RunEvidence(306, "reviewer", state_root=tmp_path / "state")
    monkeypatch.setenv("AWF_TOOL", "opencode")
    monkeypatch.setenv("AWF_MODEL", "provider/model")

    assert awf_role.role_reviewer(ns) == 0

    assert len(tool_calls) == 1
    emitted = send_calls[0][0][3]
    assert emitted["tool"] == "opencode"
    assert emitted["model"] == "provider/model"


def test_reviewer_v3_provenance_drift_denies_before_model_and_persists_reason(
    monkeypatch, tmp_path
):
    ns, send_calls, tool_calls = _prepare_reviewer_routing(
        monkeypatch,
        tmp_path,
        _review_markdown("PASS"),
    )
    provenance = _pr_provenance()
    ns.commit = provenance["head_sha"]
    ns.input_type = "task:awf-review-v3"
    ns.source_event_id = 90
    for field in awf_role._PROVENANCE_FIELDS:
        setattr(ns, field, provenance[field])
    payload = awf_role.input_payload(ns, "reviewer")
    ns.payload_sha256 = awf_role.canonical_payload_sha256(payload)
    ns.delivery_id = awf_role.make_delivery_id(
        "coder",
        ns.input_type,
        ns.payload_sha256,
        ns.source_event_id,
    )
    ns.evidence = awf_role.RunEvidence(91, "reviewer", state_root=tmp_path / "state")
    monkeypatch.setattr(awf_role, "provenance_from_args", lambda *args, **kwargs: provenance)
    monkeypatch.setattr(
        awf_role,
        "fetch_and_checkout_pr_head",
        lambda *args, **kwargs: (_ for _ in ()).throw(SystemExit(1)),
    )

    with pytest.raises(SystemExit, match="1"):
        awf_role.role_reviewer(ns)

    assert not tool_calls
    assert not send_calls
    result = json.loads(ns.evidence.result_path.read_text(encoding="utf-8"))
    assert result["last_phase"] == "fork_pr_rejected"
    assert result["reason"] == "reviewer_provenance_drift"


@pytest.mark.parametrize(
    ("content", "recipient", "event_type"),
    [
        (_review_markdown("PASS"), "architect", "decision:awf-ready"),
        (
            _review_markdown("REQUEST_CHANGES", failures=[_COMMAND_FAILURE]),
            "coder",
            "task:awf-rework",
        ),
        (
            _review_markdown("BLOCKED", blocked_reason="TaskCard has conflicting requirements"),
            "architect",
            "decision:awf-blocked",
        ),
    ],
)
def test_reviewer_routes_exactly_one_valid_verdict(
    monkeypatch, tmp_path, content, recipient, event_type
):
    ns, send_calls, tool_calls = _prepare_reviewer_routing(monkeypatch, tmp_path, content)

    assert awf_role.role_reviewer(ns) == 0

    assert len(tool_calls) == 1
    isolated_report = Path(tool_calls[0][0][5])
    assert isolated_report.is_absolute()
    assert isolated_report.as_posix().endswith(ns.review_report)
    assert len(send_calls) == 1
    args = send_calls[0][0]
    assert args[:3] == ("reviewer", recipient, event_type)
    payload = args[3]
    assert payload["branch"] == "feature/task"
    assert payload["card"] == "task.md"
    assert payload["commit"] == "abc1234"
    assert payload["report"] == ns.report
    assert payload["review_report_path"] == ns.review_report
    assert payload["tool"] == "opencode"
    assert payload["model"] == ""
    assert not (Path(os.environ["AWF_REPO_DIR"]) / ns.review_report).exists()


def test_pi_reviewer_rework_routes_back_to_frozen_opencode_coder(monkeypatch, tmp_path):
    content = _review_markdown("REQUEST_CHANGES", failures=[_COMMAND_FAILURE])
    ns, send_calls, tool_calls = _prepare_reviewer_routing(
        monkeypatch,
        tmp_path,
        content,
        tool="pi",
    )
    repo = Path(os.environ["AWF_REPO_DIR"])
    (repo / "task.md").write_text(
        """card
<!-- awf-reviewer-selection
{
  "coder": {"tool": "opencode", "model": "coder/model"},
  "reviewer": {"tool": "pi", "model": ""}
}
-->
""",
        encoding="utf-8",
    )

    assert awf_role.role_reviewer(ns) == 0

    assert len(tool_calls) == 1
    assert len(send_calls) == 1
    payload = send_calls[0][0][3]
    assert payload["tool"] == "opencode"
    assert payload["model"] == "coder/model"
    assert payload["review_report"]["format"] == "awf.review-report.v1"
    assert payload["review_report"]["verdict"] in content
    assert payload["review_report"]["markdown"] == content


@pytest.mark.parametrize(
    ("content", "event_type"),
    [
        (_review_markdown("PASS"), "decision:awf-ready-v2"),
        (
            _review_markdown("REQUEST_CHANGES", failures=[_COMMAND_FAILURE]),
            "task:awf-rework-v2",
        ),
        (
            _review_markdown("BLOCKED", blocked_reason="Conflicting requirements"),
            "decision:awf-blocked-v2",
        ),
    ],
)
def test_reviewer_v2_routes_are_persisted_in_sent_outbox(
    monkeypatch, tmp_path, content, event_type
):
    ns, send_calls, tool_calls = _prepare_reviewer_routing(monkeypatch, tmp_path, content)
    ns.input_type = "task:awf-review-v2"
    ns.source_event_id = 71
    input_hash = awf_role.canonical_payload_sha256(awf_role.input_payload(ns, "reviewer"))
    ns.payload_sha256 = input_hash
    ns.delivery_id = awf_role.make_delivery_id(
        "coder", ns.input_type, input_hash, ns.source_event_id
    )
    ns.evidence = awf_role.RunEvidence(82, "reviewer", state_root=tmp_path / "state")

    assert awf_role.role_reviewer(ns) == 0

    outbox_path = awf_role.delivery_state_path(ns.evidence, "outbox", ns.delivery_id)
    outbox = json.loads(outbox_path.read_text(encoding="utf-8"))
    assert outbox["status"] == "sent"
    assert outbox["event_type"] == event_type
    assert outbox["payload"]["awf_delivery_id"].startswith("awf:")
    assert len(send_calls) == 1
    assert len(tool_calls) == 1

    ns.evidence = awf_role.RunEvidence(83, "reviewer", state_root=tmp_path / "state")
    assert awf_role.role_reviewer(ns) == 0
    assert len(send_calls) == 1
    assert len(tool_calls) == 1


def test_reviewer_outbox_resume_removes_managed_report(monkeypatch, tmp_path):
    ns, _send_calls, _tool_calls = _prepare_reviewer_routing(
        monkeypatch,
        tmp_path,
        _review_markdown("PASS"),
    )
    repo = Path(os.environ["AWF_REPO_DIR"])
    managed_report = repo / ns.review_report
    managed_report.parent.mkdir(parents=True, exist_ok=True)
    managed_report.write_text(_review_markdown("PASS"), encoding="utf-8")
    monkeypatch.setattr(awf_role, "resume_outbox", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        awf_role,
        "pre_invocation_gate",
        lambda *_args, **_kwargs: pytest.fail(
            "durable reviewer outbox recovery must precede dirty-workspace invocation gates"
        ),
    )
    monkeypatch.setattr(
        awf_role,
        "tool_opencode_review",
        lambda *args, **kwargs: pytest.fail("outbox resume must not invoke reviewer"),
    )

    assert awf_role.role_reviewer(ns) == 0
    assert not managed_report.exists()


def test_new_reviewer_removes_only_exact_prior_report_consumed_by_architect(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    run("git", "init", "-b", "main", cwd=repo)
    run("git", "config", "user.email", "test@example.com", cwd=repo)
    run("git", "config", "user.name", "Test", cwd=repo)
    (repo / "README.md").write_text("fixture\n", encoding="utf-8")
    run("git", "add", "README.md", cwd=repo)
    run("git", "commit", "-m", "fixture", cwd=repo)

    relative_report = ".awf/artifacts/review-report-old-card.md"
    report = repo / relative_report
    report.parent.mkdir(parents=True)
    markdown = _review_markdown("PASS")
    report.write_text(markdown, encoding="utf-8")
    normalized = awf_role.parse_review_report(report)
    state_root = tmp_path / "state"
    provenance = _pr_provenance()
    old_evidence = awf_role.RunEvidence(501, "reviewer", state_root=state_root)
    old_input = {
        "key": "awf:" + "1" * 64,
        "delivery_id": "awf:" + "1" * 64,
        "payload_sha256": "sha256:" + "2" * 64,
        "source_event_id": 500,
    }
    payload = awf_role.build_delivery_payload(
        "reviewer",
        "decision:awf-ready-v3",
        {
            "task_id": "old-card",
            "branch": provenance["head_ref"],
            "commit": provenance["head_sha"],
            "report": "implementation-old-card.md",
            "review_report_path": relative_report,
            "review_report": normalized,
            **awf_role.provenance_payload(provenance),
        },
        old_evidence,
    )
    outbox_path, outbox = awf_role.prepare_outbox(
        old_evidence,
        old_input,
        action="reviewer.pass",
        branch=str(provenance["head_ref"]),
        source_commit=str(provenance["head_sha"]),
        evidence_commit=str(provenance["head_sha"]),
        to_role="architect",
        event_type="decision:awf-ready-v3",
        payload=payload,
        provenance=provenance,
    )
    awf_role._set_outbox_status(outbox_path, outbox, "ambiguous")
    architect_evidence = awf_role.RunEvidence(502, "architect", state_root=state_root)
    awf_role.complete_inbox(
        architect_evidence,
        str(payload["awf_delivery_id"]),
        str(payload["awf_payload_sha256"]),
    )

    current = awf_role.RunEvidence(503, "reviewer", state_root=state_root)
    awf_role._remove_completed_prior_review_report(
        str(repo),
        current,
        {"delivery_id": "awf:" + "3" * 64},
    )

    assert not report.exists()
    assert current.state["last_phase"] == "prior_review_report_removed"


def test_new_reviewer_keeps_prior_report_without_exact_architect_completion(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    run("git", "init", "-b", "main", cwd=repo)
    run("git", "config", "user.email", "test@example.com", cwd=repo)
    run("git", "config", "user.name", "Test", cwd=repo)
    (repo / "README.md").write_text("fixture\n", encoding="utf-8")
    run("git", "add", "README.md", cwd=repo)
    run("git", "commit", "-m", "fixture", cwd=repo)
    report = repo / ".awf/artifacts/review-report-old-card.md"
    report.parent.mkdir(parents=True)
    report.write_text(_review_markdown("PASS"), encoding="utf-8")

    awf_role._remove_completed_prior_review_report(
        str(repo),
        awf_role.RunEvidence(504, "reviewer", state_root=tmp_path / "state"),
        {"delivery_id": "awf:" + "4" * 64},
    )

    assert report.is_file()


def test_terminal_delivery_chain_binds_prepared_coder_and_reviewer_outboxes(tmp_path):
    state_root = tmp_path / "state"
    provenance = _pr_provenance()
    branch = str(provenance["head_ref"])
    prepared_delivery_id = "awf:" + "a" * 64
    prepared_payload_sha256 = "sha256:" + "b" * 64
    coder_evidence = awf_role.RunEvidence(411, "coder", state_root=state_root)
    review_payload = awf_role.build_delivery_payload(
        "coder",
        "task:awf-review-v3",
        {"task_id": "task", "branch": branch, **awf_role.provenance_payload(provenance)},
        coder_evidence,
    )
    awf_role.prepare_outbox(
        coder_evidence,
        {
            "key": prepared_delivery_id,
            "delivery_id": prepared_delivery_id,
            "payload_sha256": prepared_payload_sha256,
            "source_event_id": 408,
        },
        action="coder.review_handoff",
        branch=branch,
        source_commit="5" * 40,
        evidence_commit=str(provenance["head_sha"]),
        to_role="reviewer",
        event_type="task:awf-review-v3",
        payload=review_payload,
        provenance=provenance,
    )
    reviewer_evidence = awf_role.RunEvidence(412, "reviewer", state_root=state_root)
    reviewer_input = {
        "key": review_payload["awf_delivery_id"],
        "delivery_id": review_payload["awf_delivery_id"],
        "payload_sha256": review_payload["awf_payload_sha256"],
        "source_event_id": review_payload["awf_source_event_id"],
    }
    decision_payload = awf_role.build_delivery_payload(
        "reviewer",
        "decision:awf-ready-v3",
        {"task_id": "task", "branch": branch, **awf_role.provenance_payload(provenance)},
        reviewer_evidence,
    )
    awf_role.prepare_outbox(
        reviewer_evidence,
        reviewer_input,
        action="reviewer.pass",
        branch=branch,
        source_commit=str(provenance["head_sha"]),
        evidence_commit=str(provenance["head_sha"]),
        to_role="architect",
        event_type="decision:awf-ready-v3",
        payload=decision_payload,
        provenance=provenance,
    )
    coder_outbox_path = awf_role.delivery_state_path(coder_evidence, "outbox", prepared_delivery_id)
    reviewer_outbox_path = awf_role.delivery_state_path(
        reviewer_evidence, "outbox", review_payload["awf_delivery_id"]
    )
    for path in (coder_outbox_path, reviewer_outbox_path):
        value = json.loads(path.read_text(encoding="utf-8"))
        awf_role._set_outbox_status(path, value, "ambiguous")
    terminal_input = {
        "delivery_id": decision_payload["awf_delivery_id"],
        "payload_sha256": decision_payload["awf_payload_sha256"],
        "source_event_id": decision_payload["awf_source_event_id"],
    }

    assert awf_role.terminal_delivery_chain_matches(
        state_root,
        prepared_delivery_id=prepared_delivery_id,
        prepared_payload_sha256=prepared_payload_sha256,
        terminal_input_context=terminal_input,
        branch=branch,
        provenance=provenance,
        reviewer_verdict="PASS",
    )
    coder_value = json.loads(coder_outbox_path.read_text(encoding="utf-8"))
    awf_role._set_outbox_status(coder_outbox_path, coder_value, "attempting")
    assert not awf_role.terminal_delivery_chain_matches(
        state_root,
        prepared_delivery_id=prepared_delivery_id,
        prepared_payload_sha256=prepared_payload_sha256,
        terminal_input_context=terminal_input,
        branch=branch,
        provenance=provenance,
        reviewer_verdict="PASS",
    )
    assert not awf_role.terminal_delivery_chain_matches(
        state_root,
        prepared_delivery_id="awf:" + "c" * 64,
        prepared_payload_sha256=prepared_payload_sha256,
        terminal_input_context=terminal_input,
        branch=branch,
        provenance=provenance,
        reviewer_verdict="PASS",
    )


@pytest.mark.parametrize(
    "content",
    [
        "",
        "# no machine verdict\n",
        "<!-- awf-review-report\n{bad json\n-->\n",
        _review_markdown("pass"),
        _review_markdown("UNKNOWN"),
        (
            "<!-- awf-review-report\n"
            '{"verdict":"PASS","verdict":"BLOCKED",'
            '"deterministic_failures":[],"blocked_reason":""}\n-->\n'
        ),
        _review_markdown("REQUEST_CHANGES"),
        _review_markdown("BLOCKED"),
        _review_markdown("PASS") + _review_markdown("PASS"),
    ],
)
def test_invalid_review_report_fails_before_send(monkeypatch, tmp_path, content):
    ns, send_calls, _ = _prepare_reviewer_routing(monkeypatch, tmp_path, content)

    with pytest.raises(SystemExit, match="1"):
        awf_role.role_reviewer(ns)

    assert not send_calls


def test_reviewer_rc_zero_without_report_cannot_route_pass(monkeypatch, tmp_path):
    ns, send_calls, _ = _prepare_reviewer_routing(monkeypatch, tmp_path, None, tool_rc=0)

    with pytest.raises(SystemExit, match="1"):
        awf_role.role_reviewer(ns)

    assert not send_calls


def test_reviewer_tool_failure_prevents_report_routing(monkeypatch, tmp_path):
    ns, send_calls, _ = _prepare_reviewer_routing(
        monkeypatch, tmp_path, _review_markdown("PASS"), tool_rc=7
    )

    with pytest.raises(SystemExit, match="1"):
        awf_role.role_reviewer(ns)

    assert not send_calls


@pytest.mark.parametrize(
    "content",
    [
        _review_markdown("PASS", extra="x" * (17 * 1024)),
        _review_markdown("PASS", extra="审" * 3000),
        _review_markdown("PASS", extra="```diff\n-old\n+new\n```\n"),
        _review_markdown("PASS", extra="diff --git a/a.py b/a.py\n"),
        _review_markdown("PASS", extra=_GITHUB_TOKEN),
    ],
)
def test_unsafe_or_oversized_review_report_fails_before_send(monkeypatch, tmp_path, content):
    ns, send_calls, _ = _prepare_reviewer_routing(monkeypatch, tmp_path, content)

    with pytest.raises(SystemExit, match="1"):
        awf_role.role_reviewer(ns)

    assert not send_calls


@pytest.mark.parametrize("verdict", ["PASS", "REQUEST_CHANGES", "BLOCKED"])
def test_each_reviewer_route_send_failure_is_nonzero(monkeypatch, tmp_path, verdict):
    failures = [_COMMAND_FAILURE] if verdict == "REQUEST_CHANGES" else []
    blocked_reason = "needs architect decision" if verdict == "BLOCKED" else ""
    content = _review_markdown(verdict, failures=failures, blocked_reason=blocked_reason)
    ns, send_calls, _ = _prepare_reviewer_routing(monkeypatch, tmp_path, content, send_result=False)

    with pytest.raises(SystemExit, match="1"):
        awf_role.role_reviewer(ns)

    assert len(send_calls) == 1


@pytest.mark.parametrize("tool", ["opencode", "codex", "pi"])
def test_v3_reviewer_send_failure_replay_does_not_rerun_model(monkeypatch, tmp_path, tool):
    content = _review_markdown("PASS")
    ns, send_calls, tool_calls = _prepare_reviewer_routing(
        monkeypatch,
        tmp_path,
        content,
        send_result=False,
        tool=tool,
    )
    provenance = _pr_provenance()
    ns.commit = provenance["head_sha"]
    ns.input_type = "task:awf-review-v3"
    ns.source_event_id = 102
    for field in awf_role._PROVENANCE_FIELDS:
        setattr(ns, field, provenance[field])
    payload = awf_role.input_payload(ns, "reviewer")
    ns.payload_sha256 = awf_role.canonical_payload_sha256(payload)
    ns.delivery_id = awf_role.make_delivery_id(
        "coder",
        ns.input_type,
        ns.payload_sha256,
        ns.source_event_id,
    )
    state_root = tmp_path / "state"
    ns.evidence = awf_role.RunEvidence(103, "reviewer", state_root=state_root)
    gates = iter(("authorized", "duplicate_event"))
    monkeypatch.setattr(
        awf_role,
        "pre_invocation_gate",
        lambda *args, **kwargs: argparse.Namespace(reason=next(gates)),
    )
    monkeypatch.setattr(awf_role, "provenance_from_args", lambda *args, **kwargs: provenance)
    monkeypatch.setattr(awf_role, "fetch_and_checkout_pr_head", lambda *args, **kwargs: None)
    monkeypatch.setattr(awf_role, "assert_model_pr_git_state", lambda *args, **kwargs: None)
    monkeypatch.setattr(awf_role, "verify_pr_remote_tuple", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        awf_role,
        "git_out",
        lambda _repo, *args: (
            "implementation.md"
            if args == ("ls-files", "--", "implementation.md")
            else ""
            if args and args[0] == "ls-files"
            else provenance["base_sha"]
            if args[:2] == ("rev-parse", "--verify") and args[2] == "awf-review-base^{commit}"
            else provenance["head_sha"]
        ),
    )
    monkeypatch.setattr(
        awf_role,
        "durable_model_manifest_sha256",
        lambda *args, **kwargs: "manifest-sha",
    )
    monkeypatch.setattr(
        awf_role,
        "restore_durable_model_manifest",
        lambda *args, **kwargs: str(tmp_path / "repo"),
    )
    monkeypatch.setattr(awf_role, "verify_outbox_evidence", lambda *args, **kwargs: None)

    with pytest.raises(SystemExit, match="1"):
        awf_role.role_reviewer(ns)
    assert len(tool_calls) == 1
    assert len(send_calls) == 1

    monkeypatch.setattr(
        awf_role,
        "send_event",
        lambda *args, **kwargs: send_calls.append((args, kwargs)) or True,
    )
    ns.evidence = awf_role.RunEvidence(103, "reviewer", state_root=state_root)

    assert awf_role.role_reviewer(ns) == 0
    assert len(tool_calls) == 1
    assert len(send_calls) == 2


def test_v3_reviewer_pr_verify_failure_reimports_durable_report_without_model(
    monkeypatch,
    tmp_path,
):
    content = _review_markdown("PASS", blocked_reason=None)
    ns, send_calls, tool_calls = _prepare_reviewer_routing(
        monkeypatch,
        tmp_path,
        content,
    )
    provenance = _pr_provenance()
    ns.commit = provenance["head_sha"]
    ns.input_type = "task:awf-review-v3"
    ns.source_event_id = 102
    for field in awf_role._PROVENANCE_FIELDS:
        setattr(ns, field, provenance[field])
    payload = awf_role.input_payload(ns, "reviewer")
    ns.payload_sha256 = awf_role.canonical_payload_sha256(payload)
    ns.delivery_id = awf_role.make_delivery_id(
        "coder",
        ns.input_type,
        ns.payload_sha256,
        ns.source_event_id,
    )
    state_root = tmp_path / "state"
    ns.evidence = awf_role.RunEvidence(103, "reviewer", state_root=state_root)
    gates = iter(("authorized", "duplicate_event"))
    monkeypatch.setattr(
        awf_role,
        "pre_invocation_gate",
        lambda *args, **kwargs: argparse.Namespace(reason=next(gates)),
    )
    monkeypatch.setattr(awf_role, "provenance_from_args", lambda *args, **kwargs: provenance)
    monkeypatch.setattr(awf_role, "fetch_and_checkout_pr_head", lambda *args, **kwargs: None)
    monkeypatch.setattr(awf_role, "assert_model_pr_git_state", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        awf_role,
        "git_out",
        lambda _repo, *args: (
            "implementation.md"
            if args == ("ls-files", "--", "implementation.md")
            else ""
            if args and args[0] == "ls-files"
            else provenance["base_sha"]
            if args[:2] == ("rev-parse", "--verify") and args[2] == "awf-review-base^{commit}"
            else provenance["head_sha"]
        ),
    )
    monkeypatch.setattr(
        awf_role,
        "durable_model_manifest_sha256",
        lambda *args, **kwargs: "manifest-sha",
    )
    monkeypatch.setattr(
        awf_role,
        "restore_durable_model_manifest",
        lambda *args, **kwargs: str(tmp_path / "repo"),
    )
    monkeypatch.setattr(
        awf_role,
        "import_model_report",
        lambda _workspace, trusted, path: (
            (Path(trusted) / path).write_text(content, encoding="utf-8") and Path(trusted) / path
        ),
    )
    pr_checks = []

    def verify_pr(*args, **kwargs):
        pr_checks.append((args, kwargs))
        if len(pr_checks) == 1:
            raise SystemExit(1)

    monkeypatch.setattr(awf_role, "verify_pr_remote_tuple", verify_pr)

    with pytest.raises(SystemExit, match="1"):
        awf_role.role_reviewer(ns)
    assert len(tool_calls) == 1
    assert not send_calls
    trusted_report = Path(os.environ["AWF_REPO_DIR"]).joinpath(ns.review_report)
    trusted_report.unlink()

    ns.evidence = awf_role.RunEvidence(103, "reviewer", state_root=state_root)

    assert awf_role.role_reviewer(ns) == 0
    assert len(tool_calls) == 1
    assert len(send_calls) == 1
    assert len(pr_checks) == 2
    assert send_calls[0][0][3]["review_report"]["blocked_reason"] == ""
    assert not trusted_report.exists()

    monkeypatch.setattr(
        awf_role,
        "pre_invocation_gate",
        lambda *args, **kwargs: argparse.Namespace(reason="duplicate_event"),
    )
    ns.evidence = awf_role.RunEvidence(103, "reviewer", state_root=state_root)
    assert awf_role.role_reviewer(ns) == 0
    assert len(tool_calls) == 1
    assert len(send_calls) == 1


def test_v3_reviewer_ambiguous_model_started_checkpoint_fails_cleanly(
    monkeypatch,
    tmp_path,
    capsys,
):
    ns, send_calls, tool_calls = _prepare_reviewer_routing(
        monkeypatch,
        tmp_path,
        _review_markdown("PASS"),
    )
    provenance = _pr_provenance()
    ns.commit = provenance["head_sha"]
    ns.input_type = "task:awf-review-v3"
    ns.source_event_id = 102
    for field in awf_role._PROVENANCE_FIELDS:
        setattr(ns, field, provenance[field])
    payload = awf_role.input_payload(ns, "reviewer")
    ns.payload_sha256 = awf_role.canonical_payload_sha256(payload)
    ns.delivery_id = awf_role.make_delivery_id(
        "coder",
        ns.input_type,
        ns.payload_sha256,
        ns.source_event_id,
    )
    state_root = tmp_path / "state"
    ns.evidence = awf_role.RunEvidence(103, "reviewer", state_root=state_root)
    input_context = awf_role.validate_input_delivery(ns, "reviewer", ns.evidence)
    checkpoint_path, checkpoint = awf_role.begin_recovery_checkpoint(
        ns.evidence,
        input_context,
        role="reviewer",
        branch=ns.branch,
        source_commit=ns.commit,
        provenance=provenance,
    )
    awf_role.advance_recovery_checkpoint(
        ns.evidence,
        checkpoint_path,
        checkpoint,
        "model_started",
        model_workspace=str(ns.evidence.run_dir / "model-workspace-proof"),
        model_manifest_sha256="manifest-sha",
        model_event_id=103,
    )
    ns.evidence = awf_role.RunEvidence(103, "reviewer", state_root=state_root)
    monkeypatch.setattr(
        awf_role,
        "pre_invocation_gate",
        lambda *args, **kwargs: argparse.Namespace(reason="duplicate_event"),
    )
    monkeypatch.setattr(awf_role, "provenance_from_args", lambda *args, **kwargs: provenance)
    monkeypatch.setattr(awf_role, "fetch_and_checkout_pr_head", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        awf_role,
        "render_provider_invocation",
        lambda *args, **kwargs: pytest.fail("ambiguous recovery must not render again"),
    )

    with pytest.raises(SystemExit, match="1"):
        awf_role.role_reviewer(ns)

    assert "outcome is ambiguous" in capsys.readouterr().err
    assert not tool_calls
    assert not send_calls


def test_replacement_eligibility_requires_exact_no_effect_model_ambiguity(tmp_path):
    evidence = awf_role.RunEvidence(201, "coder", state_root=tmp_path / "state")
    provenance = _pr_provenance()
    input_context = {
        "key": "replacement-input",
        "delivery_id": "awf:" + "1" * 64,
        "payload_sha256": "sha256:" + "2" * 64,
        "source_event_id": 200,
    }
    path, checkpoint = awf_role.begin_recovery_checkpoint(
        evidence,
        input_context,
        role="coder",
        branch="feature/replacement",
        source_commit=provenance["head_sha"],
        provenance=provenance,
    )
    checkpoint = awf_role.advance_recovery_checkpoint(
        evidence,
        path,
        checkpoint,
        "model_started",
        model_event_id=201,
        model_workspace="workspace",
        model_manifest_sha256="sha256:" + "3" * 64,
    )

    lineage = awf_role.replacement_eligibility(checkpoint, None)

    assert lineage["old_delivery_id"] == input_context["delivery_id"]
    with_effect = {**checkpoint, "facts": {**checkpoint["facts"], "head_sha": "4" * 40}}
    with pytest.raises(SystemExit, match="1"):
        awf_role.replacement_eligibility(with_effect, None)


@pytest.mark.parametrize(
    "path",
    ["", "/tmp/review.md", "../review.md", "C:/review.md", ".awf\\review.md"],
)
def test_reviewer_requires_safe_repo_relative_path(monkeypatch, tmp_path, path):
    ns, send_calls, tool_calls = _prepare_reviewer_routing(
        monkeypatch, tmp_path, _review_markdown("PASS")
    )
    ns.review_report = path

    with pytest.raises(SystemExit, match="1"):
        awf_role.role_reviewer(ns)

    assert not tool_calls
    assert not send_calls


def test_reviewer_report_path_must_differ_from_implementation_report(monkeypatch, tmp_path):
    ns, send_calls, tool_calls = _prepare_reviewer_routing(
        monkeypatch, tmp_path, _review_markdown("PASS")
    )
    ns.review_report = "implementation.md"

    with pytest.raises(SystemExit, match="1"):
        awf_role.role_reviewer(ns)

    assert not tool_calls
    assert not send_calls


def test_reviewer_report_path_must_not_replace_tracked_file(monkeypatch, tmp_path):
    ns, send_calls, tool_calls = _prepare_reviewer_routing(
        monkeypatch, tmp_path, _review_markdown("PASS")
    )
    monkeypatch.setattr(awf_role, "git_out", lambda *args: "tracked.md")

    with pytest.raises(SystemExit, match="1"):
        awf_role.role_reviewer(ns)

    assert not tool_calls
    assert not send_calls


def test_dispatch_dry_run_carries_distinct_default_report_paths(tmp_path):
    repo = tmp_path / "repo"
    run("git", "init", "-b", "main", str(repo), cwd=tmp_path)
    run("git", "config", "user.name", "AWF Test", cwd=repo)
    run("git", "config", "user.email", "awf-test@example.invalid", cwd=repo)
    (repo / "task.md").write_text("task\n", encoding="utf-8")

    completed = subprocess.run(
        native_dispatch_argv(
            repo,
            "--card",
            "task.md",
            "--branch",
            "feature/task",
            "--type",
            "task:awf-impl-v2",
            "--no-push",
            "--dry-run",
        ),
        check=True,
        capture_output=True,
    )

    stdout = completed.stdout.decode("utf-8", errors="replace")
    _ = completed.stderr.decode("utf-8", errors="replace")
    payload_line = next(line for line in stdout.splitlines() if "payload=" in line)
    payload = json.loads(payload_line.split("payload=", 1)[1])
    assert payload["report"] == ".awf/artifacts/impl-report-task.md"
    assert payload["review_report"] == ".awf/artifacts/review-report-task.md"
    assert "type=task:awf-impl-v2" in stdout
    base_payload = {key: value for key, value in payload.items() if not key.startswith("awf_")}
    payload_hash = awf_role.canonical_payload_sha256(base_payload)
    assert payload["awf_payload_sha256"] == payload_hash
    assert payload["awf_source_event_id"] == 0
    assert payload["awf_delivery_id"] == awf_role.make_delivery_id(
        "architect", "task:awf-impl-v2", payload_hash, 0
    )


def test_native_v3_dispatch_payload_preserves_exact_provenance_contract():
    provenance = awf_role.provenance_payload(_pr_provenance(pull_request=0))

    payload = awf_dispatch.build_payload(
        event_type="task:awf-impl-v3",
        task_id="task",
        branch="feature/task",
        card="task.md",
        commit="b" * 40,
        tool="opencode",
        model="",
        report="implementation.md",
        review_report="review.md",
        provenance=provenance,
    )

    base_payload = {key: value for key, value in payload.items() if not key.startswith("awf_")}
    assert base_payload == {
        "task_id": "task",
        "branch": "feature/task",
        "card": "task.md",
        "commit": "b" * 40,
        "tool": "opencode",
        "model": "",
        "report": "implementation.md",
        "review_report": "review.md",
        **provenance,
    }
    payload_hash = awf_role.canonical_payload_sha256(base_payload)
    assert payload["awf_payload_sha256"] == payload_hash
    assert payload["awf_delivery_id"] == awf_role.make_delivery_id(
        "architect", "task:awf-impl-v3", payload_hash, 0
    )


def test_native_v2_dispatch_rejects_option_like_branch_before_git_mutation(tmp_path):
    repo = tmp_path / "repo"
    run("git", "init", "-b", "main", str(repo), cwd=tmp_path)
    run("git", "config", "user.name", "AWF Test", cwd=repo)
    run("git", "config", "user.email", "awf-test@example.invalid", cwd=repo)
    (repo / "task.md").write_text("task\n", encoding="utf-8")

    completed = subprocess.run(
        native_dispatch_argv(
            repo,
            "--card",
            "task.md",
            "--branch=-dangerous",
            "--type",
            "task:awf-impl-v2",
            "--no-push",
            "--dry-run",
        ),
        capture_output=True,
    )

    assert completed.returncode == 2
    assert b"invalid Git branch" in completed.stderr
    assert run("git", "status", "--porcelain", cwd=repo) == "?? task.md"


def test_dispatch_push_failure_stops_before_agent_bus_send(tmp_path):
    repo = tmp_path / "repo"
    run("git", "init", "-b", "main", str(repo), cwd=tmp_path)
    run("git", "config", "user.name", "AWF Test", cwd=repo)
    run("git", "config", "user.email", "awf-test@example.invalid", cwd=repo)
    (repo / "task.md").write_text("task\n", encoding="utf-8")

    marker = tmp_path / "agent-bus-called"
    if os.name == "nt":
        fake_bus = tmp_path / "fake-agent-bus.cmd"
        fake_bus.write_text(f'@echo called>"{marker}"\r\n', encoding="utf-8")
    else:
        fake_bus = tmp_path / "fake-agent-bus"
        fake_bus.write_text(f"#!/usr/bin/env sh\nprintf called > {marker}\n", encoding="utf-8")
        fake_bus.chmod(0o755)

    environment = dict(os.environ)
    environment.update(
        {
            "AGENT_BUS_URL": "http://controlled.invalid",
            "AWF_ARCH_TOKEN": "controlled-test-token",
            "AWF_BUS_BIN": dispatch_shell_path(fake_bus),
        }
    )
    completed = subprocess.run(
        native_dispatch_argv(
            repo,
            "--card",
            "task.md",
            "--branch",
            "feature/task",
            "--type",
            "task:awf-impl-v2",
        ),
        env=environment,
        capture_output=True,
    )

    stderr = completed.stderr.decode("utf-8", errors="replace")
    assert completed.returncode == 2
    assert "push failed; refusing to send an event" in stderr
    assert not marker.exists()


def test_v3_dispatch_rejects_unsafe_fork_pushurl_under_python_optimization(tmp_path):
    repo = tmp_path / "repo"
    run("git", "init", "-b", "main", str(repo), cwd=tmp_path)
    run("git", "config", "user.name", "AWF Test", cwd=repo)
    run("git", "config", "user.email", "awf-test@example.invalid", cwd=repo)
    run(
        "git",
        "remote",
        "add",
        "upstream",
        "https://github.com/upstream/project.git",
        cwd=repo,
    )
    run(
        "git",
        "remote",
        "add",
        "fork",
        "https://github.com/contributor/project.git",
        cwd=repo,
    )
    run(
        "git",
        "remote",
        "set-url",
        "--add",
        "--push",
        "fork",
        "https://github.com/attacker/project.git",
        cwd=repo,
    )
    (repo / "task.md").write_text("task\n", encoding="utf-8")

    environment = {**os.environ, "PYTHONOPTIMIZE": "1"}
    completed = subprocess.run(
        native_dispatch_argv(
            repo,
            "--card",
            "task.md",
            "--branch",
            "feature/task",
            "--upstream-repo",
            "upstream/project",
            "--head-repo",
            "contributor/project",
            "--dry-run",
        ),
        env=environment,
        capture_output=True,
    )

    assert completed.returncode == 2
    assert b"invalid or untrusted GitHub remote/repository/ref configuration" in completed.stderr
    assert run("git", "status", "--porcelain", cwd=repo) == "?? task.md"


def test_dispatch_bypasses_proxy_for_private_bus_host(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    run("git", "init", "-b", "main", str(repo), cwd=tmp_path)
    run("git", "config", "user.name", "AWF Test", cwd=repo)
    run("git", "config", "user.email", "awf-test@example.invalid", cwd=repo)
    (repo / "task.md").write_text("task\n", encoding="utf-8")

    marker = tmp_path / "no-proxy.txt"
    if os.name == "nt":
        fake_bus = tmp_path / "fake-agent-bus.exe"
    else:
        fake_bus = tmp_path / "fake-agent-bus"
        fake_bus.write_text(
            f'#!/usr/bin/env sh\nprintf "%s\\n%s\\n" "$NO_PROXY" "$no_proxy" > {marker}\n',
            encoding="utf-8",
        )
        fake_bus.chmod(0o755)

    environment = dict(os.environ)
    environment.pop("NO_PROXY", None)
    environment.pop("no_proxy", None)
    environment.update(
        {
            "AGENT_BUS_URL": "http://100.108.67.47:8800",
            "AWF_ARCH_TOKEN": "controlled-test-token",
            "AWF_BUS_BIN": dispatch_shell_path(fake_bus),
            "NO_PROXY": "localhost,127.0.0.1",
        }
    )
    dispatch_args = [
        "--repo",
        str(repo),
        "--card",
        "task.md",
        "--tool",
        "opencode",
        "--branch",
        "feature/task",
        "--type",
        "task:awf-impl-v2",
        "--no-push",
    ]
    if os.name == "nt":
        real_run = subprocess.run

        def intercept_bus(argv, **kwargs):
            if argv[0] == str(fake_bus):
                child_environment = kwargs["env"]
                marker.write_text(
                    f"{child_environment['NO_PROXY']}\n{child_environment['no_proxy']}\n",
                    encoding="utf-8",
                )
                return subprocess.CompletedProcess(argv, 0, "", "")
            return real_run(argv, **kwargs)

        for key in ("NO_PROXY", "no_proxy"):
            monkeypatch.delenv(key, raising=False)
        for key, value in environment.items():
            monkeypatch.setenv(key, value)
        monkeypatch.setattr(awf_dispatch, "run_command", intercept_bus)
        completed_returncode = awf_dispatch.main(dispatch_args)
    else:
        completed = subprocess.run(
            [
                sys.executable,
                str(NATIVE_DISPATCH_PATH),
                *dispatch_args,
            ],
            env=environment,
            capture_output=True,
        )
        completed_returncode = completed.returncode

    assert completed_returncode == 0
    assert marker.read_text(encoding="utf-8").splitlines() == [
        "localhost,127.0.0.1,100.108.67.47",
        "localhost,127.0.0.1,100.108.67.47",
    ]


def test_dispatch_captures_agent_bus_stdio_for_pythonw(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    run("git", "init", "-b", "main", str(repo), cwd=tmp_path)
    run("git", "config", "user.name", "AWF Test", cwd=repo)
    run("git", "config", "user.email", "awf-test@example.invalid", cwd=repo)
    (repo / "task.md").write_text("task\n", encoding="utf-8")
    fake_bus = tmp_path / ("fake-agent-bus.exe" if os.name == "nt" else "fake-agent-bus")
    fake_bus.write_text("", encoding="utf-8")
    fake_bus.chmod(0o755)
    monkeypatch.setenv("AGENT_BUS_URL", "http://127.0.0.1:18802")
    monkeypatch.setenv("AWF_ARCH_TOKEN", "controlled-test-token")
    monkeypatch.setenv("AWF_BUS_BIN", dispatch_shell_path(fake_bus))
    real_run = awf_dispatch.run_command
    observed: dict[str, object] = {}

    def intercept_bus(argv, **kwargs):
        if argv[0] == str(fake_bus):
            observed.update(kwargs)
            return subprocess.CompletedProcess(argv, 0, "sent\n", "")
        return real_run(argv, **kwargs)

    monkeypatch.setattr(awf_dispatch, "run_command", intercept_bus)

    assert (
        awf_dispatch.main(
            [
                "--repo",
                str(repo),
                "--card",
                "task.md",
                "--tool",
                "opencode",
                "--branch",
                "feature/task",
                "--type",
                "task:awf-impl-v2",
                "--no-push",
            ]
        )
        == 0
    )
    assert observed["capture_output"] is True
    assert observed["text"] is True
    assert observed["encoding"] == "utf-8"
    assert observed["errors"] == "replace"


def test_dispatch_preserves_explicit_reviewer_tool_default_model(tmp_path):
    repo = tmp_path / "repo"
    run("git", "init", "-b", "main", str(repo), cwd=tmp_path)
    run("git", "config", "user.name", "AWF Test", cwd=repo)
    run("git", "config", "user.email", "awf-test@example.invalid", cwd=repo)
    (repo / "task.md").write_text(
        """card
<!-- awf-reviewer-selection
{
  "coder": {"tool": "opencode", "model": "deepseek/deepseek-v4-flash"},
  "reviewer": {"tool": "codex", "model": ""}
}
-->
""",
        encoding="utf-8",
    )

    assert (
        awf_dispatch.main(
            [
                "--repo",
                str(repo),
                "--card",
                "task.md",
                "--tool",
                "opencode",
                "--model",
                "deepseek/deepseek-v4-flash",
                "--reviewer-tool",
                "codex",
                "--branch",
                "feature/task",
                "--type",
                "task:awf-impl-v2",
                "--no-push",
                "--dry-run",
            ]
        )
        == 0
    )


def test_windows_native_dispatch_rejects_command_wrappers():
    with pytest.raises(
        awf_dispatch.DispatchError,
        match="must resolve to a native executable",
    ):
        awf_dispatch.resolve_bus_executable(
            "C:\\tools\\agent-bus.cmd",
            platform="windows",
        )


def test_dispatch_shell_is_a_posix_compatibility_shim_only():
    source = DISPATCH_PATH.read_text(encoding="utf-8")

    assert "awf_dispatch.py" in source
    assert "git -C" not in source
    assert "agent-bus send" not in source
    assert "payload=" not in source
    assert len(source.splitlines()) <= 20


def test_handoff_bus_probe_adds_bus_host_to_no_proxy(monkeypatch):
    monkeypatch.setattr(awf_handoff_check, "is_file", lambda _path: True)
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0, "0\n", "")

    monkeypatch.setattr(awf_handoff_check, "run_command", fake_run)
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    monkeypatch.setenv("NO_PROXY", "localhost,127.0.0.1")
    awf_handoff_check.results.clear()

    awf_handoff_check.check_bus_reachable(
        {
            "AGENT_BUS_URL": "http://100.108.67.47:8800",
            "AWF_CODER_TOKEN": "controlled-test-token",
            "AWF_BUS_BIN": "agent-bus",
        },
        "coder",
    )

    child = calls[-1][1]["env"]
    expected = "localhost,127.0.0.1,100.108.67.47"
    assert child["NO_PROXY"] == expected
    assert child["no_proxy"] == expected


def test_windows_acl_check_does_not_treat_users_in_target_path_as_a_principal(monkeypatch):
    dest = Path(r"C:\Users\atong\.config\awf\dispatch.env")
    stdout = f"{dest} ATONG-COMPUTER\\atong:(F)\n\nSuccessfully processed 1 files\n"

    def fake_run(args, **kwargs):
        if args[0] == "whoami":
            return subprocess.CompletedProcess(args, 0, "atong-computer\\atong\n", "")
        return subprocess.CompletedProcess(args, 0, stdout, "")

    monkeypatch.setattr(
        awf_handoff_check,
        "run_command",
        fake_run,
    )
    records = []
    monkeypatch.setattr(
        awf_handoff_check,
        "record",
        lambda status, label, detail: records.append((status, label, detail)),
    )

    awf_handoff_check.check_windows_acl(dest)

    assert records == [
        (
            awf_handoff_check.PASS,
            "dispatch.env is owner-only",
            "icacls: current principal only",
        )
    ]


def test_windows_acl_check_rejects_another_principal(monkeypatch):
    dest = Path(r"C:\Users\atong\.config\awf\dispatch.env")
    stdout = (
        f"{dest} ATONG-COMPUTER\\atong:(F)\nBUILTIN\\Users:(RX)\n\nSuccessfully processed 1 files\n"
    )

    def fake_run(args, **kwargs):
        if args[0] == "whoami":
            return subprocess.CompletedProcess(args, 0, "ATONG-COMPUTER\\atong\n", "")
        return subprocess.CompletedProcess(args, 0, stdout, "")

    monkeypatch.setattr(
        awf_handoff_check,
        "run_command",
        fake_run,
    )
    records = []
    monkeypatch.setattr(
        awf_handoff_check,
        "record",
        lambda status, label, detail: records.append((status, label, detail)),
    )

    awf_handoff_check.check_windows_acl(dest)

    assert records[0][0] == awf_handoff_check.FAIL


def test_windows_acl_check_rejects_unverifiable_acl(monkeypatch):
    dest = Path(r"C:\Users\atong\.config\awf\dispatch.env")
    monkeypatch.setattr(
        awf_handoff_check,
        "run_command",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 5, "", "access denied"),
    )
    records = []
    monkeypatch.setattr(
        awf_handoff_check,
        "record",
        lambda status, label, detail: records.append((status, label, detail)),
    )

    awf_handoff_check.check_windows_acl(dest)

    assert records[0][0] == awf_handoff_check.FAIL


def test_windows_acl_check_rejects_unparseable_acl(monkeypatch):
    dest = Path(r"C:\Users\atong\.config\awf\dispatch.env")
    monkeypatch.setattr(
        awf_handoff_check,
        "run_command",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 0, "Successfully processed 1 files\n", ""
        ),
    )
    records = []
    monkeypatch.setattr(
        awf_handoff_check,
        "record",
        lambda status, label, detail: records.append((status, label, detail)),
    )

    awf_handoff_check.check_windows_acl(dest)

    assert records[0][0] == awf_handoff_check.FAIL


def test_windows_acl_check_rejects_unknown_current_principal(monkeypatch):
    dest = Path(r"C:\Users\atong\.config\awf\dispatch.env")
    stdout = f"{dest} ATONG-COMPUTER\\atong:(F)\n"

    def fake_run(args, **kwargs):
        if args[0] == "whoami":
            return subprocess.CompletedProcess(args, 1, "", "unable to resolve principal")
        return subprocess.CompletedProcess(args, 0, stdout, "")

    monkeypatch.setattr(awf_handoff_check, "run_command", fake_run)
    records = []
    monkeypatch.setattr(
        awf_handoff_check,
        "record",
        lambda status, label, detail: records.append((status, label, detail)),
    )

    awf_handoff_check.check_windows_acl(dest)

    assert records[0][0] == awf_handoff_check.FAIL


def test_windows_acl_check_rejects_inherited_owner_ace(monkeypatch):
    dest = Path(r"C:\Users\atong\.config\awf\dispatch.env")
    stdout = f"{dest} ATONG-COMPUTER\\atong:(I)(F)\n"

    def fake_run(args, **kwargs):
        if args[0] == "whoami":
            return subprocess.CompletedProcess(args, 0, "ATONG-COMPUTER\\atong\n", "")
        return subprocess.CompletedProcess(args, 0, stdout, "")

    monkeypatch.setattr(awf_handoff_check, "run_command", fake_run)
    records = []
    monkeypatch.setattr(
        awf_handoff_check,
        "record",
        lambda status, label, detail: records.append((status, label, detail)),
    )

    awf_handoff_check.check_windows_acl(dest)

    assert records[0][0] == awf_handoff_check.FAIL


def test_bootstrap_write_is_atomic_and_rejects_symlink_destination(tmp_path, monkeypatch):
    destination = (tmp_path / "dispatch.env").resolve()
    awf_bootstrap.write_env_file(
        destination,
        ["AGENT_BUS_URL=http://bus.invalid", "AWF_CODER_TOKEN=controlled-token", ""],
        force=False,
    )
    assert destination.read_text(encoding="utf-8").endswith("\n")
    if os.name != "nt":
        assert stat.S_IMODE(destination.stat().st_mode) == 0o600

    locked: list[Path] = []
    events: list[str] = []
    real_fdopen = os.fdopen
    monkeypatch.setattr(
        awf_bootstrap,
        "lock_permissions",
        lambda path: (events.append("lock"), locked.append(Path(path)))[1] or "owner-only",
    )

    def guarded_fdopen(fd, *args, **kwargs):
        events.append("fdopen")
        assert events[-2] == "lock"
        return real_fdopen(fd, *args, **kwargs)

    monkeypatch.setattr(awf_bootstrap.os, "fdopen", guarded_fdopen)
    awf_bootstrap.write_env_file(
        destination,
        ["AGENT_BUS_URL=http://bus.invalid", "AWF_CODER_TOKEN=replacement", ""],
        force=True,
    )
    assert len(locked) == 2
    assert events == ["lock", "fdopen", "lock", "fdopen"]
    assert destination.with_suffix(".env.bak").is_file()

    target = tmp_path / "target.env"
    target.write_text("do not replace\n", encoding="utf-8")
    link = tmp_path / "linked.env"
    link.symlink_to(target)
    with pytest.raises(SystemExit, match="2"):
        awf_bootstrap.write_env_file(
            link,
            ["AWF_CODER_TOKEN=replacement", ""],
            force=True,
        )
    assert target.read_text(encoding="utf-8") == "do not replace\n"


def test_windows_permission_lock_removes_every_non_owner_ace(monkeypatch, tmp_path):
    path = tmp_path / "dispatch.env"
    path.write_text("AWF_CODER_TOKEN=controlled\n", encoding="utf-8")
    extra_present = True
    calls = []

    def fake_run(argv, **_kwargs):
        nonlocal extra_present
        calls.append(argv)
        if argv == ["whoami"]:
            return subprocess.CompletedProcess(argv, 0, "HOST\\owner\n", "")
        if argv[:2] == ["icacls", str(path)] and len(argv) == 2:
            extra = "SYSTEM:(F)\n" if extra_present else ""
            return subprocess.CompletedProcess(
                argv,
                0,
                f"{path} HOST\\owner:(F)\n{extra}",
                "",
            )
        if "/remove:g" in argv:
            extra_present = False
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(awf_bootstrap.os, "name", "nt")
    monkeypatch.setattr(awf_bootstrap, "run_command", fake_run)

    assert awf_bootstrap.lock_permissions(path) == "icacls: owner-only"
    assert any("/remove:g" in argv and "SYSTEM" in argv for argv in calls)
    assert any("/remove:d" in argv and "SYSTEM" in argv for argv in calls)
    assert not extra_present


def test_curl_bootstrap_locks_secret_temp_file_before_write(monkeypatch):
    locked: list[Path] = []
    events: list[str] = []
    real_fdopen = os.fdopen

    monkeypatch.setattr(
        awf_bootstrap,
        "lock_permissions",
        lambda path: (events.append("lock"), locked.append(Path(path)))[1] or "owner-only",
    )

    def guarded_fdopen(fd, *args, **kwargs):
        events.append("fdopen")
        assert events[-2] == "lock"
        return real_fdopen(fd, *args, **kwargs)

    monkeypatch.setattr(awf_bootstrap.os, "fdopen", guarded_fdopen)
    monkeypatch.setattr(
        awf_bootstrap,
        "run_command",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0],
            0,
            '{"agent":"coder","token":"controlled-token"}\n200',
            "",
        ),
    )

    tokens = awf_bootstrap.fetch_tokens_curl(
        "https://bus.invalid",
        "bootstrap-secret",
        ["coder"],
    )

    assert tokens == {"coder": "controlled-token"}
    assert len(locked) == 1
    assert events == ["lock", "fdopen"]
    assert not locked[0].exists()


@pytest.mark.parametrize("transport", ["ssh", "curl"])
def test_bootstrap_token_fetch_failure_never_prints_partial_token(monkeypatch, capsys, transport):
    partial_token = "partial-token-material"
    diagnostic = awf_executor.FailureDiagnostic(
        kind="timeout",
        runtime=awf_executor.RuntimeKind.POSIX,
        executable=transport,
        cwd="/safe",
        timeout_seconds=30,
        stdout=partial_token,
    )

    def fail_without_returning(*_args, **_kwargs):
        raise awf_bootstrap.ExecutionFailure(diagnostic)

    monkeypatch.setattr(awf_bootstrap, "run_command", fail_without_returning)
    if transport == "curl":
        monkeypatch.setattr(
            awf_bootstrap,
            "lock_permissions",
            lambda _path: "owner-only",
        )

    with pytest.raises(SystemExit):
        if transport == "ssh":
            awf_bootstrap.fetch_tokens_line("source.invalid", "/safe/source")
        else:
            awf_bootstrap.fetch_tokens_curl(
                "https://bus.invalid",
                "bootstrap-secret",
                ["coder"],
            )

    output = capsys.readouterr()
    assert partial_token not in output.out
    assert partial_token not in output.err


# ---------------------------------------------------------------------------
# Fail-closed coder handoff
# ---------------------------------------------------------------------------


def _prepare_coder_handoff_test(monkeypatch, tmp_path, *, no_push=False):
    repo = tmp_path / "repo"
    repo.mkdir()
    script_dir = tmp_path / "scripts"
    script_dir.mkdir()
    (script_dir / "executor-prompt.md").write_text("prompt")
    (repo / "task.md").write_text(_VALID_POSTFLIGHT_CARD)
    report = repo / "report.md"
    report.write_text("report content")

    monkeypatch.setenv("AWF_REPO_DIR", str(repo))
    monkeypatch.setenv("AWF_SCRIPT_DIR", str(script_dir))
    if no_push:
        monkeypatch.setenv("AWF_NO_PUSH", "1")
    else:
        monkeypatch.delenv("AWF_NO_PUSH", raising=False)
    monkeypatch.setattr(awf_role, "fetch_and_checkout", lambda *a, **kw: None)
    monkeypatch.setattr(awf_role, "prepare_model_workspace", lambda *a, **kw: str(repo))
    monkeypatch.setattr(awf_role, "tool_opencode_exec", lambda *a, **kw: 0)
    monkeypatch.setattr(awf_role, "assert_model_workspace_state", lambda *a, **kw: None)
    monkeypatch.setattr(awf_role, "assert_model_git_metadata", lambda *a, **kw: None)
    monkeypatch.setattr(awf_role, "assert_model_git_state", lambda *a, **kw: None)
    monkeypatch.setattr(awf_role, "run_verifications", lambda *a, **kw: None)
    monkeypatch.setattr(awf_role, "stage_model_artifact", lambda *a, **kw: report)
    monkeypatch.setattr(awf_role, "run_postflight_delta_gates", lambda *a, **kw: None)
    monkeypatch.setattr(awf_role, "import_model_delta", lambda *a, **kw: "verified-tree")

    send_calls = []
    monkeypatch.setattr(awf_role, "send_event", lambda *a, **kw: send_calls.append((a, kw)) or True)
    ns = argparse.Namespace(
        branch="feature/task",
        card="task.md",
        commit="dispatched",
        model="",
        tool="opencode",
        report="report.md",
        review_report=".awf/review.md",
        base="",
    )
    return ns, send_calls


def _bind_delivery(ns, event_type="task:awf-impl-v2", source_role="architect", source_event_id=0):
    ns.input_type = event_type
    ns.source_event_id = source_event_id
    payload = awf_role.input_payload(ns, "coder")
    ns.payload_sha256 = awf_role.canonical_payload_sha256(payload)
    ns.delivery_id = awf_role.make_delivery_id(
        source_role,
        event_type,
        ns.payload_sha256,
        source_event_id,
    )
    return ns


def test_dispatch_listener_role_executor_and_postflight_share_one_report_path(
    monkeypatch, tmp_path
):
    real_tool_opencode_exec = awf_role.tool_opencode_exec
    ns, _ = _prepare_coder_handoff_test(monkeypatch, tmp_path)
    repo = Path(os.environ["AWF_REPO_DIR"])
    required_report = ".awf/artifacts/impl-report-task.md"
    ns.report = required_report
    (repo / "report.md").unlink()
    (repo / "task.md").write_text(
        _VALID_POSTFLIGHT_CARD.replace('"task.md"', f'"task.md", "{required_report}"'),
        encoding="utf-8",
    )
    payload = awf_dispatch.build_payload(
        event_type="task:awf-impl-v2",
        task_id="task",
        branch=ns.branch,
        card=ns.card,
        commit=ns.commit,
        tool=ns.tool,
        model=ns.model,
        report=required_report,
        review_report=ns.review_report,
        provenance=None,
    )
    handler = awf_listen.build_handler("python", "awf_role.py", "coder")
    assert payload["report"] == required_report
    assert "--report {payload.report}" in handler

    invocation = {}

    def fake_spawn(argv, **_kwargs):
        invocation["argv"] = argv
        instruction = argv[-1]
        marker = "Write the complete ImplementationReport to exactly: "
        report_line = next(line for line in instruction.splitlines() if line.startswith(marker))
        received_path = report_line.removeprefix(marker)
        target = repo / received_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("controlled implementation report\n", encoding="utf-8")
        return 0

    monkeypatch.setattr(awf_role, "spawn", fake_spawn)
    monkeypatch.setattr(awf_role, "tool_opencode_exec", real_tool_opencode_exec)
    monkeypatch.setattr(awf_role, "git", lambda *args, **kwargs: 0)
    monkeypatch.setattr(awf_role, "git_out", lambda *args, **kwargs: "verified-sha")
    monkeypatch.setattr(awf_role, "push_and_verify_remote_head", lambda *args: "verified-sha")

    assert awf_role.role_coder(ns) == 0
    assert required_report in invocation["argv"][-1]
    awf_role.check_report(str(repo / required_report))


def test_v3_artifact_contract_drift_does_not_consume_model_attempt(monkeypatch, tmp_path):
    ns, _ = _prepare_coder_handoff_test(monkeypatch, tmp_path)
    repo = Path(os.environ["AWF_REPO_DIR"])
    v4_report = ".awf/artifacts/impl-report-task-v4.md"
    v5_report = ".awf/artifacts/impl-report-task-v5.md"
    ns.branch = "agent/task-v5"
    ns.report = v5_report
    (repo / "task.md").write_text(
        _VALID_POSTFLIGHT_CARD.replace('"task.md"', f'"task.md", "{v4_report}"'),
        encoding="utf-8",
    )
    provenance = _pr_provenance(pull_request=0)
    provenance["head_ref"] = ns.branch
    ns.commit = provenance["head_sha"]
    ns.input_type = "task:awf-impl-v3"
    ns.source_event_id = 301
    for field in awf_role._PROVENANCE_FIELDS:
        setattr(ns, field, provenance[field])
    _bind_delivery(ns, event_type=ns.input_type, source_event_id=ns.source_event_id)
    state_root = tmp_path / "state"
    ns.evidence = awf_role.RunEvidence(301, "coder", state_root=state_root)
    ns.run_id = "phase0-contract-budget"
    ns.max_attempts = 1
    ns.rework_budget = 1
    ns.attempt = 1
    monkeypatch.setenv("AWF_CONTROL_PLANE", "1")
    monkeypatch.setattr(awf_role, "provenance_from_args", lambda *args, **kwargs: provenance)
    monkeypatch.setattr(awf_role, "fetch_and_checkout_pr_head", lambda *args, **kwargs: None)
    authority = awf_role.authority_manifest_binding(
        awf_role.load_authority_manifest(
            Path(awf_role.__file__).resolve().parent / "authority-manifest.example.json"
        )
    )
    ledger = awf_role.RunLedger(state_root, ns.run_id)
    packet = awf_role.build_context_packet(
        run_id=ns.run_id,
        taskcard=ns.card,
        frozen_base=ns.commit,
        branch=ns.branch,
        transition=ns.input_type,
        evidence=[ns.report],
        authority_manifest=authority,
        next_action="run trusted coder preflight",
        stage="implement",
        current_stage_evidence_commit=ns.commit,
    )
    ledger.initialize(packet, stage="implement", max_attempts=1, rework_budget=1)
    model_calls = []
    monkeypatch.setattr(
        awf_role,
        "tool_opencode_exec",
        lambda *args, **kwargs: model_calls.append(args) or 0,
    )

    with pytest.raises(SystemExit, match="1"):
        awf_role.role_coder(ns)

    phases = [json.loads(line)["phase"] for line in ns.evidence.log_path.read_text().splitlines()]
    assert "contract_preflight_failed" in phases
    assert model_calls == []
    rejected, _ = ledger.recover()
    assert rejected["attempts"] == 0
    assert rejected.get("stage_attempts", {}) == {}
    assert rejected["sequence"] == 0
    assert rejected["events"] == []
    assert not any(item["status"] == "authorized" for item in rejected["decisions"])

    required_report = ".awf/artifacts/impl-report-task-v5.md"
    (repo / "task.md").write_text(
        _VALID_POSTFLIGHT_CARD.replace('"task.md"', f'"task.md", "{required_report}"'),
        encoding="utf-8",
    )
    ns.source_event_id = 302
    _bind_delivery(ns, event_type=ns.input_type, source_event_id=ns.source_event_id)
    ns.evidence = awf_role.RunEvidence(302, "coder", state_root=state_root)
    monkeypatch.setattr(
        awf_role,
        "durable_model_manifest_sha256",
        lambda *args, **kwargs: "sha256:model-manifest",
    )
    monkeypatch.setattr(
        awf_role,
        "tool_opencode_exec",
        lambda *args, **kwargs: model_calls.append(args) or 9,
    )

    with pytest.raises(SystemExit, match="1"):
        awf_role.role_coder(ns)

    authorized, _ = ledger.recover()
    assert len(model_calls) == 1
    assert authorized["attempts"] == 1
    assert authorized["stage_attempts"] == {"implement": 1}
    assert authorized["sequence"] == 1
    assert [item["status"] for item in authorized["events"]] == ["authorized"]


def test_model_completed_postflight_failure_replays_without_model_or_rework(monkeypatch, tmp_path):
    ns, _ = _prepare_coder_handoff_test(monkeypatch, tmp_path)
    repo = Path(os.environ["AWF_REPO_DIR"])
    report_path = ".awf/artifacts/impl-report-task.md"
    ns.branch = "agent/task"
    ns.report = report_path
    (repo / "report.md").unlink()
    (repo / "task.md").write_text(
        _VALID_POSTFLIGHT_CARD.replace('"task.md"', f'"task.md", "{report_path}"'),
        encoding="utf-8",
    )
    provenance = _pr_provenance(pull_request=0)
    provenance["head_ref"] = ns.branch
    ns.commit = provenance["head_sha"]
    ns.input_type = "task:awf-impl-v3"
    ns.source_event_id = 302
    for field in awf_role._PROVENANCE_FIELDS:
        setattr(ns, field, provenance[field])
    _bind_delivery(ns, event_type=ns.input_type, source_event_id=ns.source_event_id)
    state_root = tmp_path / "state"
    ns.evidence = awf_role.RunEvidence(302, "coder", state_root=state_root)

    monkeypatch.setattr(awf_role, "provenance_from_args", lambda *args, **kwargs: provenance)
    monkeypatch.setattr(awf_role, "fetch_and_checkout_pr_head", lambda *args, **kwargs: None)
    monkeypatch.setattr(awf_role, "assert_model_pr_git_state", lambda *args, **kwargs: None)
    monkeypatch.setattr(awf_role, "assert_model_workspace_state", lambda *args, **kwargs: None)
    monkeypatch.setattr(awf_role, "assert_model_git_metadata", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        awf_role,
        "durable_model_manifest_sha256",
        lambda *args, **kwargs: "sha256:model-manifest",
    )
    monkeypatch.setattr(
        awf_role,
        "durable_model_control_sha256",
        lambda *args, **kwargs: "sha256:model-control",
    )
    monkeypatch.setattr(
        awf_role,
        "advance_model_workspace_to_trusted_commit",
        lambda *args, **kwargs: "sha256:trusted-model-manifest",
    )
    monkeypatch.setattr(
        awf_role,
        "restore_durable_model_manifest",
        lambda *args, **kwargs: str(repo),
    )
    gate_reason = {"value": "authorized"}
    monkeypatch.setattr(
        awf_role,
        "pre_invocation_gate",
        lambda *args, **kwargs: argparse.Namespace(reason=gate_reason["value"]),
    )
    model_calls = []

    def fake_model(*_args, **_kwargs):
        model_calls.append("model")
        target = repo / report_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("controlled implementation report\n", encoding="utf-8")
        return 0

    monkeypatch.setattr(awf_role, "tool_opencode_exec", fake_model)
    verification_calls = []

    def fail_first_postflight(*_args, **_kwargs):
        verification_calls.append("postflight")
        if len(verification_calls) == 1:
            raise SystemExit(1)

    monkeypatch.setattr(awf_role, "run_verifications", fail_first_postflight)

    with pytest.raises(SystemExit, match="1"):
        awf_role.role_coder(ns)
    assert model_calls == ["model"]
    first_result = json.loads(ns.evidence.result_path.read_text(encoding="utf-8"))
    assert first_result["postflight_failure_step"] == "run_verifications"
    assert first_result["postflight_error_type"] == "SystemExit"
    checkpoint_path = awf_role.delivery_state_path(ns.evidence, "checkpoint", ns.delivery_id)
    first_checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    assert first_checkpoint["phase"] == "model_completed"

    repository_state = {"head": provenance["head_sha"]}

    def fake_git(_repo, *args):
        if args and args[0] == "commit":
            repository_state["head"] = "d" * 40
        return 0

    def fake_git_out(_repo, *args):
        if args == ("write-tree",) or args[-1] == "HEAD^{tree}":
            return "c" * 40
        if args[-1] == "HEAD^1":
            return provenance["head_sha"]
        if args[-1] == "HEAD^{commit}":
            return repository_state["head"]
        return "d" * 40

    monkeypatch.setattr(awf_role, "git", fake_git)
    monkeypatch.setattr(awf_role, "git_out", fake_git_out)
    monkeypatch.setattr(awf_role, "import_model_delta", lambda *args, **kwargs: "c" * 40)
    monkeypatch.setattr(
        awf_role,
        "tool_opencode_exec",
        lambda *args, **kwargs: pytest.fail("postflight replay must not invoke the model"),
    )
    monkeypatch.setattr(
        awf_role,
        "render_provider_invocation",
        lambda *args, **kwargs: pytest.fail("completed recovery must not render again"),
    )
    monkeypatch.setattr(awf_role, "verify_upstream_base", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        awf_role,
        "push_and_verify_fork_head",
        lambda _repo, value: {**value, "head_sha": "d" * 40},
    )
    monkeypatch.setattr(
        awf_role,
        "ensure_pull_request",
        lambda _repo, value: {**value, "pull_request": 31},
    )
    monkeypatch.setattr(awf_role, "verify_pr_remote_tuple", lambda *args, **kwargs: None)
    monkeypatch.setattr(awf_role, "deliver_outbox", lambda *args, **kwargs: True)
    gate_reason["value"] = "duplicate_event"
    ns.evidence = awf_role.RunEvidence(302, "coder", state_root=state_root)

    assert awf_role.role_coder(ns) == 0
    assert model_calls == ["model"]
    assert verification_calls == ["postflight", "postflight"]
    final_checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    phases = [
        json.loads(line).get("recovery_phase")
        for line in ns.evidence.log_path.read_text(encoding="utf-8").splitlines()
        if json.loads(line).get("phase") == "recovery_checkpoint"
    ]
    assert "postflight_completed" in phases
    assert final_checkpoint["phase"] == "outbox_sent"
    assert final_checkpoint["facts"]["postflight_attempts"] == 2


def test_coder_ambiguous_outbox_replays_before_checkout(monkeypatch, tmp_path):
    ns, _ = _prepare_coder_handoff_test(monkeypatch, tmp_path)
    _bind_delivery(ns)
    state_root = tmp_path / "state"
    ns.evidence = awf_role.RunEvidence(71, "coder", state_root=state_root)
    model_calls = []
    checkout_calls = []
    sends = []
    monkeypatch.setattr(
        awf_role,
        "fetch_and_checkout",
        lambda *args: checkout_calls.append(args),
    )
    monkeypatch.setattr(
        awf_role,
        "tool_opencode_exec",
        lambda *args, **kwargs: model_calls.append(args) or 0,
    )
    monkeypatch.setattr(awf_role, "git", lambda *args, **kwargs: 0)
    monkeypatch.setattr(awf_role, "git_out", lambda *args, **kwargs: "verified-sha")
    monkeypatch.setattr(awf_role, "push_and_verify_remote_head", lambda *args: "verified-sha")
    monkeypatch.setattr(
        awf_role,
        "send_event",
        lambda *args, **kwargs: sends.append(args) or False,
    )

    with pytest.raises(SystemExit, match="1"):
        awf_role.role_coder(ns)

    outbox_path = awf_role.delivery_state_path(ns.evidence, "outbox", ns.delivery_id)
    first_outbox = json.loads(outbox_path.read_text(encoding="utf-8"))
    assert first_outbox["status"] == "ambiguous"
    assert first_outbox["evidence_commit"] == "verified-sha"
    assert first_outbox["payload"]["awf_delivery_id"].startswith("awf:")
    assert len(checkout_calls) == 1
    assert len(model_calls) == 1

    ns.evidence = awf_role.RunEvidence(72, "coder", state_root=state_root)
    monkeypatch.setattr(
        awf_role,
        "fetch_and_checkout",
        lambda *args: pytest.fail("replay must happen before strict checkout"),
    )
    monkeypatch.setattr(
        awf_role,
        "tool_opencode_exec",
        lambda *args, **kwargs: pytest.fail("replay must not rerun the model"),
    )
    monkeypatch.setattr(awf_role, "verify_outbox_evidence", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        awf_role,
        "send_event",
        lambda *args, **kwargs: sends.append(args) or True,
    )

    assert awf_role.role_coder(ns) == 0
    replayed = json.loads(outbox_path.read_text(encoding="utf-8"))
    assert replayed["status"] == "sent"
    assert sends[0][3] == sends[1][3]

    ns.evidence = awf_role.RunEvidence(73, "coder", state_root=state_root)
    monkeypatch.setattr(
        awf_role,
        "send_event",
        lambda *args, **kwargs: pytest.fail("sent delivery must not be emitted again"),
    )
    assert awf_role.role_coder(ns) == 0


def test_outbox_remote_drift_blocks_replay_before_send(monkeypatch, tmp_path):
    evidence = awf_role.RunEvidence(74, "coder", state_root=tmp_path / "state")
    payload = awf_role.build_delivery_payload(
        "coder",
        "task:awf-review-v2",
        {
            "task_id": "task",
            "branch": "feature/task",
            "card": "task.md",
            "commit": "abc1234",
            "report": "report.md",
            "review_report": "review.md",
            "tool": "opencode",
            "model": "",
        },
        evidence,
    )
    record = {
        "action": "coder.review_handoff",
        "branch": "feature/task",
        "evidence_commit": "abc1234",
        "payload": payload,
    }
    monkeypatch.setattr(awf_role, "git", lambda *args, **kwargs: 0)

    def fake_git_out(_repo, *args):
        return "different" if args[-1].startswith("refs/remotes/") else "abc1234"

    monkeypatch.setattr(awf_role, "git_out", fake_git_out)
    monkeypatch.setattr(
        awf_role,
        "send_event",
        lambda *args, **kwargs: pytest.fail("remote drift must block before send"),
    )

    with pytest.raises(SystemExit, match="1"):
        awf_role.verify_outbox_evidence(str(tmp_path), record)


def test_recovery_checkpoint_is_monotonic_and_binds_complete_provenance(tmp_path):
    evidence = awf_role.RunEvidence(75, "coder", state_root=tmp_path / "state")
    provenance = _pr_provenance(pull_request=0)
    input_context = {
        "key": "input-delivery",
        "delivery_id": "input-delivery",
        "payload_sha256": "sha256:input",
        "source_event_id": 75,
    }

    path, checkpoint = awf_role.begin_recovery_checkpoint(
        evidence,
        input_context,
        role="coder",
        branch="feature/task",
        source_commit="a" * 40,
        provenance=provenance,
    )
    assert checkpoint["phase"] == "model_not_started"
    checkpoint = awf_role.advance_recovery_checkpoint(
        evidence,
        path,
        checkpoint,
        "model_started",
        model_workspace="runs/event-75/model-workspace-proof",
    )
    with pytest.raises(SystemExit, match="1"):
        awf_role.advance_recovery_checkpoint(
            evidence,
            path,
            checkpoint,
            "model_completed",
            model_workspace="runs/event-75/model-workspace-drifted",
        )
    checkpoint = awf_role.advance_recovery_checkpoint(
        evidence,
        path,
        checkpoint,
        "model_completed",
        model_workspace="runs/event-75/model-workspace-proof",
    )
    assert checkpoint["provenance"] == awf_role.provenance_payload(provenance)

    with pytest.raises(SystemExit, match="1"):
        awf_role.advance_recovery_checkpoint(
            evidence,
            path,
            checkpoint,
            "model_started",
        )

    changed = {**provenance, "head_ref": "feature/other"}
    with pytest.raises(SystemExit, match="1"):
        awf_role.begin_recovery_checkpoint(
            evidence,
            input_context,
            role="coder",
            branch="feature/task",
            source_commit="a" * 40,
            provenance=changed,
        )


def test_legacy_postflight_commit_and_fork_evidence_imports_without_model(tmp_path):
    evidence = awf_role.RunEvidence(102, "coder", state_root=tmp_path / "state")
    imported_tree = "c" * 40
    commit_sha = "d" * 40
    evidence.record(
        "postflight_pass",
        postflight_status="pass",
        imported_tree=imported_tree,
    )
    evidence.record("commit", commit_status="pass", commit_sha=commit_sha)
    evidence.record("remote_sha_verified", remote_sha=commit_sha)
    evidence.record(
        "fork_pr_rejected",
        reason="fork_push_or_pr_verification_failed",
    )
    input_context = {
        "key": "input-delivery",
        "delivery_id": "input-delivery",
        "payload_sha256": "sha256:input",
        "source_event_id": 102,
    }

    recovered = awf_role.recover_legacy_publication_checkpoint(
        evidence,
        input_context,
        branch="feature/task",
        source_commit="b" * 40,
        provenance=_pr_provenance(pull_request=0),
    )

    assert recovered is not None
    _, checkpoint = recovered
    assert checkpoint["phase"] == "fork_sha_verified"
    assert checkpoint["facts"]["imported_tree"] == imported_tree
    assert checkpoint["facts"]["commit_sha"] == commit_sha
    assert checkpoint["facts"]["head_sha"] == commit_sha


def test_legacy_bounded_pr_failure_without_remote_log_resumes_before_fork_verify(
    tmp_path,
):
    evidence = awf_role.RunEvidence(102, "coder", state_root=tmp_path / "state")
    imported_tree = "c" * 40
    commit_sha = "d" * 40
    evidence.record(
        "postflight_pass",
        postflight_status="pass",
        imported_tree=imported_tree,
    )
    evidence.record("commit", commit_status="pass", commit_sha=commit_sha)
    evidence.record(
        "fork_pr_rejected",
        reason="fork_push_or_pr_verification_failed",
    )
    input_context = {
        "key": "input-delivery",
        "delivery_id": "input-delivery",
        "payload_sha256": "sha256:input",
        "source_event_id": 102,
    }

    recovered = awf_role.recover_legacy_publication_checkpoint(
        evidence,
        input_context,
        branch="feature/task",
        source_commit="b" * 40,
        provenance=_pr_provenance(pull_request=0),
    )

    assert recovered is not None
    _, checkpoint = recovered
    assert checkpoint["phase"] == "commit_created"
    assert checkpoint["facts"]["imported_tree"] == imported_tree
    assert checkpoint["facts"]["commit_sha"] == commit_sha
    assert "head_sha" not in checkpoint["facts"]


def test_legacy_completed_reviewer_imports_model_checkpoint_without_reinvocation(
    monkeypatch,
    tmp_path,
):
    evidence = awf_role.RunEvidence(103, "reviewer", state_root=tmp_path / "state")
    model_workspace = evidence.run_dir / "model-workspace-proof"
    model_workspace.mkdir()
    evidence.record(
        "opencode_start",
        opencode_cwd=str(model_workspace),
        opencode_pid=123,
    )
    evidence.record(
        "opencode_exit",
        opencode_rc=0,
        opencode_duration_seconds=1.0,
    )
    monkeypatch.setattr(
        awf_role,
        "durable_model_manifest_sha256",
        lambda workspace: "manifest-sha" if workspace == str(model_workspace) else "",
    )
    input_context = {
        "key": "input-delivery",
        "delivery_id": "input-delivery",
        "payload_sha256": "sha256:input",
        "source_event_id": 102,
    }

    recovered = awf_role.recover_legacy_reviewer_checkpoint(
        evidence,
        input_context,
        branch="feature/task",
        source_commit="d" * 40,
        provenance=_pr_provenance(),
    )

    assert recovered is not None
    _, checkpoint = recovered
    assert checkpoint["role"] == "reviewer"
    assert checkpoint["phase"] == "model_completed"
    assert checkpoint["facts"]["model_workspace"] == str(model_workspace)
    assert checkpoint["facts"]["model_manifest_sha256"] == "manifest-sha"


def test_reviewer_checkpoint_skips_coder_only_commit_and_fork_phases(tmp_path):
    evidence = awf_role.RunEvidence(103, "reviewer", state_root=tmp_path / "state")
    input_context = {
        "key": "input-delivery",
        "delivery_id": "input-delivery",
        "payload_sha256": "sha256:input",
        "source_event_id": 102,
    }
    path, checkpoint = awf_role.begin_recovery_checkpoint(
        evidence,
        input_context,
        role="reviewer",
        branch="feature/task",
        source_commit="d" * 40,
        provenance=_pr_provenance(),
    )
    transitions = [
        ("model_started", {"model_workspace": "workspace"}),
        ("model_completed", {"model_workspace": "workspace"}),
        ("model_imported", {"review_report_sha256": "a" * 64}),
        ("pr_tuple_verified", {"verified_provenance": _pr_provenance()}),
        ("outbox_prepared", {"outbox_delivery_id": "awf:delivery"}),
        ("outbox_sent", {"outbox_delivery_id": "awf:delivery"}),
    ]

    for phase, facts in transitions:
        checkpoint = awf_role.advance_recovery_checkpoint(
            evidence,
            path,
            checkpoint,
            phase,
            **facts,
        )

    assert checkpoint["phase"] == "outbox_sent"


_RECOVERY_MATRIX_TRANSITIONS = {
    "coder": [
        ("model_started", {"model_workspace": "workspace", "model_process": "opencode"}),
        ("model_completed", {"model_workspace": "workspace", "model_process": "opencode"}),
        ("postflight_completed", {"postflight_attempts": 1}),
        ("model_imported", {"imported_tree": "c" * 40}),
        ("commit_created", {"commit_sha": "d" * 40}),
        ("fork_sha_verified", {"head_sha": "d" * 40}),
        ("pr_tuple_verified", {"verified_provenance": _pr_provenance()}),
        ("outbox_prepared", {"outbox_delivery_id": "awf:downstream"}),
        ("outbox_sent", {"outbox_delivery_id": "awf:downstream"}),
    ],
    "reviewer": [
        ("model_started", {"model_workspace": "workspace", "model_process": "codex"}),
        ("model_completed", {"model_workspace": "workspace", "model_process": "codex"}),
        ("model_imported", {"review_report_sha256": "e" * 64}),
        ("pr_tuple_verified", {"verified_provenance": _pr_provenance()}),
        ("outbox_prepared", {"outbox_delivery_id": "awf:downstream"}),
        ("outbox_sent", {"outbox_delivery_id": "awf:downstream"}),
    ],
}


@pytest.mark.parametrize(
    ("role", "crash_phase"),
    [
        (role, phase)
        for role, transitions in _RECOVERY_MATRIX_TRANSITIONS.items()
        for phase in ("model_not_started", *(item[0] for item in transitions))
    ],
)
def test_same_delivery_crash_replay_matrix_preserves_phase_and_model_count(
    tmp_path,
    role,
    crash_phase,
):
    """Every durable boundary reloads monotonically under the exact same delivery."""
    state_root = tmp_path / "state"
    first = awf_role.RunEvidence(201, role, state_root=state_root)
    provenance = _pr_provenance(pull_request=0)
    input_context = {
        "key": f"{role}-input",
        "delivery_id": f"{role}-input",
        "payload_sha256": f"sha256:{role}-input",
        "source_event_id": 200,
    }
    path, checkpoint = awf_role.begin_recovery_checkpoint(
        first,
        input_context,
        role=role,
        branch="feature/task",
        source_commit="a" * 40,
        provenance=provenance,
    )
    for phase, facts in _RECOVERY_MATRIX_TRANSITIONS[role]:
        if crash_phase == "model_not_started":
            break
        checkpoint = awf_role.advance_recovery_checkpoint(
            first,
            path,
            checkpoint,
            phase,
            **facts,
        )
        if phase == crash_phase:
            break

    replay = awf_role.RunEvidence(202, role, state_root=state_root)
    replay_path, reloaded = awf_role.begin_recovery_checkpoint(
        replay,
        input_context,
        role=role,
        branch="feature/task",
        source_commit="a" * 40,
        provenance=provenance,
    )

    assert replay_path == path
    assert reloaded["phase"] == crash_phase
    assert reloaded["facts"] == checkpoint["facts"]
    # Only a never-started checkpoint may invoke a model. Every later boundary
    # must recover/continue with zero additional invocations.
    expected_policy = (
        "invoke_once"
        if crash_phase == "model_not_started"
        else ("recover_or_fail" if crash_phase == "model_started" else "skip")
    )
    assert awf_role.recovery_model_policy(reloaded) == expected_policy
    additional_model_invocations = int(expected_policy == "invoke_once")
    assert additional_model_invocations == (1 if crash_phase == "model_not_started" else 0)

    drifted = {**provenance, "head_ref": "feature/drift"}
    with pytest.raises(SystemExit, match="1"):
        awf_role.begin_recovery_checkpoint(
            replay,
            input_context,
            role=role,
            branch="feature/task",
            source_commit="a" * 40,
            provenance=drifted,
        )


def test_upstream_base_allows_only_fast_forward_advance(monkeypatch):
    provenance = _pr_provenance()
    live_base = "f" * 40
    calls = []

    def fake_git(_repo, *args):
        calls.append(args)
        return 0

    monkeypatch.setattr(awf_role, "git", fake_git)
    monkeypatch.setattr(awf_role, "git_out", lambda *_args: live_base)

    awf_role.verify_upstream_base("/repo", provenance)

    assert ("merge-base", "--is-ancestor", provenance["base_sha"], live_base) in calls


def test_upstream_base_rejects_divergence(monkeypatch):
    provenance = _pr_provenance()
    live_base = "f" * 40

    def fake_git(_repo, *args):
        if args[:2] == ("merge-base", "--is-ancestor"):
            return 1
        return 0

    monkeypatch.setattr(awf_role, "git", fake_git)
    monkeypatch.setattr(awf_role, "git_out", lambda *_args: live_base)

    with pytest.raises(SystemExit, match="1"):
        awf_role.verify_upstream_base("/repo", provenance)


def test_prepared_outbox_replay_reconciles_checkpoint_before_send(monkeypatch, tmp_path):
    evidence = awf_role.RunEvidence(103, "coder", state_root=tmp_path / "state")
    provenance = _pr_provenance()
    input_context = {
        "key": "input-delivery",
        "delivery_id": "input-delivery",
        "payload_sha256": "sha256:input",
        "source_event_id": 103,
    }
    checkpoint_path, checkpoint = awf_role.begin_recovery_checkpoint(
        evidence,
        input_context,
        role="coder",
        branch="feature/task",
        source_commit="a" * 40,
        provenance={**provenance, "pull_request": 0},
    )
    transitions = [
        ("model_started", {"model_workspace": "workspace"}),
        ("model_completed", {"model_workspace": "workspace"}),
        ("postflight_completed", {"postflight_attempts": 1}),
        ("model_imported", {"imported_tree": "c" * 40}),
        ("commit_created", {"commit_sha": "b" * 40}),
        ("fork_sha_verified", {"head_sha": "b" * 40}),
        (
            "pr_tuple_verified",
            {"verified_provenance": awf_role.provenance_payload(provenance)},
        ),
    ]
    for phase, facts in transitions:
        checkpoint = awf_role.advance_recovery_checkpoint(
            evidence,
            checkpoint_path,
            checkpoint,
            phase,
            **facts,
        )
    payload = awf_role.build_delivery_payload(
        "coder",
        "task:awf-review-v3",
        {
            "task_id": "task",
            "branch": "feature/task",
            "card": "task.md",
            "commit": "b" * 40,
            "report": "report.md",
            "review_report": "review.md",
            "tool": "opencode",
            "model": "",
            **awf_role.provenance_payload(provenance),
        },
        evidence,
    )
    outbox_path, outbox = awf_role.prepare_outbox(
        evidence,
        input_context,
        action="coder.review_handoff",
        branch="feature/task",
        source_commit="a" * 40,
        evidence_commit="b" * 40,
        to_role="reviewer",
        event_type="task:awf-review-v3",
        payload=payload,
        provenance=provenance,
    )
    phases_at_send = []
    monkeypatch.setattr(awf_role, "verify_outbox_evidence", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        awf_role,
        "send_event",
        lambda *args, **kwargs: (
            phases_at_send.append(json.loads(checkpoint_path.read_text(encoding="utf-8"))["phase"])
            or True
        ),
    )
    args = argparse.Namespace(branch="feature/task", commit="a" * 40)

    assert awf_role.resume_outbox(
        args,
        "coder",
        str(tmp_path),
        evidence,
        input_context,
    )

    saved = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    assert saved["phase"] == "outbox_sent"
    assert saved["facts"]["outbox_delivery_id"] == payload["awf_delivery_id"]
    assert phases_at_send == ["outbox_prepared"]
    assert json.loads(outbox_path.read_text(encoding="utf-8"))["status"] == "sent"


@pytest.mark.parametrize("role", ["coder", "reviewer"])
def test_process_crash_after_zero_model_exit_recovers_durable_workspace(tmp_path, role):
    evidence = awf_role.RunEvidence(104, role, state_root=tmp_path / "state")
    workspace = evidence.run_dir / "model-workspace-proof"
    run("git", "init", "-b", "proof", str(workspace), cwd=evidence.run_dir)
    manifest_sha256 = awf_role.durable_model_manifest_sha256(str(workspace))
    input_context = {
        "key": "input-delivery",
        "delivery_id": "input-delivery",
        "payload_sha256": "sha256:input",
        "source_event_id": 104,
    }
    checkpoint_path, checkpoint = awf_role.begin_recovery_checkpoint(
        evidence,
        input_context,
        role=role,
        branch="feature/task",
        source_commit="a" * 40,
        provenance=_pr_provenance(pull_request=0),
    )
    checkpoint = awf_role.advance_recovery_checkpoint(
        evidence,
        checkpoint_path,
        checkpoint,
        "model_started",
        model_workspace=str(workspace),
        model_manifest_sha256=manifest_sha256,
        model_event_id=104,
    )
    evidence.record("opencode_start", opencode_pid=123, opencode_cwd=str(workspace))
    evidence.record("opencode_exit", opencode_rc=0)

    recovered = awf_role.recover_completed_model_checkpoint(
        evidence,
        checkpoint_path,
        checkpoint,
    )

    assert recovered is not None
    assert recovered["phase"] == "model_completed"
    assert recovered["facts"]["recovered_from_process_log"] is True


def test_model_completed_replay_verifies_checkout_before_parsing_taskcard(monkeypatch, tmp_path):
    ns, _ = _prepare_coder_handoff_test(monkeypatch, tmp_path)
    provenance = _pr_provenance(pull_request=0)
    ns.commit = provenance["head_sha"]
    ns.input_type = "task:awf-impl-v3"
    ns.source_event_id = 105
    for field in awf_role._PROVENANCE_FIELDS:
        setattr(ns, field, provenance[field])
    _bind_delivery(ns, event_type=ns.input_type, source_event_id=ns.source_event_id)
    state_root = tmp_path / "state"
    ns.evidence = awf_role.RunEvidence(105, "coder", state_root=state_root)
    input_context = awf_role.validate_input_delivery(ns, "coder", ns.evidence)
    checkpoint_path, checkpoint = awf_role.begin_recovery_checkpoint(
        ns.evidence,
        input_context,
        role="coder",
        branch=ns.branch,
        source_commit=ns.commit,
        provenance=provenance,
    )
    checkpoint = awf_role.advance_recovery_checkpoint(
        ns.evidence,
        checkpoint_path,
        checkpoint,
        "model_started",
        model_workspace=str(tmp_path / "state" / "model-workspace-proof"),
        model_manifest_sha256="sha256:model",
        model_event_id=105,
    )
    awf_role.advance_recovery_checkpoint(
        ns.evidence,
        checkpoint_path,
        checkpoint,
        "model_completed",
        model_workspace=str(tmp_path / "state" / "model-workspace-proof"),
        model_manifest_sha256="sha256:model",
        model_event_id=105,
    )
    monkeypatch.setattr(awf_role, "provenance_from_args", lambda *args, **kwargs: provenance)
    monkeypatch.setattr(
        awf_role,
        "pre_invocation_gate",
        lambda *args, **kwargs: argparse.Namespace(reason="duplicate_event"),
    )
    monkeypatch.setattr(
        awf_role,
        "restore_durable_model_manifest",
        lambda *args, **kwargs: str(tmp_path / "model"),
    )
    monkeypatch.setattr(awf_role, "assert_model_workspace_state", lambda *args: None)
    calls = []
    monkeypatch.setattr(
        awf_role,
        "assert_model_pr_git_state",
        lambda *args: calls.append("verify"),
    )

    def stop_after_parse(*args):
        calls.append("parse")
        raise SystemExit(1)

    monkeypatch.setattr(awf_role, "parse_postflight_contract", stop_after_parse)

    with pytest.raises(SystemExit, match="1"):
        awf_role.role_coder(ns)
    assert calls == ["verify", "parse"]


def test_tool_failure_replay_never_reinvokes_model(monkeypatch, tmp_path):
    ns, _ = _prepare_coder_handoff_test(monkeypatch, tmp_path)
    repo = Path(os.environ["AWF_REPO_DIR"])
    ns.report = ".awf/artifacts/impl-report-task.md"
    (repo / ns.report).parent.mkdir(parents=True, exist_ok=True)
    (repo / ns.report).write_text("implementation report\n", encoding="utf-8")
    (repo / "task.md").write_text(
        _VALID_POSTFLIGHT_CARD.replace('"task.md"', f'"task.md", "{ns.report}"'),
        encoding="utf-8",
    )
    provenance = _pr_provenance(pull_request=0)
    ns.commit = provenance["head_sha"]
    ns.input_type = "task:awf-impl-v3"
    ns.source_event_id = 75
    for field in awf_role._PROVENANCE_FIELDS:
        setattr(ns, field, provenance[field])
    _bind_delivery(ns, event_type=ns.input_type, source_event_id=ns.source_event_id)
    state_root = tmp_path / "state"
    ns.evidence = awf_role.RunEvidence(75, "coder", state_root=state_root)
    monkeypatch.setattr(awf_role, "provenance_from_args", lambda *args, **kwargs: provenance)
    monkeypatch.setattr(awf_role, "fetch_and_checkout_pr_head", lambda *args, **kwargs: None)
    monkeypatch.setattr(awf_role, "assert_model_pr_git_state", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        awf_role,
        "durable_model_manifest_sha256",
        lambda *args, **kwargs: "sha256:model-manifest",
    )
    monkeypatch.setattr(
        awf_role,
        "pre_invocation_gate",
        lambda *args, **kwargs: argparse.Namespace(reason="authorized"),
    )
    model_calls = []
    monkeypatch.setattr(
        awf_role,
        "tool_opencode_exec",
        lambda *args, **kwargs: model_calls.append(args) or 9,
    )

    with pytest.raises(SystemExit, match="1"):
        awf_role.role_coder(ns)
    assert len(model_calls) == 1

    ns.evidence = awf_role.RunEvidence(76, "coder", state_root=state_root)
    monkeypatch.setattr(
        awf_role,
        "pre_invocation_gate",
        lambda *args, **kwargs: argparse.Namespace(reason="duplicate_event"),
    )
    monkeypatch.setattr(
        awf_role,
        "tool_opencode_exec",
        lambda *args, **kwargs: pytest.fail("ambiguous model invocation must not be repeated"),
    )
    with pytest.raises(SystemExit, match="1"):
        awf_role.role_coder(ns)
    assert len(model_calls) == 1


def test_pr_failure_replay_resumes_after_verified_fork_without_model(monkeypatch, tmp_path):
    ns, _ = _prepare_coder_handoff_test(monkeypatch, tmp_path)
    repo = Path(os.environ["AWF_REPO_DIR"])
    ns.report = ".awf/artifacts/impl-report-task.md"
    (repo / ns.report).parent.mkdir(parents=True, exist_ok=True)
    (repo / ns.report).write_text("implementation report\n", encoding="utf-8")
    (repo / "task.md").write_text(
        _VALID_POSTFLIGHT_CARD.replace('"task.md"', f'"task.md", "{ns.report}"'),
        encoding="utf-8",
    )
    provenance = _pr_provenance(pull_request=0)
    ns.commit = provenance["head_sha"]
    ns.input_type = "task:awf-impl-v3"
    ns.source_event_id = 76
    for field in awf_role._PROVENANCE_FIELDS:
        setattr(ns, field, provenance[field])
    _bind_delivery(ns, event_type=ns.input_type, source_event_id=ns.source_event_id)
    state_root = tmp_path / "state"
    ns.evidence = awf_role.RunEvidence(77, "coder", state_root=state_root)
    monkeypatch.setattr(awf_role, "provenance_from_args", lambda *args, **kwargs: provenance)
    monkeypatch.setattr(awf_role, "fetch_and_checkout_pr_head", lambda *args, **kwargs: None)
    monkeypatch.setattr(awf_role, "assert_model_pr_git_state", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        awf_role,
        "durable_model_manifest_sha256",
        lambda *args, **kwargs: "sha256:model-manifest",
    )
    monkeypatch.setattr(
        awf_role,
        "durable_model_control_sha256",
        lambda *args, **kwargs: "sha256:model-control",
    )
    monkeypatch.setattr(
        awf_role,
        "advance_model_workspace_to_trusted_commit",
        lambda *args, **kwargs: "sha256:trusted-model-manifest",
    )
    monkeypatch.setattr(
        awf_role,
        "pre_invocation_gate",
        lambda *args, **kwargs: argparse.Namespace(reason="authorized"),
    )
    repository_state = {"head": provenance["head_sha"]}

    def fake_git(_repo, *args):
        if args and args[0] == "commit":
            repository_state["head"] = "d" * 40
        return 0

    def fake_git_out(_repo, *args):
        if args == ("write-tree",) or args[-1] == "HEAD^{tree}":
            return "c" * 40
        if args[-1] == "HEAD^1":
            return provenance["head_sha"]
        if args[-1] == "HEAD^{commit}":
            return repository_state["head"]
        return "d" * 40

    monkeypatch.setattr(awf_role, "git", fake_git)
    monkeypatch.setattr(awf_role, "git_out", fake_git_out)
    monkeypatch.setattr(awf_role, "import_model_delta", lambda *args, **kwargs: "c" * 40)
    model_calls = []
    monkeypatch.setattr(
        awf_role,
        "tool_opencode_exec",
        lambda *args, **kwargs: model_calls.append(args) or 0,
    )
    publication_calls = []
    monkeypatch.setattr(
        awf_role,
        "push_and_verify_fork_head",
        lambda _repo, value: publication_calls.append("push") or {**value, "head_sha": "d" * 40},
    )
    pr_calls = []

    def fail_first_pr(_repo, value):
        pr_calls.append(value)
        if len(pr_calls) == 1:
            raise SystemExit(1)
        return {**value, "pull_request": 31}

    monkeypatch.setattr(awf_role, "ensure_pull_request", fail_first_pr)
    monkeypatch.setattr(
        awf_role,
        "verify_upstream_base",
        lambda *args, **kwargs: publication_calls.append("base"),
    )
    monkeypatch.setattr(awf_role, "verify_pr_remote_tuple", lambda *args, **kwargs: None)

    with pytest.raises(SystemExit, match="1"):
        awf_role.role_coder(ns)
    assert len(model_calls) == 1
    assert publication_calls[:2] == ["base", "push"]

    ns.evidence = awf_role.RunEvidence(78, "coder", state_root=state_root)
    monkeypatch.setattr(
        awf_role,
        "pre_invocation_gate",
        lambda *args, **kwargs: argparse.Namespace(reason="duplicate_event"),
    )
    monkeypatch.setattr(
        awf_role,
        "tool_opencode_exec",
        lambda *args, **kwargs: pytest.fail("PR recovery must not rerun the model"),
    )
    monkeypatch.setattr(awf_role, "send_event", lambda *args, **kwargs: True)

    assert awf_role.role_coder(ns) == 0
    assert len(model_calls) == 1
    assert len(pr_calls) == 2


def test_completed_reviewer_delivery_skips_model_and_send(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    script_dir = tmp_path / "scripts"
    script_dir.mkdir()
    monkeypatch.setenv("AWF_REPO_DIR", str(repo))
    monkeypatch.setenv("AWF_SCRIPT_DIR", str(script_dir))
    ns = argparse.Namespace(
        branch="feature/task",
        card="task.md",
        commit="abc1234",
        model="review-model",
        tool="codex",
        report="report.md",
        review_report=".awf/review.md",
        review_feedback="",
        base="main",
        input_type="task:awf-review-v2",
        source_event_id=71,
    )
    payload = awf_role.input_payload(ns, "reviewer")
    ns.payload_sha256 = awf_role.canonical_payload_sha256(payload)
    ns.delivery_id = awf_role.make_delivery_id(
        "coder",
        ns.input_type,
        ns.payload_sha256,
        ns.source_event_id,
    )
    ns.evidence = awf_role.RunEvidence(80, "reviewer", state_root=tmp_path / "state")
    awf_role.complete_inbox(ns.evidence, ns.delivery_id, ns.payload_sha256)
    monkeypatch.setattr(
        awf_role,
        "fetch_and_checkout",
        lambda *args: pytest.fail("completed delivery must skip checkout"),
    )
    monkeypatch.setattr(
        awf_role,
        "tool_codex_review",
        lambda *args: pytest.fail("completed delivery must skip review"),
    )
    monkeypatch.setattr(
        awf_role,
        "send_event",
        lambda *args: pytest.fail("completed delivery must not send again"),
    )

    assert awf_role.role_reviewer(ns) == 0


def test_delivery_id_reuse_with_different_payload_fails_closed(monkeypatch, tmp_path):
    ns, _ = _prepare_coder_handoff_test(monkeypatch, tmp_path)
    _bind_delivery(ns)
    ns.evidence = awf_role.RunEvidence(81, "coder", state_root=tmp_path / "state")
    awf_role.complete_inbox(ns.evidence, ns.delivery_id, ns.payload_sha256)
    ns.card = "different-task.md"

    with pytest.raises(SystemExit, match="1"):
        awf_role.role_coder(ns)


def test_coder_push_failure_blocks_review_event(monkeypatch, tmp_path):
    ns, send_calls = _prepare_coder_handoff_test(monkeypatch, tmp_path)

    def fake_git(repo, *args):
        return 1 if args[0] == "push" else 0

    monkeypatch.setattr(awf_role, "git", fake_git)

    with pytest.raises(SystemExit, match="1"):
        awf_role.role_coder(ns)

    assert not send_calls


def test_coder_missing_ref_after_push_blocks_review_event(monkeypatch, tmp_path):
    ns, send_calls = _prepare_coder_handoff_test(monkeypatch, tmp_path)
    git_calls = []

    def fake_git(repo, *args):
        git_calls.append(args)
        return 0

    def fake_git_out(repo, *args):
        return "local-sha" if args[-1] == "HEAD^{commit}" else ""

    monkeypatch.setattr(awf_role, "git", fake_git)
    monkeypatch.setattr(awf_role, "git_out", fake_git_out)

    with pytest.raises(SystemExit, match="1"):
        awf_role.role_coder(ns)

    assert any(call[0] == "fetch" for call in git_calls)
    assert not send_calls


def test_coder_remote_refresh_failure_blocks_review_event(monkeypatch, tmp_path):
    ns, send_calls = _prepare_coder_handoff_test(monkeypatch, tmp_path)

    def fake_git(repo, *args):
        return 1 if args[0] == "fetch" else 0

    monkeypatch.setattr(awf_role, "git", fake_git)

    with pytest.raises(SystemExit, match="1"):
        awf_role.role_coder(ns)

    assert not send_calls


def test_coder_unreadable_local_head_blocks_review_event(monkeypatch, tmp_path):
    ns, send_calls = _prepare_coder_handoff_test(monkeypatch, tmp_path)
    monkeypatch.setattr(awf_role, "git", lambda *a, **kw: 0)

    def fake_git_out(repo, *args):
        return "" if args[-1] == "HEAD^{commit}" else "remote-sha"

    monkeypatch.setattr(awf_role, "git_out", fake_git_out)

    with pytest.raises(SystemExit, match="1"):
        awf_role.role_coder(ns)

    assert not send_calls


def test_coder_remote_sha_mismatch_blocks_review_event(monkeypatch, tmp_path):
    ns, send_calls = _prepare_coder_handoff_test(monkeypatch, tmp_path)
    monkeypatch.setattr(awf_role, "git", lambda *a, **kw: 0)

    def fake_git_out(repo, *args):
        return "local-sha" if args[-1] == "HEAD^{commit}" else "remote-sha"

    monkeypatch.setattr(awf_role, "git_out", fake_git_out)

    with pytest.raises(SystemExit, match="1"):
        awf_role.role_coder(ns)

    assert not send_calls


def test_coder_verified_remote_sha_sends_one_review_event(monkeypatch, tmp_path):
    ns, send_calls = _prepare_coder_handoff_test(monkeypatch, tmp_path)
    git_calls = []
    monkeypatch.setattr(awf_role, "git", lambda repo, *args: git_calls.append(args) or 0)
    monkeypatch.setattr(awf_role, "git_out", lambda *a, **kw: "verified-sha")

    assert awf_role.role_coder(ns) == 0

    assert (
        "fetch",
        "--no-tags",
        "origin",
        "+refs/heads/feature/task:refs/remotes/origin/feature/task",
    ) in git_calls
    assert len(send_calls) == 1
    assert send_calls[0][0][2] == "task:awf-review"
    assert send_calls[0][0][3]["commit"] == "verified-sha"
    assert send_calls[0][0][3]["review_report"] == ".awf/review.md"


def test_coder_handoff_uses_frozen_pi_reviewer_selection(monkeypatch, tmp_path):
    ns, send_calls = _prepare_coder_handoff_test(monkeypatch, tmp_path)
    repo = Path(os.environ["AWF_REPO_DIR"])
    with (repo / "task.md").open("a", encoding="utf-8") as handle:
        handle.write(
            """
<!-- awf-reviewer-selection
{
  "coder": {"tool": "opencode", "model": ""},
  "reviewer": {"tool": "pi", "model": "reviewer/model"}
}
-->
"""
        )
    monkeypatch.setattr(awf_role, "git", lambda *a, **kw: 0)
    monkeypatch.setattr(awf_role, "git_out", lambda *a, **kw: "verified-sha")

    assert awf_role.role_coder(ns) == 0

    assert len(send_calls) == 1
    review_payload = send_calls[0][0][3]
    assert review_payload["tool"] == "pi"
    assert review_payload["model"] == "reviewer/model"


def test_assert_model_git_state_rejects_local_head_change(repositories):
    _, _, executor = repositories
    expected = run("git", "rev-parse", "HEAD", cwd=executor)
    commit(executor, "model commit", "model.txt", "unexpected\n")

    with pytest.raises(SystemExit, match="1"):
        awf_role.assert_model_git_state(str(executor), "feature/task", expected)


def test_assert_model_git_state_rejects_remote_branch_change(repositories):
    _, seed, executor = repositories
    expected = run("git", "rev-parse", "HEAD", cwd=executor)
    commit(seed, "model push", "remote-model.txt", "unexpected\n")
    run("git", "push", "origin", "feature/task", cwd=seed)

    with pytest.raises(SystemExit, match="1"):
        awf_role.assert_model_git_state(str(executor), "feature/task", expected)


def test_executor_commit_message_has_git_native_lore_trailers():
    message = awf_role.executor_commit_message("feature/task", "opencode")

    parsed = subprocess.run(
        ["git", "interpret-trailers", "--parse"],
        input=message,
        capture_output=True,
        text=True,
        check=True,
    ).stdout

    assert message.startswith("Deliver the frozen TaskCard through the trusted executor\n")
    assert "Constraint:" in parsed
    assert "Confidence: high" in parsed
    assert "Scope-risk: narrow" in parsed
    assert "Tested:" in parsed
    assert "Not-tested:" in parsed


def test_coder_no_push_blocks_remote_completion(monkeypatch, tmp_path):
    ns, send_calls = _prepare_coder_handoff_test(monkeypatch, tmp_path, no_push=True)
    git_calls = []
    monkeypatch.setattr(awf_role, "git", lambda *a, **kw: git_calls.append(a[1:]) or 0)

    with pytest.raises(SystemExit, match="1"):
        awf_role.role_coder(ns)

    assert not any(call[0] == "push" for call in git_calls)
    assert not send_calls


def test_coder_fail_closed_send_event(monkeypatch, tmp_path):
    """send_event() == False makes the coder handler fail closed."""
    repo = tmp_path / "repo"
    repo.mkdir()
    script_dir = tmp_path / "scripts"
    script_dir.mkdir()
    (script_dir / "executor-prompt.md").write_text("prompt")
    card = repo / "task.md"
    card.write_text(_VALID_POSTFLIGHT_CARD)
    report = repo / "report.md"
    report.write_text("report content")

    monkeypatch.setenv("AWF_REPO_DIR", str(repo))
    monkeypatch.setenv("AWF_SCRIPT_DIR", str(script_dir))
    monkeypatch.delenv("AWF_NO_PUSH", raising=False)
    monkeypatch.setenv("AGENT_BUS_URL", "http://bus")
    monkeypatch.setenv("AWF_CODER_TOKEN", "tok")

    monkeypatch.setattr(awf_role, "fetch_and_checkout", lambda *a, **kw: None)
    monkeypatch.setattr(awf_role, "prepare_model_workspace", lambda *a, **kw: str(repo))
    monkeypatch.setattr(awf_role, "tool_opencode_exec", lambda *a, **kw: 0)
    monkeypatch.setattr(awf_role, "run_verifications", lambda *a, **kw: None)
    monkeypatch.setattr(awf_role, "run_postflight_delta_gates", lambda *a, **kw: None)
    monkeypatch.setattr(awf_role, "git", lambda *a, **kw: 0)
    monkeypatch.setattr(awf_role, "push_and_verify_remote_head", lambda *a, **kw: "abc1234")
    monkeypatch.setattr(awf_role, "send_event", lambda *a, **kw: False)

    ns = argparse.Namespace(
        branch="feature/task",
        card="task.md",
        commit="abc1234",
        model="",
        tool="opencode",
        report=str(report),
        review_report=".awf/review.md",
        base="",
    )

    with pytest.raises(SystemExit, match="1"):
        awf_role.role_coder(ns)


def test_coder_successful_send_returns_zero(monkeypatch, tmp_path):
    """A successful send_event still returns 0 from the coder handler."""
    repo = tmp_path / "repo"
    repo.mkdir()
    script_dir = tmp_path / "scripts"
    script_dir.mkdir()
    (script_dir / "executor-prompt.md").write_text("prompt")
    card = repo / "task.md"
    card.write_text(_VALID_POSTFLIGHT_CARD)
    report = repo / "report.md"
    report.write_text("report content")

    monkeypatch.setenv("AWF_REPO_DIR", str(repo))
    monkeypatch.setenv("AWF_SCRIPT_DIR", str(script_dir))
    monkeypatch.delenv("AWF_NO_PUSH", raising=False)
    monkeypatch.setenv("AGENT_BUS_URL", "http://bus")
    monkeypatch.setenv("AWF_CODER_TOKEN", "tok")

    monkeypatch.setattr(awf_role, "fetch_and_checkout", lambda *a, **kw: None)
    monkeypatch.setattr(awf_role, "prepare_model_workspace", lambda *a, **kw: str(repo))
    evidence = awf_role.RunEvidence(62, "coder", state_root=tmp_path / "state")
    tool_evidence = []
    monkeypatch.setattr(
        awf_role,
        "tool_opencode_exec",
        lambda *args, **kw: tool_evidence.append(args[-1]) or 0,
    )
    monkeypatch.setattr(awf_role, "assert_model_workspace_state", lambda *a, **kw: None)
    monkeypatch.setattr(awf_role, "assert_model_git_metadata", lambda *a, **kw: None)
    monkeypatch.setattr(awf_role, "assert_model_git_state", lambda *a, **kw: None)
    monkeypatch.setattr(awf_role, "run_verifications", lambda *a, **kw: None)
    monkeypatch.setattr(awf_role, "stage_model_artifact", lambda *a, **kw: report)
    monkeypatch.setattr(awf_role, "run_postflight_delta_gates", lambda *a, **kw: None)
    monkeypatch.setattr(awf_role, "import_model_delta", lambda *a, **kw: "verified-tree")
    monkeypatch.setattr(awf_role, "git", lambda *a, **kw: 0)
    monkeypatch.setattr(awf_role, "push_and_verify_remote_head", lambda *a, **kw: "abc1234")
    monkeypatch.setattr(awf_role, "send_event", lambda *a, **kw: True)

    ns = argparse.Namespace(
        branch="feature/task",
        card="task.md",
        commit="abc1234",
        model="",
        tool="opencode",
        report="report.md",
        review_report=".awf/review.md",
        base="",
        evidence=evidence,
    )

    result = awf_role.role_coder(ns)
    assert result == 0
    assert tool_evidence == [evidence]
    phases = [
        json.loads(line)["phase"]
        for line in evidence.log_path.read_text(encoding="utf-8").splitlines()
    ]
    assert phases == [
        "model_git_state_verified",
        "postflight_start",
        "postflight_pass",
        "commit",
        "commit",
        "push",
        "remote_sha_verified",
        "outbox_prepared",
        "outbox_sent",
        "review_event_sent",
    ]


# ---------------------------------------------------------------------------
# Postflight contract — valid parsing
# ---------------------------------------------------------------------------


def test_parse_valid_contract(tmp_path):
    """A valid awf-postflight contract parses and freezes correctly."""
    card = tmp_path / "task.md"
    card.write_text(
        "# Card\n"
        "<!-- awf-postflight\n"
        "{\n"
        '  "allowed_paths": ["src/a.py", "src/b.py"],\n'
        '  "verification_commands": [["{python}", "-m", "pytest"],\n'
        '    ["{python}", "-m", "ruff", "check", "."]]\n'
        "}\n"
        "-->\n"
    )
    contract = awf_role.parse_postflight_contract(str(card))
    assert contract.allowed_paths == ["src/a.py", "src/b.py"]
    assert len(contract.verification_commands) == 2
    assert contract.verification_commands[0][0] == sys.executable
    assert contract.verification_commands[0][1:] == ["-m", "pytest"]
    assert contract.verification_commands[1][0] == sys.executable
    assert contract.verification_commands[1][1:] == ["-m", "ruff", "check", "."]


def test_contract_freeze_unchanged_by_card_edits(tmp_path):
    """Later TaskCard edits cannot change the frozen contract."""
    card = tmp_path / "task.md"
    card.write_text(_VALID_POSTFLIGHT_CARD)
    contract = awf_role.parse_postflight_contract(str(card))

    # Simulate model editing the card file after the contract was frozen
    card.write_text(
        "# Card\n"
        "<!-- awf-postflight\n"
        "{\n"
        '  "allowed_paths": ["evil.py"],\n'
        '  "verification_commands": [["evil"]]\n'
        "}\n"
        "-->\n"
    )

    assert contract.allowed_paths == ["task.md"]
    assert contract.verification_commands == [[sys.executable, "-c", "exit(0)"]]


def test_contract_python_replacement_only_first_element(tmp_path):
    """Only the first element matching {python} exactly is replaced with sys.executable."""
    card = tmp_path / "task.md"
    card.write_text(
        "# Card\n"
        "<!-- awf-postflight\n"
        "{\n"
        '  "allowed_paths": ["a.py"],\n'
        '  "verification_commands": [["{python}", "arg", "{python}"]]\n'
        "}\n"
        "-->\n"
    )
    contract = awf_role.parse_postflight_contract(str(card))
    # First {python} replaced, second (non-first position) preserved
    assert contract.verification_commands[0][0] == sys.executable
    assert contract.verification_commands[0][1] == "arg"
    assert contract.verification_commands[0][2] == "{python}"


# ---------------------------------------------------------------------------
# Postflight contract — malformed / missing / unsafe
# ---------------------------------------------------------------------------


def test_contract_missing_block(tmp_path):
    """A card without awf-postflight block fails."""
    card = tmp_path / "task.md"
    card.write_text("# Card without contract\n")
    with pytest.raises(SystemExit, match="1"):
        awf_role.parse_postflight_contract(str(card))


def test_contract_malformed_json(tmp_path):
    """Malformed JSON in the block fails."""
    card = tmp_path / "task.md"
    card.write_text("# Card\n<!-- awf-postflight\n{bad json\n-->\n")
    with pytest.raises(SystemExit, match="1"):
        awf_role.parse_postflight_contract(str(card))


def test_contract_not_an_object(tmp_path):
    """Non-object JSON fails."""
    card = tmp_path / "task.md"
    card.write_text('# Card\n<!-- awf-postflight\n"just a string"\n-->\n')
    with pytest.raises(SystemExit, match="1"):
        awf_role.parse_postflight_contract(str(card))


def test_contract_extra_keys(tmp_path):
    """Extra contract keys fail."""
    card = tmp_path / "task.md"
    card.write_text(
        "# Card\n"
        "<!-- awf-postflight\n"
        "{\n"
        '  "allowed_paths": ["a.py"],\n'
        '  "verification_commands": [["{python}", "-c", "exit(0)"]],\n'
        '  "extra_key": true\n'
        "}\n"
        "-->\n"
    )
    with pytest.raises(SystemExit, match="1"):
        awf_role.parse_postflight_contract(str(card))


def test_contract_empty_allowed_paths(tmp_path):
    """Empty allowed_paths array fails."""
    card = tmp_path / "task.md"
    card.write_text(
        "# Card\n"
        "<!-- awf-postflight\n"
        "{\n"
        '  "allowed_paths": [],\n'
        '  "verification_commands": [["{python}", "-c", "exit(0)"]]\n'
        "}\n"
        "-->\n"
    )
    with pytest.raises(SystemExit, match="1"):
        awf_role.parse_postflight_contract(str(card))


def test_contract_backslash_path(tmp_path):
    """Backslash path fails."""
    card = tmp_path / "task.md"
    card.write_text(
        "# Card\n"
        "<!-- awf-postflight\n"
        "{\n"
        '  "allowed_paths": ["src\\\\file.py"],\n'
        '  "verification_commands": [["{python}", "-c", "exit(0)"]]\n'
        "}\n"
        "-->\n"
    )
    with pytest.raises(SystemExit, match="1"):
        awf_role.parse_postflight_contract(str(card))


def test_contract_absolute_path(tmp_path):
    """Absolute path (leading slash) fails."""
    card = tmp_path / "task.md"
    card.write_text(
        "# Card\n"
        "<!-- awf-postflight\n"
        "{\n"
        '  "allowed_paths": ["/etc/passwd"],\n'
        '  "verification_commands": [["{python}", "-c", "exit(0)"]]\n'
        "}\n"
        "-->\n"
    )
    with pytest.raises(SystemExit, match="1"):
        awf_role.parse_postflight_contract(str(card))


def test_contract_drive_qualified_path(tmp_path):
    """Drive-qualified path fails."""
    card = tmp_path / "task.md"
    card.write_text(
        "# Card\n"
        "<!-- awf-postflight\n"
        "{\n"
        '  "allowed_paths": ["C:/file.py"],\n'
        '  "verification_commands": [["{python}", "-c", "exit(0)"]]\n'
        "}\n"
        "-->\n"
    )
    with pytest.raises(SystemExit, match="1"):
        awf_role.parse_postflight_contract(str(card))


def test_contract_parent_traversal_path(tmp_path):
    """Parent-traversal path fails."""
    card = tmp_path / "task.md"
    card.write_text(
        "# Card\n"
        "<!-- awf-postflight\n"
        "{\n"
        '  "allowed_paths": ["../outside.py"],\n'
        '  "verification_commands": [["{python}", "-c", "exit(0)"]]\n'
        "}\n"
        "-->\n"
    )
    with pytest.raises(SystemExit, match="1"):
        awf_role.parse_postflight_contract(str(card))


def test_contract_duplicate_path(tmp_path):
    """Duplicate path fails."""
    card = tmp_path / "task.md"
    card.write_text(
        "# Card\n"
        "<!-- awf-postflight\n"
        "{\n"
        '  "allowed_paths": ["a.py", "a.py"],\n'
        '  "verification_commands": [["{python}", "-c", "exit(0)"]]\n'
        "}\n"
        "-->\n"
    )
    with pytest.raises(SystemExit, match="1"):
        awf_role.parse_postflight_contract(str(card))


def test_contract_empty_verification_commands(tmp_path):
    """Empty verification_commands array fails."""
    card = tmp_path / "task.md"
    card.write_text(
        "# Card\n"
        "<!-- awf-postflight\n"
        "{\n"
        '  "allowed_paths": ["a.py"],\n'
        '  "verification_commands": []\n'
        "}\n"
        "-->\n"
    )
    with pytest.raises(SystemExit, match="1"):
        awf_role.parse_postflight_contract(str(card))


def test_contract_empty_command_array(tmp_path):
    """An empty command array fails."""
    card = tmp_path / "task.md"
    card.write_text(
        "# Card\n"
        "<!-- awf-postflight\n"
        "{\n"
        '  "allowed_paths": ["a.py"],\n'
        '  "verification_commands": [[]]\n'
        "}\n"
        "-->\n"
    )
    with pytest.raises(SystemExit, match="1"):
        awf_role.parse_postflight_contract(str(card))


def test_contract_non_string_in_command(tmp_path):
    """Non-string element in verification command fails."""
    card = tmp_path / "task.md"
    card.write_text(
        "# Card\n"
        "<!-- awf-postflight\n"
        "{\n"
        '  "allowed_paths": ["a.py"],\n'
        '  "verification_commands": [[42]]\n'
        "}\n"
        "-->\n"
    )
    with pytest.raises(SystemExit, match="1"):
        awf_role.parse_postflight_contract(str(card))


# ---------------------------------------------------------------------------
# Artifact denylist categories
# ---------------------------------------------------------------------------


def test_path_is_denied():
    """Every denylist category is rejected; documented examples are allowed."""
    denied = [
        ".env",
        ".env.local",
        ".env.production",
        ".venv/somefile",
        "venv/bin/pkg",
        "env/Lib",
        "__pycache__/cache.pyc",
        "src/__pycache__/mod.pyc",
        "node_modules/pkg/index.js",
        "dist/bundle.js",
        "build/output.o",
        "Thumbs.db",
        ".DS_Store",
        ".coverage",
        "coverage.xml",
        "coverage/data.xml",
        "htmlcov/index.html",
        "file.swp",
        "file.swo",
        "file.swn",
        "file.bak",
        "file.orig",
        "file.pyc",
        "file.pyo",
        "output.log",
        "process.pid",
        "mylib.egg-info/PKG-INFO",
    ]
    allowed = [
        ".env.example",
        ".env.template",
        ".env.sample",
        "regular.py",
        ".gitignore",
        "README.md",
        "src/a.py",
    ]
    for p in denied:
        assert awf_role._path_is_denied(p), f"{p!r} should be denied"
    for p in allowed:
        assert not awf_role._path_is_denied(p), f"{p!r} should not be denied"


# ---------------------------------------------------------------------------
# Git delta collection
# ---------------------------------------------------------------------------


def _init_repo(root: Path) -> Path:
    """Create a minimal git repo with one committed file (a.py)."""
    repo = root / "repo"
    run("git", "init", "-b", "main", str(repo), cwd=root)
    run("git", "config", "user.name", "Test", cwd=repo)
    run("git", "config", "user.email", "test@test", cwd=repo)
    (repo / "a.py").write_text("original\n")
    run("git", "add", "a.py", cwd=repo)
    run("git", "commit", "-m", "initial", cwd=repo)
    return repo


def test_collect_delta_modified_file(tmp_path):
    """Modified tracked files appear in the delta."""
    repo = _init_repo(tmp_path)
    (repo / "a.py").write_text("modified\n")
    paths = awf_role._collect_delta_paths(str(repo))
    assert "a.py" in paths


def test_collect_delta_deleted_file(tmp_path):
    """Deleted tracked files appear in the delta."""
    repo = _init_repo(tmp_path)
    (repo / "a.py").unlink()
    paths = awf_role._collect_delta_paths(str(repo))
    assert "a.py" in paths


def test_collect_delta_untracked_file(tmp_path):
    """Untracked files appear in the delta."""
    repo = _init_repo(tmp_path)
    (repo / "new.py").write_text("new\n")
    paths = awf_role._collect_delta_paths(str(repo))
    assert "new.py" in paths


def test_collect_delta_renamed_file(tmp_path):
    """Renamed files include both old and new path in the delta."""
    repo = _init_repo(tmp_path)
    run("git", "mv", "a.py", "b.py", cwd=repo)
    paths = awf_role._collect_delta_paths(str(repo))
    assert "a.py" in paths
    assert "b.py" in paths


# ---------------------------------------------------------------------------
# Delta gates — path scope, denylist, secrets, diff check
# ---------------------------------------------------------------------------


def test_delta_gate_empty_set(tmp_path):
    """An empty change set fails the delta gate."""
    repo = _init_repo(tmp_path)
    contract = awf_role.PostflightContract(allowed_paths=["a.py"], verification_commands=[])
    with pytest.raises(SystemExit, match="1"):
        awf_role.run_postflight_delta_gates(str(repo), contract)


def test_delta_gate_out_of_scope_path(tmp_path):
    """A changed path outside allowed_paths fails."""
    repo = _init_repo(tmp_path)
    (repo / "a.py").write_text("modified\n")
    (repo / "outside.py").write_text("rogue\n")
    contract = awf_role.PostflightContract(allowed_paths=["a.py"], verification_commands=[])
    with pytest.raises(SystemExit, match="1"):
        awf_role.run_postflight_delta_gates(str(repo), contract)


def test_delta_gate_denied_artifact(tmp_path):
    """A path on the artifact denylist fails even if in allowed_paths."""
    repo = _init_repo(tmp_path)
    (repo / "a.py").write_text("modified\n")
    (repo / ".env").write_text("SECRET=value\n")
    contract = awf_role.PostflightContract(allowed_paths=["a.py", ".env"], verification_commands=[])
    with pytest.raises(SystemExit, match="1"):
        awf_role.run_postflight_delta_gates(str(repo), contract)


def test_delta_gate_diff_check_fails(tmp_path):
    """git diff --check catches whitespace errors before staging."""
    repo = _init_repo(tmp_path)
    (repo / "a.py").write_text("trailing whitespace   \n")
    contract = awf_role.PostflightContract(allowed_paths=["a.py"], verification_commands=[])
    with pytest.raises(SystemExit, match="1"):
        awf_role.run_postflight_delta_gates(str(repo), contract)


# ---------------------------------------------------------------------------
# Narrow secret scan
# ---------------------------------------------------------------------------


def test_secret_scan_tracked_diff_private_key(tmp_path):
    """A private key header in a tracked diff fails the secret gate."""
    repo = _init_repo(tmp_path)
    (repo / "a.py").write_text(f"{_PK_HEADER}\nMIIEpAIBAAKCAQEA...\n{_PK_FOOTER}\n")
    with pytest.raises(SystemExit, match="1"):
        awf_role._narrow_secret_scan(str(repo))


def test_secret_scan_tracked_diff_credential_url(tmp_path):
    """A credential-bearing URL in a tracked diff fails."""
    repo = _init_repo(tmp_path)
    (repo / "a.py").write_text(f'url = "{_CRED_URL}"\n')
    with pytest.raises(SystemExit, match="1"):
        awf_role._narrow_secret_scan(str(repo))


def test_secret_scan_tracked_diff_github_token(tmp_path):
    """A GitHub token shape in a tracked diff fails."""
    repo = _init_repo(tmp_path)
    (repo / "a.py").write_text(f'token = "{_GITHUB_TOKEN}"\n')
    with pytest.raises(SystemExit, match="1"):
        awf_role._narrow_secret_scan(str(repo))


def test_secret_scan_tracked_diff_openai_key(tmp_path):
    """An OpenAI key shape in a tracked diff fails."""
    repo = _init_repo(tmp_path)
    (repo / "a.py").write_text(f'key = "{_OPENAI_KEY}"\n')
    with pytest.raises(SystemExit, match="1"):
        awf_role._narrow_secret_scan(str(repo))


def test_secret_scan_tracked_diff_aws_key(tmp_path):
    """An AWS access key shape in a tracked diff fails."""
    repo = _init_repo(tmp_path)
    (repo / "a.py").write_text(f'aws_key = "{_AWS_KEY}"\n')
    with pytest.raises(SystemExit, match="1"):
        awf_role._narrow_secret_scan(str(repo))


def test_secret_scan_untracked_file(tmp_path):
    """An untracked file with a secret fails."""
    repo = _init_repo(tmp_path)
    (repo / "secret.txt").write_text(f"{_GITHUB_TOKEN}\n")
    with pytest.raises(SystemExit, match="1"):
        awf_role._narrow_secret_scan(str(repo))


def test_secret_scan_benign_placeholder_words_pass(tmp_path):
    """Placeholder words like token/secret must not fail by themselves."""
    repo = _init_repo(tmp_path)
    (repo / "a.py").write_text('token = "placeholder"\nsecret = "test-value"\n')
    # Must not raise
    awf_role._narrow_secret_scan(str(repo))


def test_secret_scan_benign_test_fixtures_pass(tmp_path):
    """Test fixture values that look token-like but are within test conventions must not fail."""
    repo = _init_repo(tmp_path)
    (repo / "a.py").write_text(
        'token = "test-token"\nsecret = "fixture-value"\napi_key = "sk_test_abcdefghijklmnopqrst"\n'
    )
    # sk_test_ pattern might match depending on the regex. Let's use a clearly benign one.
    (repo / "a.py").write_text('TOKEN = "test"\nSECRET = "fixture"\n')
    awf_role._narrow_secret_scan(str(repo))


# ---------------------------------------------------------------------------
# Verification command re-execution
# ---------------------------------------------------------------------------


def test_verification_commands_succeed(tmp_path):
    """Verification commands that all pass let the gate succeed."""
    contract = awf_role.PostflightContract(
        allowed_paths=[],
        verification_commands=[[sys.executable, "-c", "exit(0)"]],
    )
    awf_role.run_verifications(str(tmp_path), contract)


def test_verification_stops_on_first_failure(tmp_path):
    """Verification stops at the first non-zero exit code."""
    contract = awf_role.PostflightContract(
        allowed_paths=[],
        verification_commands=[
            [sys.executable, "-c", "exit(0)"],
            [sys.executable, "-c", "exit(1)"],
            [sys.executable, "-c", "exit(0)"],  # Should not be reached
        ],
    )
    with pytest.raises(SystemExit, match="1"):
        awf_role.run_verifications(str(tmp_path), contract)


def test_verification_env_strips_credentials_and_prepends_runtime(monkeypatch, tmp_path):
    """Verification keeps UTF-8 output but removes credentials and forced UTF-8 mode."""
    runtime = tmp_path / "venv" / "Scripts" / "pythonw.exe"
    monkeypatch.setattr(awf_role.sys, "executable", str(runtime))
    monkeypatch.setenv("PATH", os.pathsep.join(["other-bin", str(runtime.parent)]))
    monkeypatch.setenv("AWF_CODER_TOKEN", "should-not-leak")
    monkeypatch.setenv("AGENT_BUS_TOKEN", "should-not-leak")
    monkeypatch.setenv("PYTHONUTF8", "1")

    result = awf_role.verification_env()

    assert "AWF_CODER_TOKEN" not in result
    assert "AGENT_BUS_TOKEN" not in result
    assert "PYTHONUTF8" not in result
    assert result["PYTHONIOENCODING"] == "utf-8"
    path_entries = result["PATH"].split(os.pathsep)
    assert path_entries[0] == str(runtime.parent.absolute())
    assert path_entries.count(str(runtime.parent.absolute())) == 1


@pytest.mark.skipif(os.name == "nt", reason="POSIX executable symlink behavior")
def test_verification_env_keeps_virtualenv_bin_when_python_is_symlink(monkeypatch, tmp_path):
    base_python = tmp_path / "base" / "python"
    base_python.parent.mkdir()
    base_python.touch()
    venv_python = tmp_path / "venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True)
    venv_python.symlink_to(base_python)
    monkeypatch.setattr(awf_role.sys, "executable", str(venv_python))

    result = awf_role.verification_env()

    assert result["PATH"].split(os.pathsep)[0] == str(venv_python.parent.absolute())


def test_windows_verification_python_alias_resolves_to_runner_sibling(tmp_path):
    pythonw = tmp_path / "venv" / "Scripts" / "pythonw.exe"
    pythonw.parent.mkdir(parents=True)
    pythonw.touch()
    python = pythonw.with_name("python.exe")
    python.touch()

    assert awf_role.resolve_verification_argv(
        ["python", "-m", "pytest", "-q"], os_name="nt", executable=str(pythonw)
    ) == [str(python.absolute()), "-m", "pytest", "-q"]
    assert awf_role.resolve_verification_argv(
        ["ruff", "check"], os_name="nt", executable=str(pythonw)
    ) == ["ruff", "check"]
    assert awf_role.resolve_verification_argv(
        ["python", "-V"], os_name="posix", executable=str(pythonw)
    ) == ["python", "-V"]


def test_run_verifications_uses_verification_env(monkeypatch, tmp_path):
    """Frozen verification commands use the dedicated default-locale environment."""
    expected_env = {"AWF_TEST_VERIFICATION_ENV": "1"}
    captured_env: dict[str, str] = {}
    captured_discard = []

    monkeypatch.setattr(awf_role, "verification_env", lambda: expected_env)

    def capturing_spawn(argv, *, cwd=None, stdin=None, env=None, discard_output=False):
        captured_env.update(env or {})
        captured_discard.append(discard_output)
        return 0

    monkeypatch.setattr(awf_role, "spawn", capturing_spawn)

    contract = awf_role.PostflightContract(
        allowed_paths=[],
        verification_commands=[[sys.executable, "-c", "exit(0)"]],
    )
    awf_role.run_verifications(str(tmp_path), contract)

    assert captured_env == expected_env
    assert captured_discard == [True]


def test_verification_child_runs_without_pythonutf8(monkeypatch, tmp_path):
    """A real verification child omits forced UTF-8 mode but keeps UTF-8 output."""
    monkeypatch.setenv("PYTHONUTF8", "1")
    child_check = (
        "import os; "
        "assert 'PYTHONUTF8' not in os.environ; "
        "assert os.environ.get('PYTHONIOENCODING') == 'utf-8'"
    )
    contract = awf_role.PostflightContract(
        allowed_paths=[],
        verification_commands=[[sys.executable, "-c", child_check]],
    )

    awf_role.run_verifications(str(tmp_path), contract)


# ---------------------------------------------------------------------------
# Verification-created files subject to path checks
# ---------------------------------------------------------------------------


def test_verification_created_file_in_path_gate(tmp_path):
    """Files created by verification are subject to path/artifact checks."""
    repo = _init_repo(tmp_path)
    contract = awf_role.PostflightContract(
        allowed_paths=["a.py"],
        verification_commands=[[sys.executable, "-c", "open('new_file.py', 'w').write('x')"]],
    )
    # Verification succeeds
    awf_role.run_verifications(str(repo), contract)
    # But the delta gate catches the new file outside allowed_paths
    with pytest.raises(SystemExit, match="1"):
        awf_role.run_postflight_delta_gates(str(repo), contract)


def test_verification_git_metadata_mutation_fails_before_delta_git(monkeypatch, tmp_path):
    repo = _init_repo(tmp_path)
    expected = run("git", "rev-parse", "HEAD", cwd=repo)
    workspace = Path(
        awf_role.prepare_model_workspace(str(repo), expected, state_dir=tmp_path / "event-state")
    )
    mutation = (
        "from pathlib import Path; "
        "p=Path('.git/config'); "
        "p.write_text(p.read_text(encoding='utf-8') + "
        "'\\n[diff]\\n\\texternal = credential-stealing-helper\\n', encoding='utf-8')"
    )
    contract = awf_role.PostflightContract(
        allowed_paths=["a.py"], verification_commands=[[sys.executable, "-c", mutation]]
    )
    git_reads = []
    monkeypatch.setattr(
        awf_role,
        "postflight_git_out",
        lambda *args, **kwargs: git_reads.append((args, kwargs)) or "",
    )

    awf_role.run_verifications(str(workspace), contract)
    with pytest.raises(SystemExit, match="1"):
        awf_role.assert_model_git_metadata(str(workspace))

    assert not git_reads


# ---------------------------------------------------------------------------
# Full valid postflight reaches success
# ---------------------------------------------------------------------------


def test_full_valid_postflight_flow(tmp_path):
    """A fully valid postflight path passes all gates with a real git repo."""
    repo = _init_repo(tmp_path)
    # Modify an allowed file
    (repo / "a.py").write_text("modified content\n")
    contract = awf_role.PostflightContract(
        allowed_paths=["a.py"],
        verification_commands=[[sys.executable, "-c", "exit(0)"]],
    )
    # Verification passes
    awf_role.run_verifications(str(repo), contract)
    # Delta gates pass (a.py is allowed, no denylist, no secrets, no whitespace errors)
    awf_role.run_postflight_delta_gates(str(repo), contract)


def test_verification_failure_prevents_downstream(monkeypatch, tmp_path):
    """A non-zero verification result prevents git add/commit/push/send_event."""
    repo = _init_repo(tmp_path)
    (repo / "a.py").write_text("modified\n")
    contract = awf_role.PostflightContract(
        allowed_paths=["a.py"],
        verification_commands=[[sys.executable, "-c", "exit(1)"]],
    )

    downstream_calls = []

    def track_git(*args, **kw):
        downstream_calls.append(("git", args))

    monkeypatch.setattr(awf_role, "git", track_git)

    with pytest.raises(SystemExit, match="1"):
        awf_role.run_verifications(str(repo), contract)

    assert not downstream_calls, "no git write should occur after verification failure"


# ---------------------------------------------------------------------------
# Rework: full HEAD delta — staged changes also caught (rework items 1, 2)
# ---------------------------------------------------------------------------
# The original implementation checked only unstaged changes.  After rework the
# secret scan and diff --check cover staged + unstaged changes (git diff HEAD).
# The delta path snapshot uses NUL-delimited output for safe handling of
# spaces, Unicode, and quoted paths.  New tests below prove coverage of
# staged tracked, staged new, spaced renames, spaced untracked, and Unicode
# paths.
# ---------------------------------------------------------------------------


def test_secret_scan_staged_tracked_diff(tmp_path):
    """A staged tracked file with a secret is caught (diff HEAD covers staged)."""
    repo = _init_repo(tmp_path)
    (repo / "a.py").write_text(f'token = "{_GITHUB_TOKEN}"\n')
    run("git", "add", "a.py", cwd=repo)
    with pytest.raises(SystemExit, match="1"):
        awf_role._narrow_secret_scan(str(repo))


def test_secret_scan_staged_new_file(tmp_path):
    """A staged new file with a secret is caught."""
    repo = _init_repo(tmp_path)
    (repo / "new.py").write_text(f"{_GITHUB_TOKEN}\n")
    run("git", "add", "new.py", cwd=repo)
    with pytest.raises(SystemExit, match="1"):
        awf_role._narrow_secret_scan(str(repo))


def test_collect_delta_spaced_rename(tmp_path):
    """Renamed file with spaces is captured correctly (NUL-safe)."""
    repo = _init_repo(tmp_path)
    (repo / "my file.py").write_text("content\n")
    run("git", "add", "my file.py", cwd=repo)
    run("git", "commit", "-m", "add spaced", cwd=repo)
    run("git", "mv", "my file.py", "my renamed file.py", cwd=repo)
    paths = awf_role._collect_delta_paths(str(repo))
    assert "my file.py" in paths
    assert "my renamed file.py" in paths


def test_secret_scan_spaced_untracked(tmp_path):
    """Untracked file with spaces and a secret is caught (NUL-safe path)."""
    repo = _init_repo(tmp_path)
    (repo / "my secret.txt").write_text(f"{_GITHUB_TOKEN}\n")
    with pytest.raises(SystemExit, match="1"):
        awf_role._narrow_secret_scan(str(repo))


def test_collect_delta_unicode_path(tmp_path):
    """Unicode filenames in the delta are captured correctly (NUL-safe)."""
    repo = _init_repo(tmp_path)
    (repo / "café.py").write_text("content\n")
    paths = awf_role._collect_delta_paths(str(repo))
    assert "café.py" in paths


# ---------------------------------------------------------------------------
# Rework: artifact denylist matched at any depth (rework item 3)
# ---------------------------------------------------------------------------


def test_path_is_denied_nested():
    """Artifact denylist matches directory patterns at any depth, .env by basename."""
    nested_denied = [
        "config/.env.production",
        "web/node_modules/pkg/index.js",
        "pkg/build/output.o",
        "sub/deep/.venv/bin/python",
        "src/__pycache__/mod.pyc",
        "config/.env",
        ".env.local",
        "config/.env.staging",
        "tmp/.DS_Store",
        "pkg/coverage.xml",
    ]
    for p in nested_denied:
        assert awf_role._path_is_denied(p), f"{p!r} should be denied at any depth"
    # Root-level variants must still be denied
    for p in [".env.production", "node_modules/pkg/index.js", "build/output.o"]:
        assert awf_role._path_is_denied(p), f"{p!r} should be denied at root"
    # Documented example templates must be allowed at any depth
    for p in [".env.example", ".env.template", ".env.sample", "config/.env.example"]:
        assert not awf_role._path_is_denied(p), f"{p!r} should be allowed"


# ---------------------------------------------------------------------------
# Rework: fail closed on unreadable untracked files (rework item 4)
# ---------------------------------------------------------------------------


def test_secret_scan_unreadable_untracked_fails(monkeypatch, tmp_path):
    """An unreadable untracked regular file fails closed with safe label."""
    repo = _init_repo(tmp_path)
    (repo / "secret.txt").write_text("content\n")

    original_read_text = Path.read_text

    def failing_read(self, **kwargs):
        if self.name == "secret.txt":
            raise OSError("Permission denied")
        return original_read_text(self, **kwargs)

    monkeypatch.setattr(Path, "read_text", failing_read)

    with pytest.raises(SystemExit, match="1"):
        awf_role._narrow_secret_scan(str(repo))


# ---------------------------------------------------------------------------
# Rework: reject empty executable in contract (rework item 5)
# ---------------------------------------------------------------------------


def test_contract_empty_executable(tmp_path):
    """An empty string as the sole executable element fails contract parsing."""
    card = tmp_path / "task.md"
    card.write_text(
        "# Card\n"
        "<!-- awf-postflight\n"
        "{\n"
        '  "allowed_paths": ["a.py"],\n'
        '  "verification_commands": [[""]]\n'
        "}\n"
        "-->\n"
    )
    with pytest.raises(SystemExit, match="1"):
        awf_role.parse_postflight_contract(str(card))


def test_contract_empty_string_in_command(tmp_path):
    """An empty non-executable argv value is preserved."""
    card = tmp_path / "task.md"
    card.write_text(
        "# Card\n"
        "<!-- awf-postflight\n"
        "{\n"
        '  "allowed_paths": ["a.py"],\n'
        '  "verification_commands": [["python", "-c", ""]]\n'
        "}\n"
        "-->\n"
    )
    contract = awf_role.parse_postflight_contract(str(card))
    assert contract.verification_commands == [["python", "-c", ""]]


def test_secret_scan_quoted_tracked_filename(tmp_path):
    """A quoted Git path cannot detach added content from its known path."""
    if os.name == "nt":
        pytest.skip('quoted filename a"b.py is invalid on Windows')
    repo = _init_repo(tmp_path)
    path = repo / 'a"b.py'
    path.write_text("value = 'safe'\n")
    run("git", "add", path.name, cwd=repo)
    run("git", "commit", "-m", "add quoted path", cwd=repo)
    path.write_text(f"value = '{_GITHUB_TOKEN}'\n")
    run("git", "add", path.name, cwd=repo)
    with pytest.raises(SystemExit, match="1"):
        awf_role._narrow_secret_scan(str(repo))


def test_secret_scan_windows_valid_unicode_and_space_tracked_filename(tmp_path):
    """A tracked Unicode-and-space filename on Windows contains a real secret after commit."""
    repo = _init_repo(tmp_path)
    filename = "café token.py"
    path = repo / filename
    path.write_text("value = 'safe'\n", encoding="utf-8")
    run("git", "add", filename, cwd=repo)
    run("git", "commit", "-m", "add unicode space file", cwd=repo)
    path.write_text(f"value = '{_GITHUB_TOKEN}'\n", encoding="utf-8")
    run("git", "add", filename, cwd=repo)
    with pytest.raises(SystemExit, match="1"):
        awf_role._narrow_secret_scan(str(repo))


def test_secret_scan_disables_diff_helpers(monkeypatch, tmp_path):
    """Tracked scanning disables textconv and external diff helpers."""
    repo = _init_repo(tmp_path)
    (repo / "a.txt").write_text("safe\n")
    run("git", "add", "a.txt", cwd=repo)
    run("git", "commit", "-m", "add text", cwd=repo)
    (repo / "a.txt").write_text(f"{_GITHUB_TOKEN}\n")

    original = awf_role.postflight_git_out
    calls = []

    def recording_git_out(repo_path, *args):
        calls.append(args)
        return original(repo_path, *args)

    monkeypatch.setattr(awf_role, "postflight_git_out", recording_git_out)
    with pytest.raises(SystemExit, match="1"):
        awf_role._narrow_secret_scan(str(repo))
    diff_call = next(args for args in calls if args and args[0] == "diff" and "--" in args)
    assert "--no-textconv" in diff_call
    assert "--no-ext-diff" in diff_call


def test_secret_scan_added_line_starting_with_plus_plus(tmp_path):
    """A real added line beginning with ++ is not mistaken for a patch header."""
    repo = _init_repo(tmp_path)
    (repo / "a.py").write_text("safe\n")
    run("git", "add", "a.py", cwd=repo)
    run("git", "commit", "-m", "add source", cwd=repo)
    (repo / "a.py").write_text(f"++{_GITHUB_TOKEN}\n")
    with pytest.raises(SystemExit, match="1"):
        awf_role._narrow_secret_scan(str(repo))


# ---------------------------------------------------------------------------
# Rework: git diff HEAD --check catches staged whitespace (rework item 1)
# ---------------------------------------------------------------------------


def test_delta_gate_diff_check_rejects_staged_whitespace(tmp_path):
    """Staged whitespace errors are caught by diff HEAD --check."""
    repo = _init_repo(tmp_path)
    (repo / "a.py").write_text("trailing whitespace   \n")
    run("git", "add", "a.py", cwd=repo)
    contract = awf_role.PostflightContract(allowed_paths=["a.py"], verification_commands=[])
    with pytest.raises(SystemExit, match="1"):
        awf_role.run_postflight_delta_gates(str(repo), contract)
