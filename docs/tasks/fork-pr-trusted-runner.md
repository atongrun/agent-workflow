# Implementation Plan: Fork/PR-aware trusted runner

## Objective

Replace the operations runner's single-`origin` publication assumption with an explicit fork/PR
contract. The trusted runner may fetch an allowlisted upstream repository, push only to an
allowlisted contribution fork, create or reuse one pull request, verify its exact head/base tuple,
and hand that tuple to the reviewer. Model processes remain remote-free and credential-free.

## Frozen baseline and branch

- Upstream baseline: `main` at `f24b5fb1a4097a24b37210643dc15277f7b5dbe6`.
- Feature branch: `codex/fork-pr-trusted-runner`.
- PR #27 is merged at the baseline above.
- PR #28 is a separate disposable-proof draft and is out of scope.

## Contract

1. Add versioned v3 implementation, review, and rework routes. Default dispatch/listeners use v3;
   legacy v1/v2 routes remain available only when explicitly selected and never interpret a v3
   provenance payload. Register all v3 stage types in the existing pre-invocation route gate.
2. Read remote names and allowed GitHub repository identities from trusted local listener/dispatch
   configuration. Event payloads contain repository identities and refs, never remote URLs or
   credentials.
3. Validate repository slugs, Git refs, remote names, commit IDs, PR identifiers, and configured
   remote URLs before Git or GitHub operations. Only canonical credential-free GitHub HTTPS remotes
   are accepted for the v3 trusted path.
4. Bind `awf.pr-provenance.v1` to upstream repo/base ref/base SHA, head repo/ref/head SHA, and PR
   number. A reviewer must verify the live PR and fork ref equal this tuple before checkout or model
   invocation.
5. The trusted coder commits, pushes `HEAD` to the configured fork ref, freshly verifies the fork
   SHA, creates or reuses the matching PR through a bounded `gh` subprocess, and verifies the live
   PR tuple before preparing the reviewer outbox.
6. Persist the complete provenance tuple in the coder outbox and reviewer input. Replay freshly
   verifies both the fork ref and PR tuple before any send; drift is a durable fail-closed reason.
7. Failures in push, fetch, GitHub CLI availability/calls, PR create/reuse, or tuple equality do not
   send a reviewer event and do not permit a successful handler return.

## Test order

1. Add regression tests for validation, trusted remote binding, fork push/SHA equality, PR
   create/reuse and exact tuple verification, reviewer pre-model checkout, and v3 listener fields.
2. Add outbox prepared/ambiguous/sent replay tests that preserve and revalidate the same tuple
   without rerunning a model.
3. Preserve the existing single-origin v1/v2 tests as explicit legacy-route coverage and prove that
   v3 rejects incomplete provenance before model invocation.
4. Run focused tests, the complete suite, Ruff check/format, shell syntax, resource validation, and
   diff checks.

## Non-goals

- No live Agent Bus event, historical event read, ACK, requeue, redispatch, or pending mutation.
- No credential inspection, credential URL, upstream write probe, dependency, Agent Bus change, or
  merge of this PR.
- No modification or expansion of PR #28.
