# RTS-031 Checksummed Atomic RunStore and Journal Implementation Report

## Result

The selected Python Runtime v2 package now contains one disposable local atomic-file `RunStore`
and per-invocation journal view. One checksummed `authority.json` envelope owns immutable `RunSpec`,
Workflow events, bounded attempt/rework consumption, embedded typed invocation facts, outgoing
handoff intent and terminal. No separate journal, checkpoint, outbox or inbox authority file is
created.

Each mutation uses one exact `O_EXCL` writer lock, validates the current envelope only after lock
acquisition, writes canonical UTF-8 to a unique same-directory temporary file, flushes/fsyncs it,
atomically replaces the authority and fsyncs the containing directory where supported. Existing or
changed locks, uncertain replacement results, symbolic-link traversal and retained temporary files
never authorize takeover, repair or replay.

## Authority and recovery semantics

- `RunStore.authorize(command, fact)` atomically persists Workflow authorization and journal
  authorization; exact replay is idempotent and conflicting identity consumes no capacity.
- `record_handoff(command, effect)` atomically joins the trusted validation effect, immutable
  outgoing intent and legal next Stage. Review cannot enter rework after its budget is exhausted.
- `record_terminal(command, effect)` atomically joins exact review validation with `completed` or
  `blocked`; unsupported owners deny and conflicting terminal evidence is preserved.
- Journal views mutate only launch intent, process observation and provider result. Facts remain
  ordered and identity-bound; exact replay is byte-stable, including after terminal.
- Authority sequence is checked against the reconstructable initialization, event and journal-fact
  count, so a rechecksummed sequence drift cannot authorize.
- `RunSnapshot` now includes the Frozen normalized outcome needed by RTS-031: launch/process without
  a trusted result projects `AMBIGUOUS_NO_REPLAY`; exact safe boundaries project `SAFE_CONTINUE`;
  terminal projects `TERMINAL_IDEMPOTENT`.
- Status reads only the validated owner envelope and exact lock presence. It never writes, repairs,
  migrates, deletes, invokes a provider or guesses recovery.

## Focused fixture surface

The disposable tests cover the full implement -> review -> rework -> review -> terminal route;
exact and conflicting authorization/journal/handoff/terminal replay; Stage, attempt and rework
budgets; launch/process/result ambiguity; initialization and writer identity; checksum, duplicate
key, newer schema, rechecksummed semantic/sequence/ordering drift; missing/foreign/symlink
authority; stale and conflicting locks; injected replacement failure; temporary evidence; and
byte-for-byte denial/status stability.

Tests perform no provider process, Agent Bus, Git/GitHub, OS manager, production/legacy state,
network, migration, default, release or destructive operation.

## Scope and budgets

Only RTS-031 frozen writable paths changed. The new Store is 644 nonblank/noncomment lines against
the 650-line limit. The new focused Store fixture is 541 lines against the 900-line limit.
The package remains standard-library only and adds no dependency or second authority family.

## Verification state

Repository-policy-safe local checks pass:

- AST parsing for all changed package and focused-test modules;
- direct source-tree smoke through exact authorization, launch, process, result and handoff;
- direct full implement/review/rework/review/completed route with 21 exact replacements;
- normalized recovery-outcome and terminal exact-replay smoke;
- import/dependency, generated-file, forbidden-representation and changed-path scans;
- LOC and line-length budgets;
- `git diff --check`.

Pytest, Ruff, installed-wheel and Linux/Windows/macOS filesystem evidence remain candidate-CI owned.
One independent TaskCard Gate Review remains required before closeout.

## Explicit non-claims

This candidate is not integrated into any production handler. It does not read, import, shadow,
dual-write, migrate or delete legacy Runtime state; invoke a provider; send/ACK Agent Bus events;
mutate Git/GitHub/OS truth; change the production default; implement the native launcher; migrate
production state; release; or authorize destructive cleanup.

<!-- awf-implementation-report
{
  "summary": "Implement one checksummed atomic-file RunStore and embedded invocation journal for disposable local Runtime v2 fixtures.",
  "changed_files": [
    "src/agent_workflow/runtime/__init__.py",
    "src/agent_workflow/runtime/ports.py",
    "src/agent_workflow/runtime/store.py",
    "tests/test_runtime_core_boundary.py",
    "tests/test_runtime_core_contracts.py",
    "tests/test_runtime_atomic_store.py",
    ".awf/artifacts/impl-report-runtime-v2-rts-031-atomic-store-journal.md"
  ],
  "commands": [
    "Python AST and direct Runtime transition/recovery smoke checks",
    "static dependency, representation and writable-path audit",
    "LOC and line-length checks",
    "git diff --check"
  ],
  "tests": [
    "Local policy-safe static and direct smoke validation PASS",
    "Candidate CI pending",
    "Independent TaskCard Gate Review pending"
  ],
  "source_revision": "2a17158e6008f3db4e34ff50f9816f35ada62ac4"
}
-->
