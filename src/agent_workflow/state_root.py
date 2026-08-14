"""Canonical host-local Agent Workflow state-root identity."""

from __future__ import annotations

import hashlib
from pathlib import Path


def resolve_state_root(value: Path | str) -> Path:
    return Path(value).expanduser().resolve()


def state_root_binding(value: Path | str) -> str:
    resolved = str(resolve_state_root(value))
    return "sha256:" + hashlib.sha256(("awf-state-root-v1\0" + resolved).encode()).hexdigest()
