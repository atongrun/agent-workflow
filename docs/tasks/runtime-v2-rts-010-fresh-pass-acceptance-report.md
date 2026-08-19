# RTS-010 Fresh Post-Remediation Business PASS — Acceptance Report

Status: **PASS; independent closeout review passed**

## 1. Outcome

RTS-010 passed with one fresh, useful Dousansi business slice after both known compiled-run entry
defects were merged. The isolated run performed exactly one Windows OpenCode implementation
invocation and exactly one Mac Pi review invocation, produced a trusted downstream commit and PR,
terminated `PASS`, reached handler-success ACK for every isolated event, returned all three scoped
role queues to zero, passed downstream CI, and merged.

The successful authority did not read, recover, ACK, requeue, redispatch, replace, or delete either
earlier failed delivery. No production/default/release/migration/destructive action occurred.

## 2. Frozen sources and identities

| Fact | Frozen value |
|---|---|
| Agent Workflow source | `d92594dcb2ba48efe2ed62c2f236b629a07f85fe` (PR #98 merge) |
| Downstream TaskCard preparation merge/base | `4f3b12760678e8dca33adad695d6e148dd092720` (PR #39) |
| Task / dispatch identity | `dousansi-runtime-v2-rts-010-home-reconsideration-r3-20260820` |
| Run ID | `task-dousansi-runtime-v2-rts-010-home-reconsideration-r3-20260820` |
| Task branch | `agent/dousansi-runtime-v2-rts-010-home-reconsideration-r3-20260820` |
| Architect/coder/reviewer | Mac Codex / Windows OpenCode / Mac Pi |
| Coder model | `opencode-go/deepseek-v4-flash` |
| Reviewer model | `opencode-go/deepseek-v4-pro` |
| Isolated Bus identity | `rts010-r3-d92594d`, dedicated TCP port `18802` and fresh SQLite store |
| Mac canonical state-root binding | `sha256:224e504e6e31b51557653c90cdc51c42eeff2e3332cf9eaabf8bf1fef4114aa6` |
| Windows canonical state-root binding | `sha256:f6ab4693cc86531b64d1f0fef9627d2df124b358c11d16bd1fbcf3aeb50c8af5` |
| Mac reviewer profile | `dousansi-rts010-r3-mac-d92594d-reviewer` |
| Windows coder profile | `dousansi-rts010-r3-win-d92594d-coder` |
| Mac compiled RunContract | `sha256:bd3ed0fbae2b30020f842cbcc93a10f473ee94e5ca349a7d7d5d6abd2ea37fb4` |
| Windows compiled RunContract | `sha256:9d0296015e2badaa5b1424fd84e2974c3d4e84f75faba8fcf34d85f95dfcff62` |
| Business delivery | `awf:e5c3950b55269195c8dc07fd48aac658a201e973848f32b4b85702327ea55c2f` |
| Business payload digest | `sha256:147e831a341ae75701f9fb5d4319454759719ad5fa8d31c7d6736ac6a2ef7b23` |
| Coder review-intent delivery | `awf:37118a3014d4d01ebfba54bc1eae88cb7b13b1cca221ac0f4ed9689a38ca9c58` |
| Reviewer terminal-intent delivery | `awf:2ce971c4231948d94b8b1d0d858b228b0a7e88a45eb6d0022402169250c68476` |

The run used a new isolated Bus database/port, canonical state root, strict operations config,
authority manifest, role profiles, TaskCard, manifests, compiled contracts, branch, run, and
delivery identities. Mac and Windows compiled the same owner intent from exact current Workflow
source. The Windows setup kept normal user application-data roots and isolated Workflow state only
through explicit absolute config/state-root and repository paths.

## 3. Entry and Preflight evidence

PR #98 first completed exact-publication-head review and CI, then merged as the Workflow source
above. Its ordinary CI run `32283698584` passed. Binary Feasibility run `32283698565` passed four
targets on attempt 1; its macOS x86_64 job completed build, measurement and SQLite checks but the
GitHub Artifact Service timed out five times during upload. Rerunning only that failed job passed,
so all five native targets and the aggregate job were green without a code change.

Downstream TaskCard PR #39 passed validation run `32285230580`, received independent `PASS` with
zero findings, and merged before any r3 listener, event, or provider started.

Fresh Fast Preflight passed all nine layers on Mac and Windows. Deep Preflight probe
`awf-preflight-d64a0a01fbc642c88f32e0a8716c2d21` used isolated events 1 and 2, passed all nine
layers, produced handler-success ACKs, and returned coder/reviewer queues from zero to zero. The
architect, coder, and reviewer queue baseline before the business dispatch was `0/0/0`; provider
start counts were zero; the Windows ledger had sequence, authorized events, and attempts all zero.

One earlier Deep command rejected locally before sending an event because the reviewer checkout was
detached and could not satisfy fork dry-run. The checkout was placed on the exact frozen branch and
the fresh probe above was then run. This was a local entry rejection, not a Workflow event or model
attempt. A first dry-run also used an absolute TaskCard argument and produced only a prospective
identity; it sent no event. The repository-relative dry-run produced the canonical business
delivery recorded above, and that delivery was dispatched exactly once as event 3.

## 4. Provider, Artifact, and trusted Git evidence

| Stage | Event | Durable provider evidence | Result |
|---|---:|---|---|
| implement | 3 | one `opencode_start` at `2026-08-19T18:27:47Z`; one exit after 256.969 s | rc 0, checkpoint `outbox_sent` |
| review | 4 | one `pi_start` at `2026-08-19T18:32:29Z`; one exit after 151.746409 s | rc 0, checkpoint `outbox_sent` |

There was no rework event or rework provider invocation. The coder's trusted postflight passed,
imported only the TaskCard allowlist, committed
`f7ef229f18cd60cd4d5443209df5a38ed1be39d5`, pushed it, and verified the fork remote SHA. The
ImplementationReport records `npm run ci` passing all four stages, 91/91 Node tests, 13/13 focused
home-reconsideration tests, the card check, and `git diff --check`. Existing content-library
warnings remained warnings and were unrelated to the change.

Pi produced one schema-valid read-only ReviewReport for the exact pushed commit with verdict
`PASS`, no deterministic failures, and two non-blocking low-severity advisories: duplicated
remaining-time formatting and cosmetic missing trailing newlines. The retained evidence binds
three deliberately distinct Artifact representations:

- ImplementationReport raw file, terminal ledger `artifacts.implementation.sha256`:
  `sha256:bf3d15f4432d1693d7714b65e93e852f9875a46d4f3a909cba5fad3adad1a0c4`;
- ReviewReport raw Markdown file, reviewer recovery checkpoint `review_report_sha256`:
  `sha256:9fc83b082f5167ff560f9a0d01389d5d8b191cbf30a1bf813a509e2a081d883d`;
- normalized `awf.review-report.v1` object embedded in the ready decision, terminal ledger
  compatibility field `artifacts.review.sha256`:
  `sha256:463faee38c0c163d60299e14079fa2d4c473710b36fb8b911b3660772e8ab250`.

The two ReviewReport digests are not expected to be equal: one hashes the imported Markdown bytes;
the other hashes the canonical normalized object that includes parsed fields and the Markdown.
This distinction is the shipped compatibility contract documented by
`factual-node-status-implementation-report.md` and regression-locked by
`test_review_artifact_distinguishes_file_and_canonical_hashes`. An independent read-only
recomputation from the retained ReviewReport reproduced both exact values. No artifact or ledger
byte was changed during that check.

## 5. Terminal, ACK, CI, and merge join

The trusted downstream PR tuple was:

- PR `atongrun/dousansi-shouzhang#40`;
- base `4f3b12760678e8dca33adad695d6e148dd092720`;
- head repository `torin-sun/dousansi-shouzhang`;
- head branch `agent/dousansi-runtime-v2-rts-010-home-reconsideration-r3-20260820`;
- head commit `f7ef229f18cd60cd4d5443209df5a38ed1be39d5`.

The Mac RunLedger ended at sequence 2, stage `review`, attempts 1, reason `review_passed`, verdict
`PASS`, and terminal event 5 with that exact branch, commit, PR number/base/head tuple, two Artifact
hashes, and reviewer terminal-intent delivery. `awf status --explain` projected
`state=completed`, terminal checkpoint `completed`, first failure `none`, and next legal action
`stop`.

The isolated payload-blind Bus status audit contained exactly five current records:

| Event | Route | Final status | Retry/error |
|---:|---|---|---|
| 1 | Deep Preflight request | `acked` | 0 / none |
| 2 | Deep Preflight result | `acked` | 0 / none |
| 3 | implementation | `acked` | 0 / none |
| 4 | review | `acked` | 0 / none |
| 5 | ready decision | `acked` | 0 / none |

Each business handler wrote its final checkpoint and returned rc 0 before the corresponding ACK.
Final architect/coder/reviewer queue counts were `0/0/0`.

Downstream PR #40's exact-head validation run `32287909583` passed. The PR then merged as
`dfa7237b1c52680f38fc2bfeefed3332f4f4ead3`, and downstream `main` resolved to that merge.
These CI/merge statements are live GitHub/Git facts. The already-completed RunLedger intentionally
still says CI `not_recorded` and merge `not_merged`; this closeout did not mutate terminal state to
collapse external truth into the local ledger.

## 6. Preserved failure and isolation boundaries

- The first retained authority exhausted isolated Windows Git transport retries before RunLedger
  authorization or provider start because its harness hid normal Git network configuration.
- The r2 authority reached upstream fetch and then failed before authorization/provider start on
  Windows/POSIX TaskCard path drift. PR #98 fixed only the owner-produced repository-relative path.
- Their unacknowledged deliveries, branches, isolated Bus stores, ledgers, handler evidence, and
  unused credential-free r2 setup files remain untouched. None contributes to the PASS counters.
- The successful r3 listener initially rejected an inherited Windows config ACL and a reviewer
  worktree with local `.awf/run-*` files before Bus connection/provider start. Only the fresh r3
  config ACL and local checkout excludes were corrected; no historical state was operated.
- The acceptance used direct disposable listeners. It proves the business transport/runtime path,
  not native managed-service lifecycle behavior; lifecycle status therefore remained separate from
  connected-listener facts.

## 7. Decision and next gate

RTS-010 is the last passed Runtime v2 gate. It supplies the fresh post-remediation real-business
evidence required by Phase 1 without weakening retained-event or external-truth boundaries.

The semantic contract remains `Draft`. RTS-011 is next, but its required
`implement -> review -> rework -> review -> terminal` path is currently unreachable because the
Python reference permits review only after implement and its default review-attempt budget is one.
The legal next implementation is a narrow, regression-locked correction under its own TaskCard,
followed by the disposable scripted-provider RTS-011 acceptance. This report authorizes neither a
workaround nor a production/default/release/migration action.

## 8. Independent closeout review

### Review 1 — `FAIL`

The independent Reviewer found one blocking documentation/acceptance ambiguity: the report named
only terminal ledger digest `463fae...`, while retained ReviewReport bytes and the reviewer
checkpoint hash to `9fc83b...`. Under wording that required undifferentiated “Artifact hashes” to
agree, the evidence appeared inconsistent.

Investigation confirmed the bytes were not corrupt and the completed ledger need not be mutated.
Current Runtime intentionally persists two representations: the checkpoint binds raw Markdown
bytes, while the terminal compatibility field binds `canonical_payload_sha256()` of the normalized
`awf.review-report.v1` object. Current status documentation and
`test_review_artifact_distinguishes_file_and_canonical_hashes` explicitly preserve this split. An
exact-source read-only recomputation produced raw `9fc83b...` and canonical `463fae...` from the
same retained file.

Remediation: label both full digests and their owners/representations, replace equality wording with
the required provenance join, and retain the first review as evidence. No Runtime, Artifact,
checkpoint, ledger, event, queue, listener, or provider state was changed.

### Review 2 — `PASS`

The independent Reviewer returned `PASS` with zero findings against the complete remediated diff.
It confirmed the exact changed-path allowlist, clean whitespace, valid repository-relative links,
the raw/canonical ReviewReport hash split in source/docs/tests, current PR #98 and downstream PR #40
merge/CI facts, and the separation between live GitHub/Git observations and unmodified terminal
CI/merge placeholders. No Runtime/source/test file changed in this closeout.
