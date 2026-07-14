# Task Card

<!--
A TaskCard is a SELF-CONTAINED handoff package. An executor (a coding agent such as
OpenCode, possibly on another machine, in a fresh session with no chat history) must be
able to complete this task from THIS FILE ALONE. If the executor would need something
that is not written here, it belongs in this card — not in a conversation.
Fill every section. Delete a section only if it is genuinely N/A, and say why.
-->

## Task ID
<!-- Stable identifier, e.g. ABUS-DIAG-001 -->

[TASK-ID]

## Background
<!-- Context and motivation. Why this task exists now, and how it fits the current milestone. -->

[Describe the background and motivation]

## Goal
<!-- The single, concrete outcome this task delivers. -->

[Describe the desired outcome]

## Scope
<!-- What is included. Keep it to one deliverable. -->

- [Item 1]

## Out of Scope
<!-- Explicitly excluded. The executor MUST NOT expand beyond scope; if tempted, escalate. -->

- [Item 1]

## Working Context (self-contained)
<!--
Everything the executor needs to start WITHOUT the planner's chat history.
This is the section that makes cross-machine / fresh-session handoff work.
-->

- **Repository / path**: [where the code lives]
- **Base branch**: [branch used to create this task branch, e.g. `main`]
- **Task branch**: [remote branch the executor must receive, e.g. `feature/task-id`]
- **Dispatched task commit**: [exact commit expected at `origin/<task-branch>`]
- **Remote baseline**: [expected `origin/<base>` commit used when the task branch was created]
- **Entry points & relevant files**: [paths the executor should read/edit first]
- **Relevant existing behavior**: [what already works and must not regress]
- **Project rules**: see this project's `AGENTS.md` for stack, conventions, and commands.
  <!-- Do NOT copy workflow/method rules here; only project-specific facts. -->

## Constraints
<!-- Non-negotiable constraints for THIS task. -->

- [Constraint 1]

## Acceptance Criteria
<!--
How success is measured. Each criterion MUST be verifiable by a concrete command or
observable check — not a vague statement. Reference the project's real commands.
-->

- [ ] [Criterion 1 — e.g. `pytest tests/test_doctor.py` passes]
- [ ] [Criterion 2 — e.g. `agent-bus doctor --json` returns valid JSON, exit 0]

## Verification Commands
<!-- The exact commands the executor runs locally to self-check before handing back. -->

```bash
[build / test / run commands, copied from the project's AGENTS.md]
```

## Rework vs. Escalate
<!-- The boundary for the executor. Keep this as-is unless the task needs a narrower rule. -->

- **Rework locally** only for deterministic failures: compile/test failure, a failed
  acceptance criterion, missing required evidence, or a clear violation of this card.
- **Escalate (stop and report)** if: the goal is ambiguous, required context is missing,
  there is an architecture/scope question, or a change would exceed **Out of Scope**.

## Risks
<!-- Known risks and severity. -->

| Risk | Severity | Mitigation |
|------|----------|------------|
|      |          |            |

## Required Output Artifacts
<!-- What the executor must hand back. -->

- ImplementationReport (what changed, commands run, deviations)
- [Other artifacts]

---

## Planner Self-Check (complete BEFORE handing this card to an executor)
<!--
Consistency gate. This card is not ready to delegate until every box is checked.
This replaces a separate "analyze" tool — it is a checklist, not code.
-->

- [ ] Goal is a single concrete deliverable (not a bundle of tasks).
- [ ] Scope and Out of Scope are explicit and non-overlapping.
- [ ] Every Acceptance Criterion is verifiable by a command or observable check.
- [ ] Verification Commands are real commands from the project (checked against its `AGENTS.md`).
- [ ] Working Context lets a fresh-session executor start without the planner's chat history.
- [ ] Base branch, task branch, dispatched task commit, and remote baseline are explicit; the
      task branch was created from the stated `origin/<base>` and pushed before dispatch.
- [ ] This task advances the current milestone (no unrelated refactors / scope creep).

---

## Postflight Contract (required for automated dispatch)

<!-- awf-postflight
{
  "allowed_paths": [
    "path/to/file1.py",
    "path/to/file2.py"
  ],
  "verification_commands": [
    ["{python}", "-m", "pytest", "-q", "tests/test_file.py"]
  ]
}
-->
