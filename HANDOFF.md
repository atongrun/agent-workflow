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

- Current verified base: `main` / `origin/main` at `7b1bb29` (PR #12 merge).
- PR #1 through PR #12 are merged. The product-positioning branch was deleted after its merge;
  the reviewer-routing branch remains until its separate cleanup gate.
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
commit/push plus remote-SHA proof, durable handler evidence, Windows handler-return/ACK, and
fail-closed semantic `PASS` / deterministic `REQUEST_CHANGES` / `BLOCKED` routing.

The remaining preserved portability branches contain failed TaskCards, not merge-ready
implementations. The next priority is a fresh Windows Python 3.12 UTF-8 closeout from current main;
review-to-merge-to-next-TaskCard live acceptance remains later work.

## Next Gates

1. Execute [`docs/tasks/windows-python312-utf8-closeout.md`](docs/tasks/windows-python312-utf8-closeout.md)
   from its frozen current-main baseline in a fresh Windows checkout.
2. After successful acceptance and merge, separately authorize deletion of the two superseded
   UTF-8 failure-evidence branches.
3. Run fresh semantic review-loop acceptance, then the first downstream multi-TaskCard dogfood.
