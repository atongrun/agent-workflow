from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import awf_executor


@pytest.mark.parametrize(
    ("environment", "platform", "os_name", "expected"),
    [
        (
            {"PSModulePath": r"C:\Windows\System32\WindowsPowerShell\v1.0\Modules"},
            "win32",
            "nt",
            awf_executor.RuntimeKind.WINDOWS_POWERSHELL,
        ),
        (
            {"MSYSTEM": "MINGW64", "PSModulePath": "inherited"},
            "win32",
            "nt",
            awf_executor.RuntimeKind.WINDOWS_GIT_BASH,
        ),
        (
            {"SHELL": "/bin/zsh"},
            "darwin",
            "posix",
            awf_executor.RuntimeKind.MACOS_ZSH,
        ),
        ({}, "win32", "nt", awf_executor.RuntimeKind.WINDOWS_NATIVE),
        ({"SHELL": "/bin/bash"}, "linux", "posix", awf_executor.RuntimeKind.POSIX),
    ],
)
def test_runtime_detection_matrix(environment, platform, os_name, expected):
    detected = awf_executor.detect_runtime(
        environ=environment,
        platform=platform,
        os_name=os_name,
    )

    assert detected.kind is expected


def test_actual_ci_launcher_when_declared():
    expected = os.environ.get("AWF_EXPECTED_RUNTIME")
    if not expected:
        pytest.skip("launch environment assertion is enabled only by the runtime CI matrix")

    assert awf_executor.detect_runtime().kind.value == expected


def test_git_bash_executable_path_normalizes_only_on_windows():
    windows = awf_executor.RuntimeInfo(
        awf_executor.RuntimeKind.WINDOWS_GIT_BASH,
        "windows",
        "git-bash",
    )
    posix = awf_executor.RuntimeInfo(awf_executor.RuntimeKind.POSIX, "linux", "bash")

    assert awf_executor.normalize_command(
        ["/c/Program Files/Agent Bus/agent-bus.exe", "--payload", "/c/not-a-path"],
        runtime=windows,
    ) == (
        r"C:\Program Files\Agent Bus\agent-bus.exe",
        "--payload",
        "/c/not-a-path",
    )
    assert awf_executor.normalize_command(["/c/tool"], runtime=posix) == ("/c/tool",)


def test_windows_batch_policy_uses_safe_powershell_companion(monkeypatch, tmp_path):
    runtime = awf_executor.RuntimeInfo(
        awf_executor.RuntimeKind.WINDOWS_POWERSHELL,
        "windows",
        "powershell",
    )
    command = tmp_path / "tool.cmd"
    companion = tmp_path / "tool.ps1"
    command.write_text("@echo off\n", encoding="utf-8")
    companion.write_text("exit 0\n", encoding="utf-8")
    real_which = awf_executor.shutil.which

    def fake_which(name, **kwargs):
        if name == "pwsh.exe":
            return r"C:\Program Files\PowerShell\7\pwsh.exe"
        return real_which(name, **kwargs)

    monkeypatch.setattr(awf_executor.shutil, "which", fake_which)

    with pytest.raises(awf_executor.ExecutionFailure) as denied:
        awf_executor.normalize_command([command, "argument"], runtime=runtime)
    assert denied.value.diagnostic.kind == "shell-wrapper-denied"

    dangerous_literal = 'argument & | < > % ^ ! " still literal'
    normalized = awf_executor.normalize_command(
        [command, dangerous_literal],
        runtime=runtime,
        allow_shell_wrapper=True,
    )
    assert normalized[:6] == (
        r"C:\Program Files\PowerShell\7\pwsh.exe",
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-File",
        str(companion),
    )
    assert normalized[6] == dangerous_literal

    batch = tmp_path / "unsafe.bat"
    batch.write_text("@echo off\n", encoding="utf-8")
    with pytest.raises(awf_executor.ExecutionFailure) as unavailable:
        awf_executor.normalize_command(
            [batch, "argument"],
            runtime=runtime,
            allow_shell_wrapper=True,
        )
    assert unavailable.value.diagnostic.kind == "safe-wrapper-unavailable"


@pytest.mark.skipif(os.name != "nt", reason="real PowerShell companion execution")
def test_windows_cmd_companion_preserves_metacharacters(tmp_path):
    command = tmp_path / "echo-args.cmd"
    companion = tmp_path / "echo-args.ps1"
    command.write_text("@exit /b 99\n", encoding="utf-8")
    companion.write_text("$args[0]\n", encoding="utf-8")
    literal = "safe & whoami | echo %PATH% ^ !"

    completed = awf_executor.run(
        [command, literal],
        allow_shell_wrapper=True,
        capture_output=True,
        text=True,
        check=True,
    )

    assert completed.stdout.strip() == literal


def test_structured_argv_never_receives_shell_reparsing():
    argument = "literal & ; $() `echo` | < >"
    completed = awf_executor.run(
        [sys.executable, "-c", "import sys; print(sys.argv[1])", argument],
        capture_output=True,
        text=True,
        check=True,
    )

    assert completed.stdout.strip() == argument


def test_default_stdin_is_closed_and_shell_is_false(monkeypatch):
    captured = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured.update(kwargs)
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(awf_executor._subprocess, "run", fake_run)

    awf_executor.run(["tool", "argument"], text=True)

    assert captured["argv"] == ("tool", "argument")
    assert captured["stdin"] is subprocess.DEVNULL
    assert captured["shell"] is False


def test_missing_executable_has_structured_runtime_diagnostic(tmp_path):
    missing = tmp_path / "definitely-missing-command"

    with pytest.raises(awf_executor.ExecutionFailure) as failed:
        awf_executor.run([missing], cwd=tmp_path)

    diagnostic = failed.value.diagnostic
    assert diagnostic.kind == "not-found"
    assert diagnostic.executable == str(missing)
    assert diagnostic.cwd == str(tmp_path.resolve())
    assert diagnostic.runtime is awf_executor.detect_runtime().kind


def test_nonzero_failure_is_bounded_and_redacted():
    secret = "credential-value-that-must-not-leak"
    code = (
        "import sys; "
        f"print({secret!r}, file=sys.stderr); "
        "print('x' * 1500, file=sys.stderr); "
        "raise SystemExit(7)"
    )

    with pytest.raises(awf_executor.ExecutionFailure) as failed:
        awf_executor.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            check=True,
            secrets=(secret,),
        )

    diagnostic = failed.value.diagnostic
    assert diagnostic.kind == "nonzero-exit"
    assert diagnostic.returncode == 7
    assert secret not in diagnostic.render()
    assert secret not in diagnostic.stderr
    assert "<redacted>" in diagnostic.stderr
    assert diagnostic.stderr.endswith("...<truncated>")


def test_timeout_is_reported_without_raw_exception_text():
    with pytest.raises(awf_executor.ExecutionFailure) as failed:
        awf_executor.run(
            [sys.executable, "-c", "import time; time.sleep(5)"],
            timeout=0.01,
        )

    assert failed.value.diagnostic.kind == "timeout"
    assert failed.value.diagnostic.timeout_seconds == 0.01


def test_environment_redaction_never_returns_secret_values():
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "AGENT_BUS_TOKEN": "bus-secret",
        "OPENAI_API_KEY": "api-secret",
        "NORMAL": "visible",
    }

    redacted = awf_executor.redacted_environment(environment)

    assert redacted["AGENT_BUS_TOKEN"] == "<redacted>"
    assert redacted["OPENAI_API_KEY"] == "<redacted>"
    assert redacted["NORMAL"] == "visible"
    assert "bus-secret" not in repr(redacted)


def test_pathlike_and_unicode_arguments_are_preserved(tmp_path):
    executable = Path(sys.executable)
    value = "目录 with spaces"

    completed = awf_executor.run(
        [executable, "-c", "import sys; print(sys.argv[1])", value],
        capture_output=True,
        text=True,
        check=True,
    )

    assert completed.stdout.strip() == value
