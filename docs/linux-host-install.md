# Linux Host installation: local preparation slices

The first slice introduced an independent `linux-host-v1` manifest contract, read-only
planning/diagnosis and an internal download/hash/staging core. That slice did not publish
a channel or installer, install programs, extract archives, execute packages,
initialize credentials, create service accounts, write systemd units, open ports,
start services, select models or change Host Defaults. The existing Windows
channel, release assets and native CLI contract are unchanged.

The initial target matrix is Ubuntu 22.04/24.04, glibc, systemd, Linux amd64.
`arm64` is reserved in the manifest schema and is rejected by staging until native
acceptance exists. Other Linux distributions, musl, macOS and Windows are outside
this Host installer matrix. Metadata observations do not prove native acceptance.

## Read-only commands

With a locally reviewed manifest file:

```text
awf host-install plan --manifest FILE [--json]
awf host-install doctor --manifest FILE [--json]
```

`plan` reads the manifest, OS release metadata, glibc loader presence and systemd
presence. `doctor` also checks proposed destination metadata, command lookup and
kernel TCP listener snapshots for 7070/3425. It never executes discovered commands,
binds/reserves ports, connects to services or makes network requests. Existing
program/config/state paths or commands require explicit review rather than
adoption or replacement. A port reported `free_observed` is only a snapshot.

`readyToStage` reports static checks only. It is neither installation permission
nor proof of a working runtime. A valid report can have `readyToStage: false` and
exit successfully; consumers must inspect the report. There are no public
`host-install install`, `stage`, `init`, `start` or `update` commands in this slice.
No operational one-line installer URL is available.

## Manifest and release asset contract

The Linux manifest is separate from `distribution/go-v1.json`; do not extend or
reinterpret that Windows channel. A future reviewed publication must supply real
asset bytes, lengths and SHA-256 digests. Fixtures are synthetic and are not a
release manifest or a promise that their example AWF tag/assets exist.

The bounded UTF-8 JSON manifest has these fields:

| Field | Contract |
| --- | --- |
| `schema`, `installerProtocol`, `extensionProtocol` | Exactly `1` |
| `channel` | Exactly `linux-host-v1` |
| `version` | Exact Go v1 tag: `v1.MINOR.PATCH` or `v1.MINOR.PATCH-rc.N` |
| `sourceCommit` | Exact 40-character lowercase commit SHA |
| `hostProtocol` | Exactly `v1` |
| `piRPCVersion` | Exactly `1.0.2` in this initial compatibility contract |
| `os`, `libc` | Exactly `linux`, `glibc` |
| `arch` | `amd64`; `arm64` reserved |
| `components` | Exactly the five components below, each once |

Each component carries `id`, exact `version`, and `artifacts`. Each artifact
carries `name`, exact official `url`, lowercase `sha256`, positive `bytes` and
`format`. Unknown fields, duplicate keys/components/artifacts, trailing JSON,
missing defaults, arbitrary URLs, query credentials, wrong formats and excessive
sizes fail closed. The manifest limit is 64 KiB, each artifact 256 MiB, the
aggregate bundle 512 MiB; Pi JSON format verification additionally limits metadata
to 4 MiB. Node's minimum engine requirement is checked, but satisfying it does not
establish a tested Node version. Publication must pin a natively validated version.

| Component | Version and exact source shape | Format |
| --- | --- | --- |
| `node` | `vVERSION`, minimum 22.19.0; `https://nodejs.org/dist/vVERSION/node-vVERSION-linux-x64.tar.gz` (`arm64` suffix reserved) | `tar.gz` |
| `pi` | `1.0.2`; `https://pi.dev/api/installer/releases/1.0.2/package.json` and `package-lock.json` | `json` |
| `awf-host` | Manifest release; `https://github.com/atongrun/agent-workflow/releases/download/TAG/awf_TAG_linux_amd64.tar.gz` | `tar.gz` |
| `awf-extension` | Same release; `https://github.com/atongrun/agent-workflow/releases/download/TAG/awf-extension_TAG.tar.gz` | `tar.gz` |
| `magpie` | Exact numeric version; `https://github.com/yetone/magpie-releases/releases/download/vVERSION/magpie-cli-linux-amd64` | `elf` |

A future Host archive needs the matching Linux Go Host binary and identity
metadata. The extension archive needs the matching `extensions/awf.ts` and its
runtime dependencies, including TypeBox: global npm installation does not establish
extension module resolution. Archive topology, extraction safety, dependency
closure and native binary/version acceptance are deliberately pending. Third-party
license/notice files must accompany future packaged components; this slice does
not invent a repository license or change licensing.

## Internal staging and trust boundary

`internal/hostinstall.Stage` is internal Go code exercised through HTTP fixtures;
the CLI does not call it. Its caller must supply an explicitly reviewed manifest,
an existing absolute private real directory and a non-nil progress observer.
Manifest hashes authenticate bytes against that reviewed input, not an arbitrary
manifest's publisher. Future bootstrap must establish the published manifest's
trust before invoking this core.

Staging verifies the AWF release tag resolves to `sourceCommit` using the official
GitHub API, including bounded annotated-tag resolution. Downloads use exact
versioned sources; only GitHub release redirects to its official asset CDNs are
accepted. Signed CDN URLs and transport bodies/errors are not displayed.
Downloaded length and SHA-256 must match the manifest. Magpie additionally gets
ELF class, byte order, type and architecture checks; Pi files must be JSON objects.
Archives remain opaque hashed bytes, and Pi metadata is not an installed or
verified npm dependency tree. No artifact is executed.

A unique private temporary directory is renamed to `bundle-<manifest SHA256>`
only after verification and a final cancellation check. Failures remove this
caller's temporary files. Concurrent callers may reuse a verified winning bundle.
Retries rehash all artifacts and recheck format and receipt rather than trusting
the directory name. Invalid existing bundles require explicit inspection, not
repair or overwrite. The receipt records `artifactsVerified: true` and
`installed: false`; it is not a runtime installation receipt. This is a same-user
private staging boundary, not protection against a malicious process that can
modify its parent/ancestors concurrently. No crash-durability or activation
transaction is claimed.

## Progress contract

The core emits actual source/download/verify/stage events and a component/stage
failure on operational errors. An observer is mandatory, including for pipes;
typed nil observers and a renderer without an output destination are refused.
Known response totals show actual received bytes and percentage (with a bar for
TTY output). Unknown totals show bytes and `total unknown`, never fabricated
percentages. TTY progress overwrites a line; non-TTY output uses stable lines with
no ANSI or carriage returns. Broken display output disables display without
changing download verification or commit decisions.

Future extraction/install/configuration/health stages must show explicit start
and completion only when those operations actually happen. This slice emits none
of those completions. Plan text labels operations as planned, not performed.

## Later installation and bootstrap slices

The eventual shell bootstrap should only detect supported architecture, obtain
and verify the reviewed installer/manifest, and hand control to Go with explicit
progress output. It must not contain a second installer or silently consume an
unpublished URL. Publication/deployment require separate explicit approval.

Proposed fixed program roots are `/opt/awf`, `/opt/pi-cli`, `/opt/magpie`; proposed
Host configuration/state are `/etc/awf/host.json` and `/var/lib/awf`. Ordinary
per-user Pi configuration remains `~/.pi/agent`; the service's independent
`PI_CODING_AGENT_DIR` is `/var/lib/awf/pi-agent`. Program installation is shared,
not a separate installation in each user's home. Existing installations and
credentials must be inspected, never silently overwritten or copied.

Pi's official managed installer/update layout and `pi update` should own Pi
program updates; do not build an AWF-specific Pi updater. Authentication/account
initialization is explicit. Magpie's headless CLI can be supplied as program bits
without interactive provider initialization; actual account/provider setup and
model catalog selection remain an explicit initialization step. The proposed
Magpie service is loopback-only (`magpie serve`, 127.0.0.1:3425), with no guessed
model default. The third slice below records source-verified configuration behavior.

Service reload/upgrades need a Host maintenance gate that freezes new dispatch,
waits for the supported idle state and performs an explicit compatible reload.
An idle snapshot followed by `systemctl restart` is not a safe upgrade gate. Full
service ownership, init, loopback health/build identity, safe archive extraction,
Pi npm installation and native Ubuntu acceptance remain pending. The third slice
below implements durable admission fencing; it grants no native activation.

Official source references:

- [Pi package and Node engine](https://github.com/earendil-works/pi/blob/v1.0.2/packages/coding-agent/package.json), [configuration](https://github.com/earendil-works/pi/blob/v1.0.2/packages/coding-agent/docs/configuration.md), [CLI](https://github.com/earendil-works/pi/blob/v1.0.2/packages/coding-agent/docs/cli.md), [managed update implementation](https://github.com/earendil-works/pi/blob/v1.0.2/packages/coding-agent/src/package-manager-cli.ts).
- [Magpie headless installer](https://github.com/yetone/magpie/blob/main/site/public/install.sh), [service documentation](https://github.com/yetone/magpie/blob/main/README.md), [MIT license](https://github.com/yetone/magpie/blob/main/LICENSE), [binary release repository](https://github.com/yetone/magpie-releases).

## Second local slice: sandbox fixture apply

The next internal entrypoint is `ApplyFixture(ctx, manifest, stagedBundle,
sandboxRoot, observer)`. It accepts only an existing private real directory
beneath literal `/tmp`, with no symlink ancestors, on Linux amd64. There is still
no public apply/install CLI, no real `/opt`, `/etc` or `/var` write, no process
execution in the installer, no account or service mutation and no network request
from apply. Tests invoke only the compiled test helper to simulate process death;
the payloads themselves are never run. The first-slice commit remains independent.

Apply revalidates the manifest and staged artifact hashes, then creates a fresh
private extraction tree. Only these fixed program files can be selected:

| Component | Sandbox generation files | Availability |
| --- | --- | --- |
| Node | `opt/node/bin/node`, required `opt/node/LICENSE`, optional README/CHANGELOG | Files only; no native execution acceptance |
| Host | `opt/awf/awf`, strict `opt/awf/build.json` | Files only; no config or health readiness |
| Extension | `opt/awf/extensions/awf.ts`, strict `extension.json` | Files prepared, runtime unavailable: TypeBox/Pi resolution not established |
| Magpie | `opt/magpie/magpie` from pinned raw official asset | Files only; no provider account, config or service readiness |
| Pi | No program files copied | Unavailable: package/lock metadata is not a verified installed dependency tree |

Node's archive must use its exact `node-VERSION-linux-x64/` prefix. Other regular
files under the official `bin/include/lib/share` namespaces are scanned and
bounded but discarded. Only the exact official npm/npx/corepack symlink names and
relative targets are recognized and discarded; no link is created. This slice
supplies the Node binary, not usable npm/npx/corepack commands. Host/extension
archives have a strict root-level whitelist, no extra files or directories.
Required Host `build.json` fields are exactly `schema: 1`, release `version`,
`sourceCommit`, `os`, `arch`, `hostProtocol`. Extension `extension.json` fields
are exactly `schema: 1`, `version`, `sourceCommit`, `extensionProtocol`,
`piRPCVersion`, all matching the manifest. Unknown/duplicate identity JSON fields
are rejected. Structural build identity and ELF checks are not execution proof.

Canonical paths (max 512 bytes), unique entries, regular files/directories,
sanitized 0644/0755 output modes and explicit file whitelists are required.
Absolute paths, traversal, backslashes, links outside the exact discarded Node
exceptions, hardlinks, devices/FIFOs, set-ID bits, PAX/sparse extensions, excessive
entries and hidden trailing nonzero tar payloads fail closed. Limits cover 8192
visible archive entries in aggregate, 256 MiB per archive file, 512 MiB expanded
stream bytes in aggregate (including discarded payloads and tar overhead), and
compressed manifest bounds. Selected executable files get ELF target validation.
Output is written through Go's directory-root API into a fresh private tree.

Third-slice source audit replaces Node XZ with the official gzip asset and the
standard-library bounded gzip/tar reader. The external XZ dependency, custom XZ
preflight and notice are removed; earlier commits remain independent. The actual
Node 22.19.0 gzip has 5780 entries, so the aggregate entry ceiling is 8192. Its
186097638 regular payload bytes fit the existing 512 MiB expanded bound. No
external decompressor, npm or downloaded program is executed by fixture apply.

### Activation, receipts and recovery

A nonblocking kernel flock on `.apply.lock` serializes applies in one sandbox.
The lock is released by process exit; no stale PID file is deleted to gain entry.
After extraction and file/directory synchronization, a verified tree is prepared
at `releases/layout-1-<manifest SHA256>`. `install.json` binds layout schema, fixture
mode, manifest/source/platform, every selected file's path/size/mode/SHA-256 and
component availability. It records `filesPrepared: true`,
`installationComplete: false`, and `runtimeReady: false` for every component.
The receipt is preparation evidence; selection is a separate step.

Only after the complete tree is verified does an atomic synchronized
`current.json` replacement select that local generation and receipt SHA-256.
That proves fixture file activation only, not an installed running product.
Cancellation before selection leaves current unchanged. A crash after generation
preparation is recovered by re-extracting pinned assets, comparing the exact
expected receipt/inventory/hashes to the prepared generation and selecting it.
Recovery never trusts an existing receipt's self-reported hashes. Missing, extra,
linked or modified files and malformed selectors require explicit inspection.
Different currently selected manifests are refused: upgrade/rollback is outside
this slice. Interrupted temporary trees are never adopted or followed; they may
remain for explicit inspection while retries create a new tree.

The sandbox is a trusted same-user fixture boundary, not an adversarial multiuser
installation root. It does not handle malicious concurrent ancestor replacement,
bind mounts or unauthorized processes sharing write access. This temporary-root
entrypoint must not become a production root override. Native apply requires its
own ownership, mount/ACL, service lifecycle and maintenance authorization design.

Progress spans actual `verify`, `extract`, and `activate` start/completion/failure.
Extraction reports observed stream bytes without an invented percentage. Pi
emits `extract: unavailable`, never an extraction/install completion. Failed
verification/extraction cannot emit activation completion. Unknown download
totals retain the first-slice bytes-only contract; pipes remain free of ANSI.

## Third local slice: metadata, initialization proposal and maintenance

`plan --json` now includes an `initialization` proposal: fixed loopback Host config,
literal systemd unit text, ordered activation requirements and unresolved items.
`BuildInitializationPlan` performs validation/rendering only. It writes no files
and never reports `readyToInstall: true`. The proposed receipt conditions depend
on a future native adapter; fixture receipts cannot satisfy them. Proposed paths
are `/opt/node`, `/opt/pi-cli`, `/opt/awf`, `/opt/magpie`, `/etc/awf`,
`/var/lib/awf` and `/var/cache/awf`. Service account `awf` has independent HOME and
Pi agent state; ordinary `~/.pi/agent` is untouched. Projects/nodes/models are
empty until explicitly initialized. Only token environment *names* are rendered.

### Verified public sources; uninstalled dependency closure

Actual fixed public bytes were downloaded to a private `/tmp` directory and
hash-checked without execution:

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| Node 22.19.0 linux-x64 gzip | 54907188 | `d36e56998220085782c0ca965f9d51b7726335aed2f5fc7321c6c0ad233aa96d` |
| Magpie v0.1.855 linux-amd64 | 31375522 | `f79df4bd90aa81371eff4386740b1fdcb557cf272d395494948c15b9f4f8ff10` |
| Pi 1.0.2 install package.json | 317 | `491cb1ec4fba98d9547b037cd9dea48ae0bba651a0a80d67dd1660705b60f1c5` |
| Pi 1.0.2 install package-lock.json | 63566 | `b8e9e6a191bcf1e6e3ff8dafe5c0c9042b48e0087cd6d6816dcaa051222ba680` |

Node matches its [official SHASUMS256](https://nodejs.org/dist/v22.19.0/SHASUMS256.txt).
Magpie matches its [release asset digest](https://github.com/yetone/magpie-releases/releases/tag/v0.1.855).
Pi's [official release metadata assets](https://github.com/earendil-works/pi/releases/tag/v1.0.2)
match byte-for-byte the fixed-tag `packages/coding-agent/install-lock` files.
The manifest permits either the original pi.dev installer pair or this exact
GitHub release pair, with local filenames `package.json` and `package-lock.json`.
It rejects mixed sources; it never substitutes repository main. Access to pi.dev
was unavailable in this execution environment; no install script was downloaded
or run and no script layout is inferred.

`InspectPiMetadata` validates bounded lock-v3 JSON, exact installer root, pinned
registry tarball URLs and SHA-512 integrity. The actual lock has 147 package
entries plus its root; 8 internal 1.0.2 entries lack integrity. Separate reviewed
version-specific public `registry.npmjs.org` metadata supplies those 8 SHA-512
pins, with independent metadata SHA-256 verification and exact name/version/URL
matching. The original official lock is not edited. The report calls this a
complete *locked catalog*, never an installed dependency closure. It lists
lifecycle-script packages (`@google/genai`, `esbuild`, `protobufjs` in this lock);
installation must use `--ignore-scripts`. It does not implement a semver resolver
or custom npm updater, verify downloaded npm tarballs, or infer native optional
modules work.

The fixed official managed update source verifies `managed-install.json`
(`kind: pi-managed-install`, `schemaVersion: 1`, `layout: releases-v1`),
`releases/VERSION/node_modules/.bin/pi`, atomic `current-version`, and
`PI_MANAGED_INSTALL_ROOT`. At the third-slice boundary, the proposed stable `/opt/pi-cli/bin/pi` launcher was
still unverified because the official initial install script could not be read.
The standalone Bun release includes additional assets; extracting only its Pi
binary is not a verified substitute. The current fixture selects Node **only**,
so it cannot yet run npm. Extension TypeBox/Pi resolution is also pending.

Magpie [source at inspected commit](https://github.com/yetone/magpie/tree/25826ea19fe0cb4416ffe6a80b2d5916c68e4e14)
confirms XDG_CONFIG_HOME/XDG_CACHE_HOME and MAGPIE_ADDR. This source inspection
is separate from release-binary acceptance. Its `settings.LAN` overrides the
address to `0.0.0.0`; the environment variable alone cannot guarantee loopback.
Initialization must explicitly enforce independent `LAN=false` configuration,
reject portable-data markers beside the shared binary, and verify actual kernel
listeners before any native activation receipt. Never copy a user's Magpie
credential/config directory to bootstrap a service.

### Durable Host admission gate

Opt-in `enableMaintenance: true` adds authenticated `GET /v1/maintenance` and
`POST /v1/maintenance/{begin,seal,end}`. Existing configs omit the flag and keep
their default routes; any persisted lease keeps its recovery API even when the
flag is disabled. These routes do not write installation paths or call systemd.

All actions require `requestId` and explicit `expectedRevision`. Begin additionally
requires exact `targetManifestSHA256`; its requestId owns the lease. Seal/end
require `ownerRequestId` identifying that original owner. Every transition increments
a durable revision and emits an audit event. Exact retries return saved receipts
without replaying effects or releasing a newer lease. There is no TTL or automatic
unseal on restart. Unknown persisted phases/revisions fail startup closed.

Begin atomically freezes new reservations and captures only already-busy tasks
for a narrow drain allowlist: existing native abort/UI replies, cancellation,
question replies, execution result/review settlement and known extension callbacks.
Idle tasks cannot acquire new drain authority. New tasks, messages, generation,
rework, model changes, settings, resume and future unknown operations are blocked.
Previously accepted work may finish; historical exact receipts remain readable.

Seal checks persisted execution status, pending questions/permissions, native
busy/pending/streaming/queued state, accrued active interval, uncertain or pending
requests, process startup and Host shutdown. Unknown outcomes block it. Startup
is serialized by the lifecycle lock. Actual mutating Node requests and Pi sends
share an effect read lease; seal takes its write lease, preventing queued budget
stops/cancel/UI/control sends from crossing the seal. Sealed durable and transient
state writes fail closed, including normalization and delayed callbacks. Explicit
owner/revision release is the only supported exit. The idle status is an
observation; seal is the atomic admission transition.

`nativeActivationReady` always remains false. Read-only native RPCs are not a
native process shutdown barrier. A future adapter must retain the sealed lease,
stop **both** systemd control groups and verify exit before replacing programs,
then verify compatible running identity/health before explicit release. The
maintenance target digest is binding evidence, not permission or implemented
upgrade/rollback. Default health and Windows runtime contracts remain unchanged.

### Minimal native Ubuntu acceptance scope still required

Current usable pieces are read-only manifest/initialization proposals, bounded
verified staging, safe `/tmp` fixture apply/recovery, metadata catalog inspection
and the opt-in durable admission API. They are not a complete installer. No
install/init/start/update mutator or one-line bootstrap is published.

The next approved test environment needs a disposable Ubuntu 22.04 or 24.04
amd64 VM with systemd and explicit root permission for fixed program roots,
`awf` user/group, `/etc/awf`, state/cache ownership and unit installation. Root
must inspect existing paths, create immutable program generations, private state
and config, and establish a reviewed shared-Pi update ownership policy. Project
write permissions need explicit configuration: the proposed strict unit sandbox
currently grants only state/cache writes. No account or unit action was run here.

Before native work, the precise dependency-install experiment is:

1. In a private temporary directory in that test environment, verify the official
   Node gzip above and retain its complete npm runtime topology. Verify the two
   fixed Pi release metadata files and the 8 supplementary public npm pins.
2. With those exact files as package.json/package-lock.json, use the pinned Node
   and npm to run the **official** arguments, with no lifecycle scripts:
   `npm ci --ignore-scripts --min-release-age=0 --omit=dev --include=optional --no-fund --no-audit --loglevel=error --progress=false`.
   Network is limited to the official npm registry. npm downloads/extracts package
   tarballs; its acceptance of all 8 supplementary pins must be verified separately
   because the official lock itself omits their integrity. Do not claim this step
   provides strict integrity until the downloaded tarball bytes are checked.
3. Verify the installed `.bin/pi --version` is exactly 1.0.2 with no credentials,
   provider initialization or model calls; inspect platform optional/native
   dependencies, TypeBox resolution and notices. Obtain/read the official initial
   managed installer source before implementing its stable launcher. Do not run an
   arbitrary fallback install script or invent the root layout.
4. Only later, with explicit native account/credential/service authorization,
   initialize distinct service credentials, start Magpie with LAN disabled,
   observe real loopback catalog and choose models explicitly; validate systemd
   ownership, groups, shutdown and Host/Pi/Magpie identity. Product E2E/model calls
   and any publication/deployment require their separately approved scope.

Bootstrap stays thin: reviewed Go installer acquisition/verification and handoff;
all installation decisions, progress and transactions belong in the Go core.

## Fourth local slice: real dependency development acceptance

The explicitly authorized dependency experiment ran only beneath
`/tmp/awf-pi-dependency-acceptance`. This machine is **Debian 13**, PID 1 `tail`,
with no running systemd; it cannot satisfy the Ubuntu 22.04/24.04 native matrix.
No system roots, service account, global npm installation, systemd service,
provider credentials, production endpoint or model call were used.

The complete hash-verified official Node 22.19.0 archive was extracted privately,
including its npm topology and three exact internal command links. Node reports
v22.19.0 and its bundled npm 10.9.3. Official Pi package/lock metadata was used
unchanged with the exact `npm ci --ignore-scripts` arguments above. Empty private
npm configs, a private cache, the existing environment network proxy and existing
system CA bundle were used; TLS verification remained enabled. Initial direct
DNS and proxy CA failures were corrected without disabling TLS or changing to a
mirror. The successful operation installed **122 packages**; **25 optional** lock
entries were skipped because their OS/CPU excludes Linux x64.

Every installed lock entry was then matched to its exact installed version and
URL-bound npm cache entry; actual cached tarball bytes were SHA-512 checked
against the official lock or the 8 previously reviewed supplementary registry
pins. The original lock SHA-256 remains unchanged. This proves the selected
platform dependency bytes for this experiment, not the unselected platform
packages or a general supported-runtime matrix. No postinstall scripts ran or
were needed for the tested entry/import/extension paths. No general permission
to enable such scripts is inferred.

Both `dist/bundle/cli.js --version` and npm `.bin/pi --version` report 1.0.2.
Twelve dependency entry imports succeeded, including Pi SDK/core/AI/TUI, TypeBox,
jiti, esbuild, protobufjs, Google GenAI and photon-node. Importing a library does
not test every native operation it exports. Official Pi extension loading resolves
the independent AWF extension outside the Pi program tree, including TypeBox;
architect and reviewer tool registrations match the existing AWF source. No
separate global TypeBox installation or AWF extension dependency bundle was
needed for these tested official Pi loading paths.

A bounded ephemeral **stdio** bundled-CLI launch, with `--no-session`, disabled
builtin tools and discovery, loaded the actual AWF extension. Only `get_state`
was sent; a test-only extension used the official `getAllTools()` API to observe
registration. No prompt, tool execution, model catalog choice or model request
was sent. `get_all_tools` is not an RPC command; it is not used by the committed
test. Closing stdin provided an orderly exit. Pi automatically creates `{}`
auth/model store placeholders even in this mode; their emptiness was checked and
the isolated test directory was removed. No credentials were issued or stored.

The checked-in opt-in `TestPiInstalledOfflineFixture` executes only when
`AWF_PI_INSTALLED_FIXTURE_DIR` explicitly names the verified private `/tmp` fixture.
It pins the extracted official Node executable and official lock hashes, uses
fresh private agent/XDG paths, checks bundled version and AWF registration,
asserts empty stores and normal EOF shutdown, then cleans its temporary state.
It does not install dependencies or run downloaded code in default test runs.
A JavaScript test guard denies fetch/HTTP(S)/TLS/TCP connection/listen APIs,
including direct Socket connects, records every denial and a final exit counter.
Zero guarded attempts are required throughout the test. This guard is for
cooperative verified software, **not an OS or adversarial native-code sandbox**.
The fixed commands never send prompts or execute tools independently of it.

The complete Pi npm tree was archived and relocated under the source-verified
`releases/1.0.2` managed data layout. All **16401 inventory entries**, regular-file
hashes/modes and **9 internal links** were preserved. The relocated npm launcher
again reports 1.0.2. This is a private packaging/relocation test, not a published
Pi release or implemented activator. The official initial install script remains
unavailable (pi.dev proxy returns 403); `/opt/pi-cli/bin/pi` stable launcher and
its initial setup cannot yet be claimed verified. Official managed update source
is known; no `pi update` was invoked and no custom updater was introduced.

At the fourth-slice boundary, the Go fixture extractor remained limited to Node-only
selection and Pi JSON metadata: it cannot consume this larger npm program tree
or claim an installed runtime. Reusing its aggregate 8192-entry archive boundary
for the 16401-entry Pi tree would fail. A next bounded implementation needs a
specific verified-Pi preparation capability, complete Node/npm selection and
ownership/notices/receipt rules; do not weaken the generic extractor silently.
Native shared-program update rights, fixed launcher verification, Ubuntu/systemd
process-group stop/activation/health acceptance, explicit credentials/catalog/model
initialization and product E2E remain required. None is replaced by these version,
import, registration or packaging checks; maintenance remains the existing narrow
admission gate.


## Fifth local slice: audited runtime preparation and shared launcher

`ApplyRuntimeFixture` now wires complete Node/npm and a dedicated Pi closure into
Go's existing private fixture transaction. It is internal Go code, not a native
install command or one-line bootstrap. `ApplyFixture` retains its nonexecuting,
Node-only/Pi-metadata behavior and schema 1 receipt. The new explicit capability
is Linux amd64 only and accepts existing private, real, same-UID directories
beneath `/tmp`; it cannot write `/opt`, `/etc`, `/var`, create accounts or units,
initialize credentials or start services.

Runtime preparation requires exactly the audited Node 22.19.0 gzip bytes, npm
10.9.3 executable tree and fixed Pi 1.0.2 package/lock bytes. The complete Node
archive, including notices, npm/corepack dependencies and the three exact known
command links, is prepared. Node's executable hash is checked again before npm
execution. Arbitrary manifest-pinned executables are insufficient for this
capability. The two official Pi metadata files remain byte-for-byte unchanged.

All **147 lock entries** are validated as a catalog; the **122 Linux x64 selected
entries** additionally require URL-bound SHA512 npm-cache evidence and their
actual tarball bytes. The **25 platform-inapplicable optional entries** are not
installed or claimed tarball-verified. All eight integrity omissions in the
unchanged official lock are supplemented by caller-reviewed, hash-verified
official npm metadata. These pins bind the schema 2 generation alongside the
manifest digest; a changed pin set cannot reuse the current generation.

Go invokes the verified bundled npm with the official installer arguments plus
`--offline`: `ci --ignore-scripts --min-release-age=0 --omit=dev
--include=optional --no-fund --no-audit --loglevel=error --progress=false`.
Empty private npm configs, explicit private cache/config/log/prefix paths and a
minimal environment prevent inherited registry credentials or npm options.
No lifecycle script runs. npm owns dependency installation and bin creation;
there is no custom npm dependency resolver or reconstruction of install scripts.
The command has a two-minute limit, and Linux cancellation kills its process
group. npm failure or cancellation leaves no selected runtime generation.

Before npm runs, Go builds an expected file inventory from the verified tarballs.
After npm exits, Go checks every selected installed file against its tarball
SHA256/length, each declared bin link, package versions/URLs/integrities in npm's
generated hidden lock, and the exact original root package/lock bytes. It refuses
missing/extra files, special entries and changed link targets; directory ownership
and private modes are checked. The generated tree has **9 exact npm bin links**.
Package notice files are retained rather than selectively discarded. File modes
are normalized to 0644/0755 and directories to 0700 inside this fixture.

The dedicated runtime archive limit is **32768 entries**, justified by the actual
Node archive's 5780 entries plus the selected Pi tarball inventory; the generic
fixture limit remains 8192. Runtime expanded streams, tar headers/padding and
Magpie's copied bytes share the 512 MiB ceiling. npm compressed tarball bytes are
also capped at 256 MiB aggregate, with 64 MiB per tarball/file, and cache indexes
at 4096 entries/4 MiB. Metadata stays bounded. Only npm tarballs permit bounded
legacy NODETAR/SCHILY metadata and canonical path/size fields; sparse/link metadata
is refused. Fixed legacy DefinitelyTyped roots are allowed for their two exact
locations/versions. Two fixed proxy packages repeat `dist/index.js` using `/./`;
only their exact audited alias pair with identical bytes, size and mode is allowed.
Third occurrences, other aliases, traversal and differing content are rejected.

The schema 2 receipt records manifest and supplementary-input digests, owner UID,
147/122/25 counts, observed archive entry/expanded-byte totals and limits, every
regular file's hash/mode and every link's exact target. It still reports
`installationComplete: false`, `runtimeReady: false` and
`nativeAcceptance: false`. Retry builds and verifies a fresh expected runtime;
it never adopts mutable stored receipt hashes. Existing flock, synchronization,
atomic selection and cancellation boundaries are reused. Different/modified
receipts, programs, links or selectors require inspection instead of replacement.
Progress exposes real closure verification, offline npm ci, extraction and fixture
selection phases. Selection is not a service activation event.

The equivalent shared `/opt/pi-cli/bin/pi` launcher uses pinned Node's `execve`
(rather than spawning another long-lived process) to preserve PID and stdio. It
validates the source-defined `managed-install.json` marker and `current-version`,
sets **`PI_MANAGED_INSTALL_ROOT`**, selects the official releases-v1 CLI path,
prepends the pinned Node/npm directory to PATH and removes the installer-API
base override. It is our source-compatible launcher, not a recovered copy of the
unavailable initial install script. The pi.dev script/API 403 was not bypassed.

Actual tests of the prepared tree verify bundled npm/Pi versions, 12 dependency
imports, the exact prepared AWF extension path's registration, launcher environment,
PID and read-only stdio RPC/EOF behavior. The official managed route for
`pi update self --force` returns its documented refusal before network access,
without changing `current-version`. These tests use a cooperative JS network guard
and empty private state, send no prompt or tool call, and do not invoke a model.
A normal network upgrade was not attempted; recognizing the managed root does
not prove upgrade acceptance or permission to update shared programs.

Native ownership is explicitly planned as **administrator-owned programs, service
read-only**. Ordinary Pi keeps `~/.pi/agent`; Host/Pi service state stays independent
at `/var/lib/awf/pi-agent`. The official ordinary-startup managed cleanup catches
permission failures, but native read-only service behavior still needs acceptance.
Shared upgrades require an explicit administrator operation retaining the durable
maintenance owner/revision, sealing/draining admission and stopping both systemd
control groups before program changes. The service is not granted shared updater
write rights. There is no custom updater or native ownership adapter in this slice.

### Remaining native Ubuntu gate

The remaining product gate requires a disposable **Ubuntu 22.04/24.04 amd64 VM
with systemd and explicit native-install permission**. The current Debian 13
container (PID 1 `tail`) is not that environment. The native adapter remains to
implement and accept fixed root/account/config/unit ownership, initialization
receipts, shutdown/process-group verification, transactional activation and
identity/loopback health. Native notice acceptance, deliberate service credentials
and catalog/model selection, a real shared upgrade and full product E2E belong in
that separately authorized environment. The synthetic Host build/identity fixtures
are not published release assets. No operational one-line install URL, publication,
release, production deployment or native acceptance is claimed here.
