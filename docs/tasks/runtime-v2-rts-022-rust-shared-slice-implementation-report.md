# RTS-022A Rust Shared Slice Closeout

Status: **RUST_SHARED_SLICE_ELIGIBLE_FOR_MAINTAINER_GATE**

Date: 2026-08-20

TaskCard: [`runtime-v2-rts-022-rust-shared-slice.md`](runtime-v2-rts-022-rust-shared-slice.md)

Pull request: [#104](https://github.com/atongrun/agent-workflow/pull/104)

## Result

One removable, zero-dependency Rust executable consumed the existing Candidate fixture and passed
all 14 machine rows on Linux x86_64/arm64, Windows x86_64, and macOS x86_64/arm64. The normal path
started exactly one implement and one review child, committed one trusted no-remote Git effect,
reached terminal, replayed idempotently, projected status byte-for-byte read-only, and stopped only
for the exact idle local run. Active invocation and active writer stop attempts failed closed.

The slice keeps immutable RunSpec, one RunStore writer, per-invocation prepared/launch/result facts,
Artifact validation, trusted Git effect, handoff and terminal separately observable. Authorized
state without its bound journal is owner-required; launch intent without a durable result is
ambiguous and never replayed. Aggregate evidence exact-binds injection, outcome, sole legal next
action, owner/source and every assertion/prohibited proof.

## Budget and material-value result

The production numerator is 3,471 nonblank/noncomment Rust lines, above the frozen 2,181 limit. It
therefore required one named machine-proven prerequisite improvement. Every target recorded
`python_invoked=false`; runtime children were only external `git` and the same Rust executable as
the scripted provider. Direct and transitive Cargo dependency counts are both zero. This proves
removal of the Python runtime prerequisite for this disposable shared slice while preserving the
shared semantics, so the deterministic result is
`RUST_SHARED_SLICE_ELIGIBLE_FOR_MAINTAINER_GATE` rather than a size stop.

This is not a Rust selection. The experiment still requires external Git and does not prove
installed `awf`, provider intelligence, Agent Bus/ACK, remote provenance, cross-host recovery,
native service lifecycle, signing, installer/updater, release trust, production migration or
default behavior.

## Review and repair evidence

The frozen TaskCard passed independent review before implementation. Implementation review found
and closed provider replay, legal-next-action, prohibited-proof and aggregate fail-closed gaps. A
focused re-review of semantic candidate `9309bb6` returned `PASS` with zero findings. Later CI
repairs were limited to exact rustfmt output, five ownership/borrowing compiler diagnostics and four
narrow Clippy diagnostics; they did not change the reviewed state/fault semantics.

The closeout head still requires one final exact-head TaskCard Gate review. A PASS authorizes only a
separately frozen RTS-022B independent-maintainer injected-fault diagnosis/repair TaskCard.

## CI evidence

On exact pre-closeout PR head `3be326378d403b6d5ed098f2589244ac69680abc` and pull-request merge
ref `aa255dee04438f0a32ead5efe29f60434f36c2af`:

- ordinary CI run [`32322178827`](https://github.com/atongrun/agent-workflow/actions/runs/32322178827)
  passed all six jobs, including Ruff, Ubuntu tests, the 8m08s Windows recovery/configuration suite,
  installed-wheel Ubuntu/Windows/macOS, and macOS runtime;
- Binary Feasibility run
  [`32322178851`](https://github.com/atongrun/agent-workflow/actions/runs/32322178851) passed all five
  Rust cells, all existing native cells, and both aggregate jobs;
- every Rust target passed pinned rustfmt, Clippy, release build, the complete 14-row suite,
  unrelated-cwd run/status/replay/stop, and credential-free evidence upload;
- the Rust aggregate required exactly five targets and returned
  `RUST_SHARED_SLICE_ELIGIBLE_FOR_MAINTAINER_GATE`.

The final closeout head requires a fresh ordinary CI run, Binary Feasibility run and exact-head
Reviewer before merge.

## Next gate

RTS-022B is the only permitted next implementation TaskCard. It must be independently frozen and
must test whether a maintainer can diagnose and repair one injected Rust fault from documented
state/evidence in one bounded review/fix pass. Failure stops Rust and may make RTS-023 entry-eligible
only if native value remains. PASS makes RTS-024 the owner decision gate. No language, Store,
physical Coordinator, product boundary, production default, migration or release decision has been
made.
