# P0-1 Canonical State-Root Contract Implementation Report

## Outcome

Node-managed execution now has one resolved host-local state root. The profile is the source,
listener argv and generated handlers carry the exact path and a credential-free binding, and
disagreement fails before Agent Bus connection or provider/model invocation. Direct script entry
retains the documented `--state-root` -> `AWF_STATE_ROOT` -> platform-default compatibility path.

## Changed files and simplifications

- `src/agent_workflow/state_root.py` centralizes resolve-and-bind behavior; production and tests do
  not duplicate the algorithm.
- `schemas/node-profile.schema.json`, `src/agent_workflow/node.py`, and `scripts/awf_listen.py` make
  the profile root explicit, bind process/lease/readiness, and propagate it through every handler.
- `scripts/awf_role.py`, `scripts/awf_control_plane.py`, and `scripts/awf_feedback.py` bind
  RunEvidence, context packets, checkpoints, business outbox/inbox, and Feedback Outbox to the
  same root. Old records with no binding are upgraded only at their already-known location;
  explicit disagreement remains fail closed.
- `src/agent_workflow/status.py`, `README.md`, lifecycle architecture, and HANDOFF expose provenance
  without credentials or a second status/lifecycle vocabulary.
- Exactly two focused tests were added: one custom-root propagation regression and one combined
  pre-Bus/pre-model mismatch regression. Existing fixture assertions cover process/readiness and
  outbox fields rather than adding a test per record type.
- Independent review found two fail-closed gaps before publication: explicit root mismatch on the
  legacy PID lease path and mismatch handling in read-only checkpoint/Feedback summaries. Both were
  closed by extending existing assertions; no third regression test was added.

## Verification

Allowed local Mac gates:

- `python -m compileall -q src/agent_workflow scripts ...` — passed.
- Python AST parse of every changed Python module — passed.
- JSON parse of `schemas/node-profile.schema.json` — passed.
- `git diff --check` — passed.
- Static inventory confirmed all TaskCard bindings and no Agent Bus Core diff.

Per the frozen Verification Level B policy, local pytest/Ruff/Rust were not run. GitHub CI owns the
full Ruff, Pytest, resource, installed-wheel, Ubuntu, Windows, and macOS verification; final run and
independent review evidence are recorded in the PR before closeout.

## Deviations and remaining risks

- No scope deviation. No live or preserved event was read or mutated.
- Existing durable records created before P0-1 may omit the binding. Compatibility accepts only
  absence, derives identity from the record's already-known root, and writes the binding on the next
  trusted touch. A present mismatched binding is never repaired automatically.
- Fresh managed lifecycle proof is intentionally not repeated in this package; platform behavior
  remains covered by the existing CI matrix and a later separately authorized milestone gate.
