# Thin Node Operations Implementation Report

## Scope

This change gives an installed `awf` wheel one small, consistent local listener surface:

```text
awf node doctor --profile <name-or-absolute-json>
awf node start --profile <name-or-absolute-json>
awf node status --profile <name-or-absolute-json>
awf node logs --profile <name-or-absolute-json> [--lines N]
awf node stop --profile <name-or-absolute-json>
```

It does not install a native service, schedule work, define a DAG, select providers generically, or
move runtime behavior into Agent Bus. Existing launchd, systemd, and WinSW files remain candidate
integration templates with their existing acceptance warning.

## Profile contract

`schemas/node-profile.schema.json` defines `awf.node-profile.v1`. A named profile lives at the
platform config home under `awf/profiles/<name>.json`; operators may instead pass an absolute JSON
path. The profile records only non-secret listener facts such as role, repository, selected tool,
model, route, remotes, state root, and log path. Unknown fields are rejected, which prevents Bus
URLs and role tokens from drifting into the profile. Those values remain in strict owner-only
`dispatch.env` and are loaded by the existing parser.

The semantic gate retains the current execution boundary: Pi is reviewer-only, while architect
terminal handling remains no-model. Repository, state, log, and config paths must be absolute.

## Lifecycle and readiness

`doctor` and `start` validate the profile, strict credential file, role-aware Git root, required
role Bus configuration, Agent Bus health, and the selected model executable's version command.
Coder and reviewer therefore still require a dedicated clean checkout; architect may use a dirty
source checkout because terminal verification is event-scoped and isolated. These checks finish
before the listener subprocess and before any event can reach a model.

`start` runs the already packaged `awf_listen.py`, redirects output to the profile log, and writes
an atomic process record bound to the exact profile digest, role, and repository. `stop` refuses to
signal a record whose binding no longer matches. POSIX uses an isolated process group and SIGINT;
Windows uses a new process group and CTRL_BREAK, allowing the listener's existing clean local-stop
path to release its lease without a `control:shutdown` event. Stale records are removed without
signalling a dead PID.

## Compatibility

The listener argv, v1-v3 event routes, RunManifest/TaskCard selection integrity, reviewer/coder
tool boundaries, checkpoint/outbox/inbox ordering, ACK semantics, and native service templates are
unchanged. `awf status --run` and `awf resume --run` retain their existing meanings; node status is
explicitly nested under `awf node`.

## Verification

Regression coverage locks profile schema and secret rejection, named-profile resolution, absolute
path and Pi boundaries, pre-spawn readiness failure, packaged listener argv, atomic process
binding, profile-drift signal refusal, POSIX clean-stop signalling, bounded log tailing, concise
errors, and CLI routing. Full Linux, Windows, and macOS verification is delegated to repository CI
in accordance with the local macOS test policy.
