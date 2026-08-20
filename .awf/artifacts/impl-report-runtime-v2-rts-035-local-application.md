# RTS-035 ImplementationReport

## Outcome

The installed Runtime v2 package now exposes one disposable local application with `run`,
`status`, and exact local `stop`. It composes the frozen RunSpec, one checksummed atomic Store and
per-invocation journal, closed OpenCode/Pi renderers, isolated no-remote workspaces, trusted local
Git import, TaskCard postflight and Artifact validation without importing the RTS-020 experiment or
any production operations script.

The Store remains a newly created disposable-state candidate. Current production
RunLedger/checkpoint/outbox/inbox/RunEvidence, Agent Bus, remote Git/GitHub, native lifecycle,
defaults, migration and release behavior are unchanged.

## Durable order and recovery

- The exact InvocationSpec, initial workspace manifest and authorization are durable before render
  or launch intent; launch intent precedes process start, process observation precedes result, and
  launch without result returns ambiguity without replay.
- Provider result facts bind exact return code, Artifact bytes, workspace delta and a recoverable
  workspace manifest. Recovery restores the durable manifest rather than accepting a fresh local
  freeze.
- Each non-initial authorization consumes the exact prior handoff delivery and payload. Store Stage,
  role, attempt and rework budgets continue to bind the full implement/review/rework lineage.
- Coder validation delegates to installed TaskCard, Artifact and workspace APIs before one trusted
  import and Store handoff. Reviewer validation joins exact trusted Git/workspace lineage before
  PASS, deterministic REQUEST_CHANGES or BLOCKED authority.
- Local stop is a typed fact inside the same authority envelope. It is exact, idempotent, denies
  ambiguous provider evidence and performs no PID signal or native lifecycle claim.

## Validation and budgets

- `application.py`: 692 nonblank/noncomment lines (budget 700).
- Focused application test plus scripted provider: below 1,100 nonblank/noncomment lines.
- `contracts.py`/`ports.py`/`store.py` combined refinement remains below 180 net
  nonblank/noncomment lines; no dependency or persistent family was added.
- Local Mac evidence: AST/import checks, exact public/effect-boundary checks, direct disposable Git
  OpenCode-coder/Pi-reviewer PASS smoke, changed-path/line-length/LOC audits and `git diff --check`.
  Per repository policy, pytest, Ruff, installed-wheel and cross-platform evidence is assigned to
  candidate CI.
- Focused fixtures cover PASS, bounded rework/PASS, BLOCKED, exact stop, provider/artifact failure,
  no-replay ambiguity, TaskCard/Git drift and all 14 frozen shared fault rows.

<!-- awf-implementation-report
{
  "summary": "Compose the selected installed Runtime v2 package seams behind one disposable local run/status/stop application with exact journal recovery and handoff lineage.",
  "changed_files": [
    "src/agent_workflow/runtime/application.py",
    "src/agent_workflow/runtime/__init__.py",
    "src/agent_workflow/runtime/ports.py",
    "src/agent_workflow/runtime/store.py",
    "tests/fixtures/runtime_v2_local_application_provider.py",
    "tests/test_runtime_application.py",
    "tests/test_runtime_atomic_store.py",
    "tests/test_runtime_core_boundary.py",
    "tests/test_runtime_core_contracts.py",
    "tests/test_runtime_command_boundary.py",
    ".awf/artifacts/impl-report-runtime-v2-rts-035-local-application.md"
  ],
  "commands": [
    "AST and installed Runtime import validation",
    "direct disposable Git scripted-provider PASS smoke",
    "exact public export and process boundary validation",
    "scope, LOC, dependency and representation audit",
    "git diff --check"
  ],
  "tests": [
    "implement review PASS terminal and byte-stable replay",
    "deterministic review rework second-review PASS",
    "BLOCKED terminal",
    "authorization launch process result effect ordering",
    "durable workspace-manifest recovery without replay",
    "exact incoming handoff lineage and rework budget",
    "all 14 shared fault rows and read-only status",
    "exact local stop and ambiguity denial",
    "closed structured subprocess and external-boundary audit"
  ],
  "source_revision": "6c46664de50b043007559e235fa496e7202c7771"
}
-->
