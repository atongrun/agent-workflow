#!/usr/bin/env python3
"""Allow only read-oriented Git commands in ordinary model subprocess calls."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

script_directory = Path(__file__).resolve().parent
scripts_root = script_directory.parent
if (scripts_root / "awf_executor.py").is_file():
    sys.path.insert(0, str(scripts_root))

from awf_executor import DEVNULL, ExecutionFailure  # noqa: E402
from awf_executor import run as run_command  # noqa: E402

ALLOWED = {
    "describe",
    "diff",
    "grep",
    "log",
    "ls-files",
    "merge-base",
    "rev-parse",
    "show",
    "status",
}
OPTIONS_WITH_VALUE = {"-C", "-c", "--exec-path", "--git-dir", "--namespace", "--work-tree"}


def command_name(argv: list[str]) -> str | None:
    index = 0
    while index < len(argv):
        value = argv[index]
        if value == "--":
            index += 1
            return argv[index] if index < len(argv) else None
        if value in OPTIONS_WITH_VALUE:
            index += 2
            continue
        long_options = (prefix for prefix in OPTIONS_WITH_VALUE if prefix.startswith("--"))
        if any(value.startswith(prefix + "=") for prefix in long_options):
            index += 1
            continue
        if value.startswith("-"):
            index += 1
            continue
        return value
    return None


def real_git() -> str | None:
    own_dir = Path(__file__).resolve().parent
    entries = []
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        try:
            if Path(entry).resolve() == own_dir:
                continue
        except OSError:
            pass
        entries.append(entry)
    return shutil.which("git", path=os.pathsep.join(entries))


def main() -> int:
    command = command_name(sys.argv[1:])
    if command not in ALLOWED:
        print("awf model Git guard: trusted runner owns Git writes", file=sys.stderr)
        return 126
    git_bin = real_git()
    if not git_bin:
        print("awf model Git guard: real Git executable not found", file=sys.stderr)
        return 127
    try:
        return run_command([git_bin, *sys.argv[1:]], stdin=DEVNULL).returncode
    except ExecutionFailure:
        print("awf model Git guard: real Git execution failed", file=sys.stderr)
        return 127


if __name__ == "__main__":
    raise SystemExit(main())
