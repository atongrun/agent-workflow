from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path

import pytest

from agent_workflow.runtime.artifact import (
    ArtifactError,
    PostflightContract,
    artifact_fact,
    compile_implementation_report_path,
    compile_review_report_path,
    compile_run_artifact_contract,
    compile_stage_artifact_contract,
    normalize_review_envelope,
    normalize_rework_feedback,
    parse_postflight_contract,
    parse_review_report,
    path_is_denied,
    postflight_result,
    resolve_repo_file,
    resolve_review_report_path,
    validate_embedded_review_report,
    validate_implementation_report,
    validate_postflight_paths,
    validate_secret_observation,
    validate_stage_artifact_contract,
)


def write_card(
    path: Path,
    *,
    allowed_paths: list[str],
    commands: list[list[str]] | None = None,
) -> None:
    payload = {
        "allowed_paths": allowed_paths,
        "verification_commands": commands or [["{python}", "-c", "raise SystemExit(0)"]],
    }
    path.write_text(
        "# TaskCard\n\n<!-- awf-postflight\n" + json.dumps(payload, indent=2) + "\n-->\n",
        encoding="utf-8",
    )


def review_markdown(
    verdict: str,
    *,
    failures: list[dict[str, object]] | None = None,
    blocked_reason: object = "",
) -> str:
    payload = {
        "verdict": verdict,
        "deterministic_failures": failures or [],
        "blocked_reason": blocked_reason,
    }
    return "# ReviewReport\n\n<!-- awf-review-report\n" + json.dumps(payload) + "\n-->\n"


def test_taskcard_contract_is_immutable_and_binds_exact_report_paths(tmp_path: Path) -> None:
    task_id = "runtime-v2-artifact"
    implementation = compile_implementation_report_path(task_id)
    review = compile_review_report_path(task_id)
    card = tmp_path / "task.md"
    write_card(card, allowed_paths=["result.txt", implementation, review])

    postflight = parse_postflight_contract(card, "/bound/python")
    stage = compile_stage_artifact_contract(
        card_path=card,
        task_id=task_id,
        requested_report_path="",
    )
    received = validate_stage_artifact_contract(
        card_path=card,
        task_id=task_id,
        required_report_path=implementation,
    )
    run = compile_run_artifact_contract(
        repo=tmp_path,
        card_path=card,
        task_id=task_id,
        implementation_report_path=implementation,
        review_report_path=review,
    )

    assert dataclasses.is_dataclass(postflight)
    assert postflight.allowed_paths == ("result.txt", implementation, review)
    assert postflight.verification_commands[0][0] == "/bound/python"
    assert stage == received
    assert run.taskcard_path == "task.md"
    assert run.allowed_paths == postflight.allowed_paths
    with pytest.raises(dataclasses.FrozenInstanceError):
        postflight.allowed_paths = ()  # type: ignore[misc]


@pytest.mark.parametrize(
    "bad_path",
    ["../outside.md", "/outside.md", "C:/outside.md", r".awf\artifacts\report.md"],
)
def test_owner_bound_report_paths_reject_escape(tmp_path: Path, bad_path: str) -> None:
    task_id = "task"
    implementation = compile_implementation_report_path(task_id)
    card = tmp_path / "task.md"
    write_card(card, allowed_paths=[implementation])

    with pytest.raises(ArtifactError):
        compile_stage_artifact_contract(
            card_path=card,
            task_id=task_id,
            requested_report_path=bad_path,
        )


def test_implementation_report_fact_binds_exact_bytes_size_and_path(tmp_path: Path) -> None:
    report = tmp_path / "implementation.md"
    raw = b"# ImplementationReport\n\nvalidated\n"
    report.write_bytes(raw)

    fact = validate_implementation_report(report, ".awf/artifacts/implementation.md")

    assert fact.path == ".awf/artifacts/implementation.md"
    assert fact.size == len(raw)
    assert fact.sha256 == hashlib.sha256(raw).hexdigest()
    report.write_bytes(raw + b"changed\n")
    assert artifact_fact(report, fact.path).sha256 != fact.sha256


@pytest.mark.parametrize(
    "content",
    [
        "",
        "\x00",
        '<!-- awf-implementation-report {"summary":"x"} -->',
        (
            '<!-- awf-implementation-report {"summary":"x","summary":"y",'
            '"changed_files":[],"commands":[],"tests":[],"source_revision":"a"} -->'
        ),
    ],
)
def test_implementation_report_rejects_invalid_bytes_or_machine_object(
    tmp_path: Path, content: str
) -> None:
    report = tmp_path / "implementation.md"
    report.write_text(content, encoding="utf-8")
    with pytest.raises(ArtifactError):
        validate_implementation_report(report)


def test_review_report_normalization_and_embedded_revalidation_are_exact(tmp_path: Path) -> None:
    report = tmp_path / "review.md"
    report.write_text(review_markdown("PASS", blocked_reason=None), encoding="utf-8")

    validated = parse_review_report(report, ".awf/artifacts/review.md")
    payload = validated.review.as_payload()

    assert payload["verdict"] == "PASS"
    assert payload["blocked_reason"] == ""
    assert validated.artifact.size == len(report.read_bytes())
    assert validate_embedded_review_report(payload).as_payload() == payload
    changed = dict(payload)
    changed["verdict"] = "BLOCKED"
    with pytest.raises(ArtifactError, match="does not match"):
        validate_embedded_review_report(changed)


def test_review_report_preserves_deterministic_request_changes_evidence(tmp_path: Path) -> None:
    failure = {
        "evidence": {"kind": "file_line", "file": "src/runtime.py", "line": 17},
        "required_correction": "preserve the bound result",
    }
    report = tmp_path / "review.md"
    report.write_text(review_markdown("REQUEST_CHANGES", failures=[failure]), encoding="utf-8")

    payload = parse_review_report(report).review.as_payload()

    assert payload["deterministic_failures"] == [failure]
    assert payload["blocked_reason"] == ""


def test_rework_projection_drops_review_prose_without_relaxing_embedded_validation() -> None:
    failure = {
        "evidence": {"kind": "criterion", "criterion": "AC-7"},
        "required_correction": "preserve the exact Artifact fact",
    }
    payload = {
        "format": "awf.review-report.v1",
        "verdict": "REQUEST_CHANGES",
        "deterministic_failures": [failure],
        "blocked_reason": "",
        "markdown": "review prose must not reach the executor",
    }

    assert json.loads(normalize_rework_feedback(payload))["deterministic_failures"] == [
        failure,
    ]
    with pytest.raises(ArtifactError, match="exactly one"):
        validate_embedded_review_report(payload)


@pytest.mark.parametrize(
    "markdown",
    [
        review_markdown("REQUEST_CHANGES"),
        review_markdown("BLOCKED"),
        review_markdown("PASS", blocked_reason="not empty"),
        "# ReviewReport\n\n```diff\n+ prohibited body\n```\n",
        "# ReviewReport\n\n<!-- awf-review-report\n{}\n-->\n",
    ],
)
def test_review_report_rejects_invalid_verdict_or_body(tmp_path: Path, markdown: str) -> None:
    report = tmp_path / "review.md"
    report.write_text(markdown, encoding="utf-8")
    with pytest.raises(ArtifactError):
        parse_review_report(report)


def test_one_line_review_envelope_normalizes_before_hash_binding(tmp_path: Path) -> None:
    report = tmp_path / "review.md"
    report.write_text(
        '<!-- awf-review-report {"verdict":"PASS","deterministic_failures":[],'
        '"blocked_reason":null} -->\n',
        encoding="utf-8",
    )

    normalize_review_envelope(report)
    validated = parse_review_report(report)

    assert report.read_text(encoding="utf-8").startswith("<!-- awf-review-report\n")
    assert validated.review.as_payload()["verdict"] == "PASS"


def test_postflight_path_policy_is_exact_and_nested() -> None:
    contract = PostflightContract(("src/a.py", "nested/.env", "nested/build/a.py"), ())

    assert validate_postflight_paths(contract, ("src/a.py",)) == ("src/a.py",)
    with pytest.raises(ArtifactError, match="not in allowed_paths"):
        validate_postflight_paths(contract, ("outside.py",))
    with pytest.raises(ArtifactError, match="denylist"):
        validate_postflight_paths(contract, ("nested/.env",))
    with pytest.raises(ArtifactError, match="denylist"):
        validate_postflight_paths(contract, ("nested/build/a.py",))
    assert path_is_denied("nested/.env.local")
    assert not path_is_denied("nested/.env.example")


def test_secret_observations_bind_content_without_exposing_values() -> None:
    token = "gh" + "p_" + "A" * 40
    with pytest.raises(ArtifactError, match=r"github-token in src/a.py") as failure:
        validate_secret_observation((("src/a.py", token),), ())
    assert token not in str(failure.value)

    digest = validate_secret_observation(
        (("src/a.py", 'token = "placeholder"'),),
        (("new file.txt", "benign"),),
    )
    assert len(digest) == 64
    with pytest.raises(ArtifactError, match="unreadable-file"):
        validate_secret_observation((), (), ("unreadable.txt",))


def test_postflight_result_is_deterministic_and_diff_check_fails_closed() -> None:
    first = postflight_result(("src/a.py",), "a" * 64, 0)
    second = postflight_result(("src/a.py",), "a" * 64, 0)

    assert first == second
    assert len(first.observation_sha256) == 64
    with pytest.raises(ArtifactError, match="whitespace errors"):
        postflight_result(("src/a.py",), "a" * 64, 1)


def test_resolved_artifact_paths_remain_repo_contained_and_distinct(tmp_path: Path) -> None:
    implementation = resolve_repo_file(
        tmp_path, "reports/implementation.md", "ImplementationReport"
    )
    review = resolve_review_report_path(tmp_path, "reports/review.md", str(implementation))

    assert implementation == tmp_path / "reports" / "implementation.md"
    assert review == tmp_path / "reports" / "review.md"
    with pytest.raises(ArtifactError):
        resolve_repo_file(tmp_path, "../outside.md", "Artifact")
    with pytest.raises(ArtifactError, match="distinct"):
        resolve_review_report_path(tmp_path, "reports/implementation.md", str(implementation))
