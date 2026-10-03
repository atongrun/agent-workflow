# Native Windows CLI lifecycle and release contract

## Availability and scope

This source adds a one-command Windows bootstrap, guided `awf init`, and a
Go-only update channel. **The full simplified flow is not live until its reviewed
script, channel metadata, and a compatible CLI release have been published and
native Windows acceptance passes.** Source changes and local packages are not a
release or installation acceptance result.

The checked-in `distribution/go-v1.json` deliberately names the existing
[v1.0.0-rc.2 release](https://github.com/atongrun/agent-workflow/releases/tag/v1.0.0-rc.2),
its actual source commit, and its published architecture hashes. That CLI has
`cliProtocol: "1"`: it predates guided init and channel-aware updates. The new
source implements protocol 2, but the manifest must not claim new binaries exist.
Do not change a historical release or use GitHub's repository-wide `latest`:
that endpoint still refers to the retired Python release line.

Supported targets are native Windows AMD64 and ARM64 on Windows 10/Server
version 1709 or newer, using Windows PowerShell 5.1 or PowerShell 7. The installer
uses the current user's `%LOCALAPPDATA%\AWF` directory and user PATH. It does not
require a directory, version, or hash argument for ordinary interactive use.
It does not install Go, Python, Node, npm, Pi, OpenCode, or Git, request admin
rights, change execution policy, configure firewall rules, or start the runtime.
Run it as the intended ordinary Windows user.

## One-command installation

**Planned command, gated on the publication and acceptance checks above.** This
uses the existing official GitHub repository; no new domain or hosting is needed.
The old script currently at that URL does not implement the new no-flags flow.

```powershell
powershell -NoProfile -Command "irm https://raw.githubusercontent.com/atongrun/agent-workflow/awf/go-v1/scripts/install.ps1 | iex"
```

With the reviewed rollout in place, the command:

1. Detects native Windows architecture, including 32-bit PowerShell on a 64-bit OS
2. Resolves the publisher's Go v1 channel to an exact release, source commit, and
   architecture-specific SHA-256; it never guesses a tag or uses `releases/latest`
3. If the selected release is a preview, asks once whether to install it and
   allow preview updates in that Go channel; the default is **no**
4. Verifies release/tag metadata, checksums, archive contents and PE architecture,
   then installs in the protected per-user directory and adds its launcher to PATH
5. For protocol 2 releases, opens `awf init` in that same interactive terminal;
   workspace, native OpenCode path and network choices are questions, followed by
   an exact configuration review. Login autostart and credential pairing remain
   separately confirmed and default **no**

Later, use `awf update`. Use `awf init` to resume incomplete setup and `awf pair`
to resume optional pairing. Installing or saving configuration never starts
AWF automatically; run `awf start` when ready. A completed install is preserved
if setup is cancelled or fails; do not rerun bootstrap to repair configuration.

The protocol 1 fixture can install actual RC2, but the installer clearly reports
that its setup and updater predate the new workflow. It saves a private channel
marker for future compatibility. An already-installed RC2 needs a separately
reviewed, exact-version update to the first protocol 2 release; its existing
updater cannot acquire these changes merely by reading the new manifest.

### Trust choice and advanced use

The convenient command executes publisher-controlled PowerShell delivered over
HTTPS from a mutable official branch. It trusts that GitHub repository, branch,
and transport before any script-internal checks run. The manifest and checksums
protect the selection and downloaded bytes; they do not independently authenticate
a compromised publisher or bootstrap. This is the explicit convenience tradeoff
of the one-command flow, not a signature-verification claim.

For independently pinned review, download `scripts/install.ps1` from a verified
40-character commit URL, inspect it, verify its SHA-256 against an independently
trusted value, and run that local copy using the machine's approved script policy.
Managed environments can use their approved signing/distribution process.
No execution-policy bypass or alternate repository/server override is provided.

```powershell
.\install.ps1                         # interactive Go-channel installation
.\install.ps1 -AllowPrerelease -SkipInit # explicit unattended preview consent
.\install.ps1 -Version '<EXACT_PUBLISHED_TAG>' -Sha256 '<INDEPENDENT_ZIP_SHA256>'
```

Exact pins are advanced options. Tags must be canonical `vX.Y.Z` or `vX.Y.Z-rc.N`,
with no aliases, leading zeros, other prerelease labels or build suffixes. An
interactive preview pin asks for consent; unattended preview pins require
`-AllowPrerelease`. `-SkipInit` suppresses the setup wizard. Without explicit
preview consent, redirected/noninteractive input fails closed. Never run the
angle-bracket placeholders literally.

Bootstrap refuses any existing install/configuration/channel/launcher marker and
directs the operator to `awf update` or explicit recovery. It does not overwrite
an existing install to bypass active-job checks. PATH is changed only after the
native installer and channel registration succeed, without replacing other PATH
entries. The current PowerShell process is also updated. A command launched in a
child PowerShell cannot rewrite its parent shell environment; open a new terminal
for `awf`, or use `%LOCALAPPDATA%\AWF\bin\awf.exe` immediately.

### Trust and archive checks

Before running a downloaded executable, bootstrap:

1. Resolves native host architecture using `IsWow64Process2`, not process
   architecture or a caller-selected override
2. Fetches the one fixed Go-channel URL (4 KiB limit, no redirects), validates its
   exact seven string fields, rejects unknown/duplicate/escaped/coerced values,
   and accepts only Go major 1 and known CLI protocols
3. Fetches exact-tag official GitHub release metadata and the lightweight tag ref;
   requires the source commit to agree, boolean non-draft status, tag/prerelease
   agreement, and exactly one selected archive and checksum asset at exact URLs
4. Downloads bounded HTTPS content with normal certificate validation; release
   asset redirects are restricted to GitHub release/CDN hosts and all metadata
   redirects are rejected. No credentials or alternate source are accepted
5. Requires the architecture ZIP digest in `SHA256SUMS` to match the channel pin
   and any independent `-Sha256`, then verifies the actual downloaded bytes
6. Requires exactly `awf.exe`, `awf-node.exe`, and `manifest.json` as root entries;
   rejects duplicates/case variants, traversal, folders, alternate data streams,
   symlinks, reparse entries, and non-regular Unix types. Metadata is limited to
   2 MiB, checksums to 1 MiB, archive and expanded payload to 100 MiB, and archive
   manifest to 4 KiB
7. Checks the archive manifest's exact three string fields and both executable
   PE headers before invoking native `_install`, which independently rechecks
   the bytes, archive, version, and protected installation tree

Staging is random under the current user's LocalAppData, restricted to that user
and SYSTEM before payload writes. Reparse ancestors are rejected. Temporary
files are cleaned up. Other processes of the same Windows user remain outside
this isolation boundary. Native `_install` is a private bootstrap interface;
preview selection passes explicit `--allow-prerelease`. Protocol 2 additionally
passes `--channel go-v1`, persisting only the disclosed preview consent. Protocol
1 compatibility creates the same separate channel marker only after verifying
the installed directory's existing private ACLs. The original `current.json`
shape stays compatible with immutable older launchers.

## Publisher-controlled Go channel

`distribution/go-v1.json` is data, not executable code. Its schema consists of
exactly these seven strings: `schema` (`"1"`), `channel` (`"go-v1"`), `version`,
`sourceCommit` (40 lowercase hex), `cliProtocol` (`"1"` or `"2"`),
`windowsAMD64SHA256`, and `windowsARM64SHA256` (64 lowercase hex each). The channel
cannot select major 0/Python or unknown future major versions. Version tags and
GitHub metadata must agree on preview status. Publisher metadata is still a
publisher trust input, not an independent cryptographic signature.

A channel change is a separate release/publication action. Before authorizing it:

- Build/review/test the exact source, including native PowerShell 5.1 x64/x86,
  PowerShell 7, native Go lifecycle fixtures and ARM64 where available
- Publish the exact source commit, lightweight tag and non-draft release with
  architecture ZIPs, the reviewed script and `SHA256SUMS`; set `target_commitish`
  to that exact commit and set prerelease status consistently
- Download/verify all public assets and their hashes, then propose a manifest
  selecting only those already-published bytes. Set protocol 2 only for a release
  that actually supports guided init and channel-aware update
- Independently review and publish that manifest and bootstrap, then verify the
  no-flags install, consent/decline, new-terminal PATH, init/pair prompts, update,
  guarded busy/unknown state, and recovery against the published artifacts

The packager does not mutate or publish the distribution channel. Local fixture
builds and future version placeholders must never be promoted as real releases.

## Reviewable initialization

Install the native OpenCode `.exe` separately and authenticate through OpenCode's
own interface as this Windows user. Provider authentication stays in native
OpenCode and is not copied into AWF config or another machine. Create/select a
dedicated, already-existing workspace yourself; AWF does not clone repositories
or create a workspace as a substitute for Git setup.

Start guided setup without path flags:

```powershell
awf init
```

It asks for missing required values and shows a detected native OpenCode `.exe`
path only as a reviewable default. It never silently selects a workspace or
remote address. EOF before required answers or save approval changes nothing.
Explicit flags remain available; when both required paths are supplied, the
existing review/confirmation sequence is preserved.

For advanced setup, replace all example paths, project IDs, and IPs with verified values:

```powershell
awf init --workspace 'C:\Work\acceptance' --project 'acceptance' --opencode 'C:\Tools\OpenCode\opencode.exe' --listen '<WINDOWS_NODE_EXACT_IP>:7071' --allow-source '<CONTROL_HOST_EXACT_IP>'
```

The project ID must match the control Host's project routing. Workspace and
OpenCode paths must be absolute and already exist; OpenCode must be a native
`.exe`, not a shell wrapper. `--listen` requires an exact interface IP and port,
never a wildcard. `--allow-source` contains exact unicast control Host IPs, not
hostnames or CIDRs; a comma-separated list is supported for explicitly approved
additional addresses. Bracket IPv6 in `--listen`, for example
`'[<WINDOWS_NODE_IPV6>]:7071'`. These placeholders are not valid addresses.

For a purely local acceptance run, `127.0.0.1:7071` can be the listener and
`127.0.0.1` the allowed source. Remote access requires the verified private node
interface and exact remote Host source. Source filtering is an application
check, not a firewall or authenticated transport. Apply and test the separately
approved firewall/Tailscale ACL yourself; never expose the node or native
OpenCode publicly.

`init` asks whether AWF should start at this Windows user's login, default **no**.
It then prints the exact paths, network endpoints, source list, project mapping,
credential-file location, and autostart choice and asks whether to save that
exact configuration. Declining leaves the configuration unsaved. An explicitly
accepted autostart choice uses a per-user login entry; bootstrap never enables
it. Initialization saves settings and does not start the runtime. It then offers
native pairing with a default **no**; EOF also skips pairing. Existing local
credentials are preserved without another pairing offer (their presence alone
does not prove that the remote credential matches). A pairing failure leaves the
reviewed configuration saved; use `awf pair` to continue.

### Native pairing and verification

New Windows machines can pair directly from the optional `init` offer or later:

```powershell
awf pair --ssh-host 'control-host' --remote-env '/home/operator/.config/awf/windows-node.env'
# Inspect without creating or transmitting a credential:
awf pair --status --ssh-host 'control-host' --remote-env '/home/operator/.config/awf/windows-node.env'
```

Omit the two destination flags to enter them interactively. The local destination
is the exact credential path already reviewed in `init`. The SSH host must be an
existing alias in your SSH configuration, using only letters, digits, dot,
underscore and hyphen (no `user@host` or extra SSH options). Configure its HostName,
User, identity, and independently verified known-host key beforehand. Pairing
uses the native Windows system OpenSSH client, with strict existing-host-key
checking and public-key-only BatchMode. It disables agent/X11/tunnel/port
forwarding, host-key updates, DNS-based host-key acceptance, local commands,
configured remote commands and connection multiplexing. Unknown/changed keys or
missing SSH keys fail closed; pairing never enrolls a key, prompts for a password,
or bypasses trust checks. The existing SSH configuration, including any explicitly
configured proxy route, remains a trust input.

The Linux control Host must already have Python 3 and the remote parent directory
owned by the SSH user with mode `0700` (or stricter). AWF does not install tools,
create remote directories, change Host configuration, or restart services. The
remote destination must be a clean absolute Linux path up to 1024 characters,
using only letters, digits, dot, underscore, hyphen and slash. No spaces, traversal,
symlink ancestors, linked destination, or existing-file replacement is allowed.
An explicit external local credential destination requires an already-private
parent; pairing does not rewrite external ACLs. UNC paths and alternate data
streams are rejected. Standard managed credential directories are created only
after confirmation.

Before creating or sending anything, `pair` shows the exact local path, SSH alias,
remote path and trust assumptions. Type `PAIR` to authorize that specific
credential creation/access and transfer. It generates 32 random bytes, encodes
them as 64 uppercase hexadecimal bytes, and protects the local identity directly
with CurrentUser DPAPI. No PowerShell or WSL is needed. The token travels only
through SSH stdin to a fixed, bounded receiver, which creates a new mode-0600
file containing exactly `AWF_WINDOWS_TOKEN=<token>` and a newline. It never appears
in CLI arguments, terminal output, logs, configuration JSON, or OpenCode's
environment. Do not paste a token into chat or source control.

Status meanings are deliberately limited:

- **paired**: a fresh challenge/HMAC verified that the two protected files contain
  the same identity. This does not prove Host service configuration, running
  processes, network reachability to the node, or end-to-end job success
- **local-only**: a valid local identity exists and inspection proved the remote
  env-file absent
- **unpaired**: both selected credential files are absent
- **remote-unknown**: reachability, authentication, remote privacy/format, or a
  matching local identity could not be established; existence is never enough

A repeat run with matching files only verifies them. It does not resend or
rotate the token. Existing mismatched or malformed files are never overwritten.
If transfer fails after local creation, the encrypted local identity is retained:

```powershell
awf pair --status --ssh-host 'control-host' --remote-env '/home/operator/.config/awf/windows-node.env'
# Only if status proves the remote file absent, explicitly reuse the local identity:
awf pair --retry --ssh-host 'control-host' --remote-env '/home/operator/.config/awf/windows-node.env'
```

`--retry` requires an existing valid local credential, displays the destinations
again, and requires `PAIR` before resending the same identity. It cannot generate
a new identity or overwrite a remote file. An interrupted partial remote write
requires explicit operator recovery; deleting files or rerunning `init` is not a
safe automatic recovery procedure. Rotation is intentionally not implemented
by these commands and must be a separately reviewed operation. Pairing never
implicitly enables autostart, changes firewall rules, provisions arbitrary Hosts,
or changes native provider authentication.

### Credential compatibility

Existing operator-approved PowerShell helper pairings remain compatible and do
not need to be recreated. The native CLI uses the same on-disk and Host env-file
contract. The old helper is optional; no hosted helper is implied.

The Windows credential file consumed by managed AWF has this contract:

- Default location: `%LOCALAPPDATA%\AWF\credentials\windows-node\node-token.dpapi`
- Plaintext before protection: exactly **64 uppercase hexadecimal ASCII bytes**,
  generated with a cryptographically secure random source
- Protection: Windows DPAPI **CurrentUser** scope, under the same Windows user
  that will run AWF
- Additional entropy: UTF-8 bytes of `AWF Windows node pairing v1`
- File content: raw DPAPI protected bytes, not Base64 text or a JSON wrapper
- Protect the file and parent directory for the intended user and SYSTEM; do not
  copy this file to another machine or user as an authentication shortcut

The paired control Host presents this token to authenticate requests to the AWF
node. It is separate from OpenCode's native provider login. An explicit `--credential-file` can select
an already approved absolute credential-file location at initialization; it does
not import or generate credentials while saving configuration; the separate
pairing confirmation can create a missing identity at that location. The selected file and its immediate parent
must have the same private owner/ACL protections and contain no reparse points,
even when they are outside the AWF installation; AWF only checks, and does not
rewrite, those external ACLs. `awf start` fails clearly when pairing is
missing, unreadable, belongs to another Windows user, or has the wrong format.

## Start, stop, and update

```powershell
awf start
awf stop
awf update --version '<EXACT_PUBLISHED_TAG>'
# Optional independent archive pin:
awf update --version '<EXACT_PUBLISHED_TAG>' --sha256 '<64_HEX_DIGITS>'
# Advanced explicit preview pin:
awf update --version '<EXACT_PUBLISHED_RC_TAG>' --allow-prerelease
```

`start` runs managed native OpenCode on `127.0.0.1:4096` and the configured AWF
node under this Windows user. It preserves native provider authentication. Do
not run a second standalone OpenCode server on that port as a substitute for
managed startup; an existing listener or ambiguous runtime must be investigated
rather than overwritten. Repeated start/stop requests must not create duplicate
managed instances or affect unrelated processes.

`stop` and `update` refuse busy or unknown work, including active or interrupted
jobs requiring recovery. They do not terminate jobs just to make an operation
succeed. Investigate status and resolve/cancel the specific job through its normal
workflow before retrying. Do not delete locks, job state, credential files, or
runtime records to force a lifecycle transition.

Native state-read failures report the affected check and a bounded failure class
(HTTP status, timeout, cancellation, malformed JSON, unexpected JSON shape, or
other request failure). They do not include native response bodies, raw error
text, workspace paths, or credentials. A successful empty session-status object
(`{}`) and empty permission/question arrays (`[]`) are valid idle state; JSON
`null`, malformed responses, authentication failures, and unavailable state
remain unknown and block stop/update. This is an idle safety check, not evidence
that an execution task completed successfully.

An unknown-state refusal leaves the runtime running. A later normal `awf stop`
may succeed if the native condition has resolved; that alone does not identify
the original cause. A new CLI cannot change the checks inside an already-running
supervisor, and no force-stop or installation-overwrite recovery is provided.

A durable `starting.json` launch intent is written before the owned child is
spawned. If startup times out before its process lock or ready record is observed,
that intent still blocks another start, stop, or update. Only the matching ready
runtime or observed exit of that exact child clears the intent. An older child
cannot clear a newer launch intent. A CLI that exits before observing the result
leaves the outcome explicitly unresolved for operator diagnosis.

`awf update` resolves the installed `go-v1` channel, revalidates its exact
release/source/architecture digest, and switches the pointer only after job-safety
checks. It never calls GitHub's repository-wide latest endpoint. Saved channel
metadata must have the known schema and channel and an explicit boolean preview
consent. A missing legacy marker is not proof of preview consent: an interactive
update asks before adopting a preview, and unattended use must explicitly pass
`--allow-prerelease`. Having an RC installed alone is not consent to future RCs.

All updates, including advanced `--version` pins, refuse downgrades and unknown
source/tag metadata. Channel updates also reject protocol 1, even at a higher
version, so they cannot silently replace the new updater with a legacy one. Unknown channels/protocols and manifest/hash disagreement
fail closed. A stable release with the same core version sorts after its RCs.
The updater preserves configuration, credentials, provider authentication and job
state. It retains saved channel/consent across version changes. If a running
runtime is stopped for an update, activation is checked; a confirmed-safe
activation failure restores the exact prior version pointer and attempts to
restart it. Unknown new runtime state blocks rollback, leaving the new pointer
for explicit recovery. Unverified work is never killed to force rollback.

`awf update --all` is **reserved for later and currently rejected**. This command
does not update Pi, OpenCode, or unrelated tools. A bootstrap rerun is not an
alternative update path.

### Installation layout

```text
%LOCALAPPDATA%\AWF\
  bin\awf.exe                       immutable initial launcher, on user PATH
  versions\vX.Y.Z\awf.exe           versioned implementation
  versions\vX.Y.Z\awf-node.exe
  versions\vX.Y.Z\manifest.json
  current.json                      atomically replaced active-version pointer
  channel.json                      protected Go channel and explicit preview consent
  starting.json                     unresolved launch identity, present only during startup
  runtime.json                      private managed runtime/control identity
  config.json                       reviewed non-secret lifecycle configuration
  credentials\windows-node\node-token.dpapi
  state\                            preserved durable node/job state
```

The launcher dispatches to the version selected by `current.json`, avoiding
replacement of a running Windows executable during update. Older versions
remain available for rollback; garbage collection is not part of this slice.

Before forwarding to any versioned executable or performing lifecycle writes,
AWF validates the installation tree. Reparse points, symlinks, non-regular
entries, and Windows descendants owned by or permitting identities other than
the intended user and SYSTEM are rejected. A private root ACL is not treated as
proof that existing protected child ACLs are safe. Managed directories are also
checked immediately before staging writes. Unsafe pre-existing trees require
explicit operator recovery rather than implicit adoption or recursive rewriting.

## Build local release assets

Prerequisites: Python 3.10+ and an installed compatible Go toolchain (see
`go.mod`). The packager uses the requested Go executable with automatic toolchain
download disabled. Run from the repository:

```text
python scripts/package_windows.py --version v1.2.3 --output <EMPTY_LOCAL_RELEASE_DIRECTORY>
```

An alternate **local compiler executable**, not a download source, can be selected
with `--go <absolute-path-to-go>`. `GOCACHE` can point to the local build cache.
The example version is only a packaging input and makes no publication claim.
Packaging remains stable-only unless `--allow-prerelease` is explicitly supplied
with an exact canonical RC tag. For a local fixture (not a publication command):

```text
python scripts/package_windows.py --version v0.0.0-rc.1 --allow-prerelease --output <EMPTY_LOCAL_FIXTURE_DIRECTORY>
```

An unapproved RC or malformed tag is rejected before invoking Go or creating or
changing the output directory. Only `vX.Y.Z` and `vX.Y.Z-rc.N` are supported, with
no leading zeros, aliases, other prerelease labels, or build suffixes. A published
RC must separately be marked as a GitHub prerelease; a stable tag must not be.

The packager cross-compiles both Windows architectures using `CGO_ENABLED=0`,
`-trimpath`, `-buildvcs=false`, an empty Go build ID, and:

```text
-X github.com/atongrun/agent-workflow/internal/lifecycle.Version=vX.Y.Z
```

For identical source and the same exact Go toolchain, archive order, fixed ZIP
metadata, uncompressed payloads, and canonical manifest bytes are deterministic.
Different source or toolchains can produce different executable hashes. The
script refuses to overwrite existing assets and produces locally:

```text
awf_vX.Y.Z_windows_amd64.zip
awf_vX.Y.Z_windows_arm64.zip
install.ps1
SHA256SUMS
```

For an opted-in RC, the complete `-rc.N` suffix is retained in asset names,
the embedded CLI version, manifest, and versioned installation directory.

Each ZIP contains exactly:

```text
awf.exe
awf-node.exe
manifest.json
```

The manifest is a UTF-8 JSON object, for example:

```json
{"version":"v1.2.3","os":"windows","arch":"amd64"}
```

`SHA256SUMS` contains lowercase SHA-256 hex, two spaces, and the exact asset name
for each ZIP and `install.ps1`, one entry per line. Asset names include the `v`
from the tag. The script validates the binaries' PE machine type and package
limits before finishing. No release is created, uploaded, tagged, or pushed.

## Tests and native acceptance limits

Pairing portable checks run as part of `go test ./...` (and `go test -race ./...`).
They exercise the exact embedded Linux receiver with synthetic temporary files:
mode-0600 creation, strict format, proof verification, exclusive no-overwrite,
symlink/hardlink/FIFO/directory rejection, private preexisting parents, and safe
retries. CLI tests cover cancellation, missing confirmation, existing matching
identities, unknown/mismatched remote state, interruption after local save, no
secret output, and default-off init. They do not contact SSH or a real Host.

Native Windows fixtures use only `t.TempDir` and synthetic identities. Run:

```text
go test ./internal/lifecycle -run "TestWindows.*Pair|TestWindowsExternalCredential|TestInit|TestPair" -count=1
```

The native writer tests cover direct CurrentUser DPAPI round-trip, compatibility
with the historical helper entropy/format, inherited private DACLs, no overwrite,
external broad-parent refusal, and UNC/alternate-stream rejection. They do not
access installed credentials, use SSH, register startup, or change Host settings.
Native Windows execution and real known-host SSH acceptance remain separate
release gates; cross-compilation is not evidence that those gates passed.


Portable package and static bootstrap checks:

```text
python -m unittest discover -s scripts -p "test_*.py" -v
```

Native PowerShell helper tests (no install, network, PATH, registry, firewall, or
credential changes):

```powershell
.\scripts\test_install.ps1
.\scripts\test_channel.ps1
```

The portable suite covers stable/RC tag grammar, explicit packaging opt-in,
pre-build rejection without output changes, deterministic archives, checksums,
and static bootstrap ordering. The native suite covers stable/RC opt-in and
metadata-flag policy, checksum parsing, official metadata URLs, manifest
schema, preview consent and legacy marker ACLs, executable machine type, and
malicious ZIP cases including traversal,
duplicates, links/reparse entries, extra members, wrong manifests, and size limits.
Fixture executables are not run. Run it under both Windows PowerShell 5.1 and
PowerShell 7, and separately verify architecture detection from 32-bit PowerShell
on AMD64 and ARM64 Windows where available.

**PowerShell and native Windows are unavailable in the Linux development
workspace, so the native PowerShell suite and real installation are not run
there.** Passing Python tests or cross-compilation does not validate Windows ACLs,
PATH behavior, DPAPI, login startup, child-process ownership, actual node/job
lifecycle, or live update rollback. A published release also needs a controlled
Windows acceptance run for these behaviors and failure cases, using dedicated
operator-approved credentials and a nonproduction workspace. Do not claim a
production deployment or working public install URL based only on local tests.
