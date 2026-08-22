from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from agent_workflow.plan_loop import (
    ArchitectBinding,
    PlanLoopError,
    PlanRunStore,
    architect_context,
    compile_plan_fact,
    completed_card_fact,
    find_plan_run,
    next_architect_context,
    parse_decision,
    parse_next_output,
    plan_start_payload,
    plan_status_lines,
    validate_plan_start_payload,
    validate_taskcard_binding,
)


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def repository(tmp_path: Path) -> tuple[Path, Path]:
    upstream = tmp_path / "upstream.git"
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "--bare", str(upstream)], check=True, capture_output=True)
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    git(repo, "config", "user.name", "Plan Test")
    git(repo, "config", "user.email", "plan@example.invalid")
    (repo / "docs").mkdir()
    (repo / "docs/plan.md").write_text("# Exact Plan\n", encoding="utf-8")
    git(repo, "add", "docs/plan.md")
    git(repo, "commit", "-m", "Add Plan")
    git(repo, "remote", "add", "upstream", str(upstream))
    git(repo, "push", "upstream", "main")
    return repo, upstream


def binding(repo: Path, tmp_path: Path) -> ArchitectBinding:
    profile = tmp_path / "architect.json"
    profile.write_text(
        json.dumps(
            {
                "upstream_repo": "owner/project",
                "upstream_remote": "upstream",
                "base_ref": "main",
            }
        ),
        encoding="utf-8",
    )
    return ArchitectBinding(
        profile=str(profile),
        profile_sha256="sha256:" + "a" * 64,
        workspace=str(repo),
        tool="pi",
        model_mode="tool-default",
        model_ref="",
    )


def taskcard(base: str) -> bytes:
    return f"""# TaskCard

## Task ID

CARD-001

- **Task branch**: `codex/CARD-001`
- **Frozen base**: `{base}`

<!-- awf-reviewer-selection
{{"coder":{{"model":"","tool":"opencode"}},"reviewer":{{"model":"","tool":"opencode"}}}}
-->
""".encode()


def test_compile_plan_fact_binds_exact_blob_and_fresh_main(tmp_path: Path) -> None:
    repo, _ = repository(tmp_path)
    selected = binding(repo, tmp_path)

    fact, raw = compile_plan_fact(repo, Path("docs/plan.md"), selected)

    assert raw == b"# Exact Plan\n"
    assert fact.path == "docs/plan.md"
    assert fact.commit == git(repo, "rev-parse", "HEAD")
    assert fact.main_sha == fact.commit
    assert fact.repository == "owner/project"
    (repo / "docs/plan.md").write_text("dirty\n", encoding="utf-8")
    with pytest.raises(PlanLoopError, match="working-tree bytes"):
        compile_plan_fact(repo, Path("docs/plan.md"), selected)


def test_start_payload_and_plan_run_are_exact_and_replayable(tmp_path: Path) -> None:
    repo, _ = repository(tmp_path)
    selected = binding(repo, tmp_path)
    fact, _ = compile_plan_fact(repo, Path("docs/plan.md"), selected)
    payload = plan_start_payload(
        fact,
        selected,
        mode="one-card",
        coder_tool="opencode",
        coder_model="",
        reviewer_tool="opencode",
        reviewer_model="",
    )
    parsed = validate_plan_start_payload(payload)
    store = PlanRunStore(tmp_path / "state", str(payload["run_id"]))

    created = store.create(payload, repo=repo)
    replay = store.create(payload, repo=repo)

    assert parsed["plan_fact"] == fact
    assert created == replay
    assert created["status"] == "start_prepared"
    assert created["current_card"] is None
    assert created["last_completion"] is None
    store.update(
        status="card_active",
        current_card={"branch": "codex/CARD-001"},
        preflight={"authoring": {"status": "PASS"}},
    )
    assert find_plan_run(tmp_path / "state", branch="codex/CARD-001") is not None
    changed = dict(payload)
    changed["mode"] = "milestone"
    with pytest.raises(PlanLoopError, match="payload identity"):
        validate_plan_start_payload(changed)


def test_architect_context_and_taskcard_binding_are_closed(tmp_path: Path) -> None:
    repo, _ = repository(tmp_path)
    selected = binding(repo, tmp_path)
    fact, raw = compile_plan_fact(repo, Path("docs/plan.md"), selected)
    coder = {"tool": "opencode", "model": ""}
    reviewer = {"tool": "opencode", "model": ""}

    context = architect_context(
        plan=fact,
        plan_bytes=raw,
        architect=selected,
        coder=coder,
        reviewer=reviewer,
    )
    task_id, branch = validate_taskcard_binding(
        taskcard(fact.main_sha),
        frozen_base=fact.main_sha,
        coder=coder,
        reviewer=reviewer,
    )

    assert fact.blob_sha256 in context
    assert "# Exact Plan" in context
    assert "review-report-<TASK_ID>.md" in context
    assert "equal the Task ID character-for-character" in context
    assert "agent/<TASK_ID>" in context
    assert (task_id, branch) == ("CARD-001", "codex/CARD-001")
    with pytest.raises(PlanLoopError, match="fresh upstream main"):
        validate_taskcard_binding(
            taskcard("f" * 40),
            frozen_base=fact.main_sha,
            coder=coder,
            reviewer=reviewer,
        )

    decorated = (
        taskcard(fact.main_sha)
        .replace(
            b"CARD-001\n\n- **Task branch**",
            b"`CARD-001`\n\n- **Task branch**",
        )
        .replace(
            f"`{fact.main_sha}`".encode(),
            f"`{fact.main_sha}` (exact current main)".encode(),
        )
    )
    assert validate_taskcard_binding(
        decorated,
        frozen_base=fact.main_sha,
        coder=coder,
        reviewer=reviewer,
    ) == ("CARD-001", "codex/CARD-001")


def test_decision_next_output_and_completed_fact_are_closed(tmp_path: Path) -> None:
    repo, _ = repository(tmp_path)
    selected = binding(repo, tmp_path)
    fact, _ = compile_plan_fact(repo, Path("docs/plan.md"), selected)
    decision = parse_decision(b"# Decision\n\n**Verdict:** approve\n")
    run = {
        "run_id": "plan-test",
        "plan": fact.to_mapping(),
        "architect": selected.to_mapping(),
    }
    card = {"task_id": "CARD-001", "branch": "codex/CARD-001", "head_sha": "b" * 40}
    completed = completed_card_fact(
        run=run,
        card=card,
        decision=decision,
        ci={"conclusion": "SUCCESS"},
        merge={"state": "MERGED", "commit": "c" * 40},
    )

    assert decision["verdict"] == "approve"
    assert completed["card"] == card
    assert len(str(completed["sha256"])) == 64
    assert parse_next_output(b"MILESTONE_COMPLETE\n") == ("MILESTONE_COMPLETE", "")
    assert parse_next_output(b"BLOCKED\nmissing evidence\n") == (
        "BLOCKED",
        "missing evidence",
    )
    assert parse_next_output(taskcard(fact.main_sha))[0] == "NEXT_TASK_CARD"
    with pytest.raises(PlanLoopError, match="non-empty reason"):
        parse_next_output(b"BLOCKED\n")
    with pytest.raises(PlanLoopError, match="complete Architect output"):
        parse_next_output(b"MILESTONE_COMPLETE\nextra")
    with pytest.raises(PlanLoopError, match="approve and green CI"):
        completed_card_fact(
            run=run,
            card=card,
            decision={"verdict": "reject"},
            ci={"conclusion": "SUCCESS"},
            merge={"state": "MERGED", "commit": "c" * 40},
        )


def test_completed_card_facts_are_immutable_and_feed_minimal_next_context(tmp_path: Path) -> None:
    repo, _ = repository(tmp_path)
    selected = binding(repo, tmp_path)
    plan, plan_bytes = compile_plan_fact(repo, Path("docs/plan.md"), selected)
    payload = plan_start_payload(
        plan,
        selected,
        mode="milestone",
        coder_tool="opencode",
        coder_model="coder/model",
        reviewer_tool="pi",
        reviewer_model="review/model",
    )
    store = PlanRunStore(tmp_path / "state", str(payload["run_id"]))
    run = store.create(payload, repo=repo)
    completion = completed_card_fact(
        run=run,
        card={"task_id": "CARD-001", "branch": "agent/CARD-001", "head_sha": "b" * 40},
        decision={"verdict": "approve"},
        ci={"conclusion": "SUCCESS"},
        merge={"state": "MERGED", "commit": "c" * 40},
    )

    first_path = store.persist_completion(completion)
    assert store.persist_completion(completion) == first_path
    assert store.completions() == (completion,)
    context = next_architect_context(
        plan=plan,
        plan_bytes=plan_bytes,
        fresh_main="d" * 40,
        last_completion=completion,
        coder=run["coder"],
        reviewer=run["reviewer"],
        completed_task_ids=("CARD-001",),
    )

    assert '"fresh_main": "' + "d" * 40 + '"' in context
    assert '"completed_task_ids": [' in context
    assert "MILESTONE_COMPLETE" in context
    assert "stdout must contain only the single line" in context
    assert "Reason silently" in context
    assert "Do not pre-generate later cards" in context
    changed = {**completion, "completed_at": "changed"}
    with pytest.raises(PlanLoopError, match="malformed"):
        store.persist_completion(changed)


def test_plan_status_is_a_read_only_projection(tmp_path: Path) -> None:
    repo, _ = repository(tmp_path)
    selected = binding(repo, tmp_path)
    fact, _ = compile_plan_fact(repo, Path("docs/plan.md"), selected)
    payload = plan_start_payload(
        fact,
        selected,
        mode="one-card",
        coder_tool="opencode",
        coder_model="",
        reviewer_tool="opencode",
        reviewer_model="",
    )
    store = PlanRunStore(tmp_path / "state", str(payload["run_id"]))
    store.create(payload, repo=repo)
    store.update(
        status="card_active",
        current_card={"task_id": "CARD-001", "branch": "codex/CARD-001"},
        preflight={
            "authoring": {"status": "PASS"},
            "remote_dispatch": {"status": "PASS", "deep": {"current": True}},
        },
    )
    before = store.path.read_bytes()

    lines = plan_status_lines(store.load())

    assert store.path.read_bytes() == before
    assert any("status=card_active" in line for line in lines)
    assert any("deep_current=True" in line for line in lines)
