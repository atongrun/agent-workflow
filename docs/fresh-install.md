# Fresh Windows installation

## Status

This is a source implementation and acceptance plan, not a published product.
No live installation or real Windows ACL/PATH acceptance is claimed.
This Programs-root correction requires its own native acceptance; any earlier
layout's acceptance does not establish that this destination works on Windows.
The unchanged Go channel selects protocol-2 RC3; the fresh bootstrap requires
protocol 3 and stops before executing that historical installer.
Publication, channel promotion and native Windows acceptance remain separate.

## Product flow

Once the reviewed release is published, an ordinary Windows terminal runs one
bootstrap command with no path, version, or hash arguments:

```powershell
powershell -NoProfile -Command "irm https://raw.githubusercontent.com/atongrun/agent-workflow/awf/go-v1/scripts/install.ps1 | iex"
```

The URL is the intended publication location. It does not expose this local
implementation until separately published. After installation, open a new
terminal and use the same executable throughout the lifecycle:

```powershell
awf init
awf start
awf stop
awf update
```

The bootstrap installs only. `init` remains an explicit configuration review;
optional pairing and autostart have their own confirmations. Initialization and
installation never imply runtime start. An authenticated native OpenCode binary
and an existing workspace are prerequisites for setup, not bundled dependencies.

A verified fresh-release `awf.exe` also exposes public `install` directly.
It resolves the fixed publisher channel and asks before installing; `--yes`
permits unattended installation, `--allow-prerelease` separately approves previews,
and `--no-path` skips PATH registration. See [windows-cli.md](windows-cli.md) for
advanced pins, verification rules, initialization, and runtime behavior.

## Fresh means absent

Both entry points resolve the actual Windows `FOLDERID_UserProgramFiles` known
folder with `SHGetKnownFolderPath` and install its `AWF` child. This standard
per-user program location is normally `%LOCALAPPDATA%\Programs\AWF`; the API's
actual result is authoritative, with no LocalAppData fallback or path override.
See Microsoft's [known-folder reference](https://learn.microsoft.com/en-us/windows/win32/shell/knownfolderid).
Planning uses `KF_FLAG_DONT_VERIFY`, never `KF_FLAG_CREATE`, so an absent Programs
directory can be resolved without creating it. Bootstrap validates Programs, or
its existing direct parent when Programs is absent, and leaves creation to Go.
Only after consent and payload verification may native installation create the
missing Programs directory with ordinary inherited permissions. It rechecks the
parent's physical location and safety and never assigns or repairs Programs ACLs.

Both entry points require that resolved `Programs\AWF` root to be completely absent. They
refuse a healthy existing install, empty directory, credentials-only root,
partial install, file, junction, symlink, redirected or unreadable root.
No existing root is adopted, migrated, overwritten, repaired, or recursively
repermissioned. There is no force flag or historical-installer fallback.
The historical `%LOCALAPPDATA%\AWF` tree is outside this product's scope. It is
neither detected nor migrated, adopted, modified, or used as a fallback; its
presence does not block a fresh install at the resolved Programs root.

A healthy installation uses `awf update`. A partial or unknown installation
requires explicit diagnosis outside this fresh-install operation. Do not delete
state, credential files, or locks, relax ACLs, or rerun bootstrap as recovery.

## Ownership and trust boundaries

- PowerShell owns only native-host/profile preflight, official release retrieval,
  strict source/hash/archive/PE checks, private temporary staging, and invocation
  of the verified native executable
- It checks the protocol-3 capability even for exact-version pins, then invokes
  public `install --yes --archive ... --version ... --sha256 ...`; all installs
  also pass `--channel go-v1` and only approved previews get `--allow-prerelease`
- Native Go owns exclusive program-root creation, role-specific ACL checks, archive
  revalidation, release/capability identity checks, version activation, launcher
  creation, the fresh-v1 product marker, channel state, and persistent user PATH registration
- Program paths preserve supported ordinary inherited ACLs: trusted user/SYSTEM/
  Administrators writes and inherited read-only access for other principals.
  Credentials, state, private runtime/control records and logs are separate
  current-user/SYSTEM-only private trees, created with private ACLs from the start
- Native installation does not initialize, start services, pair credentials,
  configure firewall rules, enable autostart, or install other tools
- PowerShell verifies the installed launcher before updating process PATH and
  reporting success. It never writes user/machine PATH or installation-root ACLs
- User PATH adds only the installed bin, preserving unrelated entries; a child
  process cannot change its parent's PATH, so a new terminal may be necessary
- Package identity and handle-final-path checks fail closed; no alternate root,
  context bypass, environment rewrite, admin elevation, or subprocess escape exists

The ordinary bootstrap trusts publisher-controlled script bytes from a mutable
HTTPS branch before its checks can run. Checksums establish consistency with the
trusted publisher inputs; they are not independent signatures. An independently
reviewed, commit-pinned script and hash are the advanced alternative.

The existing release packaging remains unchanged: exact version tags,
architecture ZIP names, `SHA256SUMS`, and a three-file ZIP containing `awf.exe`,
`awf-node.exe`, and `manifest.json`. Only the channel capability value advances
to 3 when an actually reviewed and published fresh-install release is selected.

## Failure behavior

Preflight and consent refusals do not create an AWF root. Bootstrap also checks
source/hash/archive and the executable capability before native installation;
its temporary stage is removed on failure. Native installation rechecks the root
at creation time, so a root that appears during download is refused rather than
reused. Direct native installation can detect an invalid archive or executable
after exclusive root creation. Such a failure leaves a protected partial root
for explicit inspection, and future fresh-install attempts refuse it.

A PATH registration failure is reported as an incomplete finishing step after
installation. The error provides the explicit launcher command for configuration.
Do not rerun bootstrap. Unknown runtime or busy-job state continues to block
`stop` and `update`; fresh installation adds no force-stop or state deletion path.

## Native acceptance checklist

Run in a disposable, operator-approved ordinary Windows user profile. Do not use
an existing installation, production workspace, real paired credentials, or a
packaged-app shell as an acceptance shortcut.

1. Run PowerShell fixtures in Windows PowerShell 5.1 and PowerShell 7:
   `test_install.ps1`, `test_channel.ps1`, `test_entry.ps1`,
   `test_install_context.ps1`, `test_install_path.ps1`, and `test_fresh_install.ps1`
2. Independently identify ordinary and packaged hosts and run the read-only
   `test_install_identity.ps1 -ExpectedIdentity NoPackage` or `Packaged` gate.
   NO_PACKAGE alone is not evidence of an unredirected installation
3. Run native Go fresh-root/ACL/path fixtures with both existing and absent
   Programs folders and their real inherited ACLs. Confirm read-only planning and
   declined consent create neither Programs nor AWF. Observe the root's actual owner,
   DACL, inheritance, and descendants. Cross-compilation cannot prove these facts
4. Verify absent-root installation, exact launcher/version identity, final physical
   paths, protected program permissions, current-user/SYSTEM-only private data,
   user-PATH preservation,
   and new-terminal command resolution on AMD64 and ARM64 where available
5. Verify refusal with unchanged existing empty, partial, credentials-only, file,
   linked, redirected, and unreadable roots; race a competing root creation and
   check that no existing tree's data or ACL is changed. Confirm an unrelated
   historical `%LOCALAPPDATA%\AWF` tree is ignored and untouched; fail closed for
   an unavailable known folder, unsafe Programs, or missing direct parent
6. Verify mismatched/unknown channel protocol, historical binary capability,
   source/tag/hash disagreement, malicious archive, preview decline/EOF, native
   failure, and PATH failure. No false success or fallback installation may occur
7. Verify bootstrap does not run init. Explicitly review init, pair and autostart
   default-no prompts; use synthetic credentials and a nonproduction workspace
8. Exercise start/stop/update and guarded busy/unknown state; preserve unrelated
   processes, configuration, credentials, provider authentication, and job state
9. After separate publication approval, verify public assets from real transport,
   channel hashes/source/capability, then repeat the ordinary no-flags command.
   Local builds and fixtures do not establish public availability

Portable checks cover package determinism, exact asset/manifest contracts,
bootstrap static trust ordering, fresh-only ownership boundaries, and Go seams.
Native PowerShell execution, real Windows ACL behavior, live user PATH, and
end-to-end published installation remain explicit acceptance gates.
