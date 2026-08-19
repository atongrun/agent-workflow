#!/usr/bin/env python3
"""Scripted no-model provider for the RTS-020 Python shared slice."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f"{path.name}.tmp-{os.getpid()}")
    temp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def _counter(path: Path, role: str) -> None:
    if path.exists():
        value = json.loads(path.read_text(encoding="utf-8"))
    else:
        value = {"implement": 0, "review": 0, "calls": []}
    value[role] = int(value.get(role, 0)) + 1
    calls = list(value.get("calls", []))
    calls.append(role)
    value["calls"] = calls
    _atomic_json(path, value)


def main() -> int:
    if "RTS020_SENTINEL_SECRET" in os.environ:
        return 71

    parser = argparse.ArgumentParser()
    parser.add_argument("--role", choices=["implement", "review"], required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--counter", required=True)
    parser.add_argument("--mode", default="normal", choices=["normal", "invalid-artifact"])
    args = parser.parse_args()

    workspace = Path(args.workspace)
    artifact = Path(args.artifact)
    _counter(Path(args.counter), args.role)

    if args.role == "implement":
        (workspace / "result.txt").write_text(
            "RTS-020 disposable Python shared slice output\n",
            encoding="utf-8",
        )
        if args.mode == "invalid-artifact":
            _atomic_json(
                artifact,
                {
                    "artifact_type": "BrokenReport",
                    "changed_files": ["result.txt"],
                    "summary": "Scripted invalid artifact for S-ARTIFACT.",
                },
            )
        else:
            _atomic_json(
                artifact,
                {
                    "artifact_type": "ImplementationReport",
                    "changed_files": ["result.txt"],
                    "summary": "Scripted implementer produced the disposable allowed delta.",
                    "synthetic_intelligence": True,
                },
            )
    else:
        if not (workspace / "result.txt").exists():
            return 2
        _atomic_json(
            artifact,
            {
                "artifact_type": "ReviewReport",
                "verdict": "PASS",
                "summary": "Scripted reviewer accepted the disposable local Git effect.",
                "synthetic_intelligence": True,
            },
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
