# TaskCard: RTS-001 Runtime v2 Semantic Contract Draft

## Task ID

RTS-001

## Goal

Extract the current Python operations Runtime's language-neutral authorization, invocation,
recovery, provenance, lifecycle, terminal, and transport semantics into a reviewable Draft. Make
every known fault boundary auditable without changing production behavior or selecting a language,
store, Coordinator topology, CLI, or migration.

## Working context

- **Repository**: `atongrun/agent-workflow`
- **Base**: `main@0ed7812a8dd9cc26d7e1ecb310ed1add95627bf2`
- **Owner evidence commit**: `6556ea6` (plan and two Review inputs; no Runtime source change)
- **Branch**: `codex/runtime-v2-rts-001`
- **Plan**: `docs/plans/runtime-v2-development-plan.md`, Phase 0 / RTS-001
- **Review basis**: `docs/reviews/2026-08-19-runtime-v2-adversarial-double-review.md`

The owner has separately authorized continuing beyond the plan's former “Complete RTS-001 only”
sentence after this TaskCard passes. That continuation authority does not weaken any Phase entry
criterion or production/live-action boundary.

## Frozen scope

- Add `docs/runtime-v2-semantic-contract.md` with maturity `Draft`.
- Add `docs/testing/runtime-v2-fault-matrix.md` and its machine-readable JSON companion.
- Add a current authority/evidence/record inventory generated from named code, tests, and reports.
- Separate observed facts from target hypotheses and explicit open questions.
- Preserve the original 2026-08-18 Review byte-for-byte as owner-provided untracked evidence.

## Out of scope

- Production code, tests that change Runtime behavior, Runtime state, queue, provider, model,
  service, remote repository, release, migration, or retained delivery operations.
- Freezing a CLI hierarchy, file layout, route name, Python symbol, store, database, language, or
  physical Coordinator.
- Reading, ACKing, requeueing, recovering, redispatching, or replacing historical/retained events.
- Claiming that historical business acceptance is the required post-remediation RTS-010 result.

## Acceptance criteria

- [x] Every normative Draft transition cites current code, test, or versioned report evidence.
- [x] Every coder/reviewer checkpoint phase, outbox status, inbox completion, terminal boundary,
      handler-success boundary, and ACK observation maps to an outcome or explicit open question.
- [x] Run, task, role, delivery, invocation, workspace, Git/PR/CI, process/incarnation, and Artifact
      identity owners are explicit.
- [x] The proposed five-state invocation enum is either sufficient or explicitly rejected and
      replaced with a representation that does not collapse distinct current effects.
- [x] Unknown, stale, corrupt, mismatched, duplicate, ambiguous, and conflicting facts fail closed;
      legal owner-only recovery decisions are distinguished from automatic recovery.
- [x] The inventory classifies each persistent record family as authority, intent, evidence,
      derived view, cache, or external observation and records its owner/multiplicity/joins.
- [x] The machine-readable fault matrix parses, has unique case IDs, and references only declared
      outcomes and evidence IDs.
- [x] Independent review returns `PASS` with no unmapped known production fault boundary.
- [x] No production behavior or external state changes.

## Verification

- Parse and validate the JSON matrix with the standard library.
- Check every matrix evidence reference and semantic outcome against the Draft's declared IDs.
- Run repository-relative link/path checks and `git diff --check`.
- Audit changed paths against the frozen allowlist below.
- Use an independent Reviewer Agent against the exact diff; on `FAIL`, repair and re-review.

Local Mac verification remains documentation/static only. Pytest, Ruff, provider calls, live queue
operations, remote nodes, and services are neither necessary nor authorized for RTS-001.

## Required output

- `docs/runtime-v2-semantic-contract.md`
- `docs/testing/runtime-v2-fault-matrix.md`
- `docs/testing/runtime-v2-fault-matrix.json`
- `docs/testing/runtime-v2-authority-record-inventory.md`
- `docs/tasks/runtime-v2-semantic-contract-draft-implementation-report.md`
- Independent reviewer verdict preserved in the implementation report/evidence.

<!-- awf-postflight
{
  "allowed_paths": [
    "docs/runtime-v2-semantic-contract.md",
    "docs/testing/runtime-v2-fault-matrix.md",
    "docs/testing/runtime-v2-fault-matrix.json",
    "docs/testing/runtime-v2-authority-record-inventory.md",
    "docs/tasks/runtime-v2-semantic-contract-draft.md",
    "docs/tasks/runtime-v2-semantic-contract-draft-implementation-report.md",
    "docs/plans/runtime-v2-development-plan.md",
    "HANDOFF.md",
    "ROADMAP.md"
  ],
  "verification_commands": [
    ["{python}", "-m", "json.tool", "docs/testing/runtime-v2-fault-matrix.json"],
    ["git", "diff", "--check"]
  ]
}
-->
