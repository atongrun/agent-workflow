# TaskCard: Retain event lifecycle evidence in future Agent Bus composition

## Goal and Baseline

Make one documentation-only improvement inside the transport-specific Agent Bus boundary note:
require future external composition to retain the event lifecycle fields used for durable evidence.

- Repository: `atongrun/agent-workflow`
- Base: `origin/main` at `3612ab5e305a82f6c67252ee34b2b6bf54f2f93a`
- Task branch: `codex/live-semantic-loop-acceptance-20260726-v5`
- The dispatched SHA must equal this frozen TaskCard commit.

This is a tiny, reversible, no-business-risk acceptance task. Do not broaden it.

## Allowed Paths

Only these two paths may change after this TaskCard commit:

1. `docs/later/agent-bus.md`
2. `docs/tasks/live-semantic-loop-acceptance-2026-07-26-v5-implementation-report.md` (create)

Do not edit this TaskCard.

## Exact Required Edit

Under `## Future Composition Rule` in `docs/later/agent-bus.md`, append exactly this rule after
existing rule 4:

```text
5. retain event ID, retry count, last error, and ACK state as transport evidence.
```

Do not rewrite, reorder, or reflow existing text.

Create `docs/tasks/live-semantic-loop-acceptance-2026-07-26-v5-implementation-report.md` containing:

- a one-sentence summary;
- exactly the two changed paths and their actions;
- the verification commands and pass/fail results;
- no deviations, or an explicit deviation if one occurred.

The implementer must not stage, commit, amend, reset, push, or change Git refs. The trusted runner
owns those operations.

## Acceptance Criteria

- The target file contains the exact new rule once, directly after rule 4.
- No existing text in the target file changes.
- The ImplementationReport contains all required sections and no unrelated claims.
- Exactly the two allowed paths differ from this frozen TaskCard commit.
- `git diff HEAD --check` passes before the trusted runner commits.

## Rework vs. Escalate

- Rework only for a deterministic failure of an acceptance criterion or verification.
- Stop if any other file must change, the checkout is dirty before execution, or the task requires
  credentials or a network call.

## Explicitly Out of Scope

- No Python, schema, workflow, template, listener, Agent Bus product, protocol, service, or
  dependency changes.
- No unrelated documentation edits, historical event access, or historical checkout changes.
- No merge, main update, branch deletion, release, tag, VPS, or server change.

## Required Output Artifact

Create `docs/tasks/live-semantic-loop-acceptance-2026-07-26-v5-implementation-report.md`.

<!-- awf-postflight
{
  "allowed_paths": [
    "docs/later/agent-bus.md",
    "docs/tasks/live-semantic-loop-acceptance-2026-07-26-v5-implementation-report.md"
  ],
  "verification_commands": [
    [
      "{python}",
      "-c",
      "from pathlib import Path; t=Path('docs/later/agent-bus.md').read_text(encoding='utf-8'); q='5. retain event ID, retry count, last error, and ACK state as transport evidence.'; assert t.count(q) == 1; assert '4. avoid teaching Agent Bus Workflow-specific verdicts or transitions.\\n'+q in t"
    ],
    ["git", "diff", "HEAD", "--check"]
  ]
}
-->

## Planner Self-Check

- [x] Goal and scope are concrete.
- [x] Verification is deterministic and local.
- [x] The edit stays in the transport-specific boundary note.
- [x] The executor needs no chat history, secret, or network call.
- [x] Trusted-runner Git ownership is explicit.
