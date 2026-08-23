from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_workflow.plan_loop import validate_taskcard_binding
from agent_workflow.runtime.architect import (
    assemble_opencode_taskcard,
    parse_opencode_task_semantic,
    persist_architect_taskcard,
)
from agent_workflow.runtime.artifact import ArtifactError, parse_postflight_contract


def taskcard(task_id: str = "P5-TEST-001") -> bytes:
    postflight = {
        "allowed_paths": [
            f".awf/artifacts/impl-report-{task_id}.md",
            f".awf/artifacts/review-report-{task_id}.md",
        ],
        "verification_commands": [["git", "diff", "--check"]],
    }
    return (
        "# Planned TaskCard\n\n"
        f"## Task ID\n\n{task_id}\n\n"
        f"- **Task branch**: `codex/{task_id}`\n\n"
        "## Goal\n\nBounded work.\n\n"
        "<!-- awf-postflight\n" + json.dumps(postflight, indent=2) + "\n-->\n"
    ).encode("utf-8")


def semantic_output(**updates: object) -> bytes:
    value: dict[str, object] = {
        "task_id": "OPEN-001",
        "objective": "Document the accepted adapter sequence.",
        "scope": ["Create one acceptance document.", "Link it from the README."],
        "change_paths": ["README.md", "docs/acceptance/open-001.md"],
        "constraints": ["Do not add application code."],
        "acceptance_criteria": ["The role sequence is stated exactly."],
        "verification_commands": [["git", "diff", "--check"]],
    }
    value.update(updates)
    return json.dumps(value, separators=(",", ":")).encode("utf-8")


def test_opencode_semantic_output_assembles_existing_strict_taskcard(tmp_path: Path) -> None:
    coder = {"tool": "opencode", "model": ""}
    reviewer = {"tool": "pi", "model": ""}
    semantic = parse_opencode_task_semantic(semantic_output())

    raw = assemble_opencode_taskcard(
        semantic,
        frozen_base="a" * 40,
        repository="owner/project",
        base_ref="main",
        coder=coder,
        reviewer=reviewer,
    )

    assert validate_taskcard_binding(
        raw,
        frozen_base="a" * 40,
        coder=coder,
        reviewer=reviewer,
    ) == ("OPEN-001", "agent/OPEN-001")
    text = raw.decode("utf-8")
    assert "- **Frozen base**: `" + "a" * 40 + "`" in text
    assert '{"coder":{"model":"","tool":"opencode"},"reviewer":{"model":"","tool":"pi"}}' in text
    assert ".awf/artifacts/impl-report-OPEN-001.md" in text
    assert ".awf/artifacts/review-report-OPEN-001.md" in text

    repo = tmp_path / "repo"
    destination = repo / "docs/tasks/OPEN-001.md"
    destination.parent.mkdir(parents=True)
    persist_architect_taskcard(repo=str(repo), destination=str(destination), stdout=raw)
    contract = parse_postflight_contract(destination, "python-test")
    assert contract.allowed_paths == (
        "README.md",
        "docs/acceptance/open-001.md",
        ".awf/artifacts/impl-report-OPEN-001.md",
        ".awf/artifacts/review-report-OPEN-001.md",
    )


@pytest.mark.parametrize(
    "raw",
    [
        b"not-json",
        semantic_output(extra="not allowed"),
        semantic_output(task_id="../escape"),
        semantic_output(change_paths=["README.md", ".awf/artifacts/forged.md"]),
    ],
)
def test_opencode_semantic_output_fails_closed(raw: bytes) -> None:
    with pytest.raises(ArtifactError):
        parse_opencode_task_semantic(raw)


def test_trusted_architect_boundary_validates_then_creates_exact_taskcard(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    destination = repo / "docs" / "tasks" / "P5-TEST-001.md"
    destination.parent.mkdir(parents=True)
    raw = taskcard()

    fact = persist_architect_taskcard(
        repo=str(repo),
        destination=str(destination),
        stdout=raw,
    )

    assert destination.read_bytes() == raw
    assert fact.path == "docs/tasks/P5-TEST-001.md"
    assert fact.size == len(raw)
    assert len(fact.sha256) == 64
    with pytest.raises(ArtifactError, match="already exists"):
        persist_architect_taskcard(repo=str(repo), destination=str(destination), stdout=raw)


def test_trusted_architect_boundary_accepts_markdown_code_span_task_id(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    destination = repo / "docs/tasks/P5-TEST-001.md"
    destination.parent.mkdir(parents=True)
    raw = taskcard().replace(b"\nP5-TEST-001\n", b"\n`P5-TEST-001`\n", 1)

    fact = persist_architect_taskcard(repo=str(repo), destination=str(destination), stdout=raw)

    assert fact.path == "docs/tasks/P5-TEST-001.md"


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda raw: b"\xff" + raw, "valid UTF-8"),
        (lambda raw: raw.replace(b"codex/P5-TEST-001", b"codex/other"), "identity"),
        (
            lambda raw: raw.replace(b"review-report-P5-TEST-001.md", b"review-report-other.md"),
            "report-path binding",
        ),
        (
            lambda raw: raw.replace(b".awf/artifacts/impl-report-P5-TEST-001.md", b"../impl.md"),
            "escape the repository",
        ),
        (lambda raw: raw + b"\nsk-example12345678901234567890\n", "prohibited"),
    ],
)
def test_trusted_architect_boundary_denies_invalid_stdout_before_write(
    tmp_path: Path,
    mutation,
    message: str,
) -> None:
    repo = tmp_path / "repo"
    destination = repo / "docs" / "tasks" / "P5-TEST-001.md"
    destination.parent.mkdir(parents=True)

    with pytest.raises(ArtifactError, match=message):
        persist_architect_taskcard(
            repo=str(repo),
            destination=str(destination),
            stdout=mutation(taskcard()),
        )
    assert not destination.exists()


def test_trusted_architect_boundary_denies_parent_and_escape_before_write(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    missing = repo / "missing" / "task.md"
    with pytest.raises(ArtifactError, match="parent is unavailable"):
        persist_architect_taskcard(repo=str(repo), destination=str(missing), stdout=taskcard())

    outside = tmp_path / "outside"
    outside.mkdir()
    escape = outside / "task.md"
    with pytest.raises(ArtifactError, match="escapes"):
        persist_architect_taskcard(repo=str(repo), destination=str(escape), stdout=taskcard())
    assert not escape.exists()


def test_trusted_architect_boundary_denies_symlink_parent(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    outside = tmp_path / "outside"
    repo.mkdir()
    outside.mkdir()
    link = repo / "tasks"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable")

    with pytest.raises(ArtifactError, match="parent is unavailable"):
        persist_architect_taskcard(
            repo=str(repo),
            destination=str(link / "task.md"),
            stdout=taskcard(),
        )
    assert not (outside / "task.md").exists()
