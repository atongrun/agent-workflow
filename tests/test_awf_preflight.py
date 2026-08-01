from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import awf_handoff_check  # noqa: E402
import awf_listen  # noqa: E402
import awf_preflight  # noqa: E402


def args(tmp_path: Path, *, intent: str = "taskcard") -> argparse.Namespace:
    config = tmp_path / "dispatch.env"
    config.write_text("placeholder\n", encoding="utf-8")
    config.chmod(0o600)
    return argparse.Namespace(
        repo=tmp_path,
        config=config,
        state_root=tmp_path / "state",
        authority_manifest=tmp_path / "authority.json",
        source_role="architect",
        target_role="coder",
        upstream_remote="upstream",
        head_remote="fork",
        gh_bin="gh",
        run_id="",
        intent=intent,
        ttl_seconds=3600,
        timeout=2.0,
        force=False,
    )


def valid_config() -> dict[str, str]:
    return {
        "AGENT_BUS_URL": "https://bus.example.invalid",
        "AWF_ARCH_TOKEN": "architect-test-token",
        "AWF_CODER_TOKEN": "coder-test-token",
        "AWF_REVIEWER_TOKEN": "reviewer-test-token",
        "AWF_BUS_BIN": "agent-bus",
        "AWF_OPENCODE_BIN": "opencode",
    }


def install_fast_fakes(monkeypatch, calls: list[list[str]], *, pending: str = "0") -> None:
    monkeypatch.setattr(awf_preflight, "load_config", lambda _path: valid_config())
    monkeypatch.setattr(
        awf_preflight,
        "load_authority_manifest",
        lambda _path: {"allowed_operations": ["diagnose"]},
    )
    monkeypatch.setattr(awf_preflight, "authorize_operation", lambda *_args: True)
    monkeypatch.setattr(awf_preflight.shutil, "which", lambda value: f"/tools/{Path(value).name}")

    def fake_run(argv, **_kwargs):
        values = [str(value) for value in argv]
        calls.append(values)
        stdout = ""
        if "pending" in values:
            stdout = pending + "\n"
        elif len(values) >= 4 and values[0] == "git" and values[3] == "rev-parse":
            stdout = "true\n"
        elif "branch" in values and "--show-current" in values:
            stdout = "codex/preflight-test\n"
        elif "remote" in values and "get-url" in values:
            remote = values[-1]
            owner = "upstream-owner" if remote == "upstream" else "fork-owner"
            stdout = f"https://github.com/{owner}/agent-workflow.git\n"
        elif "repo" in values and "view" in values:
            stdout = '{"nameWithOwner":"upstream-owner/agent-workflow"}\n'
        elif "--version" in values:
            stdout = "test-tool 1.0\n"
        return subprocess.CompletedProcess(values, 0, stdout, "")

    monkeypatch.setattr(awf_preflight, "run_command", fake_run)


def test_fast_is_read_only_and_allows_taskcard_without_deep(tmp_path, monkeypatch):
    calls: list[list[str]] = []
    install_fast_fakes(monkeypatch, calls)
    value = args(tmp_path)
    before = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))

    report = awf_preflight.run_fast(value).report

    after = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))
    assert report["format"] == awf_preflight.REPORT_FORMAT
    assert report["status"] == "PASS"
    assert report["allow_taskcard_authoring"] is True
    assert report["allow_remote_dispatch"] is False
    assert report["required_next_action"] == "author_taskcard"
    assert before == after
    forbidden = {"send", "listen", "ack", "requeue", "redispatch", "run", "exec"}
    assert not any(forbidden.intersection(call) for call in calls)
    assert any("--dry-run" in call and "fork" in call for call in calls)
    assert any(call[-1] == "--version" for call in calls)


def test_fast_remote_dispatch_requires_current_deep_proof(tmp_path, monkeypatch):
    calls: list[list[str]] = []
    install_fast_fakes(monkeypatch, calls)
    value = args(tmp_path, intent="remote-dispatch")

    first = awf_preflight.run_fast(value)
    assert first.report["required_next_action"] == "run_deep_preflight"
    cached = {
        "format": awf_preflight.REPORT_FORMAT,
        "mode": "deep",
        "status": "PASS",
        "fingerprint": first.fingerprint,
        "expires_at": awf_preflight.iso(awf_preflight.utc_now() + timedelta(hours=1)),
        "allow_remote_dispatch": True,
        "required_next_action": "remote_dispatch_allowed",
        "layers": [
            {
                "id": layer,
                "status": "PASS",
                "error_code": "",
                "duration_ms": 0,
                "evidence": {},
            }
            for layer in sorted(awf_preflight.REMOTE_LAYERS)
        ],
        "deep": {
            "current": True,
            "probe_id": "awf-preflight-" + "9" * 32,
            "source_role": "architect",
            "target_role": "coder",
            "request_event_id": 91,
            "reply_event_id": 92,
            "pending_before": {"architect": 0, "coder": 0},
            "pending_after": {"architect": 0, "coder": 0},
            "request_handler": "pass",
            "request_child": "pass",
            "result_handler": "pass",
            "result_child": "pass",
            "request_ack_evidence": "inferred-handler-success-and-zero-pending",
            "reply_ack_evidence": "inferred-handler-success-and-zero-pending",
        },
    }
    cached = awf_preflight.sign_deep_report(cached, valid_config(), "architect", "coder")
    awf_preflight.atomic_write(awf_preflight.cache_path(value.state_root), cached)

    second = awf_preflight.run_fast(value).report
    assert second["allow_remote_dispatch"] is True
    assert second["required_next_action"] == "remote_dispatch_allowed"


def test_minimal_or_tampered_deep_cache_never_authorizes_dispatch(tmp_path, monkeypatch):
    calls: list[list[str]] = []
    install_fast_fakes(monkeypatch, calls)
    value = args(tmp_path, intent="remote-dispatch")
    first = awf_preflight.run_fast(value)
    minimal = {
        "format": awf_preflight.REPORT_FORMAT,
        "mode": "deep",
        "status": "PASS",
        "fingerprint": first.fingerprint,
        "expires_at": awf_preflight.iso(awf_preflight.utc_now() + timedelta(hours=1)),
    }
    awf_preflight.atomic_write(awf_preflight.cache_path(value.state_root), minimal)

    report = awf_preflight.run_fast(value).report
    assert report["allow_remote_dispatch"] is False
    assert report["required_next_action"] == "run_deep_preflight"


def test_fast_config_failure_is_fail_closed_and_secret_safe(tmp_path, monkeypatch):
    value = args(tmp_path)
    monkeypatch.setattr(
        awf_preflight,
        "load_config",
        lambda _path: (_ for _ in ()).throw(awf_preflight.ConfigError("invalid key")),
    )
    monkeypatch.setattr(awf_preflight.shutil, "which", lambda value: f"/tools/{value}")

    report = awf_preflight.run_fast(value).report

    assert report["allow_taskcard_authoring"] is False
    assert report["required_next_action"] == "fix_fast_preflight"
    encoded = json.dumps(report)
    assert "architect-test-token" not in encoded
    assert "coder-test-token" not in encoded


def test_noninteger_pending_denies_remote_but_not_local_authoring(tmp_path, monkeypatch):
    calls: list[list[str]] = []
    install_fast_fakes(monkeypatch, calls, pending="not-a-count")

    report = awf_preflight.run_fast(args(tmp_path)).report
    layers = {layer["id"]: layer for layer in report["layers"]}

    assert report["allow_taskcard_authoring"] is True
    assert layers["agent-bus"]["status"] == "FAIL"
    assert layers["agent-bus"]["error_code"] == "BUS_PENDING_INVALID"


def passing_fast(tmp_path: Path) -> awf_preflight.FastResult:
    report = {
        "format": awf_preflight.REPORT_FORMAT,
        "mode": "fast",
        "generated_at": awf_preflight.iso(awf_preflight.utc_now()),
        "status": "FAIL",
        "allow_taskcard_authoring": True,
        "allow_remote_dispatch": False,
        "required_next_action": "run_deep_preflight",
        "layers": [
            {"id": layer, "status": "PASS", "error_code": "", "duration_ms": 0, "evidence": {}}
            for layer in sorted(awf_preflight.REMOTE_LAYERS)
        ],
        "fingerprint": "a" * 64,
        "deep": {"required": True, "current": False, "expires_at": None},
    }
    return awf_preflight.FastResult(report, valid_config(), "a" * 64)


def test_deep_nonzero_baseline_never_sends_or_listens(tmp_path, monkeypatch):
    value = args(tmp_path, intent="remote-dispatch")
    monkeypatch.setattr(awf_preflight, "run_fast", lambda _args: passing_fast(tmp_path))
    monkeypatch.setattr(awf_preflight, "pending_count", lambda *_args: 1)
    calls: list[list[str]] = []
    monkeypatch.setattr(
        awf_preflight,
        "run_command",
        lambda argv, **_kwargs: (
            calls.append(list(argv)) or subprocess.CompletedProcess(argv, 0, "", "")
        ),
    )

    report = awf_preflight.run_deep(value)

    assert report["status"] == "FAIL"
    assert report["deep"]["error_code"] == "DEEP_NONZERO_BASELINE"
    assert not any({"send", "listen", "ack", "requeue"}.intersection(call) for call in calls)


def test_deep_success_requires_matching_result_and_zero_pending(tmp_path, monkeypatch):
    value = args(tmp_path, intent="remote-dispatch")
    fixed_id = "1" * 32

    class FixedUUID:
        hex = fixed_id

    monkeypatch.setattr(awf_preflight, "run_fast", lambda _args: passing_fast(tmp_path))
    monkeypatch.setattr(awf_preflight, "pending_count", lambda *_args: 0)
    monkeypatch.setattr(awf_preflight.uuid, "uuid4", lambda: FixedUUID())
    monkeypatch.setattr(awf_preflight.shutil, "which", lambda value: f"/tools/{value}")

    def fake_run(argv, **_kwargs):
        values = [str(value) for value in argv]
        if "send" in values:
            payload = json.loads(values[values.index("--payload") + 1])
            probe = payload["probe_id"]
            awf_preflight.atomic_write(
                awf_preflight.probe_dir(value.state_root, probe) / "source-result.json",
                {
                    "format": "awf.preflight-control-result.v1",
                    "probe_id": probe,
                    "fingerprint": "a" * 64,
                    "request_event_id": 101,
                    "reply_event_id": 102,
                    "request_type": awf_preflight.REQUEST_TYPE,
                    "result_type": awf_preflight.RESULT_TYPE,
                    "source_role": "architect",
                    "target_role": "coder",
                    "request_child_rc": 0,
                    "result_child_rc": 0,
                },
            )
        return subprocess.CompletedProcess(values, 0, "", "")

    monkeypatch.setattr(awf_preflight, "run_command", fake_run)

    report = awf_preflight.run_deep(value)

    assert report["status"] == "PASS"
    assert report["allow_remote_dispatch"] is True
    assert report["deep"]["request_event_id"] == 101
    assert report["deep"]["reply_event_id"] == 102
    assert report["deep"]["pending_before"] == {"architect": 0, "coder": 0}
    assert report["deep"]["pending_after"] == {"architect": 0, "coder": 0}
    assert awf_preflight.cache_path(value.state_root).is_file()


def test_request_and_result_handlers_run_children_and_publish_evidence(tmp_path, monkeypatch):
    config_path = tmp_path / "dispatch.env"
    config_path.write_text("placeholder\n", encoding="utf-8")
    config_path.chmod(0o600)
    monkeypatch.setattr(awf_preflight, "load_config", lambda _path: valid_config())
    monkeypatch.setattr(awf_preflight.shutil, "which", lambda value: f"/tools/{value}")
    commands: list[list[str]] = []

    def fake_run(argv, **_kwargs):
        commands.append([str(value) for value in argv])
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(awf_preflight, "run_command", fake_run)
    monkeypatch.setenv("AGENT_BUS_AGENT", "coder")
    probe = "awf-preflight-" + "2" * 32
    request = argparse.Namespace(
        event_id="201",
        event_type=awf_preflight.REQUEST_TYPE,
        probe_id=probe,
        fingerprint="b" * 64,
        source_role="architect",
        target_role="coder",
        state_root=tmp_path / "state",
        config=config_path,
    )
    assert awf_preflight.handle_request(request) == 0
    assert any(command[:2] == [awf_preflight.sys.executable, "-c"] for command in commands)
    assert any("send" in command and awf_preflight.RESULT_TYPE in command for command in commands)

    monkeypatch.setenv("AGENT_BUS_AGENT", "architect")
    result = argparse.Namespace(
        event_id="202",
        event_type=awf_preflight.RESULT_TYPE,
        probe_id=probe,
        fingerprint="b" * 64,
        source_role="architect",
        target_role="coder",
        state_root=tmp_path / "state",
        request_event_id="201",
        request_child_rc="0",
    )
    assert awf_preflight.handle_result(result) == 0
    saved = json.loads(
        (awf_preflight.probe_dir(result.state_root, probe) / "source-result.json").read_text()
    )
    assert saved["request_event_id"] == 201
    assert saved["reply_event_id"] == 202
    assert saved["result_child_rc"] == 0


def test_listener_registers_no_model_preflight_handlers():
    handler = awf_listen.build_preflight_handler(
        "python",
        "awf_preflight.py",
        "handle-request",
        config_path=Path("/safe/config"),
        state_root=Path("/safe/state"),
    )
    assert "handle-request" in handler
    assert "{id}" in handler
    assert "{payload.probe_id}" in handler
    assert "opencode" not in handler
    assert "codex" not in handler


def test_listener_preflight_routes_are_explicit_opt_in(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    config = tmp_path / "dispatch.env"
    config.write_text("placeholder\n", encoding="utf-8")
    config.chmod(0o600)
    environment = {
        "AGENT_BUS_URL": "https://bus.example.invalid",
        "AWF_CODER_TOKEN": "test-token",
    }
    monkeypatch.setattr(awf_listen.os, "environ", environment)
    monkeypatch.setattr(awf_listen, "load_into_environment", lambda _path: {})
    seen: list[str] = []
    monkeypatch.setattr(
        awf_listen,
        "run_command",
        lambda argv, **_kwargs: seen.extend(argv) or subprocess.CompletedProcess(argv, 0, "", ""),
    )

    result = awf_listen.main(
        [
            "--role",
            "coder",
            "--repo",
            str(repo),
            "--config",
            str(config),
            "--upstream-repo",
            "upstream/project",
            "--head-repo",
            "contributor/project",
            "--enable-preflight",
            "--state-root",
            str(tmp_path / "state"),
        ]
    )

    assert result == 0
    assert awf_preflight.REQUEST_TYPE in seen
    assert awf_preflight.RESULT_TYPE in seen


def test_deep_failure_always_returns_versioned_report(tmp_path, monkeypatch):
    value = args(tmp_path, intent="remote-dispatch")
    monkeypatch.setattr(awf_preflight, "run_fast", lambda _args: passing_fast(tmp_path))
    monkeypatch.setattr(awf_preflight, "pending_count", lambda *_args: 0)
    monkeypatch.setattr(awf_preflight.shutil, "which", lambda value: f"/tools/{value}")
    # Use a direct failure at the safe execute seam; the wrapper must still emit v1.
    monkeypatch.setattr(
        awf_preflight,
        "execute",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            awf_preflight.PreflightError("DEEP_SEND_FAILED", "send failed")
        ),
    )

    report = awf_preflight.run_deep(value)
    assert report["format"] == awf_preflight.REPORT_FORMAT
    assert report["status"] == "FAIL"
    assert report["allow_remote_dispatch"] is False
    assert report["deep"]["error_code"] == "DEEP_SEND_FAILED"


def test_handoff_check_renders_fast_report_and_preserves_exit_contract(
    tmp_path, monkeypatch, capsys
):
    config = tmp_path / "dispatch.env"
    config.write_text("placeholder\n", encoding="utf-8")
    monkeypatch.setattr(
        awf_handoff_check,
        "run_fast",
        lambda _args: awf_preflight.FastResult(
            {
                "layers": [
                    {
                        "id": "runtime",
                        "status": "PASS",
                        "error_code": "",
                        "duration_ms": 0,
                        "evidence": {},
                    }
                ]
            },
            {},
            "a" * 64,
        ),
    )

    rc = awf_handoff_check.main(["--role", "coder", "--repo", str(tmp_path), "--dest", str(config)])

    assert rc == 0
    assert "RESULT: PASS" in capsys.readouterr().out


def test_handoff_profile_preserves_role_only_no_repo_contract(tmp_path, monkeypatch):
    calls: list[list[str]] = []
    install_fast_fakes(monkeypatch, calls)
    monkeypatch.setattr(
        awf_preflight,
        "load_config",
        lambda _path: {
            "AGENT_BUS_URL": "https://bus.example.invalid",
            "AWF_ARCH_TOKEN": "architect-only-token",
            "AWF_BUS_BIN": "agent-bus",
        },
    )
    value = args(tmp_path)
    value.profile = "handoff"
    value.repo_required = False
    value.source_role = "architect"
    value.target_role = "architect"

    report = awf_preflight.run_fast(value).report

    assert all(layer["status"] == "PASS" for layer in report["layers"])
    assert not any("--dry-run" in call for call in calls)
    assert not any("--version" in call for call in calls)


def test_handoff_profile_preserves_coder_repo_push_dry_run(tmp_path, monkeypatch):
    calls: list[list[str]] = []
    install_fast_fakes(monkeypatch, calls)
    monkeypatch.setattr(
        awf_preflight,
        "load_config",
        lambda _path: {
            "AGENT_BUS_URL": "https://bus.example.invalid",
            "AWF_CODER_TOKEN": "coder-only-token",
            "AWF_BUS_BIN": "agent-bus",
            "AWF_OPENCODE_BIN": "opencode",
        },
    )
    value = args(tmp_path)
    value.profile = "handoff"
    value.repo_required = True
    value.source_role = "coder"
    value.target_role = "coder"

    report = awf_preflight.run_fast(value).report

    assert all(layer["status"] == "PASS" for layer in report["layers"])
    dry_runs = [call for call in calls if "--dry-run" in call]
    assert len(dry_runs) == 1
    assert "fork" not in dry_runs[0]
    assert any("--version" in call for call in calls)


def test_preflight_template_obeys_agent_bus_single_argv_placeholder_contract():
    """Lock the Agent Bus v0.3 render_command contract used by listener templates."""
    placeholder = re.compile(r"\{([^{}]+)\}")

    def lookup(event, expression):
        current = event
        for part in expression.split("."):
            current = current[part]
        return str(current)

    def render(template, event):
        rendered = []
        for token in shlex.split(template, posix=True):
            match = placeholder.fullmatch(token)
            if match:
                rendered.append(lookup(event, match.group(1).strip()))
            else:
                rendered.append(
                    placeholder.sub(lambda item: lookup(event, item.group(1).strip()), token)
                )
        return rendered

    handler = awf_listen.build_preflight_handler(
        "/safe/python",
        "/safe/awf_preflight.py",
        "handle-request",
        config_path=Path("/safe/config"),
        state_root=Path("/safe/state"),
    )
    attack = "value; touch /tmp/not-executed --source-role reviewer"
    event = {
        "id": 9,
        "type": awf_preflight.REQUEST_TYPE,
        "payload": {
            "probe_id": attack,
            "fingerprint": attack,
            "source_role": attack,
            "target_role": attack,
        },
    }

    argv = render(handler, event)

    assert argv[:3] == ["/safe/python", "/safe/awf_preflight.py", "handle-request"]
    assert argv.count(attack) == 4
    assert "touch" not in argv
    assert ";" not in argv


def test_installed_agent_bus_renders_preflight_metacharacters_as_one_argv_element():
    """Optional live contract: point CI/runtime at the installed Agent Bus source and Python."""
    bus_python = os.environ.get("AWF_AGENT_BUS_PYTHON", "")
    bus_source = os.environ.get("AWF_AGENT_BUS_SOURCE_ROOT", "")
    if not bus_python or not bus_source:
        pytest.skip("installed Agent Bus contract paths were not supplied")
    handler = awf_listen.build_preflight_handler(
        "/safe/python",
        "/safe/awf_preflight.py",
        "handle-request",
        config_path=Path("/safe/config"),
        state_root=Path("/safe/state"),
    )
    attack = "hello; touch /tmp/not-executed --target-role reviewer"
    event = {
        "id": 17,
        "type": awf_preflight.REQUEST_TYPE,
        "payload": {
            "probe_id": attack,
            "fingerprint": attack,
            "source_role": attack,
            "target_role": attack,
        },
    }
    code = (
        "import json,sys; "
        "sys.path.insert(0,sys.argv[1]); "
        "from client.cli import render_command; "
        "print(json.dumps(render_command(sys.argv[2],json.loads(sys.argv[3]))))"
    )
    completed = subprocess.run(
        [bus_python, "-c", code, bus_source, handler, json.dumps(event)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    argv = json.loads(completed.stdout)
    assert argv[:3] == ["/safe/python", "/safe/awf_preflight.py", "handle-request"]
    assert argv.count(attack) == 4
    assert "touch" not in argv
