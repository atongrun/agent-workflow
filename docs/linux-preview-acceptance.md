# Linux RC2/RC3 acceptance candidate

Reviewed application source: `510e6b893c6524873297b972edc72e801b870b0d`.
Packaging source: `e520c8c6f09719ee11551124e3443869d21a7c61`.
Both new versions remain prereleases. Publication does not promote a channel.

The first standard GitHub ephemeral Ubuntu24.04 VM downloads all nine RC2 public
assets, verifies their actual published pins, and executes the release-bound
public bootstrap with only `--allow-prerelease`. The bootstrap itself fetches its
immutable release manifest and Host archive; no local manifest/archive override
is passed. Initial installation remains Node22.19.0, Pi1.0.2 and Magpie0.1.855.

After init/start and native service checks, the harness creates one explicitly
synthetic task through the local Host API. This creates persisted state without
starting a model turn. A service-account official Pi RPC runs only `get_state`
and `get_commands`. An observational temporary extension checks the actual
production extension's registered and active AWF tools through Pi's public API.
It never invokes those tools or submits a prompt.

After AWF stop and verified empty service cgroups, the harness executes the
official bare `pi update`, using a fresh root-private HOME and the ordinary Pi
default agent path. It inspects the official updater's npm command first and
requires `/opt/pi-cli`, global installation and `--ignore-scripts`. It records
the actual official selection and resulting package/version, then repeats
start/health/RPC with the updated Pi. The mutable upstream latest version is
recorded at runtime rather than hardcoded.

`awf update --version v1.0.1-rc.3 --yes` then tests genuine cross-version
replacement before channel promotion. The updater's earlier explicit Linux
preview permission must remain sufficient. The harness records all three old
program-root identities and exact backup destinations before execution. New
roots enter the cleanup ledger only after the immutable target, complete runtime
receipt and recorded old backup identities match. A partial or unknown
replacement blocks recursive cleanup instead of adopting newly discovered paths.

After upgrade, the harness checks the complete current Pi tree fingerprint,
config and generated-credential bytes, persisted synthetic task, service agent
root, external Node/npm/npx and real native lifecycle. Three exact owned backups
are included in cleanup; no glob removal occurs. Unknown residue is reported.

Only after this VM succeeds may the independent `awf/linux-v1` channel select
the immutable RC3 manifest. A second standard ephemeral VM then executes the
public channel bootstrap and genuine bare `awf update`. Same-version success
must preserve program/receipt inodes and bytes and service PIDs. This is a
separate branch push, so the first native test is not automatically rerun.

Each new VM requires an explicit bounded approval for the two physical,
root-owned, root-group-owned `/opt` and `/usr/local/bin` directories whose exact
initial mode is `0777`. Before any permission write, the helper records both
identities and original modes in a root-private durable receipt, temporarily
sets only those two objects to `0755`, and independently restores both original
objects/modes after owned cleanup. No recursion, ownership changes, child-mode
changes or other parent paths are permitted. Prior VM permission approvals do
not authorize these new machines.

Only the bounded report is uploaded. Raw logs, credentials, task payloads,
private ledgers and upstream dependency caches remain private to the disposable
VM. No provider account, model request, production server, public listener,
firewall change, low-memory acceptance or cloud purchase is part of this test.
