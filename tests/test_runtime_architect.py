from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_workflow.runtime.architect import parse_architect_decision, persist_architect_taskcard
from agent_workflow.runtime.artifact import ArtifactError


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


def decision(verdict: str = "approve") -> str:
    return (
        "# Decision\n\n"
        "## Verdict\n\n"
        f"**Verdict:** {verdict}\n\n"
        "## Rationale\n\nEvidence is sufficient.\n\n"
        "## Mandatory Actions\n\n- None.\n\n"
        "## Optional Actions\n\n- None.\n\n"
        "## Next Stage\n\ntrusted-merge\n"
    )


def test_terminal_architect_parser_accepts_only_existing_decision_verdicts(tmp_path: Path) -> None:
    path = tmp_path / "decision.md"
    path.write_text(decision(), encoding="utf-8")

    verdict, fact = parse_architect_decision(path, ".awf/artifacts/decision.md")

    assert verdict == "approve"
    assert fact.path == ".awf/artifacts/decision.md"
    assert fact.size == len(decision().encode())

    path.write_text(decision("blocked"), encoding="utf-8")
    with pytest.raises(ArtifactError, match="one supported verdict"):
        parse_architect_decision(path, ".awf/artifacts/decision.md")
