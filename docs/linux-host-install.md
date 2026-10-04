# Linux Host installation: first local slice

This slice adds an independent `linux-host-v1` manifest contract, read-only
planning/diagnosis and an internal download/hash/staging core. It does not publish
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
| `node` | `vVERSION`, minimum 22.19.0; `https://nodejs.org/dist/vVERSION/node-vVERSION-linux-x64.tar.xz` (`arm64` suffix reserved) | `tar.xz` |
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
model default or inferred Magpie configuration environment variable.

Service reload/upgrades need a Host maintenance gate that freezes new dispatch,
waits for the supported idle state and performs an explicit compatible reload.
An idle snapshot followed by `systemctl restart` is not a safe upgrade gate. Full
service ownership, init, loopback health/build identity, safe archive extraction,
Pi npm installation, native Ubuntu acceptance and that maintenance gate require
later bounded slices; none is implemented here.

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
entries and hidden trailing nonzero tar payloads fail closed. Limits cover 4096
visible archive entries in aggregate, 256 MiB per archive file, 512 MiB expanded
stream bytes in aggregate (including discarded payloads and tar overhead), and
compressed manifest bounds. Selected executable files get ELF target validation.
Output is written through Go's directory-root API into a fresh private tree.

A pinned pure-Go `github.com/ulikunitz/xz v0.5.15` decoder handles Node XZ without
executing an external decompressor. Its `DictCap` is a minimum, not a maximum.
Preflight validates one XZ stream's footer/index, every indexed block header and
raw LZMA2 chunk boundaries before decoder construction; it accepts one LZMA2
filter, at most a 64 MiB dictionary, a 1 MiB index, bounded blocks/chunks and
expanded sizes. Chunk scanning prevents a lying index from hiding an unexamined
next block header. The decoder additionally verifies compressed data, index
consistency and checksums. Unsupported compression features are rejected, not
silently delegated to a shell. A native official Node asset still requires later
acceptance against these intentionally bounded rules.

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

### Third-slice interfaces to design before native implementation

The future native controller should separate these capabilities rather than
reuse a generic root-path option on the fixture API:

- A program preparation capability verifies a fully published component closure,
  required notices and native build/version acceptance before activation.
- An explicit initialization capability owns service account/config paths and
  credential entry. Shared Pi program root is `/opt/pi-cli`; service agent state
  is `/var/lib/awf/pi-agent`; ordinary `~/.pi/agent` remains independent. No model
  is selected until the actual loopback Magpie catalog is observed and confirmed.
- A maintenance lease freezes new Host dispatch, records ownership/revision,
  waits for the supported idle condition and authorizes compatible reload. A
  service adapter may reload only with that lease; a stale idle snapshot is
  insufficient. Failures and process death must retain a recoverable outcome.
- A native service adapter owns explicit unit/account actions and verifies
  loopback health plus exact running build identity. Those actions need separate
  native acceptance and publication/deployment authorization.

These are design boundaries, not runnable stubs or capabilities granted by a
sandbox receipt. No third-slice interface implementation is included here.
