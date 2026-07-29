# Shared Configuration and Recovery Matrix Implementation Report

## Status

Implementation-complete on the feature branch; merge and live maturity acceptance remain separate
gates.

## Scope

This change closes two operations-surface gaps without changing the stateless `awf` core:

1. one strict, shell-free Python configuration loader shared by bootstrap, handoff checks,
   listeners, dispatch, and native service entry points;
2. an automated coder/reviewer recovery matrix covering every durable phase and downstream outbox
   status.

It does not claim that the required three-card uninterrupted Mac → Windows → Mac → architect
dogfood has passed.

## Configuration Contract

`scripts/awf_config.py` treats `dispatch.env` as data:

- exact UTF-8 `KEY=VALUE` parsing with read-only compatibility for legacy `export KEY=VALUE`;
- no quoting, interpolation, variable expansion, command substitution, or shell execution;
- duplicate keys, unknown keys, empty values, invalid URLs, control characters, and oversized
  files fail closed;
- the path must be absolute, regular, non-symlinked, current-user-owned, and owner-only;
- Windows uses explicit `icacls` plus `whoami` verification instead of `os.chmod`;
- errors name only fields or failure classes and never include credential values.

Bootstrap writes a deterministic key order through the same serializer. Replacement is an atomic
same-directory operation; an existing destination is verified before backup/replacement. New
production service entry points call native Python on all three operating systems. Windows no
longer invokes Git Bash, and POSIX wrappers no longer source the credential file.

## Recovery Matrix

The checkpoint policy is explicit:

| Durable state | Additional model invocation |
|---|---:|
| `model_not_started` | exactly one permitted |
| `model_started` | zero; recover a proven zero-exit process or fail ambiguous |
| `model_completed` and later | zero |

Automated same-delivery restart coverage includes:

- coder: model start/completion, artifact and tree import, trusted commit, fork SHA, PR tuple,
  outbox prepared/sent;
- reviewer: both OpenCode and Codex model adapters, ReviewReport import/hash, PR tuple, outbox
  prepared/sent;
- outbox record statuses: prepared, attempting, ambiguous, and sent;
- immutable input delivery, payload hash, source event, provenance, report, and evidence commit;
- remote/provenance/report drift before replay;
- process-log recovery after a zero model exit and fail-closed ambiguous model outcomes.

Inbox completion remains after downstream sent evidence. A failed or ambiguous downstream send
returns nonzero, so Agent Bus must not ACK the source delivery.

## Verification

Local verification on macOS:

- focused configuration tests;
- focused recovery/outbox tests;
- full pytest suite;
- Ruff lint and format checks;
- role, workflow, and example resource validation;
- wheel and source-distribution schema-content verification;
- independent security and code reviews.

The CI workflow has a separate clean Windows Python 3.12 job that runs Ruff, the full suite, and
resource validation against the exact PR head.

## Remaining Acceptance

- obtain clean exact-head Windows CI evidence;
- complete three new, independent, reversible TaskCards through the real transport with no manual
  state edits, artifact moves, replacement events, or workaround credit;
- show coder, reviewer, and architect queues empty after each accepted canary;
- open and verify the GitHub PR; do not merge without new explicit user authorization.
