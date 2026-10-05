# Public native Ubuntu test

## Current diagnostic rerun

The first real run 37335670384 reached terminal Failure before installation:
`/opt` failed the parent trust prerequisite. The current workflow explicitly
uses `--diagnostic-only`, with a five-minute job timeout. Even a clean runner
cannot proceed into installation in this mode. It collects only `lstat`/`stat`
UID, GID, octal mode, directory/symlink status for `/opt` and `/`, plus the exact
published Go predicate and failed terms. Group ID is metadata, not a required
root-group condition. No chmod/chown, adopted directory, namespace mutation,
runtime download or provider data is part of this diagnostic run. Its workflow
has no cleanup invocation, since diagnostics create no native ownership ledger
or installation. Native acceptance remains false; a failed prerequisite retains
a failed job result.
The parent explicitly authorized this one diagnostic correction/run.

## Native harness retained for later permitted execution

The user approved this GitHub Actions acceptance on 2026-10-05 15:26 UTC.
The independent branch is `awf/linux-native-ci-test-v1`; push on that branch in
this repository is the only trigger. No default branch, PR, self-hosted runner,
container, release write or model/provider secret is used. Only `contents: read`
is granted, checkout credentials are not persisted, and official actions are
pinned to the previously verified full SHAs. The old release workflow does not
match this branch. The retained full acceptance plan has a 30-minute budget,
with an internal 22-minute command budget, eight-minute installation and bounded
lifecycle/cleanup calls. The current diagnostic workflow is limited to five
minutes and cannot execute this sequence.

One standard `ubuntu-24.04` VM is used first. Actual root/PID1 systemd, glibc,
cgroup v2, required root capabilities, storage, fresh fixed paths, units,
accounts and 7070/3425 are checked before installation. A full 60-second window
must observe at least 512 MiB available and no full memory stalls. Missing
features or conflicts fail, without moving paths, modifying overrides or
stopping existing services. This is not a clean minimal OS image: the runner's
preinstalled Node/npm/npx are fingerprinted and must be preserved.

The nine actual public `v1.0.1-rc.1` assets are downloaded from their canonical
release URLs and checked against immutable byte counts/SHA256 values, then the
manifest/provenance/bootstrap contract is verified. The source/tag remains
`f0a2f98bbab111aed4cc612667e7387af5e4c7bf`; the acceptance harness commit is
recorded separately. No private kit or runtime cache is distributed or used.

The verified public bootstrap receives the already pinned local manifest and
Host archive with `--manifest`, `--archive` and `--allow-prerelease`, avoiding an
unchecked second release manifest/Host download. All upstream runtime inputs are
still downloaded and verified by the real native installer. It runs in a new owned
`awf-native-ci-install.scope`: MemoryHigh=1G, MemoryMax=2G, MemorySwapMax=256M,
TasksMax=256, CPUQuota=200%. These are normal CI safety bounds, not CloudCone
low-memory acceptance limits. Literal service units are not overridden. The
harness observes cgroup memory/OOM events and aborts if combined service memory
exceeds 2 GiB or available memory repeatedly falls below 192 MiB.

The real sequence is install; Host/Pi/Node versions and Host identity;
`awf init --yes`; `awf start`; authenticated local read-only Host identity and
Magpie health; `awf stop`; then a second start/health/stop. Health checks actual
non-root MainPIDs, cgroup membership, owned IPv4 loopback sockets, the real
read-only settings bind and inode, independent Pi state and empty projects/nodes.
Stop must establish inactive MainPID-zero units and empty recursive cgroups.
No autostart enablement, provider login, model/task request or Pi update occurs.

Initialization generates distinct temporary local Host/extension tokens in the
root-only `host.env`. Tokens are never printed, placed in command arguments,
copied to public reports or supplied from repository secrets. All native raw
output and the ownership ledger stay root-private in a new exact `/tmp`
directory. Only the structured sanitized report is an artifact. No journal or
environment dump is published.

Before writes, all native targets must be absent. Newly created fixed paths
receive device/inode/type records; the account/group IDs and
literal unit hashes are recorded. Cleanup first stops only a matching owned
installer scope and literal owned AWF units, checks processes/cgroups, and
validates ownership, mounts and ledger identity before removal. It deletes only
the exact three links, two units, four program roots and AWF config/state/cache.
Installer scratch is removed by the immutable installer's own defers. Matching
a temporary name or UID is insufficient proof; leftover scratch fails cleanup
without deleting it by glob. `userdel` has no `-r`; an unused recorded group
may then be deleted. Existing Node/npm/npx must still match. Unknown or changed
ownership blocks cleanup and retains private evidence. A separate `always()`
step retries only the same ledger's cleanup after failure/cancellation. A hard
runner timeout that prevents cleanup must be reported as unverified cleanup.

Success covers this Ubuntu 24.04 VM and the tested process lifecycle only.
Ubuntu 22.04, genuine upstream Pi update, model-backed work, Debian and CloudCone
low-resource acceptance remain separate. CloudCone stays paused; its earlier
resource failure is not an installer code result.
