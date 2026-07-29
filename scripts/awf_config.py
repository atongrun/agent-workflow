#!/usr/bin/env python3
"""Strict, shell-free Agent Workflow operations configuration.

The credential file is data, never a program.  This module is the only parser
used by bootstrap, handoff checks, listeners, dispatch, and service entry
points.  Legacy ``export KEY=VALUE`` lines remain readable for migration, but
values are not quoted, expanded, interpolated, or executed.
"""

from __future__ import annotations

import argparse
import os
import re
import stat
import subprocess
import sys
from pathlib import Path
from typing import Callable, Mapping
from urllib.parse import urlsplit

MAX_CONFIG_BYTES = 64 * 1024
TOKEN_KEYS = frozenset({"AWF_ARCH_TOKEN", "AWF_CODER_TOKEN", "AWF_REVIEWER_TOKEN"})
ALLOWED_KEYS = frozenset(
    {
        "AGENT_BUS_URL",
        *TOKEN_KEYS,
        "AWF_BUS_BIN",
        "AWF_OPENCODE_BIN",
        "AWF_CODEX_BIN",
        "AWF_GH_BIN",
    }
)
_KEY_RE = re.compile(r"[A-Z][A-Z0-9_]*\Z")
_ACE_RE = re.compile(r"(.+?):((?:\([A-Za-z,]+\))+)\Z")


class ConfigError(RuntimeError):
    """Credential-safe configuration failure."""


def default_config_path() -> Path:
    configured = os.environ.get("AWF_DISPATCH_ENV", "")
    return Path(configured) if configured else Path.home() / ".config/awf/dispatch.env"


def native_executable(path: str, *, platform: str | None = None) -> str:
    """Translate a legacy Git-Bash drive path for native Windows subprocesses."""
    resolved_platform = platform or ("windows" if os.name == "nt" else "posix")
    if (
        resolved_platform == "windows"
        and len(path) >= 3
        and path[0] == "/"
        and path[2] == "/"
        and path[1].isalpha()
    ):
        return f"{path[1].upper()}:\\" + path[3:].replace("/", "\\")
    return path


def validate_config_path(
    path: Path,
    *,
    platform: str,
    expected_uid: int | None,
    runner: Callable[..., subprocess.CompletedProcess],
) -> None:
    if not path.is_absolute():
        raise ConfigError("configuration path must be absolute")
    try:
        info = path.lstat()
    except OSError as exc:
        raise ConfigError("configuration file is unavailable") from exc
    if stat.S_ISLNK(info.st_mode):
        raise ConfigError("configuration file must not be a symbolic link")
    if not stat.S_ISREG(info.st_mode):
        raise ConfigError("configuration path must be a regular file")
    if info.st_size > MAX_CONFIG_BYTES:
        raise ConfigError("configuration file exceeds the size limit")
    if platform == "windows":
        _validate_windows_acl(path, runner)
        return
    uid = os.geteuid() if expected_uid is None else expected_uid
    if info.st_uid != uid:
        raise ConfigError("configuration file owner does not match the current user")
    if stat.S_IMODE(info.st_mode) & 0o077:
        raise ConfigError("configuration file must be owner-only")


def _parse_icacls_aces(path: Path, output: str) -> list[tuple[str, str]]:
    target = str(path)
    aces: list[tuple[str, str]] = []
    for raw in output.splitlines():
        entry = raw.strip()
        if not entry or entry.casefold().startswith("successfully processed"):
            continue
        if entry.casefold().startswith(target.casefold()):
            entry = entry[len(target) :].strip()
        match = _ACE_RE.fullmatch(entry)
        if not match:
            if ":(" in entry:
                return []
            continue
        aces.append((match.group(1), match.group(2)))
    return aces


def _validate_windows_acl(
    path: Path,
    runner: Callable[..., subprocess.CompletedProcess],
) -> None:
    acl = runner(["icacls", str(path)], capture_output=True, text=True)
    if acl.returncode != 0:
        raise ConfigError("could not verify configuration ACL")
    identity = runner(["whoami"], capture_output=True, text=True)
    principal = identity.stdout.strip() if identity.returncode == 0 else ""
    aces = _parse_icacls_aces(path, acl.stdout)
    if not principal or not aces:
        raise ConfigError("could not verify configuration owner")
    if any("(I)" in permissions for _, permissions in aces):
        raise ConfigError("configuration ACL must not be inherited")
    if any(owner.casefold() != principal.casefold() for owner, _ in aces):
        raise ConfigError("configuration ACL grants another principal")


def _validate_entry(key: str, value: str) -> None:
    if not _KEY_RE.fullmatch(key) or key not in ALLOWED_KEYS:
        raise ConfigError(f"unknown configuration key '{key}'")
    if not value:
        raise ConfigError(f"configuration key '{key}' must not be empty")
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        raise ConfigError(f"configuration key '{key}' contains a control character")
    if key in TOKEN_KEYS and any(char.isspace() for char in value):
        raise ConfigError(f"configuration key '{key}' contains whitespace")
    if key == "AGENT_BUS_URL":
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ConfigError("AGENT_BUS_URL must be a credential-free HTTP(S) origin")


def parse_config_text(text: str) -> dict[str, str]:
    if "\x00" in text:
        raise ConfigError("configuration file contains NUL")
    result: dict[str, str] = {}
    for line_number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :]
        if "=" not in line:
            raise ConfigError(f"line {line_number} is not a KEY=VALUE assignment")
        key, value = line.split("=", 1)
        if key != key.strip() or not key:
            raise ConfigError(f"line {line_number} has an invalid assignment key")
        if key in result:
            raise ConfigError(f"duplicate configuration key '{key}'")
        _validate_entry(key, value)
        result[key] = value
    return result


def load_config(
    path: Path | str,
    *,
    platform: str | None = None,
    expected_uid: int | None = None,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> dict[str, str]:
    resolved_platform = platform or ("windows" if os.name == "nt" else "posix")
    config_path = Path(path)
    validate_config_path(
        config_path,
        platform=resolved_platform,
        expected_uid=expected_uid,
        runner=runner,
    )
    try:
        raw = config_path.read_bytes()
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ConfigError("configuration file must be strict UTF-8") from exc
    except OSError as exc:
        raise ConfigError("configuration file could not be read") from exc
    return parse_config_text(text)


def load_into_environment(
    path: Path | str,
    *,
    overwrite: bool = False,
    **kwargs: object,
) -> dict[str, str]:
    values = load_config(path, **kwargs)
    for key, value in values.items():
        if overwrite or key not in os.environ:
            os.environ[key] = value
    return values


def serialize_config(values: Mapping[str, str]) -> str:
    checked: dict[str, str] = {}
    for key, value in values.items():
        text = str(value)
        _validate_entry(key, text)
        checked[key] = text
    return "".join(f"{key}={checked[key]}\n" for key in sorted(checked))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="awf_config")
    parser.add_argument("--config", type=Path, default=default_config_path())
    parser.add_argument("--optional", action="store_true")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if not args.command:
        parser.error("a command is required after --")
    if args.command[0] == "--":
        args.command = args.command[1:]
    try:
        if args.config.exists():
            load_into_environment(args.config)
        elif not args.optional:
            raise ConfigError("configuration file is unavailable")
    except ConfigError as exc:
        print(f"awf_config: {exc}", file=sys.stderr)
        return 2
    os.environ["AWF_CONFIG_LOADED"] = "1"
    try:
        return subprocess.run(args.command, env=dict(os.environ)).returncode
    except FileNotFoundError:
        print("awf_config: configured command is unavailable", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
