from __future__ import annotations

import json
import runpy
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
feasibility = SimpleNamespace(
    **runpy.run_path(ROOT / "experiments/binary-feasibility/verify.py")
)


def evidence(candidate: str, target: str, *, passes: bool = True) -> dict:
    probe = {name: passes for name in feasibility.REQUIRED_PROBES}
    probe.update(
        {
            "format": "awf.binary-runtime-probe.v1",
            "real_service_mutation": False,
            "remote_connection": False,
            "model_invocation": False,
        }
    )
    return {
        "format": feasibility.EVIDENCE_FORMAT,
        "candidate": candidate,
        "target": target,
        "actual_target": target,
        "artifact": {"bytes": 10, "files": 1, "sha256": "a" * 64},
        "version_command": passes,
        "no_model_run_check": passes,
        "runtime_probe": probe,
        "go_checksum_fail_closed": passes if candidate == "go-launcher-pex-app" else None,
        "upgrade_rollback": {
            "manifest_swap_tested": passes if candidate == "go-launcher-pex-app" else None,
            "status": "fixture",
        },
        "tooling": {
            "python": "3.12",
            "pyinstaller": "6",
            "pex": "2",
            "go": "go1.23",
        },
        "sbom": {"format": "CycloneDX-1.5", "sha256": "b" * 64},
        "trust": {
            "signed": False,
            "notarized": False,
            "attested": False,
            "status": "not-attempted-no-credentials",
        },
        "antivirus_reputation": {"tested": False, "status": "unproved"},
        "real_service_mutation": False,
        "remote_business_event": False,
        "model_invocation": False,
    }


@pytest.mark.parametrize(
    ("system", "machine", "expected"),
    [
        ("Linux", "x86_64", "linux-x86_64"),
        ("Linux", "aarch64", "linux-arm64"),
        ("Windows", "AMD64", "windows-x86_64"),
        ("Darwin", "x86_64", "macos-x86_64"),
        ("Darwin", "arm64", "macos-arm64"),
    ],
)
def test_native_target_normalizes_supported_runner_identities(
    monkeypatch, system, machine, expected
):
    monkeypatch.setattr(feasibility.platform, "system", lambda: system)
    monkeypatch.setattr(feasibility.platform, "machine", lambda: machine)
    assert feasibility.native_target() == expected


def test_artifact_facts_are_content_and_relative_path_bound(tmp_path):
    artifact = tmp_path / "artifact"
    artifact.mkdir()
    (artifact / "one.txt").write_text("one", encoding="utf-8")
    first = feasibility.artifact_facts(artifact)
    (artifact / "one.txt").write_text("two", encoding="utf-8")
    second = feasibility.artifact_facts(artifact)
    assert first["bytes"] == second["bytes"] == 3
    assert first["files"] == second["files"] == 1
    assert first["sha256"] != second["sha256"]


def test_evidence_rejects_target_drift_and_trust_claims():
    value = evidence("pex-scie-eager", "linux-x86_64")
    value["actual_target"] = "linux-arm64"
    with pytest.raises(feasibility.FeasibilityError, match="native runner"):
        feasibility.validate_evidence(value)
    value = evidence("pex-scie-eager", "linux-x86_64")
    value["trust"]["signed"] = True
    with pytest.raises(feasibility.FeasibilityError, match="trust facts"):
        feasibility.validate_evidence(value)


def test_summary_requires_complete_matrix_and_keeps_failed_candidate_as_evidence(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    for candidate in feasibility.CANDIDATES:
        for target in feasibility.TARGETS:
            passes = not (candidate == "pyinstaller-onedir" and target == "windows-x86_64")
            path = source / f"{candidate}-{target}.json"
            path.write_text(
                json.dumps(evidence(candidate, target, passes=passes)), encoding="utf-8"
            )
    output = tmp_path / "summary.json"
    feasibility.summarize(source, output)
    summary = json.loads(output.read_text(encoding="utf-8"))
    assert summary["format"] == feasibility.SUMMARY_FORMAT
    assert summary["results"]["pyinstaller-onedir"]["windows-x86_64"] is False
    assert summary["decision_input"] == "GO_LAUNCHER"
    assert summary["production_abi_created"] is False


def test_summary_fails_closed_when_one_target_is_missing(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "one.json").write_text(
        json.dumps(evidence("pex-scie-eager", "linux-x86_64")), encoding="utf-8"
    )
    with pytest.raises(feasibility.FeasibilityError, match="missing candidate evidence"):
        feasibility.summarize(source, tmp_path / "summary.json")
