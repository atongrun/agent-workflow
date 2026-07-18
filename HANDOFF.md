# Repository Handoff

> Current as of 2026-07-18. Repository files and Git refs are authoritative; this document contains
> no private endpoint, credential, host, or personal-path data.

## Product Position

Agent Workflow is a model-agnostic development method, structured handoff protocol, and verifiable
process contract. It isolates scarce high-value-model capacity in downstream projects by assigning
frequent bounded work to lower-cost models and reserving high-value participation for architecture,
genuine escalation, and milestone acceptance. Infrastructure development may use high-value models
freely when quality or safety benefits.

Read in this order:

1. [`constitution.md`](constitution.md)
2. [`README.md`](README.md)
3. [`ROADMAP.md`](ROADMAP.md)
4. [`docs/adr/0005-high-value-model-capacity-isolation.md`](docs/adr/0005-high-value-model-capacity-isolation.md)
5. [`docs/reviews/2026-07-18-product-positioning-audit.md`](docs/reviews/2026-07-18-product-positioning-audit.md)

AI Memory can provide long-term/private background to an Architect or Planner. It does not override
these versioned files, and a fresh Executor must not need it when a TaskCard is complete.

## Repository and Branch Truth

- Audited base before this positioning work: `main` / `origin/main` at `19d8c44` (PR #10 merge).
- PR #1 through PR #10 were merged; no open or closed-unmerged PR existed at audit time.
- `codex/windows-python312-utf8` and `codex/windows-python312-utf8-rerun` are preserved failure-
  evidence branches. Do not delete, reset, reuse, or treat them as current product direction.
- A detached dirty postflight self-test worktree is preserved for separate audit; do not clean it as
  part of unrelated work.

Refresh refs before relying on this snapshot.

## Current Implementation Boundary

- Core: `constitution.md`, Role/Workflow/Artifact contracts, templates, and stateless validation CLI.
- Operations dogfood: `scripts/`, service templates, Agent Bus transport calls, model processes,
  checkout/postflight/push gates, and handler evidence.
- External: Agent Bus transport and AI Memory knowledge.
- Deferred: Agent Host, Plugin SDK, generic runtime, provider adapters, UI, and SaaS.

## Proven and Missing

Proven operations boundaries include exact checkout, trusted model-process and postflight gates,
commit/push plus remote-SHA proof, durable handler evidence, and Windows handler-return/ACK.

Missing from the complete chain: semantic ReviewReport routing, verdict-dependent fail-closed send,
review-to-merge decision, and automatic next TaskCard. The reviewer-routing TaskCard must be
regenerated from the post-positioning `main` before dispatch.

## Next Gates

1. Merge the product-positioning branch and refresh the reviewer-routing TaskCard baseline.
2. Close and verify semantic `PASS` / deterministic `REQUEST_CHANGES` / `BLOCKED` operations routing.
3. Run the first downstream multi-TaskCard dogfood and measure high-value-model capacity isolation.
