#!/usr/bin/env python3
"""Single process boundary for Agent Workflow runtime commands.

Business modules pass structured argv to this module.  They never select or
invoke a shell themselves.  The shell that launched Python (PowerShell, Git
Bash, or macOS zsh) is detected only for path normalization and diagnostics;
it never reparses ordinary business commands.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess as _subprocess
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import IO, Mapping, Sequence

CompletedProcess = _subprocess.CompletedProcess
DEVNULL = _subprocess.DEVNULL
PIPE = _subprocess.PIPE

_GIT_BASH_DRIVE = re.compile(r"^/([A-Za-z])/(.*)$")
_SECRET_KEY = re.compile(r"(?:TOKEN|SECRET|PASSWORD|PASSWD|API_KEY|AUTH)", re.IGNORECASE)
_SENSITIVE_ARG = re.compile(
    r"(?i)(?:token|secret|password|passwd|api[_-]?key|authorization)=([^\s]+)"
)
_TEXT_ENCODING = "utf-8"
_TEXT_ERRORS = "replace"


class RuntimeKind(str, Enum):
    WINDOWS_POWERSHELL = "windows-powershell"
    WINDOWS_GIT_BASH = "windows-git-bash"
    WINDOWS_NATIVE = "windows-native"
    MACOS_ZSH = "macos-zsh"
    POSIX = "posix"


@dataclass(frozen=True)
class RuntimeInfo:
    kind: RuntimeKind
    platform: str
    launcher: str


@dataclass(frozen=True)
class FailureDiagnostic:
    kind: str
    runtime: RuntimeKind
    executable: str
    cwd: str
    returncode: int | None = None
    timeout_seconds: float | None = None
    argv: tuple[str, ...] = ()
    stdout: str = ""
    stderr: str = ""

    def render(self) -> str:
        fields = [
            f"kind={self.kind}",
            f"runtime={self.runtime.value}",
            f"executable={self.executable}",
            f"cwd={self.cwd}",
        ]
        if self.returncode is not None:
            fields.append(f"exit={self.returncode}")
        if self.timeout_seconds is not None:
            fields.append(f"timeout={self.timeout_seconds:g}s")
        if self.stderr:
            fields.append(f"stderr={self.stderr}")
        elif self.stdout:
            fields.append(f"stdout={self.stdout}")
        return "command failed (" + ", ".join(fields) + ")"


class ExecutionFailure(RuntimeError):
    """Structured, credential-safe process launch or completion failure."""

    def __init__(self, diagnostic: FailureDiagnostic):
        self.diagnostic = diagnostic
        super().__init__(diagnostic.render())


def detect_runtime(
    *,
    environ: Mapping[str, str] | None = None,
    platform: str | None = None,
    os_name: str | None = None,
) -> RuntimeInfo:
    values = os.environ if environ is None else environ
    resolved_platform = sys.platform if platform is None else platform
    resolved_os_name = os.name if os_name is None else os_name
    shell = values.get("SHELL", "")
    if resolved_os_name == "nt":
        if values.get("MSYSTEM") or "usr/bin/bash" in shell.replace("\\", "/").casefold():
            return RuntimeInfo(RuntimeKind.WINDOWS_GIT_BASH, "windows", "git-bash")
        if values.get("PSModulePath") or values.get("POWERSHELL_DISTRIBUTION_CHANNEL"):
            return RuntimeInfo(RuntimeKind.WINDOWS_POWERSHELL, "windows", "powershell")
        return RuntimeInfo(RuntimeKind.WINDOWS_NATIVE, "windows", "native")
    if resolved_platform == "darwin" and Path(shell).name.casefold() == "zsh":
        return RuntimeInfo(RuntimeKind.MACOS_ZSH, "macos", "zsh")
    return RuntimeInfo(RuntimeKind.POSIX, resolved_platform, Path(shell).name or "native")


def _native_windows_executable(value: str) -> str:
    match = _GIT_BASH_DRIVE.fullmatch(value)
    if not match:
        return value
    return f"{match.group(1).upper()}:\\" + match.group(2).replace("/", "\\")


def native_executable(path: str, *, platform: str | None = None) -> str:
    """Return the native executable spelling for one configured path."""
    resolved_platform = platform or ("windows" if os.name == "nt" else "posix")
    return _native_windows_executable(path) if resolved_platform == "windows" else path


def normalize_command(
    argv: Sequence[str | os.PathLike[str]],
    *,
    runtime: RuntimeInfo | None = None,
    allow_shell_wrapper: bool = False,
    environment: Mapping[str, str] | None = None,
) -> tuple[str, ...]:
    if isinstance(argv, (str, bytes)) or not argv:
        raise ValueError("command must be a non-empty argv sequence")
    normalized = tuple(os.fspath(value) for value in argv)
    if any(not value or "\x00" in value for value in normalized):
        raise ValueError("command arguments must be non-empty and NUL-free")
    active = runtime or detect_runtime()
    executable = normalized[0]
    if active.platform == "windows":
        executable = _native_windows_executable(executable)
        search_environment = os.environ if environment is None else environment
        if not Path(executable).parent.name:
            executable = shutil.which(executable, path=search_environment.get("PATH")) or executable
    normalized = (executable, *normalized[1:])
    if executable.casefold().endswith((".cmd", ".bat")):
        if active.platform != "windows":
            return normalized
        if not allow_shell_wrapper:
            diagnostic = _diagnostic(
                "shell-wrapper-denied",
                normalized,
                runtime=active,
                cwd=None,
            )
            raise ExecutionFailure(diagnostic)
        # Never feed arbitrary argv to cmd.exe /c: CreateProcess quoting does
        # not escape cmd metacharacters. npm-style .cmd shims normally ship an
        # equivalent .ps1 launcher, whose -File arguments remain structured.
        if executable.casefold().endswith(".bat"):
            wrapper = None
        else:
            wrapper = Path(executable).with_suffix(".ps1")
        if wrapper is None or not wrapper.is_file():
            raise ExecutionFailure(
                _diagnostic(
                    "safe-wrapper-unavailable",
                    normalized,
                    runtime=active,
                    cwd=None,
                )
            )
        search_environment = os.environ if environment is None else environment
        powershell = shutil.which("pwsh.exe", path=search_environment.get("PATH"))
        powershell = powershell or shutil.which(
            "powershell.exe",
            path=search_environment.get("PATH"),
        )
        powershell = powershell or "powershell.exe"
        return (
            powershell,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(wrapper),
            *normalized[1:],
        )
    return normalized


def _redact(value: str, secrets: Sequence[str] = ()) -> str:
    redacted = value
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, "<redacted>")
    return _SENSITIVE_ARG.sub(
        lambda match: match.group(0).replace(match.group(1), "<redacted>"),
        redacted,
    )


def redacted_environment(environment: Mapping[str, str] | None) -> dict[str, str]:
    if environment is None:
        return {}
    return {
        key: "<redacted>" if _SECRET_KEY.search(key) else _redact(str(value))
        for key, value in environment.items()
    }


def _bounded(value: object, *, secrets: Sequence[str] = (), limit: int = 1000) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        text = value.decode("utf-8", errors="replace")
    else:
        text = str(value)
    text = _redact(text, secrets).strip().replace("\x00", "\ufffd")
    return text if len(text) <= limit else text[:limit] + "...<truncated>"


def _diagnostic(
    kind: str,
    argv: Sequence[str],
    *,
    runtime: RuntimeInfo,
    cwd: str | os.PathLike[str] | None,
    returncode: int | None = None,
    timeout: float | None = None,
    stdout: object = None,
    stderr: object = None,
    secrets: Sequence[str] = (),
) -> FailureDiagnostic:
    safe_argv = tuple(_redact(value, secrets) for value in argv)
    return FailureDiagnostic(
        kind=kind,
        runtime=runtime.kind,
        executable=safe_argv[0] if safe_argv else "<missing>",
        cwd=str(Path(cwd).resolve()) if cwd is not None else str(Path.cwd()),
        returncode=returncode,
        timeout_seconds=timeout,
        argv=safe_argv,
        stdout=_bounded(stdout, secrets=secrets),
        stderr=_bounded(stderr, secrets=secrets),
    )


def failure_diagnostic(
    completed: CompletedProcess,
    *,
    runtime: RuntimeInfo | None = None,
    cwd: str | os.PathLike[str] | None = None,
    secrets: Sequence[str] = (),
) -> FailureDiagnostic:
    active = runtime or detect_runtime()
    argv = tuple(str(value) for value in completed.args)
    return _diagnostic(
        "nonzero-exit",
        argv,
        runtime=active,
        cwd=cwd,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        secrets=secrets,
    )


def _child_environment(environment: Mapping[str, str] | None) -> dict[str, str]:
    values = dict(os.environ if environment is None else environment)
    if environment is None:
        values.setdefault("PYTHONUTF8", "1")
        values.setdefault("PYTHONIOENCODING", "utf-8")
    return values


def run(
    argv: Sequence[str | os.PathLike[str]],
    *,
    cwd: str | os.PathLike[str] | None = None,
    env: Mapping[str, str] | None = None,
    input: str | bytes | None = None,
    stdin: int | IO[object] | None = None,
    stdout: int | IO[object] | None = None,
    stderr: int | IO[object] | None = None,
    capture_output: bool = False,
    text: bool | None = None,
    encoding: str | None = None,
    errors: str | None = None,
    timeout: float | None = None,
    check: bool = False,
    allow_shell_wrapper: bool = False,
    secrets: Sequence[str] = (),
    runtime: RuntimeInfo | None = None,
) -> CompletedProcess:
    active = runtime or detect_runtime()
    child_environment = _child_environment(env)
    normalized = normalize_command(
        argv,
        runtime=active,
        allow_shell_wrapper=allow_shell_wrapper,
        environment=child_environment,
    )
    if input is None and stdin is None:
        stdin = DEVNULL
    if text is None:
        text = encoding is not None or isinstance(input, str)
    if text and encoding is None:
        encoding = _TEXT_ENCODING
    if text and errors is None:
        errors = _TEXT_ERRORS
    try:
        completed = _subprocess.run(
            normalized,
            cwd=cwd,
            env=child_environment,
            input=input,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            capture_output=capture_output,
            text=text,
            encoding=encoding,
            errors=errors,
            timeout=timeout,
            check=False,
            shell=False,
        )
    except _subprocess.TimeoutExpired as exc:
        raise ExecutionFailure(
            _diagnostic(
                "timeout",
                normalized,
                runtime=active,
                cwd=cwd,
                timeout=timeout,
                stdout=exc.stdout,
                stderr=exc.stderr,
                secrets=secrets,
            )
        ) from None
    except FileNotFoundError:
        raise ExecutionFailure(
            _diagnostic("not-found", normalized, runtime=active, cwd=cwd, secrets=secrets)
        ) from None
    except PermissionError:
        raise ExecutionFailure(
            _diagnostic("permission-denied", normalized, runtime=active, cwd=cwd, secrets=secrets)
        ) from None
    except OSError:
        raise ExecutionFailure(
            _diagnostic("spawn-error", normalized, runtime=active, cwd=cwd, secrets=secrets)
        ) from None
    if check and completed.returncode != 0:
        raise ExecutionFailure(
            failure_diagnostic(completed, runtime=active, cwd=cwd, secrets=secrets)
        )
    return completed


def start(
    argv: Sequence[str | os.PathLike[str]],
    *,
    cwd: str | os.PathLike[str] | None = None,
    env: Mapping[str, str] | None = None,
    stdin: int | IO[object] | None = None,
    stdout: int | IO[object] | None = None,
    stderr: int | IO[object] | None = None,
    text: bool = True,
    encoding: str | None = None,
    errors: str | None = None,
    allow_shell_wrapper: bool = False,
    secrets: Sequence[str] = (),
    runtime: RuntimeInfo | None = None,
) -> _subprocess.Popen:
    active = runtime or detect_runtime()
    child_environment = _child_environment(env)
    normalized = normalize_command(
        argv,
        runtime=active,
        allow_shell_wrapper=allow_shell_wrapper,
        environment=child_environment,
    )
    if stdin is None:
        stdin = DEVNULL
    if text and encoding is None:
        encoding = _TEXT_ENCODING
    if text and errors is None:
        errors = _TEXT_ERRORS
    try:
        return _subprocess.Popen(
            normalized,
            cwd=cwd,
            env=child_environment,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            text=text,
            encoding=encoding,
            errors=errors,
            shell=False,
        )
    except FileNotFoundError:
        raise ExecutionFailure(
            _diagnostic("not-found", normalized, runtime=active, cwd=cwd, secrets=secrets)
        ) from None
    except PermissionError:
        raise ExecutionFailure(
            _diagnostic("permission-denied", normalized, runtime=active, cwd=cwd, secrets=secrets)
        ) from None
    except OSError:
        raise ExecutionFailure(
            _diagnostic("spawn-error", normalized, runtime=active, cwd=cwd, secrets=secrets)
        ) from None
