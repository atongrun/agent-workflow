# TaskCard: Dogfood Finding Phase A — Capture, Transport, Durable Ingest

## Goal

Capture at most one safe Finding from an existing coder or reviewer Report, remove it before the
formal Report enters validation/hash/import, queue it independently of Workflow delivery state,
send it through Agent Bus only on an explicit operator command, and ACK the Bus event only after
the reporter has durably ingested the exact occurrence.

## Scope

- OpenCode coder and reviewer Reports.
- Codex reviewer fresh-run Report output.
- Pi reviewer stdout, with a 20 KiB combined bound and the existing 16 KiB final ReviewReport
  bound preserved after extraction.
- Strict EOF Finding envelope, transport safety gate, deterministic occurrence identity, local
  Feedback Outbox, `awf feedback status|flush|ingest`, and duplicate-safe reporter filesystem
  state.
- Agent Bus event type `feedback:awf-finding-v1` and recipient `awf-reporter`.

## Out of scope

- Architect Finding, new Workflow roles/stages, triage, grouping, publication, GitHub access,
  automatic flush service, provider registry, database, Agent Bus code/protocol changes, and
  Codex reviewer checkpoint expansion.
- A claim that the provider's raw local Report carrier never temporarily contains the model's
  unsafe candidate. Unsafe content must not be copied into Feedback state, Bus, reporter state,
  or the final formal Report.

## Contracts

1. The reserved marker is `<!-- awf-dogfood-finding-v1` and is recognized only as one complete,
   strict-JSON EOF block. Duplicate keys, keys outside `kind/component/summary/observed/expected`,
   invalid enums, control characters, multiline values, malformed markers, and envelopes above
   4096 bytes fail closed. No marker is an exact byte-preserving no-op.
2. `kind` is one of `bug/reliability/diagnostic/usability`; `component` is one of
   `adapter/artifact/configuration/control_plane/dispatch/node/postflight/preflight/recovery/
   routing/transport`. Summary is at most 200 UTF-8 bytes; observed and expected are at most 1024
   bytes each.
3. Source safety rejects credentials, authenticated or ordinary URLs, absolute paths, environment
   values, raw prompts/logs/diffs, and source-code blocks before Feedback Outbox or Bus. Rejection
   evidence contains only a reason and candidate hash.
4. Occurrence identity is SHA-256 over canonical JSON containing the identity format, trusted
   input delivery ID, fixed candidate index zero, and normalized candidate. Models do not supply
   identity authority.
5. Feedback state lives under `<state-root>/feedback` and never reuses Workflow `awf.outbox.v1/v2`
   state or semantics. Queue/send failure cannot change business verdict, handler success, business
   outbox, or ACK.
6. Reporter ingest validates and recomputes identity, deduplicates under a lock, fsyncs the file,
   atomically replaces it, fsyncs the directory, and only then returns zero for Agent Bus ACK.
   Exact duplicate ingest is success after revalidating existing state and fsyncing its directory;
   corrupt or conflicting state fails closed. Phase A reporter ingest is a POSIX VPS surface and
   fails closed where directory fsync cannot be proven; source status/flush remain cross-platform.

## Implementation boundary

- Add `scripts/awf_feedback.py` and `tests/test_awf_feedback.py`.
- Update `scripts/awf_role.py`, the OpenCode/Codex/Pi argv renderers,
  `src/agent_workflow/cli.py`, installed-wheel verification, and focused regression tests.
- Keep schemas, roles, workflows, constitution, RunManifest, Workflow delivery formats, business
  routes/checkpoint phases, Architect consumer, and the Agent Bus repository unchanged.

## Acceptance criteria

1. No Finding preserves Report bytes and existing business behavior.
2. A valid safe Finding is queued once and absent from formal Report validation, hash, import,
   verdict, and downstream business event.
3. Same delivery/candidate replay produces one occurrence ID and one source record.
4. Unsafe candidates are stripped but do not enter Feedback Outbox or Bus; metadata contains no
   raw candidate.
5. Feedback Outbox or Bus failure leaves feedback pending/lost as applicable without changing the
   already completed business path.
6. Duplicate Bus delivery produces one reporter occurrence and returns success. Corrupt reporter
   state is never overwritten or ACKed.
7. Reporter success is impossible before file and directory durability.
8. Pi accepts a final ReviewReport up to its existing 16 KiB contract plus a Finding envelope up
   to 4 KiB without charging the Finding against the final ReviewReport limit.
9. Agent Workflow CI passes and Agent Bus Core has zero diff.

## Verification

GitHub CI must run Ruff, Pytest, resource validation, and installed-wheel verification on the
supported matrix. Local architecture work may run compile/static/manual contract probes but does
not replace CI.
