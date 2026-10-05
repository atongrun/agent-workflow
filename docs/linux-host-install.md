# Linux Host fresh-machine installer

This is a complete **local source candidate**, with a thin bootstrap and a Go
native adapter. No Linux release assets or channel have been published. It has
not installed a real machine or activated real services. Ubuntu acceptance and
publication require separately approved environments and actions.

The target is Ubuntu 22.04/24.04, glibc, systemd with unified cgroup v2, amd64,
with root administering a fresh machine. Existing programs, AWF accounts, fixed
roots or unit overrides require inspection; installation never adopts, repairs
or migrates them. Windows lifecycle dispatch, release artifacts and channels are
unchanged. There is no Dashboard source in this repository or installer.

Go owns machine and process lifecycle. Official Pi owns its session, context,
tools and self-update. The existing AWF Pi extension owns business behavior.
There is one official Pi package installation, at `/opt/pi-cli`.

## Commands and publication boundary

The candidate bootstrap is `scripts/install-linux.sh`. After release review and
publication it will acquire a verified Go executable from an independent Linux
manifest and invoke the native installer. Its default channel path is currently
unpublished; it must fail rather than substitute the Windows channel or guess
release hashes. A reviewed local manifest and Host archive can be supplied:

```sh
sudo sh scripts/install-linux.sh --manifest /path/to/reviewed-linux-manifest.json --archive /path/to/verified-host.tar.gz --allow-prerelease
sudo awf init
sudo awf start
sudo awf stop
sudo awf start
sudo awf update --manifest /path/to/reviewed-next-linux-manifest.json --allow-prerelease
```

These are future native acceptance commands, not evidence they ran here. Install
and init request confirmation; `--yes` permits unattended execution. The
bootstrap invokes install with `--yes`. Install prepares programs, the account
and units; init creates service state and local tokens. Neither starts services.
`start --enable` separately enables boot autostart after health verification.
There is no public system-root override or environment override for native writes.

The bootstrap needs Python 3 already on Ubuntu. It checks root, platform,
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
| Commands | `/usr/local/bin/{awf,node,npm,npx,pi,magpie}` |
| Root-owned configuration and install evidence | `/etc/awf` |
| Dedicated service state and cache | `/var/lib/awf`, `/var/cache/awf` |
| Service Pi agent directory | `/var/lib/awf/pi-agent` |
| Service Magpie config | `/var/lib/awf/magpie-config/magpie/settings.json` |
| Fixed systemd units | `awf-host.service`, `awf-magpie.service` |

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
`ProtectHome`, `ProtectSystem=strict`, and only service state/cache write access.
Native start requires the exact unit files, root fragment paths, no drop-ins,
`system.slice` and the dedicated account. It also requires active MainPIDs in the
fixed control groups, exact running Host identity and actual IPv4 loopback
listeners on 7070 and 3425. These checks are implemented; real systemd behavior
and socket ownership still require native acceptance.

Magpie is configured with explicit `lan: false`, `noAutoUpdate: true` and
`noStats: true`, independent HOME/XDG roots and `MAGPIE_ADDR=127.0.0.1:3425`.
The inspected upstream source gives LAN mode precedence over that environment
address, so native start reads and checks the service settings before activation,
refuses portable markers beside the binary, and checks kernel listeners afterward.
A failed startup or health check stops both units and verifies process exit;
unknown cleanup remains a failure. No public listen or firewall change is needed.
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
No scripts are enabled or substituted.

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
owner/target evidence is persisted before seal. A busy seal leaves draining state
and refuses systemctl stop; a later idle retry uses the same owner. After seal,
both units must be inactive with MainPID zero and empty descendant cgroup.procs.
Shutdown failures retain the lease and do not permit program replacement.

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

Before publishing, use separately approved fresh Ubuntu 22.04 and 24.04 amd64
systemd machines to verify the real bootstrap, permissions/account separation,
notice completeness, install/init/start/stop, both entire process groups exiting,
exact actual Magpie settings and loopback sockets, genuine `pi update` on the
same prefix, extension/model catalog and an explicitly approved model-backed E2E.
Review failure/interruption and reboot/autostart behavior there. The current
Debian 13/PID1-tail executor does not meet that acceptance matrix. No production
machine, account mutation, systemctl action, listening service, firewall,
credentials or cloud purchase is authorized by these local checks.
