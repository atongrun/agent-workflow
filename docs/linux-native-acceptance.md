# Private native acceptance on an existing machine

This is a reviewable plan, not authorization or evidence of installation. The
current executor is Debian 13 without systemd as PID1; all completed machine
adapter tests here are isolated fixtures. Ubuntu 22.04/24.04 and Debian 12 amd64,
glibc, systemd/cgroup v2 are source-supported targets with native acceptance
pending. Windows RC9 assets, tags and dispatch remain unchanged.

## Exact candidate and private artifact route

Use the final independently reviewed commit/tree and kit/manifest SHA256 recorded
in the accompanying local evidence. Build once in the development executor with
Go 1.25+, never on the target VPS. The private version `v1.999.999-rc.0` is an
unpublished executable identity; it is not a tag or release. Both the Host and
test runner receive the existing `internal/host.BuildVersion` and
`internal/host.BuildSourceCommit` linker values. `scripts/private_native_kit.py`
packages those executables, the actual AWF extension, audited official Node/Pi/
Magpie artifacts, eight fixed public metadata responses and the reviewed npm
cache. It excludes cache logs, npm configuration, credentials, Library signed
references and private Dashboard source. No public upload is part of this plan.

The kit ZIP and its SHA256 must be privately transferred only after approval.
Keep it root-owned 0600 on the target. The reviewed extractor requires the
independently approved exact checksum, uses one same-owner non-linked source
descriptor for hash and extraction, validates all paths/types/modes/duplicates
and expansion budgets, and creates a new private `/tmp` destination. Destination
ancestors are same-owner private directories; root requires root-owned sticky
`/tmp`. Every write uses held nofollow directory/file descriptors. It never
uses `unzip`/tar extraction with unchecked paths or writes system roots.

The precompiled Go test runner accepts only an independently approved manifest
hash, matching compiled build identity, audited Node/Pi bytes, fixed supplemental
pins and rehashed stage/cache contents. Its default mode prepares a private
runtime and makes no native writes. Real installation needs the explicit
`-awf-private-native-install` flag; it uses the real native adapter's root,
platform, trusted executable, path, account, unit and port guards, real useradd
and systemctl, and fresh root-owned programs. No filesystem-root or mock command
override exists in this route. It performs offline `npm ci --ignore-scripts`,
then installs programs without init or service activation. The selected Pi
closure is identical to public preparation: 147 lock entries, 122 installed,
25 other-platform optional entries skipped. Actual verification must establish
those values; fixture receipts never count as native acceptance.

This explicitly private provenance route does not validate a public release/tag,
download progress or bootstrap E2E. The production bootstrap/Go installer retain
all public source checks, and the Linux public channel remains unpublished.

After separately approved extraction, the installation invocation has this form:

```sh
systemd-run --scope --unit=awf-acceptance-install \
  -p MemoryHigh=224M -p MemoryMax=320M -p MemorySwapMax=128M \
  -p TasksMax=96 -p CPUQuota=100% \
  /tmp/APPROVED_PRIVATE_KIT/tools/native-acceptance.test \
  -test.run '^TestPrivateNativeAcceptance$' -test.v -test.timeout 12m \
  -awf-private-native-input /tmp/APPROVED_PRIVATE_KIT/input \
  -awf-private-native-manifest-sha256 APPROVED_MANIFEST_SHA256 \
  -awf-private-native-install
```

These exact scope budgets are trial limits, not measured sufficient resources.
Verify the scope properties on the actual systemd version before execution.
The scope bounds installer descendants; systemd service units are separate.
Do not create service drop-ins or use `systemctl set-property` on AWF units: the
candidate correctly refuses unit overrides. Literal units must remain unchanged.

## Machine, time window and resource gates for one approval

The proposed first target is the ops-confirmed existing CloudCone Debian 12 amd64
VPS: 2 CPUs, approximately 960 MiB RAM, 3 GiB swap (298 MiB used), 485 MiB
MemAvailable and 9.69 GiB free disk at the prior read-only snapshot. The ops owner
must bind approval to its actual machine identifier/address and SSH host-key
fingerprint; neither is guessed here. Refresh these figures at the window start.
Stopping sub2api would recover only about 40–50 MiB and is not part of the plan.
Keep sub2api, PostgreSQL, Redis, Docker, nginx, Beszel, cloudflared and SSH running.
No source compilation, apt/package upgrade, parallel load, model task or actual
Pi network update occurs in this first slice.

The Debian 12 package set supports the used systemd directives and account tools.
Pinned Node requires glibc 2.28 or later; the locally built Host currently uses
symbols up to glibc 2.34. Debian 12's reported glibc 2.36 meets those requirements;
this is a compatibility assessment, not execution evidence. Verify the target's
C++ runtime and binaries before writes. See the pinned [Node build requirements](https://github.com/nodejs/node/blob/v22.19.0/BUILDING.md),
[Debian systemd execution directives](https://manpages.debian.org/bookworm/systemd/systemd.exec.5.en.html),
[systemd package file list](https://packages.debian.org/bookworm/amd64/systemd/filelist),
[useradd options](https://manpages.debian.org/bookworm/passwd/useradd.8.en.html) and
[Debian C++ runtime](https://packages.debian.org/bookworm/libstdc++6).

Approval covers one 30-minute window beginning when ops records the approved UTC
start, with a recorded UTC end. Install is bounded to 10 minutes and each service
health/stop phase to 2 minutes; end the slice on timeout or failure. Do not retry
stressfully or change budgets to turn a failed run into a pass. Require systemd
as PID1, unified cgroup v2, trusted account tools, Python 3/CA certificates,
available required kernel namespaces/mount protection and no portable Magpie
marker. Require `/tmp` and program/state filesystems to have at least 4 GiB free
and `/tmp` to be disk-backed, not a RAM tmpfs. Confirm fresh AWF roots/account/
commands/units and free 7070/3425; existing Node 18 is permitted and preserved.

Sample every 2 seconds during each serial phase. Abort on MemAvailable below
192 MiB for three consecutive samples, installer/service budget above 320 MiB,
swap growth above 128 MiB from baseline, any new OOM/oom-kill count, free disk
below 4 GiB, unexpected public listener, fixed-path/unit/owner drift, or changed
health of an unrelated baseline service. Observe memory.current, memory.peak
where available, memory.events and process counts for the installer and both
AWF cgroups; services have a combined observed 320 MiB ceiling, with no model
work. Record CPU/time and memory/swap/pressure alongside outcomes. Never assert
that heap or cgroup limits prove low-resource compatibility. Any resource abort
is failed or inconclusive native acceptance.

## Writes and serial checks covered by that approval

Before mutation, create a root-private ledger and record target identity,
candidate/tree, kit/manifest checksums, UTC window, resources, unrelated service
state and existing Node/npm/npx resolution, inode, mode and checksum. Record that
each newly owned fixed path/account/group is absent; if the installer lock
directory already exists, record it and never claim ownership or delete it.

The complete new persistent scope is:

| Item | Exact target |
| --- | --- |
| Program roots | `/opt/node`, `/opt/pi-cli`, `/opt/awf`, `/opt/magpie` |
| Three command links | `/usr/local/bin/awf`, `/usr/local/bin/pi`, `/usr/local/bin/magpie` |
| Dedicated identity | newly created non-login system account and group `awf`; record actual UID/GID |
| Root configuration/evidence | `/etc/awf`, including private local tokens and Magpie settings snapshot |
| Private service state/cache | `/var/lib/awf` including `pi-agent` and `magpie-config/magpie`, `/var/cache/awf` |
| Installer lock | `/var/cache/awf-installer`, only if absent/new |
| Unit files/reload | `/etc/systemd/system/awf-host.service`, `/etc/systemd/system/awf-magpie.service`, daemon-reload |
| Activation | only those two units, IPv4 loopback `127.0.0.1:7070` and `127.0.0.1:3425` |
| Temporary acceptance work | approved new private extraction directory, named runtime scratch, root-private ledger/logs and `awf-acceptance-install.scope` |

The adapter's `/opt/.awf-install-*` scratch is named and temporary; record any
residue on interruption. There is no autostart enablement, firewall change,
nginx/tunnel change, foreign service restart, user credential copy or existing
Node/npm/npx replacement. Root ordinary Pi retains its own `~/.pi/agent`; this
slice runs only Pi `--version`, which the offline checks observe without agent
state creation. No configuration there is initialized or altered.

Run serially: preflight/ledger, private extraction and binary identity, bounded
offline program installation, inventory/account/unit validation, `awf init
--yes`, `awf start`, read-only identity/socket/mount checks, `awf stop`, inactive
MainPID-zero/recursive-cgroup-empty checks, then one start/stop repeat. Keep both
units stopped at window end. Verify native receipt, exact program ownership and
commands, preserved Node 18, separate service Pi directory, settings bind inode
and read-only mount, writable service provider directory, and loopback socket
ownership. Reads of local Host maintenance use the freshly issued local token
without logging it. No model account is needed for these process checks; if
upstream startup unexpectedly requires credentials, stop and report the blocker.

Bare `pi update` remains supported on the sole global prefix; its real network
execution and post-update compatibility are a later explicitly reviewed slice,
with both services stopped. Public bootstrap, other target OS versions, reboot,
autostart, interrupted replacement and model-backed E2E remain separate gates.

## Rollback limited to this attempt's newly owned items

Record created items' device/inode, owner/mode, exact links, unit hashes,
inventory/receipts and account UID/GID immediately after each phase. Partial
installation can fail before a native receipt exists, so the initial absence
and incremental ledger are essential. Preserve logs and lease/pending evidence.
The candidate has no automatic native uninstall or multi-root rollback.

Stop and verify only trusted literal AWF units, with MainPID zero and empty
recursive cgroups. Normal `awf stop` uses its durable lease; if failure preceded
initialization/Host health, ops may stop only the ledger-owned matching fixed
units for this no-work slice. Never force-open a seal, kill processes by broad
name, or stop an untrusted unit. Remove only the three links still matching their
exact owned targets, the two still-matching unit files and explicitly enumerated
new AWF roots/state/cache/lock/scratch from the ledger; then daemon-reload.
Verify ownership and no foreign use/content before any recursive removal. If
anything differs, stop and inspect instead of inferring ownership or deleting it.

Delete the newly created account only when its recorded UID/GID, home and shell
still match and no process/other resource uses it; use `userdel` without `-r`.
Remove the newly created group only if no other member/user uses it. Never
restore entire passwd/group files or touch `/usr/bin/node`, existing npm/npx,
nginx, containers, databases, SSH or another application's roots. Remove only
the approved private temporary kit after preserving evidence. No machine-wide
snapshot restoration is assumed or authorized on this existing VPS. Unknown
ownership or changed state is a reported rollback blocker.
