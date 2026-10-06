# Public native Ubuntu test

## Current authorized two-parent native run

On 2026-10-06 02:22 UTC the user approved the complete diagnostic's two known
permission changes for the next disposable GitHub Ubuntu VM: physical
root:root `/opt` and `/usr/local/bin`, each `0777` to `0755`, nonrecursive, then
independent restoration to the original modes after owned cleanup.

The current 30-minute job calls `native_ci_parent.py --prepare-ci-parents`.
Both new VM objects must match the approved metadata. A schema-2 private receipt
captures both original identities/modes before the first permission write. No
old VM inode is reused. Every permission write uses a verified directory
descriptor, changes no owner or child, and leaves the installer trust rules
unchanged. Partial apply, failure and cancellation attempt restoration of each
recorded parent independently. An `always()` cleanup retry revalidates both
parents and, only while native control remains, reacquires trusted `0755` for
both before path-based cleanup, then independently restores both. Unknown
objects block changes; restoration/cleanup failures retain private evidence and
fail the job. Successful cleanup removes the private parent receipt. The public
report records each preparation/restoration result without logs or tokens.

The approved native sequence is immutable RC1 install and version checks,
local-only init, two start/health/stop rounds and owned cleanup. Model/provider
authentication, Pi network update, production/CloudCone access, release/Windows
changes and further permission targets are outside this run.

## Completed complete read-only diagnostic

Run 37341262966 verified the approved `/opt` adjustment and restoration but
then stopped at `/usr/local/bin`, before installation. The completed five-minute
workflow ran `native_acceptance.py --diagnostic-only` with no parent-preparation
or cleanup invocation. It collects every fixed installation parent and all its
components, plus the fixed native-command parents, before freshness can fail:
`/opt`, `/etc`, `/var/lib`, `/var/cache`, `/usr/local/bin`,
`/etc/systemd/system`, `/usr/bin`, `/usr/sbin` and their exact ancestors.
Every Go trust term is evaluated; GID remains metadata. Fixed AWF objects,
account/group, commands, bounded source-derived unit/drop-in/dependency conflicts
and the two ports are collected together. Root Pi agent presence is a separately
labelled test-isolation check; no home, authentication or environment scan occurs.
The diagnostic performs no chmod/chown/install/cleanup, and can never claim
native acceptance. Read-only errors are reported without hiding later entries.

## Previous approved single-parent preparation

The diagnostic run [37338037770](https://github.com/atongrun/agent-workflow/actions/runs/37338037770)
proved `/opt` was a physical root:root directory with mode `0777`. Only the group
and other write conditions failed. On 2026-10-05 16:14 UTC the user explicitly
approved temporarily changing only this disposable VM's `/opt` to `0755`,
running the native acceptance and scoped cleanup, then restoring `0777`.

The then-used `native_ci_parent.py --prepare-ci-opt` required that exact initial metadata;
different metadata stops the run. A root-private write-ahead receipt records
the original device/inode/type and mode before an `fchmod` on a verified
directory descriptor. There is no recursive chmod, chown, child permission
change or installer-check exception. The wrapper's outer finally restores the
same directory after the harness's cleanup attempt, including preflight or
native failures. An `always()` step retries only existing ledger-owned cleanup
and that same parent restoration; it never adopts a new parent. When a native
ownership ledger remains after the first attempt restored `0777`, the retry
revalidates the same private receipt/inode and temporarily reacquires `0755`
before path-based cleanup, then restores `0777` in its finally. With no remaining
native control it performs no second permission adjustment. A successful
restoration verifies the original identity, root:root ownership and `0777`.
Unexpected identity/mode or unknown control contents block changes and retain
the private receipt. A hard VM/job termination without receipts remains
unverified restoration, not a success claim.

The completed native run had a 30-minute timeout. The wrapper is restricted to
the approved hosted Ubuntu 24.04 branch/job. The immutable RC1 installer and
assets remain unchanged. Actual Pi update, provider authentication and model
calls are outside this approval.

## Completed diagnostic rerun

The first real run 37335670384 reached terminal Failure before installation:
`/opt` failed the parent trust prerequisite. The diagnostic workflow explicitly
used `--diagnostic-only`, with a five-minute job timeout. Even a clean runner
cannot proceed into installation in this mode. It collects only `lstat`/`stat`
UID, GID, octal mode, directory/symlink status for `/opt` and `/`, plus the exact
published Go predicate and failed terms. Group ID is metadata, not a required
root-group condition. No chmod/chown, adopted directory, namespace mutation,
runtime download or provider data is part of this diagnostic run. Its workflow
has no cleanup invocation, since diagnostics create no native ownership ledger
or installation. Native acceptance remains false; a failed prerequisite retains
a failed job result.
The parent explicitly authorized that single diagnostic correction/run, now
completed. The read-only diagnostic option remains available separately.

## Native acceptance harness

The user approved this GitHub Actions acceptance on 2026-10-05 15:26 UTC.
The independent branch is `awf/linux-native-ci-test-v1`; push on that branch in
this repository is the only trigger. No default branch, PR, self-hosted runner,
container, release write or model/provider secret is used. Only `contents: read`
is granted, checkout credentials are not persisted, and official actions are
pinned to the previously verified full SHAs. The old release workflow does not
match this branch. The full acceptance plan has a 30-minute budget,
with an internal 22-minute command budget, eight-minute installation and bounded
lifecycle/cleanup calls.

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
