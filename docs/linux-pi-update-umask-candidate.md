# Fresh-install Pi update umask candidate

This local candidate starts at `510e6b893c6524873297b972edc72e801b870b0d`.
Its only application change is in the Linux shared Pi launcher: immediately
before execve, root with first argument exactly `update` sets the current process
umask to `0022`. The official Pi CLI, npm arguments and single global prefix are
retained. No system account, service, production path, release asset or channel
is changed by preparing this candidate.

## Evidence and limits

The actual Ubuntu 24.04.5 diagnostic
[run 37415293853](https://github.com/atongrun/agent-workflow/actions/runs/37415293853)
installed public RC2, initialized and started/stopped services, and updated
official Pi from 1.0.2 to 1.0.4. The following start failed before service
activation with `system path ownership, type or permissions require inspection`.
Cleanup and restoration passed. That VM did **not** record the failed inode or
its inherited umask. Its failure is consistent with this candidate cause; the
cause was not conclusively located on that VM.

Separate controlled local npm replacements of fresh, normalized Pi 1.0.2
fixtures produced these results; they ran as UID 1000, never actual root:

| Inherited mask | Updated package directory | Updated package.json | Unique group/other-writable entries |
| --- | --- | --- | --- |
| `0002` | `0775` | `0664` | 16,460 |
| `0022` | `0755` | `0644` | 0 |

The candidate's opt-in launcher regressions use the verified Node 22.19.0 binary
and simulate only `process.getuid()`. Ten cases check root update under `0002`
and `0077`, root version/RPC/prompt/other/no-command cases, case-sensitive command
matching, and non-root updates under both masks. They compare execve PID/argv,
child mask and newly created file/directory modes, and verify the parent process
keeps its mask. No Go test process changes its own umask.

A second opt-in test runs the **real official Pi 1.0.2 CLI and npm updater**
with the latest-version HTTP response fixed to cached 1.0.4. npm runs offline
with scripts disabled and a cooperative JavaScript guard rejects real socket
attempts. The fixture now keeps the complete production `lib` layout, including
`package.json`, `package-lock.json` and `node_modules`. Before reading updated
package identity or running its CLI, it uses `Lstat`, the original native
package-file and parent checks, and the original relative/in-prefix link rules
for every prefix entry. It preserves the prefix inode, launcher bytes and parent
mask. Updated Pi also runs offline version, read-only `get_state`, PID/stdio and
AWF four-tool checks. This remains UID 1000 local evidence with a simulated
JavaScript root query, not actual root/systemd acceptance or kernel isolation.

The former fixture skipped every symlink and used `Stat` for package modes;
its successful mode inventory did not establish complete native trust. The new
default regressions reject external and internal package-root links, a linked
package JSON, absolute links even when their targets are inside the prefix,
escaping relative links and writable physical package directories. Safe relative
links inside the prefix remain accepted.

The subsequent real Ubuntu 24.04 [run 37419819716](https://github.com/atongrun/agent-workflow/actions/runs/37419819716)
installed and passed initial init/start/health/RPC/stop, then bare `pi update`
exited 0. Prefix validation failed at the package root with UID/GID 0 and mode 0777.
That report omitted object type, link target, realpath and actual npm argv; it
cannot identify a physical writable directory or symlink, or confirm the
updated installed version. The failure therefore does **not** establish that
the launcher umask change resolved the actual problem. The post-Pi service,
AWF replacement and default-entry gates remain incomplete.

Four separate local official 1.0.2-to-1.0.4 runs used canonical registry package
arguments and produced physical 0755 package roots. Adding the two missing
manifests, reproducing the CI cwd/default config locations, and retaining an
actual production-prepared runtime did not reproduce the native failure. Real
npm directory and `file:` directory controls produced 0777 external package-root
symlinks. Those controls prove a possible mechanism and the old test blind spot,
not what the finished VM actually installed.

Default adapter regressions still reject writable package files/directories,
deep writable files, writable launchers and changed launcher bytes before any
machine command or receipt rewrite. Existing AWF replacement tests retain
updated Pi and its provenance. The application ownership, permissions and exact
launcher checks are unchanged.

Reproduction, with separately approved private fixture directories:

```sh
umask 022
AWF_PI_INSTALLED_FIXTURE_DIR=/tmp/approved-pi \
AWF_PI_UPDATE_NPM_CACHE_DIR=/tmp/approved-update-cache \
go test ./internal/hostinstall -run '^TestPiLauncher' -v
go test ./internal/hostinstall -run '^TestNativePiUpdate' -v
```

Default test runs skip downloaded executable fixtures. The latest-version response
is a test fixture, not a replacement updater or a production environment flag.

## Compatibility boundary

This is a **fresh-install candidate**. RC2/RC3 embed the former launcher (648
bytes, SHA256 `f6eb186b77cbe07667321ac9d338074b3b7143d14904c62e0ab294a457aff07f`).
AWF replacement deliberately preserves the entire Pi prefix and original Pi
receipt. A newer Host therefore rejects that older launcher at its exact byte
check. This candidate neither allows legacy launcher bytes nor rewrites an old
launcher or recursively chmods an existing tree. RC2/RC3-to-this-source upgrade
is not supported by this candidate and must not be reported as verified.

The next cross-version acceptance must start from a fresh install and use two
immutable Linux previews built from the same frozen candidate source, so
their launcher bytes agree. Supporting earlier failed previews would be a
separate compatibility decision and is outside this minimal fix.

## Fixed minimum diagnostic checklist

This checklist is the prerequisite for a future independently authorized run.
This test-only candidate does not change or activate the VM collector. Amend and
review the existing harness at these fixed points before a parent chooses to run
it; do not add a general diagnostic framework or rely on raw logs after cleanup.

| Fixed point | Required bounded evidence |
| --- | --- |
| Before updating | Product/harness commits, launcher/Node/npm hashes, Node/npm and trusted installed Pi versions, actual UID/GID, prefix inode, parent shell umask and actual Node CLI/npm child UID/umask observations, cwd. |
| Actual npm child spawn | Executed command/executable and argument array, inherited cwd and exact install source; classify registry name/version, remote tarball, directory or `file:` directory. This must observe the executed spawn, not only `getSelfUpdateCommand()`'s proposed command. Observe without replacing npm, its arguments, cwd, UID, umask or live release response. |
| Immediately after exit, before any trust assertion | Exit/signal, elapsed time, parent mask after, bounded updater-reported semver and requested package/version from actual argv. Persist this before a later assertion can fail. |
| Package root, package JSON, launcher and first unsafe prefix entry | `lstat` type, octal mode, UID/GID, device/inode; symlink `readlink`, resolved `realpath`, absolute/relative and inside/outside-prefix result; physical-directory or physical-file predicate and specific failed checks. For a non-link, record `readlink=null`. `0777` symlink bits alone are not writable-directory evidence. |
| Installed version | Read bounded package identity only through trusted physical parents and a non-linked regular package JSON. Record unavailable reason if trust fails. Execute `pi --version` only after the complete prefix/launcher trust guard succeeds. Keep installed version, CLI version and updater-reported version separate. |
| Failure and cleanup | Preserve the above safe JSON even when validation fails. Record skipped later gates, owned-process/path cleanup and parent inode/mode restoration; never substitute updater exit 0 for acceptance. |

Collect paths only under `/opt/pi-cli`, `/opt/node`, the fixed approved private
control directory and the recorded checkout; at most one extra first-unsafe
object under the Pi prefix. `readlink`/`realpath` observe path strings only: never
read an external target's contents. Bound strings to 4096 characters and
serialize as escaped JSON. Unexpected, oversized or credential-shaped argv/link
values must have an explicit redacted/unavailable reason and digest; do not drop
the entire object record. Retain safe expected source forms and approved
controlled directory paths; do not output environment variables, npm configs,
auth/model stores, URL userinfo/query secrets or uncontrolled stdout/stderr.
Cap private update output at 1 MiB and parse only allowlisted version/umask markers; record output-limit or marker-unavailable reasons without emitting raw output. Errors
in observation must be recorded distinctly and must not weaken the trust gate.

## Proposed scope of one later Ubuntu VM

No VM, push, release or channel write is authorized or performed in this round.
The parent can decide a single bounded diagnostic run using the existing frozen
RC4 source `3c5ffcca9b432d71bf61739089646ac8856a8702` and existing immutable assets,
without new preview publication. Its manifest SHA256 is
16d41c68eff5984de5105093f1c2b3be6264ffbf83207d7d62971b2bf97a81f5.
The test candidate adds no product behavior; a future harness collector needs its
own exact reviewed commit before execution.

Use one Ubuntu 24.04 amd64/glibc/systemd VM, one run/attempt, no automatic retry,
at most 30 minutes including cleanup. Run preflight and owned-path ledger,
explicit-version public fresh installation, init/start/health/read-only
production-extension RPC/stop, one bare official root `pi update` under parent
umask `0002` with a fresh private HOME, then the fixed observations above. On a
trust failure stop and clean up immediately. If trust succeeds, verify trusted
version identity and one post-Pi start/health/read-only RPC/stop. This slice does
not advance AWF cross-version or default-channel acceptance.

The real mutation scope is only the newly absent AWF program roots
`/opt/node`, `/opt/pi-cli`, `/opt/awf`, `/opt/magpie`; command links
`/usr/local/bin/{awf,pi,magpie}`; newly created non-login `awf` account/group;
`/etc/awf`, `/var/lib/awf`, `/var/cache/awf`, newly owned
`/var/cache/awf-installer`; the two literal AWF unit files and their
daemon-reload/start/stop; fresh private `/tmp/awf-native-ci-*` work and named
installer scratch. The two services may bind only their existing loopback
ports 7070/3425. If needed, separately include the existing narrow parent-mode
preparation for physical `/opt` and `/usr/local/bin`, recording original
inodes/modes before changing only those two parent modes and restoring them.

Cleanup may remove only ledger-owned objects with unchanged identities, stop
only owned units/processes, preserve preexisting system Node/npm/npx and restore
recorded parents; upload only bounded safe JSON. No provider authentication,
model request, production VPS, firewall, foreign-service change, new cloud
purchase, preview publication or Linux channel mutation belongs to this scope.
The current native failure remains unresolved until adequate actual evidence
exists; the parent must not infer that this test fix or umask candidate resolves
it.
