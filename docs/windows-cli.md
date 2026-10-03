# Native Windows CLI lifecycle and release contract

## Availability and scope

The fresh-install product in this source is **not published or accepted on native Windows**.
The checked-in `distribution/go-v1.json` still selects the unchanged
[v1.0.0-rc.3 prerelease](https://github.com/atongrun/agent-workflow/releases/tag/v1.0.0-rc.3),
with CLI protocol 2. That release does not provide the public fresh installer.
This bootstrap requires protocol 3 and refuses the current channel without
installing AWF. A reviewed release, separate publication approval, and real
Windows acceptance are required before advertising the command as live.

The supported product flow is a fresh, per-user installation followed by
explicit `awf init`, `awf start`, `awf stop`, and `awf update`. See
[fresh-install.md](fresh-install.md) for the contract and acceptance checklist.
There is no migration, existing-tree adoption, ACL repair, historical release
installation, or bootstrap-based update path. Any existing `%LOCALAPPDATA%\AWF`
entry, including an empty directory, credentials-only root, file, linked entry,
or partial installation, is refused without changing that entry.

Targets are native Windows AMD64 and ARM64 on Windows 10/Server version 1709 or
newer, using Windows PowerShell 5.1 or PowerShell 7. Run as the intended ordinary
Windows user in a normal terminal opened directly from Windows. Installation
needs no administrator rights and uses `%LOCALAPPDATA%\AWF` and user PATH.
It does not install Go, Python, Node, npm, Pi, OpenCode, or Git, change execution
policy, configure firewall rules, run initialization, pair credentials, enable
login startup, or start the runtime.

## One-command installation

After the fresh-install release and bootstrap have been accepted and published,
the intended ordinary-terminal entry is:

```powershell
powershell -NoProfile -Command "irm https://raw.githubusercontent.com/atongrun/agent-workflow/awf/go-v1/scripts/install.ps1 | iex"
```

This is the intended publication endpoint, not a claim that this local source
is available there. Do not run it expecting the unpublished implementation.
The flow needs no manually supplied directory, release version, or digest:

1. Check native architecture, the actual Windows known folder, package identity,
   and the absence of the entire AWF root before staging or download
2. Resolve the fixed Go v1 channel to an exact protocol-3 release, source commit,
   and architecture-specific SHA-256; never use GitHub's `releases/latest`
3. Ask once before installing a preview and approving future preview updates in
   that channel; the default is **no**, and EOF/redirected input is not consent
4. Verify the official release/tag metadata, checksums, ZIP contents, PE machine
   type, and downloaded CLI's `install-protocol` capability
5. Invoke public native `awf install` with the verified local archive, exact
   version, and digest. The native installer creates its protected program root, writes
   release/channel state and launcher, and registers user PATH
6. Verify the installed launcher's physical location, refresh this PowerShell
   process's PATH, and print the next commands. Initialization is never automatic

Open a new terminal, then run:

```powershell
awf init
awf start
awf stop
awf update
```

`awf init` reviews workspace, native OpenCode path, and network choices. Pairing
and login startup require their own explicit confirmations. Cancelling setup
leaves the installed program available; run `awf init` again when ready.

### Public native installer

A separately obtained, verified executable from a fresh-install release exposes:

```powershell
.\awf.exe install
```

It resolves the same official channel and asks before the fresh install and user
PATH registration. `--yes` allows unattended installation, but a preview still
requires `--allow-prerelease`. `--no-path` leaves PATH registration to the operator.
All of these routes require an absent AWF root; there is no override.

The bootstrap uses `install --yes --archive <verified-local-zip> --version
<exact-tag> --sha256 <verified-digest>`, adding `--channel go-v1` and `--allow-prerelease` only after preview consent.
Exact-version installation also saves the Go-v1 channel for later updates. This local-archive
path performs no second release download. The native installer independently
validates the archive, release identity, and fresh-install capability before
activating the install. These advanced flags are not needed for normal use.

### Installation context and ownership

Bootstrap and native installation require an unpackaged process and matching
Windows known-folder/environment paths. Only `APPMODEL_ERROR_NO_PACKAGE` permits
installation; an identified package or unknown API result fails closed. There
is no bypass flag, environment rewrite, or subprocess escape.

Package identity alone cannot establish an unredirected filesystem view.
Bootstrap verifies its private temporary stage by handle before downloading and
the installed launcher before refreshing process PATH or reporting success.
Native installation independently checks physical paths and owns exclusive
program-root creation and the role-specific installation ACL policy. The bootstrap's
only ACL assignment is on its newly created random temporary stage, before any
payload files are written. It never rewrites installation-root ACLs.

An existing root is rejected before bootstrap staging. Native installation
rechecks absence and exclusively creates the root, rejecting a root that appears
while downloads or consent are pending. A late failure can leave a protected
partial root; it is not automatically deleted, adopted, repaired, or overwritten.
Inspect it explicitly rather than deleting state or relaxing permissions to retry.

Native Go owns persistent user PATH registration. The PowerShell bootstrap only
promotes the verified bin in its current process. Promotion removes duplicates
of that exact normalized bin entry and preserves unrelated entries and order.
It never changes machine PATH or removes another executable, alias, or function.
The bootstrap warns if command resolution still selects something else.
A child PowerShell cannot update its parent terminal's environment, so reopen
that terminal or invoke `%LOCALAPPDATA%\AWF\bin\awf.exe` directly.

### Trust choice and advanced use

The convenient command executes publisher-controlled PowerShell over HTTPS from
a mutable official branch. It trusts that repository, branch and transport
before script-internal checks run. Hashes and metadata do not independently authenticate
a compromised publisher or bootstrap; no signature-verification claim is made.

For independently pinned review, obtain `scripts/install.ps1` from a verified
40-character commit URL, inspect it and verify an independently trusted hash,
then run that copy under the machine's approved script policy. No execution-policy
bypass or alternate repository/server override is provided.

```powershell
.\install.ps1
.\install.ps1 -AllowPrerelease
.\install.ps1 -Version '<EXACT_PUBLISHED_FRESH_TAG>' -Sha256 '<INDEPENDENT_ZIP_SHA256>'
```

Exact pins must name a fresh-install release, with canonical `vX.Y.Z` or
`vX.Y.Z-rc.N` tags. The downloaded executable must report `install-protocol` 3,
including when an exact version bypasses channel selection. Historical binaries
are refused, with no fallback to a private installer. Unattended preview pins
also require `-AllowPrerelease`. Never run the placeholders literally.

### Release and archive verification

Before invoking a downloaded executable, bootstrap:

- Detects native host architecture through `IsWow64Process2`
- Fetches the one fixed channel URL with a 4 KiB limit and no redirects; validates
  all seven string fields and rejects duplicate, unknown, escaped or coerced values
- Requires protocol 3 for fresh installation and Go major 1 for channel selection
- Fetches exact-tag GitHub release metadata and a lightweight tag ref; requires
  the same source commit, a non-draft release, matching boolean prerelease status,
  and exactly one selected archive/checksum asset at its exact official URL
- Uses bounded HTTPS downloads with normal certificate validation; metadata
  redirects are forbidden and release redirects are limited to GitHub/CDN hosts
- Matches `SHA256SUMS` against the channel digest and optional independent pin,
  then verifies the actual ZIP digest
- Requires exactly `awf.exe`, `awf-node.exe`, and `manifest.json` as regular root
  ZIP entries; rejects traversal, streams, duplicates, case variants, linked
  entries, directories, and oversized or truncated contents
- Validates the exact three-field archive manifest and both native PE headers

Release metadata is limited to 2 MiB, checksums to 1 MiB, archive and expanded
payload to 100 MiB, and manifest to 4 KiB. Temporary files are cleaned up.
Staging is private to the current user and SYSTEM with no reparse ancestors;
other processes running as that same user remain outside this isolation boundary.

## Publisher-controlled Go channel

The channel retains the existing seven-field schema: `schema` (`"1"`), `channel`
(`"go-v1"`), `version`, `sourceCommit` (40 lowercase hex), `cliProtocol`, and
`windowsAMD64SHA256`/`windowsARM64SHA256` (64 lowercase hex each). Protocol 3
identifies a release supporting public fresh installation. The parser recognizes
older protocol values only to reject them clearly at the fresh-install boundary.
The ZIP, tag, checksum-file, asset-name, and archive-manifest formats are unchanged.

Publication is a separate operation: build and review the exact source, complete
native Windows acceptance, publish matching immutable artifacts, independently
verify the downloads, then promote the channel with real hashes and protocol 3.
Do not rewrite historical release assets or substitute fixture hashes/version
placeholders. No files in this source change publish or promote a release.

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

### Credential file contract

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

A durable `private\starting.json` launch intent is written before the owned child is
spawned. If startup times out before its process lock or ready record is observed,
that intent still blocks another start, stop, or update. Only the matching ready
runtime or observed exit of that exact child clears the intent. An older child
cannot clear a newer launch intent. A CLI that exits before observing the result
leaves the outcome explicitly unresolved for operator diagnosis.

`awf update` resolves the installed `go-v1` channel, revalidates its exact
release/source/architecture digest, and switches the pointer only after job-safety
checks. It never calls GitHub's repository-wide latest endpoint. Saved channel
metadata must have the known schema and channel and an explicit boolean preview
consent. Missing channel consent is not proof of preview approval: an interactive
update asks before adopting a preview, and unattended use must explicitly pass
`--allow-prerelease`. Having an RC installed alone is not consent to future RCs.

All updates, including advanced `--version` pins, refuse downgrades and unknown
source/tag metadata. Channel updates also reject protocol 1, even at a higher
version, so they cannot silently replace the new updater with an incompatible one. Unknown channels/protocols and manifest/hash disagreement
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
  installation.json                 fresh-v1 product identity; no historical adoption
  current.json                      atomically replaced active-version pointer
  channel.json                      protected Go channel and explicit preview consent
  private\starting.json             unresolved launch identity during startup
  private\runtime.json              private managed runtime/control identity
  config.json                       reviewed non-secret lifecycle configuration
  credentials\windows-node\node-token.dpapi
  state\                            preserved durable node/job state
```

The launcher dispatches to the version selected by `current.json`, avoiding
replacement of a running Windows executable during update. Older versions
remain available for rollback; garbage collection is not part of this slice.

Before forwarding or performing lifecycle writes, AWF requires the fresh-v1
`installation.json` marker and validates the installation tree. Historical or
unmarked layouts are not adopted. Reparse points, symlinks, non-regular entries,
and unsafe ownership or access rules are rejected without rewriting ACLs.

Program files keep ordinary per-user inherited permissions. Their supported
policy permits current-user, SYSTEM and Administrators writes and inherited
read-only access for other principals. A protected program root does not imply
that child paths are safe. Credentials, state, private runtime/control records,
and logs use separate private directories restricted to current-user and SYSTEM
full control; their private ACLs are set when those new directories are created.
Managed paths are checked again immediately before writes. Existing trees are
inspected, never repaired or recursively repermissioned.

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
.\scripts\test_entry.ps1
.\scripts\test_install_context.ps1
.\scripts\test_install_path.ps1
.\scripts\test_fresh_install.ps1
```

`test_entry.ps1` launches fresh copies of the current PowerShell executable. Its
first-download shim supplies the unmodified local installer to actual `irm | iex`;
child-only empty `LOCALAPPDATA` forces the real profile guard before staging or
network. It also checks malformed optional pins before side effects and invokes
the real `Read-Host` with stdin closed. It never installs AWF or modifies the
parent environment. This regression does not replace a controlled, published
one-command install through real transport and guided init.

The portable suite covers stable/RC tag grammar, explicit packaging opt-in,
pre-build rejection without output changes, deterministic archives, checksums,
and static bootstrap ordering. The native suite covers stable/RC opt-in and
metadata-flag policy, checksum parsing, official metadata URLs, manifest
schema, preview consent, fresh-only root/protocol guards, executable machine type, and
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

## Read-only diagnosis (source; not in existing RC3 assets)

`awf doctor` prints a metadata-only snapshot; `awf doctor --json` emits schema 1
with a `findings` array (`check`, `status`, `detail`). A successfully emitted
report exits zero even for missing, mismatched or unknown findings; this is not
a readiness/health success code. Argument/output failures still fail.

The command runs before launcher forwarding and installation validation. It
reports process package context and architecture, Windows known-folder agreement,
executable search results, and a fixed installation/configuration/runtime/default
credential marker inventory. Existing paths are checked for reparse boundaries,
physical-path agreement and the same role-specific ownership/DACL policy
used by lifecycle commands. Fully observed policy failures are mismatches; unavailable or incomplete
inspection is explicitly unknown, with the observed metadata reasons. Missing and malformed roots remain reportable.

Doctor never reads file contents (including configuration, pointers, runtime
secrets or DPAPI credentials), decrypts credentials, creates directories/locks,
walks arbitrary trees, makes HTTP requests, changes ACLs/PATH, or starts/stops
processes. OS metadata and executable lookup use the configured filesystem view.
Configured external credential paths, file validity, selected version,
job idleness, runtime health and shell aliases/functions remain unassessed.
This snapshot observes this process's view; it does not authorize or prove that
installation/recovery can proceed. Native facts are unknown on non-Windows.
Human-readable paths are quoted to prevent terminal-control injection.

An older installed launcher may reject a broken root before forwarding: invoke
the explicit path of a separately verified executable containing doctor instead.
Do not overwrite a launcher as a diagnostic step.

Acceptance requires `TestDoctorNativeMetadataReadOnly` on native Windows and
separately identified ordinary/packaged host observations. Missing, redirected,
broad-ACL and inaccessible disposable roots must remain unchanged. Native
junction/reparse fixtures remain required. Portable seams and cross-compilation
are not native acceptance. Doctor provides no installation, ACL repair, or recovery apply operation.

### Complete read-only ACL metadata (local source extension)

The doctor ACL finding includes an optional structured `acl` object in schema 1
and matching human-readable details. It reports owner/current-process-user SIDs,
DACL absence/null/presence, protection/defaulting/control flags, declared ACE count
and each bounded entry's index, type, size, raw flags, inheritance/type-specific
flag names, mask and SID when that layout is understood. Account names are not
resolved. Unknown layouts or incomplete reads stay explicit and do not discard
later entries with valid boundaries; a corrupt boundary stops enumeration rather
than guessing. Callback/resource payloads are neither interpreted nor displayed.

`complete` means the requested metadata was observed and understood, not effective
access, trustworthy installation identity, job idleness or repair authorization.
The role-specific program/private policy is summarized with every observed
issue. A complete mismatch uses `mismatch`; unavailable/incomplete metadata uses
`unknown`. Program findings distinguish protected code integrity from private
credential/state access. The doctor shares those policy checks with lifecycle
validation but never changes a descriptor.

The Windows collector reads one OWNER|DACL security-descriptor allocation per
path and uses its control/DACL metadata before freeing it. The current-user SID
comes from query-only process-token access, without account-name/profile lookup
or changing thread impersonation. Physical-path and ACL observations are still
separate advisory snapshots; concurrent replacement can change what a name refers
to, and this report must not authorize filesystem mutations.

The zero-write fixture uses a fresh `os.Lstat` for every enumerated path instead
of Windows `DirEntry.Info`'s cached enumeration metadata. It retains exact
inventory, mode, mtime and content comparisons with no tolerance. Regression cases
must still detect same-size content edits, file/directory mtime changes, creation
and deletion. Native ACL/control before/after equality is a separate additional
assertion. This extension requires its own native Windows fixture acceptance.
