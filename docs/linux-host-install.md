# Linux Host fresh-machine installer

The thin bootstrap acquires verified public AWF bytes; Go owns native machine
and service lifecycle. The immutable Linux TEST ONLY RC1 was published and
installed on a real disposable GitHub Ubuntu24.04 amd64 systemd VM in run
[37404774253](https://github.com/atongrun/agent-workflow/actions/runs/37404774253).
Its install, version, init, two start/health/stop rounds and owned cleanup passed.
This source adds the independent Linux update channel; its new release and
actual upgrade results must be recorded separately and cannot inherit a pass
merely from source fixtures. No production deployment is implied.

The targets are Ubuntu 22.04/24.04 and Debian 12, glibc, systemd with unified
cgroup v2, amd64. Root may install on an existing machine with fresh AWF paths
and accounts. Existing AWF/Pi/Magpie commands, accounts, fixed roots or unit
overrides require inspection; installation never adopts, repairs
or migrates them. Windows lifecycle dispatch, release artifacts and channels are
unchanged. There is no Dashboard source in this repository or installer.

Go owns machine and process lifecycle. Official Pi owns its session, context,
tools and self-update. The existing AWF Pi extension owns business behavior.
There is one official Pi package installation, at `/opt/pi-cli`.

## Commands and publication boundary

The default bootstrap and bare `awf update` use the fixed independent URL
`https://raw.githubusercontent.com/atongrun/agent-workflow/awf/linux-v1/distribution/linux-host-v1.json`.
The channel selects an exact release. Its complete manifest must agree with that
release's canonical immutable manifest. Download length/hash, public tag/source
and executable build identity are verified before placement. There is no
Windows-channel fallback, guessed mirror or repository-wide latest selector.
Unavailable/invalid metadata fails before program replacement. Initial preview
installation explicitly permits future Linux previews; old receipts without
that approval default to false. `--yes` alone never grants preview permission.

After publication, the ordinary commands are:

```sh
curl -fsSL https://raw.githubusercontent.com/atongrun/agent-workflow/awf/linux-v1/scripts/install-linux.sh | sudo sh -s -- --allow-prerelease
sudo awf init
sudo awf start
sudo awf update
sudo awf stop
sudo pi update
sudo awf start
```

Optional administrator controls retain a reviewed local manifest/archive or an
exact update version:

```sh
sudo sh scripts/install-linux.sh --manifest /path/to/reviewed-linux-manifest.json --archive /path/to/verified-host.tar.gz --allow-prerelease
sudo awf init
sudo awf start
sudo awf stop
sudo awf start
sudo awf update --manifest /path/to/reviewed-next-linux-manifest.json --allow-prerelease
sudo awf update --version v1.0.1-rc.3 --allow-prerelease
```

The release evidence records which exact commands actually ran. Install, init
and a changing update request confirmation; `--yes` permits unattended execution. The
bootstrap invokes install with `--yes`. Install prepares programs, the account
and units; init creates service state and local tokens. Neither starts services.
`start --enable` separately enables boot autostart after health verification.
There is no public system-root override or environment override for native writes.

Default updates and same-version no-ops verify the published source. Downgrades
and different source/payload under the same version are refused. All three
replacement backup conflicts are checked before the first rename. Program roots
are replaced individually under a durable maintenance seal; interrupted updates
retain the seal, marker and exact backups for inspection. This is not automatic
whole-bundle rollback. Current configuration, local credentials, user task state,
service Pi directory and the current official Pi package tree are retained.

The bootstrap needs Python 3 already on the target system. It checks root, platform,
glibc and running systemd, downloads to a private `/tmp` directory, reports real
received bytes, verifies exact compressed length/SHA256, and extracts only `awf`
and `build.json`. It refuses duplicate, traversal, link, PAX, sparse, extra and
privileged archive entries, hidden trailing payloads and oversized expansion.
It checks amd64 ELF, executable protocol and build identity before invoking Go.
Go repeats full manifest, source and payload checks before program placement.

Read-only `awf host-install plan|doctor --manifest FILE [--json]` remains useful
without root or systemd. The plan's `readyToInstall: false` means that a plan does
not authorize writes or establish native acceptance. Stage and runtime fixture
receipts also never establish native installation.

## Fixed layout and service state

| Purpose | Location |
| --- | --- |
| Node 22.19.0, bundled npm 10.9.3 and notices | `/opt/node` |
| Sole official Pi npm prefix | `/opt/pi-cli` |
| Pi package | `/opt/pi-cli/lib/node_modules/@earendil-works/pi-coding-agent` |
| npm-owned Pi command link | `/opt/pi-cli/bin/pi` |
| Stable shared Pi launcher | `/opt/pi-cli/awf-launcher.mjs` |
| Go Host and independent AWF Pi extension | `/opt/awf/awf`, `/opt/awf/extensions/awf.ts` |
| Magpie CLI 0.1.855 | `/opt/magpie/magpie` |
| Commands | `/usr/local/bin/{awf,pi,magpie}` |
| Root-owned configuration and install evidence | `/etc/awf` |
| Dedicated service state and cache | `/var/lib/awf`, `/var/cache/awf` |
| Service Pi agent directory | `/var/lib/awf/pi-agent` |
| Service Magpie mutable settings / provider files | `/var/lib/awf/magpie-config/magpie` |
| Root-owned Magpie settings snapshot | `/etc/awf/magpie-settings.json` (0640, root:awf) |
| Fixed systemd units | `awf-host.service`, `awf-magpie.service` |

System Node/npm/npx commands are preserved, including an existing Node 18. AWF
exports only its three commands, and uses absolute bundled Node plus a private
runtime PATH. It does not replace or shadow the machine's general Node/npm/npx
commands. No apt upgrade, Node migration or unrelated account/service adoption
is performed. Debian supports trusted `/usr/bin/systemctl` or `/bin/systemctl`
and validates `useradd`/`nologin` before mutable operations.

Programs are root-owned and service-read-only. The `awf` account is a non-root
system account with a non-login shell. `/etc/awf` is root-owned, group `awf`, mode
0750; `host.json` is 0640. `host.env` is root-only 0600 and holds distinct random
local Host/extension tokens. State and cache are private 0700, service-owned.
Initialization uses a confined state root and descriptor ownership changes.
It neither copies root's Pi/Magpie credentials nor invents provider credentials.
Projects and nodes start empty; no model is selected or invoked.

Ordinary root `pi` keeps the official default `~/.pi/agent`. Only the Host unit
sets `PI_CODING_AGENT_DIR=/var/lib/awf/pi-agent`. The shared launcher preserves an
explicit caller agent directory, prepends bundled Node to PATH, removes managed
installer overrides, and uses Node's `execve` to preserve PID and stdio. It adds
no AWF extension to ordinary root Pi; the Host passes its own extension explicitly.

Units use `KillMode=control-group`, a dedicated account, private temporary files,
`ProtectHome` and `ProtectSystem=strict`. Native lifecycle checks require regular
root-owned 0644 literal unit files, trusted parents, fixed root fragment paths,
no drop-ins, `system.slice` and the dedicated account. Fresh preflight also checks
loaded manager state and systemd vendor/runtime definitions, aliases, dependency
links and applicable drop-ins before modifying programs or accounts. Occupied
7070/3425 ports are refused without stopping other applications.

Host runs a read-only configuration guard on **every** systemd activation,
including boot and automatic restart. Magpie runs a corresponding snapshot/mount
guard. Its unit binds `/etc/awf/magpie-settings.json` read-only over the service
settings file, makes state ancestors read-only, and permits writes only inside
the mounted Magpie app directory and service cache. Provider/auth files remain
writable; the process cannot replace the settings bind or rename its ancestors.
The guard checks the bound inode and the kernel read-only mount record. These
unit directives and guards are covered locally; real mounts and account isolation
still need native acceptance.

The snapshot fixes `lan: false`, `noAutoUpdate: true`, `noStats: true` and uses
independent HOME/XDG roots plus `MAGPIE_ADDR=127.0.0.1:3425`. Upstream LAN overrides
the environment address, so the immutable settings bind is necessary. While both
units are stopped, `awf start` copies valid private service settings into the root
snapshot and forces the safety fields. Omitted `lan` is accepted as upstream's
default false; explicit true, null or non-boolean values are refused. Other
settings are retained. Changes made by a separate administrative Magpie CLI take
effect after `awf stop`/`awf start`; boot/restart retains the last root snapshot.
Portable markers beside the binary are refused.

Health requires exact Host build identity and read-only Magpie root identity and
version, active fixed-unit MainPIDs with exact executable paths, main-process
cgroup membership, and actual IPv4 loopback listeners on 7070/3425. Socket inodes
must occur in descriptors owned by the corresponding unit's cgroup processes;
unrelated listeners cannot satisfy health. Unit/process/socket checks repeat at
health completion before any maintenance lease is released. Maintenance mutations
also require the owned Host listener. A failed startup attempts stop and process
verification for **each** trusted unit even if another unit's stop fails; unknown
cleanup remains a failure. No public listen or firewall change is needed.

Service Magpie authentication and a real Pi model catalog must be configured
explicitly later; startup is not proof that model-backed work is ready.

## Pi update contract

**Bare `pi update` self-updates the sole Pi installation.** This candidate uses
Pi's supported global npm prefix detection, not the earlier managed-release
fixture. In official Pi 1.0.2, `lib/node_modules` identifies the prefix and the
updater selects `npm --prefix /opt/pi-cli install -g --ignore-scripts
--min-release-age=0` for the official selected package version. A local
`node_modules` development install instead refuses self-update. The actual
upstream command-selection implementation was executed in the isolated fixture.
[Official configuration/update selection](https://github.com/earendil-works/pi/blob/v1.0.2/packages/coding-agent/src/config.ts),
[official update CLI](https://github.com/earendil-works/pi/blob/v1.0.2/packages/coding-agent/src/package-manager-cli.ts).

The normal npm-owned `bin/pi` link is retained. A custom wrapper there can make
npm replacement fail; the stable AWF launcher lives outside `bin` and remains
unchanged by npm. There is no managed marker, managed installer API override,
custom upstream updater or permanent self-update refusal. Use the administrative
root shell for `pi update`; the service account cannot modify program roots.
For a working Host, first `awf stop`, then `pi update`, then `awf start`, so both
service process groups have exited before shared Pi packages change. Do not run
plain npm installs over the prefix while services are active.

The initial Pi install uses the official 1.0.2 lock and audited supplemental
integrity evidence. A later **upstream npm update does not preserve those initial
transitive dependency pins**. Its current package and executable must agree, the
prefix must stay root-owned and read-only to the service, and all links stay in
the prefix; the initial hashes are provenance, not a lock that disables updates.
The stable launcher and other fixed programs retain exact verification. Future
Pi compatibility and actual native network updates remain acceptance gates.
`awf update` replaces AWF/Node/Magpie, preserves the current Pi tree and original
Pi evidence, and never silently restores Pi 1.0.2 over an upstream update.

## Manifest and verified preparation

The independent manifest is bounded UTF-8 JSON, at most 64 KiB. It rejects
unknown fields, duplicate keys at every depth and multiple JSON values. Identity
fields are schema 1, channel `linux-host-v1`, installer protocol 1, Host protocol
`v1`, extension protocol 1, Pi RPC version `1.0.2`, Linux amd64/glibc, an exact
`v1.MINOR.PATCH[-rc.N]` release and a full 40-character source commit. Prereleases
need explicit `--allow-prerelease`. Select a new Linux release tag; do not repoint
or replace the released Windows RC9 tag/assets.

Exactly five default components are required: `node`, `pi`, `awf-host`,
`awf-extension`, `magpie`. Each specifies exact version, artifact name, canonical
versioned official URL, compressed byte count, SHA256 and format. Artifacts are
bounded to 256 MiB each and 512 MiB total. Go verifies the public AWF tag's commit
through GitHub's API. Only GitHub release redirects to official asset CDNs are
allowed; unavailable official sources fail without an alternate guessed source.
The manifest is trusted publisher HTTPS metadata, not a signed release.

Host archives contain only the executable and strict `build.json` identity;
extension archives contain only `awf.ts` and strict `extension.json` identity.
Linux packaging must set the existing Host `BuildVersion` and `BuildSourceCommit`
linker variables to match the manifest and archived metadata. Pi metadata must
be a coherent official pair from the fixed installer API or official GitHub
release copies; repository main is never an installer fallback.

This native candidate intentionally accepts only the reproduced Node/Pi inputs:

| Official input | Bytes | SHA256 |
| --- | ---: | --- |
| Node `node-v22.19.0-linux-x64.tar.gz` | 54907188 | `d36e56998220085782c0ca965f9d51b7726335aed2f5fc7321c6c0ad233aa96d` |
| Pi installer `package.json` | 317 | `491cb1ec4fba98d9547b037cd9dea48ae0bba651a0a80d67dd1660705b60f1c5` |
| Pi installer `package-lock.json` | 63566 | `b8e9e6a191bcf1e6e3ff8dafe5c0c9042b48e0087cd6d6816dcaa051222ba680` |
| Magpie reproduced release artifact | 31375522 | `f79df4bd90aa81371eff4386740b1fdcb557cf272d395494948c15b9f4f8ff10` |

The official Pi lock has 147 entries; 122 Linux/x64 packages are installed and
integrity-checked, and 25 other-platform optional entries are skipped. Eight
fixed Pi packages need supplemental SHA512 metadata; their exact versioned
registry response SHA256 values are checked into `native_prepare_linux.go`.
A changed registry response fails closed. The lock is not rewritten. Three
locked packages declare lifecycle scripts; all npm phases use `--ignore-scripts`.
No scripts are enabled or substituted. Installer npm processes have a 192 MiB
V8 old-space cap; this is a heap limit, not an RSS limit or a measured runtime
minimum. Node identity is checked by streaming SHA256, avoiding a 121 MiB
whole-executable allocation. Ordinary Pi and its upstream updater are unchanged.

Preparation extracts complete audited Node/npm, fetches official npm packages
into a fresh isolated cache with scripts disabled and no inherited npm auth or
configuration, then performs verified **offline** `npm ci`. It validates cached
SHA512 bodies, exact installed bytes, package metadata, closure topology, modes
and declared command links. The runtime budget is 32768 entries and 512 MiB
expanded bytes. Two locked duplicate-file conventions have narrow checks for
identical bytes and exact package versions; general duplicates and path aliases
are refused. Node gzip removes the custom XZ path.

Progress reports real artifact bytes with percentage only when the server
supplies a length. npm dependency progress reports observed completed cache
bytes with no invented denominator. Extraction, closure checks, executable
identity, system placement, account creation, unit reload, maintenance, service
stop/start, health and completion have explicit stage events. Cancellation stops
the npm process group and never publishes a selected incomplete fixture tree.

## Native completion, stop and update

A private operation lock serializes native lifecycle commands. Fresh installation
copies only a revalidated complete inventory into an `/opt` scratch directory,
creates exact links after regular files, synchronizes and renames the fixed
program roots, creates the account/state and units, reloads systemd, and writes
`/etc/awf/install.json` last. A failure can leave partial system paths for explicit
inspection, with no completion claim or automatic adoption on retry.

The native receipt says `programsInstalled: true` only after those operations
finish. `nativeAcceptance: false` remains explicit. Fixture schema-2 evidence
inside it is preparation provenance, not an assertion that the operating system
was installed or accepted by a test. Init markers describe completed writes,
not acceptance or provider readiness.

Stop/update use the existing opt-in durable Host maintenance API at
`/v1/maintenance`: begin freezes admissions, seal requires settled native work,
and end requires the original owner plus compare-and-swap revision. The local
owner/target evidence is file- and parent-directory-synced before seal. A busy
seal leaves draining state and refuses systemctl stop; a later idle retry uses
the same owner. The returned sealed lease is atomically replaced and synced before
any systemctl stop. Both units must be inactive with MainPID zero and empty
descendant cgroup.procs. If Host stopped before the other unit failed, retry uses
that persisted sealed owner/target plus verified inactive Host/empty cgroup;
an offline draining lease cannot authorize shutdown. Each trusted unit is stopped
and checked independently. Failures retain the lease and prohibit replacement.

AWF update prepares and checks the new executable before maintenance. Under the
seal and verified stop it replaces Node/AWF/Magpie roots, retaining per-root
`.before-<manifest-digest>` backups and a private pending marker. This is **not an
atomic transaction across all program roots**. Interrupted replacement fails
with services sealed/stopped and requires inspection; it does not auto-repair,
roll back unknown state, or erase backups. It writes the new receipt, verifies
startup/build/loopback, releases only the original lease and then removes the
pending marker. Pi is not copied by this replacement.

## Reproduced local checks and remaining acceptance

Go 1.25 or later is required for the Linux native adapter's confined `os.Root`
link APIs. The module requirement is aligned with those APIs; Windows release
behavior and released artifacts are not changed. Local automated checks are:

```sh
umask 022
go test ./...
go test -race ./...
go vet ./...
GOOS=windows GOARCH=amd64 go build ./cmd/awf
GOOS=windows GOARCH=amd64 go build ./cmd/awf-node
python3 scripts/test_linux_bootstrap.py
python3 scripts/test_private_native_kit.py
sh -n scripts/install-linux.sh
```

Opt-in official byte/runtime fixtures require separately prepared private local
directories; default tests skip them explicitly:

```sh
AWF_PUBLIC_AUDIT_FIXTURE_DIR=/tmp/approved-audit AWF_PI_INSTALLED_FIXTURE_DIR=/tmp/approved-pi go test ./internal/hostinstall -run 'TestOfficialPreparationEvidence|TestRuntimeOfficialOfflineFixture|TestPiInstalledOfflineFixture|TestNativeOfficialInventoryFixture' -v
```

This cloud task reproduced actual Node22/npm10/Pi1.0.2 offline version/import
checks, AWF extension tool registration, launcher PID/stdio, read-only `get_state`
and same-prefix upstream update selection. A cooperative JavaScript network guard
observed zero network attempts; it is not kernel isolation. No model call or
actual updater ran. Adapter tests substitute account/systemctl/HTTP commands and
use synthetic program bytes in confined directories; they prove refusal and
state transitions, not root ownership, OS account creation or native services.
They run as a non-root fixture user. The optional native inventory fixture copies
and rechecks the actual full official program inventory beneath a temporary root,
with synthetic Host bytes and substituted machine commands; it also cannot prove
native installation or operating-system service ownership.

The next Ubuntu24.04 preview must verify its public bootstrap, cross-version AWF
update, actual official same-prefix Pi update and read-only production-extension
RPC compatibility, lifecycle and owned cleanup in the separately approved
disposable GitHub environment. Ubuntu22.04/Debian12, provider/model-backed work
and reboot/autostart are not claimed as accepted by that slice. Low-memory and
CloudCone acceptance are cancelled and are not release gates. Local fixtures
grant no production machine, credential, firewall or cloud-purchase authority.

## Native acceptance routes

The first existing-machine slice is defined in [native acceptance plan](linux-native-acceptance.md).
It uses a precompiled private offline kit, no source build, no credential import,
no model calls, and serial installation/process checks. It preserves unrelated
services and the existing system Node. That slice still requires one explicit
machine/action approval and does not establish public bootstrap acceptance.

Public bootstrap acceptance needs separately approved Linux release assets/tag
matching the candidate and canonical manifest URLs. The default channel is
unpublished; supplying only a local Host archive cannot bypass Go's public tag
and remaining asset checks. Private test input is a distinct developer-only
provenance route, never a released installer flag or a claimed public release.

Complete acceptance on the three target distributions must also cover actual
account/root isolation, read-only systemd settings mounts and provider writes,
loopback/socket ownership, both recursive process groups exiting, boot/restart,
genuine same-prefix `pi update`, AWF update retaining that Pi, notices, extension
catalog and separately approved model-backed E2E. Failure injection, arbitrary
cgroup children, reboot and interrupted replacement belong on separately
approved disposable environments or explicit maintenance windows. They are
excluded from the first existing-machine slice. No cloud purchase is implied.
