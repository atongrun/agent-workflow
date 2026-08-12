# Dogfood Finding Phase A Implementation Report

## Result

Implemented the bounded Capture + Transport + Durable Ingest phase without changing Agent Bus
Core, Workflow roles/stages, RunManifest, business delivery formats, business checkpoint phases,
or business ACK ordering.

## Changes

- Added one strict EOF Finding contract with duplicate-key rejection, exact enums/keys, independent
  field/envelope bounds, NFC/single-line/control-character validation, and deterministic canonical
  occurrence identity.
- Added a fail-closed source transport gate for credential shapes, URLs, absolute paths,
  environment values, prompts, logs, diffs, and source-code blocks. Unsafe candidates are stripped
  before formal Report handling and leave only bounded reason/hash metadata.
- Added `<state-root>/feedback` as a separate Feedback Outbox namespace. Source queue and explicit
  Agent Bus flush failures do not alter business verdict, handler success, business outbox, or ACK.
- Added `awf feedback status`, `awf feedback flush`, and `awf feedback ingest` to the installed
  operations CLI.
- Added reporter exact-ID dedupe under a lock. First ingest returns success only after file fsync,
  atomic replace, and directory fsync; an exact duplicate revalidates state and repeats directory
  fsync before returning success. Corrupt or conflicting state is not overwritten. Reporter
  ingest is intentionally POSIX/VPS-only in Phase A and fails closed on Windows, where this
  implementation cannot prove directory durability; source capture/status/flush remain
  cross-platform.
- Inserted extraction before coder postflight/report validation and before reviewer import/parse/
  hash. Codex remains a fresh-run capture path; its existing business checkpoint policy is not
  expanded.
- Increased only Pi's raw combined stdout limit to 20 KiB. Extraction keeps the existing final
  ReviewReport 16 KiB contract independent from the Finding envelope's 4 KiB bound.
- Added focused contract, adapter, role, CLI, reporter durability, and installed-wheel tests.

## Security and privacy boundary

Existing providers produce their raw Report before the trusted runner can inspect it. The source
gate therefore guarantees that rejected candidate content is not copied into Feedback Outbox,
Agent Bus, reporter state, rejection metadata, or the final formal Report; it does not claim that
the original provider Report carrier never temporarily held those bytes locally.

Agent Bus payloads contain only source-gated structured occurrences. Source tokens remain in the
existing strict dispatch configuration and are passed to the existing shell-free executor with
diagnostic redaction.

## Verification

Completed locally on macOS without installing dependencies or running Pytest/Ruff:

- `python3 -m compileall -q ...` — pass for changed source and test modules.
- `git diff --check` — pass.
- safe capture → one source outbox record → reporter ingest → exact duplicate ingest probe — pass.
- unsafe absolute-path capture → source rejection → no outbox/raw rejection content probe — pass.
- seven-category safety detector matrix probe — pass.
- manual line-length audit — no new Python lines above the repository's 100-character limit.

The source environment does not currently provide the package dependency `jsonschema`, so direct
source CLI import stopped before command parsing. No dependency was installed on the architecture
Mac.

GitHub Actions run
[`31516238980`](https://github.com/atongrun/agent-workflow/actions/runs/31516238980) passed all
six jobs:

- Linux Ruff, full Pytest, and repository/resource validation — pass.
- Windows recovery and configuration suite — pass.
- installed-wheel CLI verification on Ubuntu, macOS, and Windows — pass.
- macOS runtime verification — pass.

After the Windows run exposed native CRLF report bytes, the Finding parser was tightened to accept
either a complete LF or complete CRLF EOF envelope while still rejecting mixed or partial markers.
The explicit CRLF regression test is included in the passing run above.

## Remaining operational work

- The explicitly authorized reporter deployment is complete. A dedicated `awf-reporter` Agent Bus
  identity and hardened system service run an isolated AWF checkout at this PR's exact SHA and the
  latest default-branch Agent Bus client checkout. Credentials remain in root-owned mode-`0600`
  files and reporter state is writable only by the dedicated service identity.
- Live acceptance used one fresh disposable event. The reporter durably committed the exact
  occurrence before handler success permitted ACK; the recipient's pending and failed queues were
  empty afterward. A service restart changed the PID and returned to `active`/`enabled` with zero
  restart failures while preserving the single ingest record.
- Do not claim Codex reviewer completed-output recovery; Phase A only captures its successful
  fresh-run Report.
- Triage, grouping, publication safety, GitHub publication, and automatic flushing remain out of
  scope.
