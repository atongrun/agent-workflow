# Native Windows CLI lifecycle and release contract

## Availability and scope

This document describes the native Windows lifecycle implementation and its
local release tooling. The examples below are templates and do not assert that
any tag or public download is available for `atongrun/agent-workflow`. Verify the
actual published release and assets before use. Publishing a release is a
separate authorized step; building locally does not create a tag, GitHub release,
or upload.

Supported targets are native Windows AMD64 and ARM64 on Windows 10/Server
version 1709 or newer. The bootstrap requires Windows PowerShell 5.1 or PowerShell 7 on Windows and detects the **native OS
architecture**, including when invoked from 32-bit PowerShell. It does not install
OpenCode, start processes after installation, configure login startup, modify
firewall/Tailscale rules, pair credentials, perform Git operations, request admin
rights, or change execution policy. Run as the intended ordinary Windows user.

## Future public installation template

After an operator has authorized publication and verified the actual release
assets, replace `<EXACT_PUBLISHED_TAG>` with an exact stable tag such as `v1.2.3`.
Stable releases are the default. A release candidate is accepted only with an
exact `vX.Y.Z-rc.N` tag **and** explicit `-AllowPrerelease`; `N` is a nonnegative
integer with no leading zeros (except `0` itself). All numeric tag components
must be canonical. Other prerelease formats, build suffixes, uppercase variants,
and `latest` are rejected. Do not run a placeholder or assume an example tag exists.

The intended release locations are:

- Metadata: `https://api.github.com/repos/atongrun/agent-workflow/releases/tags/<EXACT_PUBLISHED_TAG>`
- Reviewed bootstrap: `https://github.com/atongrun/agent-workflow/releases/download/<EXACT_PUBLISHED_TAG>/install.ps1`
- Native archive: `https://github.com/atongrun/agent-workflow/releases/download/<EXACT_PUBLISHED_TAG>/awf_<EXACT_PUBLISHED_TAG>_windows_<amd64|arm64>.zip`
- Checksums: `https://github.com/atongrun/agent-workflow/releases/download/<EXACT_PUBLISHED_TAG>/SHA256SUMS`

Download and inspect the bootstrap from the verified release before executing it.
Do not pipe a network response into `Invoke-Expression`. The bootstrap is itself
code and is part of the trust boundary; its own checksum should be verified
against an independently obtained value before execution. `SHA256SUMS` also
includes `install.ps1`, but downloading a script and its checksum from one
compromised source would not independently authenticate the script.

Run the reviewed local copy using the existing permitted script-execution policy:

```powershell
.\install.ps1 -Version '<EXACT_PUBLISHED_TAG>'
```

For an independently pinned **native-architecture ZIP** digest:

```powershell
.\install.ps1 -Version '<EXACT_PUBLISHED_TAG>' -Sha256 '<64_HEX_DIGITS_FROM_AN_INDEPENDENT_TRUSTED_SOURCE>'
```

### Future one-line installation template

This alternative is one PowerShell line. It downloads the exact release's
bootstrap into memory, verifies an **independently trusted bootstrap-script
SHA-256** before parsing or invoking the code, and does not write executable
script bytes to a swappable temporary file. Replace both placeholders only after
publication is authorized and the tag and script digest are verified. The digest
here is for `install.ps1`, **not** a binary ZIP. No tag/hash shown here is real.

```powershell
& { $v='<EXACT_PUBLISHED_TAG>'; $pin='<INDEPENDENT_INSTALL_PS1_SHA256>'; if ($v -cnotmatch '\Av(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\z' -or $pin -notmatch '\A[0-9A-Fa-f]{64}\z') { throw 'Replace the exact tag and independently verified script hash first' }; $tls=[Net.ServicePointManager]::SecurityProtocol; $wc=New-Object Net.WebClient; $sha=[Security.Cryptography.SHA256]::Create(); try { [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; $b=$wc.DownloadData("https://github.com/atongrun/agent-workflow/releases/download/$v/install.ps1"); if ($b.Length -gt 1MB -or ([BitConverter]::ToString($sha.ComputeHash($b))).Replace('-','') -ine $pin) { throw 'Bootstrap SHA-256 verification failed' }; & ([ScriptBlock]::Create((New-Object Text.UTF8Encoding($false,$true)).GetString($b))) -Version $v } finally { $wc.Dispose(); $sha.Dispose(); [Net.ServicePointManager]::SecurityProtocol=$tls } }
```

The script bytes are never executed on a digest mismatch. This uses the existing
session and does not change persisted execution policy. In managed environments,
follow the administrator's approved script-signing and execution process; use the
reviewed local script flow instead if interactive script evaluation is prohibited.

### Explicit preview installation template

Only after verifying an actual published **GitHub prerelease**, replace
`<EXACT_PUBLISHED_RC_TAG>` with its exact `vX.Y.Z-rc.N` tag. For a reviewed local
bootstrap, opt in explicitly:

```powershell
.\install.ps1 -Version '<EXACT_PUBLISHED_RC_TAG>' -AllowPrerelease
# Optional independently verified native-architecture ZIP digest:
.\install.ps1 -Version '<EXACT_PUBLISHED_RC_TAG>' -AllowPrerelease -Sha256 '<64_HEX_DIGITS_FROM_AN_INDEPENDENT_TRUSTED_SOURCE>'
```

The preview one-line template retains the same independently verified **script**
hash check before parsing or execution; it additionally requires an exact RC tag
and supplies `-AllowPrerelease`. It never discovers or selects a latest preview:

```powershell
& { $v='<EXACT_PUBLISHED_RC_TAG>'; $pin='<INDEPENDENT_INSTALL_PS1_SHA256>'; if ($v -cnotmatch '\Av(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)-rc\.(?:0|[1-9][0-9]*)\z' -or $pin -notmatch '\A[0-9A-Fa-f]{64}\z') { throw 'Replace the exact RC tag and independently verified script hash first' }; $tls=[Net.ServicePointManager]::SecurityProtocol; $wc=New-Object Net.WebClient; $sha=[Security.Cryptography.SHA256]::Create(); try { [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; $b=$wc.DownloadData("https://github.com/atongrun/agent-workflow/releases/download/$v/install.ps1"); if ($b.Length -gt 1MB -or ([BitConverter]::ToString($sha.ComputeHash($b))).Replace('-','') -ine $pin) { throw 'Bootstrap SHA-256 verification failed' }; & ([ScriptBlock]::Create((New-Object Text.UTF8Encoding($false,$true)).GetString($b))) -Version $v -AllowPrerelease } finally { $wc.Dispose(); $sha.Dispose(); [Net.ServicePointManager]::SecurityProtocol=$tls } }
```

Without explicit opt-in, an RC is rejected before bootstrap staging or network
requests. Draft releases are always rejected. RC tags require GitHub metadata
with `prerelease: true`; stable tags require `prerelease: false`, even when
`-AllowPrerelease` is supplied. Preview opt-in does not persist and does not
weaken the checksum, official-origin, archive, native-PE, or ACL checks below.

No source/repository override, execution-policy bypass, credential argument, or
administrator step is supported. If policy blocks the reviewed script, follow
that machine's approved signing/execution process; do not loosen machine or
user policy as an installation workaround.

The bootstrap refuses an existing installation and directs the operator to
`awf update`. A launcher-only interrupted install also triggers this conservative
bootstrap check; do not remove the launcher to bypass it. Native `_install` may
reuse an identical orphan launcher under its own integrity checks, but that
recovery requires explicit operator review rather than a bootstrap retry.

Bootstrap only adds `%LOCALAPPDATA%\AWF\bin` to the current user's PATH
**after** the native installer succeeds, without rewriting machine PATH or
clobbering existing entries. It also appends the launcher to the current PowerShell
process PATH, so `awf init` is available immediately there. If PATH registration
fails after a successful install, use the full launcher path below and repair
user PATH explicitly rather than rerunning bootstrap:

```powershell
& "$env:LOCALAPPDATA\AWF\bin\awf.exe" version
```

### Trust and archive checks

Before running any downloaded executable, bootstrap:

1. Resolves native host architecture with `IsWow64Process2`, not the PowerShell
   process architecture or a caller-selected architecture. `GetNativeSystemInfo`
   is deliberately avoided because it may report an emulated CPU on ARM64; see
   [Microsoft’s architecture-detection guidance](https://learn.microsoft.com/en-us/windows/win32/api/wow64apiset/nf-wow64apiset-iswow64process2)
2. Fetches only the requested tag's official GitHub release metadata; rejects
   drafts, unapproved RCs, a mismatched tag or prerelease status, missing assets,
   duplicate selected assets, or assets whose URL differs from the exact official
   release URL
3. Downloads bounded content over HTTPS with normal certificate validation;
   redirects are limited to GitHub's release/CDN hosts, while metadata redirects
   are rejected; no bearer token or alternate source is accepted
4. Requires a valid `SHA256SUMS` entry for the selected ZIP, checks any independent
   `-Sha256` pin against it, and verifies the actual archive SHA-256
5. Requires exactly `awf.exe`, `awf-node.exe`, and `manifest.json` as root entries;
   rejects duplicate/case-variant names, traversal, folders, alternate data
   streams, symlinks, reparse entries, and non-regular Unix entry types
6. Limits metadata to 2 MiB, checksums to 1 MiB, the archive and total expanded
   payload to 100 MiB, and the manifest to 4 KiB; streams are bounded while read
7. Checks the manifest's exact three string fields and values, rejects duplicate
   or extra fields, and checks both executable PE headers against native AMD64
   or ARM64 before invoking `awf.exe`

Staging is a random directory in the current user's LocalAppData with inheritance
removed and access restricted to that user and SYSTEM. Bootstrap rejects reparse
points in its staging ancestor chain. Temporary files are removed on exit. This
boundary does not isolate other processes running as the same Windows user.

The verified staged executable is invoked using native arguments, with an
absolute archive path:

```text
awf.exe _install --archive <absolute-verified-zip> --version <exact-tag> --sha256 <verified-digest>
```

The bootstrap appends `--allow-prerelease` only when the operator supplied
`-AllowPrerelease`. Native `_install` independently requires that flag for an RC;
using the private interface directly does not bypass preview policy.

`_install` is a private bootstrap interface, not a separate public installer or
an unsafe-update workaround. It rechecks the archive and rejects an existing
installation. It establishes the protected per-user installation root, stages
versioned executables, creates the initial immutable launcher, and atomically
writes the current-version pointer. SHA-256 from the same release protects
integrity; an independent pin adds a separate trust anchor. Neither mechanism
establishes that the publisher or compiled code is benign.

## Reviewable initialization

Install the native OpenCode `.exe` separately and authenticate through OpenCode's
own interface as this Windows user. Provider authentication stays in native
OpenCode and is not copied into AWF config or another machine. Create/select a
dedicated, already-existing workspace yourself; AWF does not clone repositories
or create a workspace as a substitute for Git setup.

Replace all example paths, project IDs, and IPs with verified values:

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
# Explicit preview update (exact RC tag and opt-in are both required):
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

`update` defaults to official stable release packages and switches the version
pointer only after the job-safety checks. It preserves configuration, credentials,
native provider authentication, and durable job state. If a running runtime was
stopped for an update, activation is checked and failure restores the prior
version pointer and attempts to restart that version when shutdown is confirmed
safe. If the new runtime state is unknown, automatic rollback is blocked and the
new pointer is retained for explicit recovery; unverified work is never killed to
force a rollback. A rollback/restart error requires operator attention; it is not reported as a successful update. The
explicit pinned-tag form above is recommended; an omitted `--version` resolves
the official latest stable release once and then pins that result for the run.
An RC update requires both an exact `--version vX.Y.Z-rc.N` and
`--allow-prerelease`; the flag alone cannot select a preview. Drafts and
tag/metadata prerelease mismatches are always rejected. An unpinned update also
refuses an older stable release when a newer version or RC is already installed;
it never silently downgrades a preview to an older stable version. A stable
release with the same core version sorts after its RCs.

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
```

The portable suite covers stable/RC tag grammar, explicit packaging opt-in,
pre-build rejection without output changes, deterministic archives, checksums,
and static bootstrap ordering. The native suite covers stable/RC opt-in and
metadata-flag policy, checksum parsing, official metadata URLs, manifest
schema, executable machine type, and malicious ZIP cases including traversal,
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
