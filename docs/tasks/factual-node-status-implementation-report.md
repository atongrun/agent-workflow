# Factual Node Status Implementation Report

## Scope

The existing node lifecycle gains one optional run-scoped, machine-readable view:

```text
awf node status --profile <name-or-absolute-json>
awf node status --profile <name-or-absolute-json> --run <run-id> --json
```

The snapshot reports listener, workspace, checkpoint, queue, artifact, pull-request, and CI facts.
Every section identifies its evidence source. Missing or unreachable evidence remains explicitly
`unknown`, `not_recorded`, `not_requested`, or `unavailable`; status does not infer success.

## Read-only boundary

The reader uses the local node process record, listener lease, a non-signalling PID probe,
read-only Git commands, immutable ledger/checkpoint reads, Agent Bus `pending --count`, artifact
bytes, and `gh pr view`. It never calls RunLedger transitions, resume, dispatch, ACK, requeue, send,
or artifact writers. A queue or GitHub outage degrades only that live section rather than hiding
the remaining recorded facts.

Recorded terminal PR/CI facts and current GitHub observations are separate fields. A changed PR
head or later CI result therefore appears as drift instead of silently replacing durable evidence.

## ReviewReport hash semantics

Earlier terminal ledgers called the normalized ReviewReport object digest `sha256`, while reviewer
recovery checkpoints persisted the raw Markdown bytes under `review_report_sha256`. The status
surface keeps both compatibility records unchanged but presents their meanings explicitly:

- `file_sha256`: raw ReviewReport Markdown bytes, sourced from the matching reviewer delivery
  checkpoint, a newer explicit terminal field, or a currently readable file;
- `canonical_report_sha256`: the normalized `awf.review-report.v1` object digest, sourced from the
  terminal ledger's compatibility field.

Live file hashes are shown separately from recorded hashes. An unavailable local ReviewReport does
not cause the canonical hash to be mislabeled as a file hash.

## Compatibility

`awf status --run` retains its bounded operator-run output. The new aggregation stays under
`awf node status`, and JSON is opt-in. Listener routes, role selection, v1-v3 payloads,
checkpoint/outbox/inbox order, recovery, and ACK semantics are unchanged. Agent Bus remains an
external transport and read-only pending source.

## Verification

Regression coverage locks dirty dedicated versus dirty architect workspace facts, checkpoint
selection, ReviewReport hash naming and provenance, recorded-versus-live PR/CI drift, queue
unavailability, snapshot schema, human hash labels, and CLI `--run --json` routing. Installed-wheel
and full Linux/Windows/macOS verification remain CI-owned under the repository's local Mac policy.
