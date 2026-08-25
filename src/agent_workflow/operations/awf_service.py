#!/usr/bin/env python3
"""Compatibility entry point for profile-first foreground listeners."""

from __future__ import annotations

import os
import sys

from agent_workflow.node import NodeError, foreground, load_profile


def die(message: str) -> None:
    print(f"awf_service: {message}", file=sys.stderr)
    raise SystemExit(2)


def main() -> int:
    profile = os.environ.get("AWF_PROFILE", "")
    if not profile:
        die("AWF_PROFILE is required")
    try:
        return foreground(load_profile(profile))
    except (NodeError, OSError) as exc:
        die(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
