#!/usr/bin/env python3
"""Build and measure CI-only binary distribution candidates."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

EVIDENCE_FORMAT = "awf.binary-feasibility.v1"
SUMMARY_FORMAT = "awf.binary-feasibility-summary.v1"
CANDIDATES = ("pyinstaller-onedir", "pex-scie-eager", "go-launcher-pex-app")
TARGETS = (
    "linux-x86_64",
    "linux-arm64",
    "windows-x86_64",
    "macos-x86_64",
    "macos-arm64",
)
REQUIRED_PROBES = (
    "resources",
    "resource_directories",
    "python_reentry_module",
    "python_reentry_script",
    "fake_external_cli_exact_argv",
    "utf8_log_round_trip",
    "native_lifecycle_render",
)


class FeasibilityError(RuntimeError):
    """Raised when evidence is missing, malformed, or internally inconsistent."""


def _run(
    argv: list[str],
    *,
    cwd: Path,
    timeout: int = 300,
    check: bool = True,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        argv,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )
    if check and result.returncode != 0:
        command = Path(argv[0]).name
        detail = (result.stderr or result.stdout).strip()
        suffix = f": {detail[-2000:]}" if detail else ""
        raise FeasibilityError(
            f"{command} failed with exit code {result.returncode}{suffix}"
        )
    return result


def _normalized_machine(value: str) -> str:
    lowered = value.lower().replace("-", "_")
    if lowered in {"amd64", "x86_64", "x64"}:
        return "x86_64"
    if lowered in {"aarch64", "arm64"}:
        return "arm64"
    return lowered


def native_target() -> str:
    systems = {"linux": "linux", "windows": "windows", "darwin": "macos"}
    system = systems.get(platform.system().lower(), platform.system().lower())
    return f"{system}-{_normalized_machine(platform.machine())}"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact_facts(path: Path) -> dict[str, object]:
    if path.is_file():
        return {"bytes": path.stat().st_size, "files": 1, "sha256": _sha256_file(path)}
    if not path.is_dir():
        raise FeasibilityError("candidate artifact is unavailable")
    digest = hashlib.sha256()
    total = 0
    count = 0
    for child in sorted(item for item in path.rglob("*") if item.is_file()):
        relative = child.relative_to(path).as_posix()
        value = _sha256_file(child)
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(value.encode("ascii"))
        total += child.stat().st_size
        count += 1
    return {"bytes": total, "files": count, "sha256": digest.hexdigest()}


def _write_sbom(path: Path) -> None:
    components = []
    distributions = sorted(
        importlib.metadata.distributions(), key=lambda item: item.metadata.get("Name", "")
    )
    for distribution in distributions:
        name = distribution.metadata.get("Name", "")
        if not name:
            continue
        version = distribution.version
        components.append(
            {
                "type": "library",
                "name": name,
                "version": version,
                "purl": f"pkg:pypi/{name.lower().replace('_', '-')}@{version}",
            }
        )
    path.write_text(
        json.dumps(
            {
                "bomFormat": "CycloneDX",
                "specVersion": "1.5",
                "version": 1,
                "components": components,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _tool_version(argv: list[str], repo: Path) -> str:
    result = _run(argv, cwd=repo, timeout=30)
    return (result.stdout or result.stderr).strip().splitlines()[0]


def _candidate_paths(root: Path) -> dict[str, tuple[Path, Path]]:
    suffix = ".exe" if os.name == "nt" else ""
    pyinstaller_root = root / "pyinstaller" / "awf-pyinstaller"
    return {
        "pyinstaller-onedir": (
            pyinstaller_root,
            pyinstaller_root / f"awf-pyinstaller{suffix}",
        ),
        "pex-scie-eager": (root / "pex", root / "pex" / f"awf-pex{suffix}"),
        "go-launcher-pex-app": (root / "go", root / "go" / f"awf-launcher{suffix}"),
    }


def build_candidates(repo: Path, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    dist = output / "wheel"
    dist.mkdir()
    _run(
        [sys.executable, "-m", "build", "--wheel", "--outdir", str(dist)],
        cwd=repo,
        timeout=600,
    )
    wheels = sorted(dist.glob("*.whl"))
    if len(wheels) != 1:
        raise FeasibilityError("expected one Workflow wheel")
    pyinstaller_parent = output / "pyinstaller"
    (output / "pyinstaller-work").mkdir()
    (output / "pyinstaller-spec").mkdir()
    _run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--onedir",
            "--name",
            "awf-pyinstaller",
            "--collect-all",
            "agent_workflow",
            "--distpath",
            str(pyinstaller_parent),
            "--workpath",
            str(output / "pyinstaller-work"),
            "--specpath",
            str(output / "pyinstaller-spec"),
            str(repo / "experiments/binary-feasibility/awf_entry.py"),
        ],
        cwd=repo,
        timeout=900,
    )
    pex_root = output / "pex"
    pex_root.mkdir()
    suffix = ".exe" if os.name == "nt" else ""
    pex_app = pex_root / f"awf-pex{suffix}"
    _run(
        [
            sys.executable,
            "-m",
            "pex",
            str(wheels[0]),
            "-D",
            str(repo / "experiments/binary-feasibility"),
            "-e",
            "awf_entry:main",
            "--scie",
            "eager",
            "-o",
            str(pex_app),
        ],
        cwd=repo,
        timeout=900,
    )
    go_root = output / "go"
    go_root.mkdir()
    go_app = go_root / f"awf-app{suffix}"
    shutil.copy2(pex_app, go_app)
    go_launcher = go_root / f"awf-launcher{suffix}"
    _run(
        ["go", "build", "-trimpath", "-o", str(go_launcher), "."],
        cwd=repo / "experiments/binary-feasibility",
        timeout=300,
    )
    (go_root / "release.json").write_text(
        json.dumps(
            {
                "format": "awf.binary-release.v1",
                "version": "0.3.0-feasibility",
                "app": go_app.name,
                "sha256": _sha256_file(go_app),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    _write_sbom(output / "sbom.cdx.json")
    (output / "tooling.json").write_text(
        json.dumps(
            {
                "python": platform.python_version(),
                "pyinstaller": _tool_version(
                    [sys.executable, "-m", "PyInstaller", "--version"], repo
                ),
                "pex": _tool_version([sys.executable, "-m", "pex", "--version"], repo),
                "go": _tool_version(["go", "version"], repo),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    for artifact_root, executable in _candidate_paths(output).values():
        if not artifact_root.exists() or not executable.is_file():
            raise FeasibilityError("candidate build did not produce its declared executable")


def _timed_version(executable: Path, cwd: Path, env: dict[str, str]) -> tuple[bool, float]:
    started = time.perf_counter()
    result = _run([str(executable), "version"], cwd=cwd, timeout=60, check=False, env=env)
    elapsed = (time.perf_counter() - started) * 1000
    return result.returncode == 0 and result.stdout.startswith("awf "), round(elapsed, 3)


def _no_model_check(executable: Path, root: Path, env: dict[str, str]) -> bool:
    repo = root / "project 世界"
    repo.mkdir()
    state_root = root / "state"
    task_id = "BINARY-FEASIBILITY-001"
    card = repo / "task.md"
    card.write_text(
        f"## Task ID\n\n{task_id}\n\n"
        "<!-- awf-postflight\n"
        + json.dumps(
            {
                "allowed_paths": [
                    "result.txt",
                    f".awf/artifacts/impl-report-{task_id}.md",
                    f".awf/artifacts/review-report-{task_id}.md",
                ],
                "verification_commands": [],
            }
        )
        + "\n-->\n",
        encoding="utf-8",
    )
    profiles = []
    for role, tool, model, route in (
        ("coder", "opencode", "coder/model", "task:awf-impl-v3"),
        ("reviewer", "pi", "reviewer/model", "task:awf-review-v3"),
    ):
        profile = repo / f"{role}.json"
        profile.write_text(
            json.dumps(
                {
                    "format": "awf.node-profile.v1",
                    "name": f"binary-{role}",
                    "role": role,
                    "repo": str(repo),
                    "tool": tool,
                    "model": model,
                    "on_type": route,
                    "state_root": str(state_root),
                    "upstream_repo": "owner/repo",
                    "head_repo": "owner/fork",
                }
            ),
            encoding="utf-8",
        )
        profiles.append(profile)
    manifest = repo / ".awf/run-manifest.json"
    setup = _run(
        [
            str(executable),
            "setup",
            "--repo",
            str(repo),
            "--card",
            "task.md",
            "--run-manifest",
            str(manifest),
            "--branch",
            f"feature/{task_id}",
            "--tool",
            "opencode",
            "--model",
            "coder/model",
            "--reviewer-tool",
            "pi",
            "--reviewer-model",
            "reviewer/model",
            "--upstream-repo",
            "owner/repo",
            "--head-repo",
            "owner/fork",
            "--state-root",
            str(state_root),
            "--profile",
            f"coder={profiles[0]}",
            "--profile",
            f"reviewer={profiles[1]}",
        ],
        cwd=root,
        timeout=60,
        check=False,
        env=env,
    )
    if setup.returncode != 0:
        return False
    checked = _run(
        [str(executable), "run", "check", "--repo", str(repo)],
        cwd=root,
        timeout=60,
        check=False,
        env=env,
    )
    return checked.returncode == 0 and "contract=compatible" in checked.stdout


def _runtime_probe(executable: Path, cwd: Path, env: dict[str, str]) -> dict[str, Any]:
    result = _run(
        [str(executable), "__feasibility_probe__"],
        cwd=cwd,
        timeout=90,
        check=False,
        env=env,
    )
    if result.returncode != 0:
        return {"format": "unavailable", "returncode": result.returncode}
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"format": "invalid-json", "returncode": result.returncode}
    return value if isinstance(value, dict) else {"format": "invalid-value"}


def _go_checksum_gate(
    artifact_root: Path, executable: Path, cwd: Path, env: dict[str, str]
) -> bool:
    manifest_path = artifact_root / "release.json"
    original = manifest_path.read_text(encoding="utf-8")
    value = json.loads(original)
    value["sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(value), encoding="utf-8")
    try:
        result = _run(
            [str(executable), "version"],
            cwd=cwd,
            timeout=30,
            check=False,
            env=env,
        )
        return result.returncode == 78 and "checksum mismatch" in result.stderr
    finally:
        manifest_path.write_text(original, encoding="utf-8")


def _go_manifest_swap_gate(
    artifact_root: Path, executable: Path, cwd: Path, env: dict[str, str]
) -> bool:
    manifest_path = artifact_root / "release.json"
    original = manifest_path.read_text(encoding="utf-8")
    value = json.loads(original)
    current = artifact_root / value["app"]
    previous = artifact_root / ("awf-app.previous.exe" if os.name == "nt" else "awf-app.previous")
    shutil.copy2(current, previous)
    value["version"] = "0.3.0-feasibility-previous"
    value["app"] = previous.name
    value["sha256"] = _sha256_file(previous)
    manifest_path.write_text(json.dumps(value), encoding="utf-8")
    try:
        previous_result = _run(
            [str(executable), "version"],
            cwd=cwd,
            timeout=30,
            check=False,
            env=env,
        )
    finally:
        manifest_path.write_text(original, encoding="utf-8")
        previous.unlink(missing_ok=True)
    current_result = _run([str(executable), "version"], cwd=cwd, timeout=30, check=False, env=env)
    return previous_result.returncode == 0 and current_result.returncode == 0


def collect_evidence(candidate: str, target: str, build_root: Path, output: Path) -> None:
    if candidate not in CANDIDATES or target not in TARGETS:
        raise FeasibilityError("candidate or target is outside the frozen matrix")
    actual_target = native_target()
    if actual_target != target:
        raise FeasibilityError(
            f"runner target mismatch: expected {target}, observed {actual_target}"
        )
    artifact_root, executable = _candidate_paths(build_root)[candidate]
    with tempfile.TemporaryDirectory(prefix="awf-binary-evidence-") as raw_temp:
        outside = Path(raw_temp) / "unrelated cwd 世界"
        outside.mkdir()
        environment = dict(os.environ)
        environment.pop("PYTHONPATH", None)
        environment["XDG_CONFIG_HOME"] = str(outside / "config")
        environment["XDG_STATE_HOME"] = str(outside / "state")
        environment["APPDATA"] = str(outside / "config")
        cold_ok, cold_ms = _timed_version(executable, outside, environment)
        warm = [_timed_version(executable, outside, environment) for _ in range(3)]
        probe = _runtime_probe(executable, outside, environment)
        no_model = _no_model_check(executable, outside, environment)
        go_gate = None
        manifest_swap = None
        if candidate == "go-launcher-pex-app":
            go_gate = _go_checksum_gate(artifact_root, executable, outside, environment)
            manifest_swap = _go_manifest_swap_gate(artifact_root, executable, outside, environment)
    sbom = build_root / "sbom.cdx.json"
    tooling = json.loads((build_root / "tooling.json").read_text(encoding="utf-8"))
    evidence = {
        "format": EVIDENCE_FORMAT,
        "candidate": candidate,
        "target": target,
        "actual_target": actual_target,
        "python": platform.python_version(),
        "artifact": artifact_facts(artifact_root),
        "startup_ms": {
            "cold": cold_ms,
            "warm_median": round(statistics.median(value for _, value in warm), 3),
        },
        "version_command": cold_ok and all(ok for ok, _ in warm),
        "runtime_probe": probe,
        "no_model_run_check": no_model,
        "go_checksum_fail_closed": go_gate,
        "upgrade_rollback": {
            "manifest_swap_tested": manifest_swap,
            "status": (
                "independent-app-manifest-swap"
                if candidate == "go-launcher-pex-app"
                else "not-applicable-monolithic-candidate"
            ),
        },
        "tooling": tooling,
        "sbom": {
            "format": "CycloneDX-1.5",
            "sha256": _sha256_file(sbom),
        },
        "trust": {
            "signed": False,
            "notarized": False,
            "attested": False,
            "status": "not-attempted-no-credentials",
        },
        "antivirus_reputation": {
            "tested": False,
            "status": "unproved-no-production-signing-or-reputation-service",
        },
        "disposable_bus": "verified-separately-in-native-job",
        "real_service_mutation": False,
        "remote_business_event": False,
        "model_invocation": False,
    }
    validate_evidence(evidence)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def validate_evidence(value: dict[str, Any]) -> None:
    if value.get("format") != EVIDENCE_FORMAT:
        raise FeasibilityError("invalid evidence format")
    if value.get("candidate") not in CANDIDATES or value.get("target") not in TARGETS:
        raise FeasibilityError("invalid evidence identity")
    if value.get("target") != value.get("actual_target"):
        raise FeasibilityError("evidence target does not match the native runner")
    artifact = value.get("artifact")
    if (
        not isinstance(artifact, dict)
        or artifact.get("bytes", 0) <= 0
        or artifact.get("files", 0) <= 0
    ):
        raise FeasibilityError("artifact facts are incomplete")
    if len(str(artifact.get("sha256", ""))) != 64:
        raise FeasibilityError("artifact checksum is invalid")
    if value.get("real_service_mutation") is not False:
        raise FeasibilityError("real service mutation is prohibited")
    if (
        value.get("remote_business_event") is not False
        or value.get("model_invocation") is not False
    ):
        raise FeasibilityError("remote events and model invocation are prohibited")
    trust = value.get("trust")
    if not isinstance(trust, dict) or any(
        trust.get(key) is not False for key in ("signed", "notarized", "attested")
    ):
        raise FeasibilityError("credential-free trust facts must remain false")
    tooling = value.get("tooling")
    if not isinstance(tooling, dict) or any(
        not str(tooling.get(name, "")).strip() for name in ("python", "pyinstaller", "pex", "go")
    ):
        raise FeasibilityError("tool version facts are incomplete")
    sbom = value.get("sbom")
    if not isinstance(sbom, dict) or len(str(sbom.get("sha256", ""))) != 64:
        raise FeasibilityError("SBOM facts are incomplete")
    antivirus = value.get("antivirus_reputation")
    if not isinstance(antivirus, dict) or antivirus.get("tested") is not False:
        raise FeasibilityError("antivirus reputation must remain explicitly unproved")
    upgrade = value.get("upgrade_rollback")
    if not isinstance(upgrade, dict) or "manifest_swap_tested" not in upgrade:
        raise FeasibilityError("upgrade and rollback facts are incomplete")


def _candidate_passes(value: dict[str, Any]) -> bool:
    probe = value.get("runtime_probe")
    return bool(
        value.get("version_command")
        and value.get("no_model_run_check")
        and isinstance(probe, dict)
        and all(probe.get(name) is True for name in REQUIRED_PROBES)
        and probe.get("real_service_mutation") is False
        and probe.get("remote_connection") is False
        and probe.get("model_invocation") is False
        and (
            value.get("candidate") != "go-launcher-pex-app"
            or (
                value.get("go_checksum_fail_closed") is True
                and value.get("upgrade_rollback", {}).get("manifest_swap_tested") is True
            )
        )
    )


def summarize(input_root: Path, output: Path) -> None:
    records: dict[tuple[str, str], dict[str, Any]] = {}
    for path in sorted(input_root.rglob("*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(value, dict) or value.get("format") != EVIDENCE_FORMAT:
            continue
        validate_evidence(value)
        key = (value["candidate"], value["target"])
        if key in records:
            raise FeasibilityError("duplicate candidate/target evidence")
        records[key] = value
    required = {(candidate, target) for candidate in CANDIDATES for target in TARGETS}
    missing = sorted(required - records.keys())
    if missing:
        raise FeasibilityError(f"missing candidate evidence: {missing}")
    results = {
        candidate: {target: _candidate_passes(records[(candidate, target)]) for target in TARGETS}
        for candidate in CANDIDATES
    }
    go_all = all(results["go-launcher-pex-app"].values())
    summary = {
        "format": SUMMARY_FORMAT,
        "targets": list(TARGETS),
        "results": results,
        "decision_input": "GO_LAUNCHER" if go_all else "NO_GO_PRODUCTION_BINARY",
        "production_abi_created": False,
        "signing_notarization_proved": False,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    build.add_argument("--repo", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    collect = commands.add_parser("collect")
    collect.add_argument("--candidate", choices=CANDIDATES, required=True)
    collect.add_argument("--target", choices=TARGETS, required=True)
    collect.add_argument("--build-root", type=Path, required=True)
    collect.add_argument("--output", type=Path, required=True)
    aggregate = commands.add_parser("summarize")
    aggregate.add_argument("--input", type=Path, required=True)
    aggregate.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            build_candidates(args.repo.resolve(), args.output.resolve())
        elif args.command == "collect":
            collect_evidence(args.candidate, args.target, args.build_root.resolve(), args.output)
        else:
            summarize(args.input.resolve(), args.output)
    except (FeasibilityError, OSError, subprocess.TimeoutExpired) as exc:
        print(f"ERROR: binary feasibility failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
