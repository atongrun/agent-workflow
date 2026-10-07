# Durable-first Host candidate status

This isolated local candidate starts at
`f5656895f241f88a0aff340ce0758ca60874a3f8`. The parked content prototype and its
PRIVATE Library evidence remain intact. It carries no old content execution
ledger, attempt scheduler, SQLite Go dependency or compatibility protocol.
Existing unrelated Host/Dash behavior is unchanged.

The [native transport draft](durable-transport-v1-draft.md) must be frozen with
the parent and PRIVATE before implementing routes, configuration/startup
handoff and typed results. This candidate currently contains the independent OS
storage-owner lease only; it does not yet start a Durable worker or mount a
content handler. It is not an installation or native acceptance result.

## Implemented physical ownership boundary

`internal/durablebridge.AcquireStorageLease` validates an existing absolute
canonical 0700 service-owned storage directory and trusted ancestry, rejects
unsafe lock-file types/permissions/owners/hard links, and takes a nonblocking
exclusive Linux flock. A second owner is refused. The descriptor can be passed
to the worker through `exec.Cmd.ExtraFiles`; closing the Go copy does not unlock
a live worker's inherited copy. There is no state in the lease file, and no
native storage open, schema, admission, retry or recovery in this Go package.

The published Pi Durable 1.0.4 README explicitly lacks cross-process locking.
This is a remaining machine/process responsibility under the Pi-first rule.
The lease requires a unique physical storage path and an unchanged lock inode;
it is an advisory ownership boundary between cooperating service processes.

## Validation on this executor

Go 1.25.14, local Linux subprocess fixtures, no real model calls:

* Race-enabled lease fixtures prove that closing the parent descriptor refuses
  a second owner while the child lives, and permits acquisition after child
  exit. They also reject symlink/hard-link/public lock paths and noncanonical
  directory inputs.
* `go vet ./internal/durablebridge` and Windows amd64 CGO-free package compile
  pass. The added boundary is Linux-only and fails closed on other platforms.
* The production-directory acceptance test explicitly skips on this cloud
  executor's mapped-root ancestry. Production validation was not weakened.
* Independent read-only review found no blocker in this lease boundary. It did
  not validate a PRIVATE worker, native storage, systemd or transport agreement.

## Remaining gates

Freeze the worker routes/envelopes, typed result and owner-scope format, request
fingerprint rules, list pagination if required, and startup/lease handoff. Then
implement the thin Go HTTP/auth/worker composition on the existing Host listener
and the PRIVATE native Harness/application Doc adapter. Actual Durable storage,
reopen/crash, dedup/model-freeze and cancel/answer ordering need a real pinned
PRIVATE adapter with faux models. Systemd control-group termination before a
replacement owner, detached tool cleanup, fixed-path permissions and Ubuntu
service activation need separately authorized native acceptance.

No push, new CI, release, production access, system mutation or user data
deletion occurred in this draft boundary work.
