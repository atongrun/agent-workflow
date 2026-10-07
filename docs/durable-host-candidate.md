# Durable-first Host candidate

This isolated local candidate starts at
`f5656895f241f88a0aff340ce0758ca60874a3f8`. The parked content prototype and its
PRIVATE Library evidence remain intact. It carries no old content execution
ledger, attempt scheduler, SQLite Go dependency or compatibility protocol.
Existing unrelated Host/Dash behavior is unchanged.

Go now implements the OS storage lease, long-lived worker lifecycle, Unix HTTP,
bounded request/receipt/list validation, trusted owner authentication and
composition on the existing Host listener. The [explicit wire defaults](durable-transport-v1-draft.md)
are isolated in `internal/durablebridge/contract.go`. The parent authorized
independent implementation while PRIVATE finalizes its adapter; actual
interoperability remains an acceptance gate. This is not an installed service or
native acceptance result.

## Host composition and physical ownership

Keep `awf host --config /etc/awf/host.json`. Add the optional operator-owned Host
field `"durableConfig":"/etc/awf/durable.json"`. Absence keeps existing behavior.
Content mounts at `/v1/content/` on the existing Host listener, with distinct
owner-scoped credentials. There is no worker TCP listener. Content credentials
cannot also grant Host/extension/node authority.

Durable config example (operator-provisioned paths; not run here):

```json
{
  "storageDir":"/var/lib/awf/durable",
  "runtimeDir":"/run/awf/durable",
  "piAgentDir":"/var/lib/awf/pi-agent",
  "worker":{
    "executable":"/opt/awf/runtime/node/bin/node",
    "args":["/opt/awf/private/durable-worker.mjs"],
    "env":{}
  },
  "credentials":[{"owner":"operator-user","tokenEnv":"AWF_CONTENT_TOKEN"}],
  "startupSeconds":15,
  "shutdownSeconds":10,
  "requestSeconds":30
}
```

The PRIVATE worker is supplied by the operator; it is not in this public repo.
Config is a private, singly linked 0600 regular file, root or service-owned with
trusted physical ancestry. Paths are absolute and canonical. Runtime/storage/
Pi-agent directories are provisioned service-owned 0700, with trusted root or
service ancestors. Go does not modify native storage or provider settings.
Credentials are resolved once at startup from trusted environment names.

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

Each start creates one owned 0700 temporary runtime directory, then launches the
explicit operator argv/environment with a separate process group and Linux
parent-death SIGTERM. No Host environment is inherited; copied public credential
values are rejected. Fixed PATH plus explicit private environment and reserved
startup values are passed: `AWF_DURABLE_PROTOCOL=1`, `AWF_DURABLE_OWNER_FD=3`,
`AWF_DURABLE_SOCKET=<owned runtime>/worker.sock`,
`AWF_DURABLE_STORAGE_DIR=<native storage>`,
`PI_CODING_AGENT_DIR=<service Pi-agent>`. Worker config cannot override reserved
values. Ordinary interactive Pi and the sole Pi installation are unaffected.

Readiness polls only native health and verifies socket owner/mode 0600, protocol
and pinned package version. PRIVATE holds/verifies the inherited FD until native
storage closes and excludes it from tool subprocesses. Startup failure cleans up
that owned process/directory or reports uncertainty. Worker exit makes content
unavailable and stops Host; Go never restarts/resubmits logical work.

Shutdown sends SIGTERM and waits for native close. After its bounded grace Go
kills the owned process group and reports `ErrForcedStop`, or `ErrStopUnknown`
when exit cannot be confirmed. Cleanup errors are joined with existing Host
errors. This does not prove detached native tools are quiescent; production
replacement requires verified systemd `KillMode=control-group` cleanup before
another Host opens storage. No persisted Go recovery gate/agent ledger is added.

## Validation on this executor

Go 1.25.14, local Linux subprocess fixtures, no real model calls:

* Real Unix HTTP and synthetic Go subprocess fixtures verify owner/auth scope,
  canonical fingerprint, rejected untrusted input/aliases, final frame budget,
  native ID/receipt/result bounds, safe public reason, summary-only pagination,
  lost ACK lookup without mutation retry, readiness/exit/startup cleanup,
  inherited lease lifetime and explicit forced-stop error.
* Composition uses the actual existing Host handler and a live Unix worker
  fixture. It does not run the actual PRIVATE SDK or full installed command.
* `go test -race -count=1 ./...` passed with fixture umask 022 (Host 69.443s,
  durablebridge 5.803s, command composition 1.022s), as did `go vet ./...` and
  Linux/Windows amd64 CGO-free `go build -buildvcs=false ./...`. This worktree
  environment could not provide automatic VCS stamp; source commit/tree are
  retained separately. No Windows release file is changed; enabling this Linux
  boundary elsewhere fails closed.
* Initial full-suite pairing fixture failures under default umask 077 reproduced
  on the exact base: its requested 0644/0755 unsafe fixtures were masked into
  0600/0700. Final umask 022 run passed without changing pairing source.
* The production-directory acceptance test explicitly skips on this cloud
  executor's mapped-root ancestry. Production validation was not weakened.
* Independent read-only review closed configuration ancestry/canonical paths,
  literal JSON tags, final frame bounds, public reason and cleanup error issues.
  It did not validate PRIVATE/native storage, systemd or transport agreement.

## Remaining gates

Reconcile PRIVATE's owner/result/cursor/lease schema with explicit defaults.
Real pinned native Harness/SQLite tests with faux models must cover reopen/crash,
dedup/model freeze, cancellation/replay ordering, result-reference authorization,
Unix socket and Linux flock inheritance. Full cmd lifecycle, fixed permissions,
systemd control-group cleanup and Ubuntu service activation remain native
acceptance gates requiring a separately authorized suitable environment.

No push, new CI, release, production access, system mutation or user data
deletion occurred in this local Host implementation.
