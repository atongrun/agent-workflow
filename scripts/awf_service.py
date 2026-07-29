#!/usr/bin/env python3
"""Native service entry point for Agent Workflow listeners on every OS."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import awf_listen
from awf_config import ConfigError, default_config_path, load_into_environment


def die(message: str) -> None:
    print(f"awf_service: {message}", file=sys.stderr)
    raise SystemExit(2)


def _append_value(argv: list[str], flag: str, variable: str, default: str = "") -> None:
    value = os.environ.get(variable, default)
    if value:
        argv.extend([flag, value])


def main() -> int:
    config = default_config_path()
    try:
        load_into_environment(config)
    except ConfigError as exc:
        die(f"invalid operations configuration: {exc}")

    role = os.environ.get("AWF_ROLE", "")
    repo = os.environ.get("AWF_REPO", "")
    if not role:
        die("AWF_ROLE is required")
    if not repo or not Path(repo).is_absolute():
        die("AWF_REPO must be an absolute path")

    argv = ["--config", str(config), "--role", role, "--repo", repo]
    _append_value(argv, "--tool", "AWF_TOOL", "opencode")
    _append_value(argv, "--model", "AWF_MODEL")
    _append_value(argv, "--base", "AWF_BASE")
    _append_value(argv, "--on-type", "AWF_ON_TYPE")
    _append_value(argv, "--upstream-repo", "AWF_UPSTREAM_REPO")
    _append_value(argv, "--upstream-remote", "AWF_UPSTREAM_REMOTE")
    _append_value(argv, "--head-repo", "AWF_HEAD_REPO")
    _append_value(argv, "--head-remote", "AWF_HEAD_REMOTE")
    _append_value(argv, "--base-ref", "AWF_BASE_REF")
    _append_value(argv, "--gh-bin", "AWF_GH_BIN")
    if os.environ.get("AWF_NO_PUSH", "0") == "1":
        argv.append("--no-push")
    return awf_listen.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
