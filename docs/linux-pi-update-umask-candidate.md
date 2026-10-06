# Fresh-install Pi update umask candidate

Status: the later actual Ubuntu run 37431059458 still failed after this change.
Process umask alone does not prevent writable objects when an inherited default
ACL grants them. The controlled reproduction and current fresh-install staging
candidate are recorded in [linux-default-acl-investigation.md](linux-default-acl-investigation.md).
The historical local evidence below does not establish native acceptance.

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

A second opt-in test runs the **real official Pi 1.0.2 CLI and npm updater** with
the latest-version HTTP response fixed to cached 1.0.4. All real socket attempts
are denied by the cooperative JavaScript guard; npm runs offline with scripts
disabled. The launcher starts under `0002`, preserves the sole prefix inode and
launcher bytes, and leaves 31,583 prefix entries passing the unchanged local
ownership/type/mode guard. Package files are `0644`, directories `0755`. The
parent still has `0002`. Updated Pi 1.0.4 also passes offline version, read-only
`get_state`, PID/stdio and AWF four-tool registration checks. This is local
process/filesystem evidence, not actual root/systemd acceptance or kernel network
isolation.

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
new immutable Linux previews built from the same frozen candidate source, so
their launcher bytes agree. Supporting earlier failed previews would be a
separate compatibility decision and is outside this minimal fix.

## Fixed plan for the next single Ubuntu VM

No VM or publishing is authorized in this local round. Before starting a new
VM, obtain approval for the exact candidate commit, two new immutable Linux
preview versions/assets/manifests, one Ubuntu 24.04 amd64 systemd VM, the narrow
fixed system writes/parent-mode restoration, and the independent Linux channel
write needed for the default-entry phase. Retain Windows RC9, main/archive/tags,
and existing RC2/RC3 assets unchanged.

Do not spend a VM on a partial sequence if the default-channel approval or
publication timing remains unresolved. Either explicitly authorize the reviewed
preview channel before the VM, or approve its conditional publication after the
explicit-version phases pass on that same VM. The latter needs parent/control
plane coordination, not a remote command loader or candidate execution framework.
Until an actual channel exists, a missing-channel refusal is not default-install
acceptance.

1. Record platform/PID1/systemd/cgroup, actual root umask, preexisting command
   links, and the narrowly scoped private cleanup/parent-mode receipt. Use the
   public bootstrap with the older new preview's explicit version and consent.
   Verify hashes/progress, one Pi prefix, private Node, root's default
   `~/.pi/agent`, service `/var/lib/awf/pi-agent`, init, start, health, read-only
   production-extension RPC, and stop/process-group exit.
2. In a root child shell under `umask 0002`, execute bare official `pi update`.
   Verify the shell mask remains `0002`, prefix inode remains, version/package
   agree, scripts stay disabled, and the package JSON, directory, executable
   and complete prefix have root ownership and safe modes. Preserve one bounded
   safe first-error code/path/mode observation on failure, not private raw logs.
3. Start, health/RPC/tool-check and stop again. Use `awf update --version` to the
   newer new preview. Verify real version change, progress, durable consent,
   current Pi version/tree and service config/state retained, then start/health/
   RPC/stop. A successful same-version no-op is not cross-version acceptance.
4. After the approved independent Linux channel names that exact newer manifest,
   perform scoped cleanup to a fresh state and use the **public default
   bootstrap without a version/manifest override**. Verify the selected newer
   version, init/start/health/read-only RPC/stop and bare default `awf update`.
   Verify channel/tag/source/manifest agreement and preview-consent behavior.
5. Always stop only owned units/processes, remove only recorded owned paths,
   preserve preexisting system Node/npm/npx, restore both recorded parent
   inodes/modes, remove the private receipt, and upload only bounded safe JSON.
   Mark acceptance true only if every required phase and restoration passed.

New VM execution, asset publication and channel writes require the parent's next
explicit action approval. No production VPS, credentials, new listener/firewall,
model calls, CloudCone work or new cloud purchases are part of this plan.
