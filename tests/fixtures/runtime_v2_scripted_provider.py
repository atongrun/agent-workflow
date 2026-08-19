#!/usr/bin/env python3
"""Deterministic no-model provider used by the Runtime v2 RTS-011 acceptance."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def _atomic_write_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f"{path.name}.tmp-{os.getpid()}")
    temp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def _bump(counter_path: Path, action: str, kind: str) -> dict[str, object]:
    if counter_path.exists():
        value = json.loads(counter_path.read_text(encoding="utf-8"))
    else:
        value = {"implement": 0, "rework": 0, "review": 0, "calls": []}
    value[kind] = int(value.get(kind, 0)) + 1
    calls = list(value.get("calls", []))
    calls.append(action)
    value["calls"] = calls
    _atomic_write_json(counter_path, value)
    return value


def _review_report(verdict: str) -> str:
    failures = []
    blocked_reason = None
    if verdict == "REQUEST_CHANGES":
        failures = [
            {
                "path": "runtime-v2-rts011.txt",
                "line": 1,
                "severity": "medium",
                "message": "scripted deterministic rework request",
            }
        ]
        blocked_reason = ""
    machine = {
        "verdict": verdict,
        "deterministic_failures": failures,
        "blocked_reason": blocked_reason,
    }
    return (
        "# ReviewReport\n\n"
        f"Verdict: {verdict}\n\n"
        "<!-- awf-review-report\n"
        f"{json.dumps(machine, indent=2, sort_keys=True)}\n"
        "-->\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--action",
        choices=["implement", "rework", "review-request-changes", "review-pass"],
        required=True,
    )
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--counter", required=True)
    parser.add_argument("--report", default="")
    args = parser.parse_args()

    workspace = Path(args.workspace)
    report = Path(args.report) if args.report else Path("impl.md")
    artifact = workspace / report
    counter_path = Path(args.counter)
    artifact.parent.mkdir(parents=True, exist_ok=True)

    if args.action == "implement":
        _bump(counter_path, args.action, "implement")
        (workspace / "runtime-v2-rts011.txt").write_text("implemented\n", encoding="utf-8")
        artifact.write_text(
            "# ImplementationReport\n\n"
            "Scripted provider produced the initial disposable implementation.\n",
            encoding="utf-8",
        )
    elif args.action == "rework":
        _bump(counter_path, args.action, "rework")
        (workspace / "runtime-v2-rts011.txt").write_text(
            "implemented\nreworked\n", encoding="utf-8"
        )
        artifact.write_text(
            "# ImplementationReport\n\n"
            "Scripted provider applied the deterministic rework.\n",
            encoding="utf-8",
        )
    elif args.action == "review-request-changes":
        _bump(counter_path, args.action, "review")
        artifact.write_text(_review_report("REQUEST_CHANGES"), encoding="utf-8")
    else:
        _bump(counter_path, args.action, "review")
        artifact.write_text(_review_report("PASS"), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
