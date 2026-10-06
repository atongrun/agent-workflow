# Linux RC2/RC3 acceptance candidate

Reviewed application source: `510e6b893c6524873297b972edc72e801b870b0d`.
Packaging source: `e520c8c6f09719ee11551124e3443869d21a7c61`.
Both new versions remain prereleases. Publication does not promote a channel.

## Actual Ubuntu24.04 results

The current approval's two disposable VMs have both been consumed. Run
[37409328088](https://github.com/atongrun/agent-workflow/actions/runs/37409328088)
installed RC2 and passed initial lifecycle/RPC, then failed before executing Pi
or AWF update. Its report upload failed because the artifact name contained a
branch-name slash. Cleanup/restoration were reported in the job log, but no
complete structured report survived.

Run [37410289437](https://github.com/atongrun/agent-workflow/actions/runs/37410289437),
harness `a7e47399f500df3b4e5030121f9f763eeb1702a9`, actually passed public RC2
installation, init, initial native health/read-only RPC, stop and bare official
`pi update` from **1.0.2 to 1.0.4** in the sole `/opt/pi-cli` prefix. Postinstall
scripts remained disabled and ordinary root Pi retained its default HOME path.
The next `awf start` exited 1. Its first error was not retained in the report;
the cause remains unknown. AWF RC2-to-RC3 update never ran. Channel waiting,
default installation and bare default update were skipped. The Linux channel
remains unpublished.

The retained phase1 artifact is ID `11389370237`, 3272 ZIP bytes, SHA256
`59f3e18af5f0e53db2761c79e36ce6d09fb40ac11331c4525170507d12c18c9c`.
Its sole `upgrade-report.json` has SHA256
`f49f64b676116293e60ee0955f5ce826abb8a52428d31aa7a4060e87fd6c1a7b`.
The report, job step outcomes and log were independently checked. All 13 owned
paths were cleaned, service processes exited and existing Node/npm/npx were
preserved. Both approved parents retained their original inode/root:root/0777,
and the private preparation receipt was removed.

An isolated local official npm 1.0.4 install with scripts disabled passed CLI
version and prefix trust checks. The actual package tree also passed the native
adapter's inventory and start/stop/start checks beneath temporary paths with
substituted machine commands. Draft/sealed Host restart tests passed locally.
These results do not establish native post-update startup or identify its error.
No published application source, tag or asset was changed in response to the
unknown failure.

The diagnostic harness now exports only exact static error codes/progress and
bounded enum/PID status from the two ledger-owned units after a failed AWF
restart/update. Raw command logs, arbitrary error text and credentials remain
private. Cleanup preserves the bounded diagnostic. This change has local tests;
it has not run on another native VM. A further native attempt requires a new
explicit machine/action approval. No approval remains from the maximum-two-VM
request, and no third VM was started.

## Planned acceptance and promotion gates

An explicitly approved standard GitHub ephemeral Ubuntu24.04 VM downloads all nine RC2 public
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

Only after actual post-Pi startup and AWF cross-version upgrade succeed, with
independently verified complete cleanup/restoration, may the independent
`awf/linux-v1` channel select the immutable RC3 manifest. The planned two-phase
workflow can then reuse that same approved VM after complete owned AWF cleanup
for the public channel bootstrap and genuine bare `awf update`. This is a
current-version verification, not another cross-version upgrade or a new image.
It must preserve program/receipt inodes and bytes and service PIDs. Each phase
independently records and restores only the same two approved parent directories.
A bounded read-only wait precedes the default phase; the native job never
promotes a channel. This plan itself authorizes no new VM.

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
