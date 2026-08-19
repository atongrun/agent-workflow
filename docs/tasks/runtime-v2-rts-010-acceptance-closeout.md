# TaskCard: RTS-010 Fresh Business PASS Acceptance Closeout

## Task ID

RTS-010-CLOSEOUT

## Goal

Preserve the credential-free evidence for the one fresh, bounded downstream business PASS required
by Runtime v2 RTS-010. Close the gate only if the frozen authority, provider counts, trusted
Git/GitHub provenance, raw-file and canonical-object Artifact hash semantics, terminal decision,
handler-success ACKs, and isolated queue return form one consistent join without operating either
retained failed delivery.

## Working context

- **Repository**: `atongrun/agent-workflow`
- **Base**: `main@d92594dcb2ba48efe2ed62c2f236b629a07f85fe`
- **Branch**: `codex/runtime-v2-rts-010-closeout`
- **Plan**: `docs/plans/runtime-v2-development-plan.md`, Phase 1 / RTS-010
- **Downstream repository**: `atongrun/dousansi-shouzhang`
- **Downstream TaskCard**:
  `docs/tasks/runtime-v2-rts-010-home-reconsideration-r3.md`
- **Downstream run**:
  `task-dousansi-runtime-v2-rts-010-home-reconsideration-r3-20260820`

## Frozen scope

- Add the RTS-010 credential-free acceptance report.
- Update only the Runtime v2 gate status in the development plan, `HANDOFF.md`, and `ROADMAP.md`.
- Preserve the two earlier fail-closed authorities as failed evidence, not recovery inputs.
- Preserve the successful isolated run evidence until this closeout is integrated.

## Out of scope

- Runtime source, test, contract, matrix, language, store, Coordinator, CLI, release, default,
  migration, production, or destructive changes.
- Reading, ACKing, requeueing, recovering, redispatching, replacing, or deleting retained events.
- Claiming that a direct-listener acceptance proves native managed lifecycle behavior.
- Attaching CI or merge facts retroactively to the completed RunLedger.
- Promoting the semantic contract from `Draft`; RTS-011 must pass first.

## Acceptance criteria

- [x] The fresh TaskCard, branch, run, delivery, Bus, state-root, and profile identities are recorded.
- [x] Exactly one coder provider start/exit and one reviewer provider start/exit are evidenced; no
      rework provider invocation occurred.
- [x] Trusted commit, push, remote SHA, exact PR tuple, green CI, ReviewReport, terminal decision,
      handler-success ACK, and final scoped queue counts form one consistent provenance join.
- [x] Raw ReviewReport file SHA, canonical normalized-object SHA, ImplementationReport SHA, and
      delivery hashes are recorded under their distinct meanings without copying credentials or
      event payloads.
- [x] Both earlier failed authorities remain untouched and are excluded from acceptance evidence.
- [x] Setup/preflight failures before the business delivery are distinguished from provider or
      Workflow failures.
- [x] External GitHub CI/merge facts remain distinct from the terminal ledger's recorded fields.
- [x] An independent Reviewer returns `PASS` against the complete closeout diff.
- [x] No production/default/release/migration/destructive action is performed.

## Verification

- Cross-check the report against the retained isolated RunLedger, handler logs, checkpoints, and
  payload-blind Agent Bus status rows.
- Cross-check the downstream PR head, CI conclusion, merge commit, and current main SHA.
- Run repository-relative link/path checks and `git diff --check`.
- Audit changed paths against the frozen allowlist below.
- Use an independent Reviewer Agent against the exact closeout diff; repair and re-review on any
  finding.

Local Mac verification for this closeout is documentation/static only. It does not run pytest,
Ruff, a provider, a listener, or a new business event.

## Required output

- `docs/tasks/runtime-v2-rts-010-fresh-pass-acceptance-report.md`
- this TaskCard;
- Runtime v2 gate-status updates in the plan, `HANDOFF.md`, and `ROADMAP.md`;
- independent reviewer verdict preserved in the acceptance report.

<!-- awf-postflight
{
  "allowed_paths": [
    "docs/tasks/runtime-v2-rts-010-acceptance-closeout.md",
    "docs/tasks/runtime-v2-rts-010-fresh-pass-acceptance-report.md",
    "docs/plans/runtime-v2-development-plan.md",
    "HANDOFF.md",
    "ROADMAP.md"
  ],
  "verification_commands": [
    ["git", "diff", "--check"]
  ]
}
-->
