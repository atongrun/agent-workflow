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
it has not run on another native VM. No approval remains from the original
maximum-two-VM request.

## Separately approved post-Pi diagnosis

On 2026-10-06 04:04:41 UTC the user approved exactly one additional GitHub-hosted
ephemeral Ubuntu24.04 VM to identify this failure and, where feasible, verify
an already authorized reviewed fix on that same VM. The only temporary parent
permission changes remain the same physical root:root `/opt` and
`/usr/local/bin`, exact `0777` to `0755`, then independent restoration. This
does not authorize an automatic further machine or workflow rerun.

The new exact trigger is `awf/linux-post-pi-diagnostic-ci-v1`, using a 30-minute
job and the original 22-minute command deadline. Only a reproduced first
`start-after-pi` failure after a successful official update may retain the
ledger-owned installation, and only after both literal units have stopped with
empty cgroups. The first safe report is uploaded immediately. Static source
error codes, metadata, dependencies, unit state, and the exact native-environment
Pi version probe identify which startup guard failed. The official version
probe may create a temporary settings lock; it invokes no model or provider.
Private logs, settings bodies, task state and credentials are not uploaded.

On the parent's 2026-10-06 follow-up, this attempt is restricted to reproduction,
the concrete startup error and the minimum fix assessment. There is no remote
continuation, candidate loader or interactive repair framework. The fixed
workflow uploads the safe first report, then immediately performs owned cleanup,
independent restoration of both original parent objects and a final report.
It does not wait for channel publication or run a second default installation.
The Linux channel remains unpublished pending actual public-product gates.

## Completed additional diagnosis

[Run 37415293853](https://github.com/atongrun/agent-workflow/actions/runs/37415293853)
used harness `43cb358d7f92db125537ec8b9b87f355f2254d0f`, tree
`21862f80aa0606b02513d2e5b3ff14a0d5604977`, on actual Ubuntu24.04.5. All 89
harness boundary tests passed. The earlier `961587c` workflow was rejected at
YAML validation with zero jobs and allocated no VM; the follow-up changed only
the invalid job-level runner-context expression to a static evidence path and
added its regression check. No further native machine or rerun is authorized.

The public RC2 installation completed in 47.16 seconds; init, first start,
native health/read-only RPC and owned stop passed. The real official bare
`pi update` completed in 9.01 seconds, changing 1.0.2 to 1.0.4 in `/opt/pi-cli`.
The next `awf start` failed in 2 seconds with the exact static error:

```
system path ownership, type or permissions require inspection
```

This is `nativeAdapter.trusted()` rejecting ownership/type/permissions before
any service-start progress. Both approved parent directories and the other
listed program/config roots passed their trust metadata checks. Unit literals,
configuration, private Magpie settings and the sealed maintenance target also
passed. The Pi package probe was unavailable while inspecting package JSON and
its trusted ancestors. The report does not identify the particular rejected
Pi inode or record the native caller's umask; those remain unobserved.

The first artifact `11390713948` is 4146 ZIP bytes, SHA256
`92d1ddb8c5fea01a14102150165469cc12945a9aeab49d508a869d1528315e53`;
its report SHA256 is
`4438b2a80efe3147c166feb123ab7cbb668fa0f6f4954f8d4a012c5c61d821b2`.
The final artifact `11390888294` is 4242 ZIP bytes, SHA256
`c4e69a9f787a6805c4167852fec78881e93803fdc1fe0c924f29bbe137eaa26c`;
its report SHA256 is
`7c485aa30fb018db6d0bc78b46fe7e5f24a229c5d90ae21ab2721f88ad84ebb9`.
Both ZIPs contain only `upgrade-report.json`; downloaded bytes, hashes and
cleanup evidence were independently checked. All 13 ledger-owned paths were
removed, service processes exited, existing Node/npm/npx remained unchanged,
both original root:root directory inodes/modes were restored to `0777`, and the
private parent receipt was removed. Acceptance remains false and AWF upgrade
was not executed.

## Isolated minimum-fix assessment

Two local, scripts-disabled, offline official npm upgrades began with the same
1.0.2 package tree normalized to the installer's original modes. They used the
verified Node22.19.0/npm10.9.3 and fixed official Pi1.0.4 package/dependencies
from the existing cache. All paths were inside the development executor; no
account, unit or fixed system path was changed.

| Inherited process umask | Pi package JSON | Pi package directory | Unique group/other-write violations |
| --- | --- | --- | --- |
| `0002` | `0664` | `0775` | 16460 |
| `0022` | `0644` | `0755` | 0 |

Both official npm commands exited 0 and installed 1.0.4. In both cases the
existing prefix, `lib` and `node_modules` stayed `0755`. Thus the `0002` case
reproduces the same early trusted-path rejection while fixed parent checks
still pass, matching the native report. This is strong local evidence for the
inherited-umask explanation, not a native measurement of the exact failed path.

The minimum product change to evaluate is a shared-program-friendly `0022`
umask at the stable AWF-owned launcher's root `pi update` entry before execve,
so the official npm updater inherits it. Preserve ordinary/service command
masks, keep the official update command and sole prefix, leave scripts disabled,
and retain the existing trust predicate. Changing only the CI test umask or
accepting group-writable vendor files would not validate that product fix.
No such application change or native verification was performed in this
diagnosis. A new immutable candidate must review its launcher byte binding and
receipt/update compatibility, then pass real post-Pi restart, AWF upgrade and
default-update gates before channel promotion. Existing RC2/RC3 assets remain
unchanged. Windows RC9, protected branches/tags and the cancelled CloudCone
plan remain unchanged.

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
