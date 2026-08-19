# Implementation Report: RTS-011 Disposable Deterministic Rework Acceptance

## Summary

Added one isolated pytest acceptance and one no-model scripted provider. The acceptance joins the
shipped `RunLedger`, recovery checkpoint, durable model workspace, exact rework lineage, outbox,
inbox, ReviewReport normalization, and architect terminal paths in one bounded run.

The provider intelligence, GitHub provenance, transport send, and ACK observer are synthetic and
are asserted as such. The subprocesses, disposable Git operations, Runtime persistence, recovery,
and terminal calls are real local execution paths. No live Agent Bus, provider, GitHub, credential,
retained event, production/default/release/migration, or destructive surface is used.

## Acceptance mapping

- four real child subprocesses: implement once, rework once, review twice;
- review 1 normalizes to `REQUEST_CHANGES`; review 2 normalizes to `PASS`;
- duplicate rework delivery is rejected before a provider start;
- rework binds the exact authorized implement checkpoint/workspace/commit/PR/Git manifest;
- a drifted lineage digest fails before provider start;
- a fresh `RunEvidence` recovers a durable rework `opencode_exit=0` while the checkpoint remains
  `model_started`, then continues without a second subprocess;
- production outbox/inbox primitives and the production architect terminal handler are instrumented
  for durability and ordering;
- the final self-validating record separates real and synthetic boundaries.

## Verification at implementation time

- `python3` syntax `compile(...)` check for `tests/test_runtime_v2_rts011_acceptance.py`
  and `tests/fixtures/runtime_v2_scripted_provider.py`: PASS
- `git diff --check`: PASS
- independent implementation Review 1: initial `REQUEST_CHANGES` on the outbox action name, fixed
  to production `reviewer.request_changes`, then re-reviewed `PASS` with zero findings;
- ordinary CI run `32301184219` on executable head `2868486`: PASS on Ubuntu, Windows, macOS
  runtime and all three installed-wheel jobs; Ubuntu collected 654 tests (`649 passed, 5 skipped`),
  Windows completed `643 passed, 11 skipped`, Ruff check/format passed;
- Binary Feasibility run `32301184171`: PASS on Linux x86_64/arm64, macOS x86_64/arm64, Windows
  x86_64 and aggregate;
- local Mac pytest/Ruff execution remains intentionally excluded; GitHub CI is authoritative.

<!-- awf-implementation-report
{
  "summary": "Join the shipped Runtime persistence and recovery primitives in one disposable scripted-provider rework acceptance.",
  "changed_files": [
    "tests/test_runtime_v2_rts011_acceptance.py",
    "tests/fixtures/runtime_v2_scripted_provider.py",
    ".awf/artifacts/impl-report-runtime-v2-rts-011-deterministic-rework-acceptance.md",
    ".awf/artifacts/review-report-runtime-v2-rts-011-deterministic-rework-acceptance.md"
  ],
  "commands": [
    "python3 syntax compile() for tests/test_runtime_v2_rts011_acceptance.py and tests/fixtures/runtime_v2_scripted_provider.py",
    "git diff --check",
    "GitHub Actions CI run 32301184219",
    "GitHub Actions Binary Feasibility run 32301184171"
  ],
  "tests": [
    "Static compile PASS",
    "Independent implementation Review 1 PASS after one deterministic rework",
    "Ordinary cross-platform CI PASS",
    "Five-target Binary Feasibility plus aggregate PASS"
  ],
  "source_revision": "2868486263aaf35814719fb9ab085a5787359408"
}
-->
