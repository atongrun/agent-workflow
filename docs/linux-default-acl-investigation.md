# Default ACL investigation and local staging candidate

The actual Ubuntu24 diagnostic run37431059458 reported official Pi update exit0,
replacement physical package directory0777, package.json0666, and a real root
npm process umask0022. It did not capture inherited default ACLs or effective
npm configuration. This document does not retrospectively claim those missing
observations. The new evidence proves a matching filesystem mechanism locally.

## Environment and fixed inputs

The recovered executor is Debian13 amd64, kernel UID/GID1000, PID1tail. Existing
source0deba4bb and the native report/private handoff hashes match. Public remote
has235refs and22releases. Compared with the saved baseline, the only ref change
is the previously authorized diagnostic commit1b83173b; every release/asset
id,size,digest,update time is unchanged. No production host or secret was read.

`/tmp` is tmpfs and rejects setting a default ACL with ENOTSUP95. `/workspace`
overlayfs supports them. Every ACL proof is inside a newly created0700
consumer-owned private directory under `/workspace`; no real /opt, /usr/local,
account or service was modified. Tests that run on unsupported filesystems skip
the ACL case explicitly. No unsupported result is represented as a passing
physical ACL test.

Official Node22.19.0/npm10.9.3 and previously verified Pi1.0.2/1.0.4 cached inputs
are unchanged. The official update runs offline with ignore-scripts and all
real socket attempts denied by the existing JavaScript guard. The latest-version
HTTP response and Node processes' JavaScript UID queries are simulated; actual
kernel UID is1000. Pi and npm source/arguments are otherwise retained.

## Mechanism and controlled results

Linux uses a parent's default ACL instead of process umask when creating an
object, with permissions limited by the explicit requested mode.
[umask(2)](https://man7.org/linux/man-pages/man2/umask.2.html)
Chmod changes current access permissions; a directory's default ACL separately
governs new children. [acl(5)](https://man7.org/linux/man-pages/man5/acl.5.html)

An initial0755 program directory can therefore retain default owner/group/other
rwx permissions. Installer chmod normalizes current mode but retains that latent
inheritance. npm's Arborist creates package directories with an implicit0777
request; pacote with config mask0 opens ordinary files with0666. Those requests
plus the inherited ACL produce0777/0666 despite process umask0022. No directory
tarball entry or chmod of the replacement package is needed to explain this
controlled reproduction.

All four cases run the real official Pi1.0.2→1.0.4 updater under observed0022,
from the same normalized initial physical tree with full npm manifests. Each
changes the package-root inode, retains the stage and parent identities, and
keeps the shared parent's ACL unchanged:

| Initial condition | Launcher/config | Updated package root | package.json | Unsafe unique physical objects |
| --- | --- | --- | --- | --- |
| No default ACL | old3c5ffcc, npm mask0 | 0755 | 0644 | 0 |
| Inherited writable default ACL | old3c5ffcc, npm mask0 | 0777 | 0666 | 16451 |
| Same inherited ACL | old0deba4bb npm-mask candidate, mask022 | 0777 | 0644 | 139 |
| Clear default ACL only on new private stage before children | old3c5ffcc, npm mask0 | 0755 | 0644 | 0 |

For package.json, actual fs.open observation requests0666 and observes0666 only
in the inherited-ACL case; without that ACL it observes0644 under the same
process mask. Explicit npm config022 requests0644, but implicit package-root
creation remains0777. This rejects the previous npm-mask candidate as sufficient
under this reproduced condition. It does not show that the old Ubuntu runner had
this ACL; that remains the next native observation.

A separate fresh inherited-ACL case observes npm's actual fs.promises.mkdir:
requested mode0777, recursive=true, resulting physical mode0777, process mask022.
Its actual fs.open requests0666 and produces0666 for package.json. These bounded
observations use the same official CLI/npm and retain launcher source bytes;
they do not infer creation modes from tarball headers or symlink metadata.

## Minimal local Go candidate

Start at3c5ffcca, preserving its existing root-update process umask and official
Pi npm path. Do not add the unsuccessful0de npm environment override. Immediately
after creating/opening each private .awf-install-/.awf-update- stage, before any
program children, open that root directory through os.Root. Require an owned
physical directory with exact0700 and no setuid/setgid, then remove only its
system.posix_acl_default through fremovexattr on the directory descriptor.
ENODATA and EOPNOTSUPP are harmless absence/unsupported cases; other errors fail
before copying or promoting program roots. Current mode, owner and inode remain
unchanged. Children no longer inherit the default, and rename retains that state.

The helper is used by fresh install and AWF program replacement. It never opens
or changes /opt or another shared parent's ACL, never walks an existing Pi tree,
never changes an existing installation, and never runs recursive chmod as a
repair. AWF update still preserves the sole official Pi prefix/provenance. This
is a fresh-install prevention candidate; existing affected prefixes are not
migrated or repaired. The previous reviewed b955 physical/link fixture correction
is included, and trusted remains strict.

Kernel ACL tests exercise inherited default retention despite chmod, descriptor
removal, unchanged private identity/mode, unchanged parent ACL, inheritance after
promotion, public-directory refusal, and real installPrepared/replacePrepared
filesystem staging. Account/systemd calls in those adapter fixtures are
substituted and do not establish actual root/systemd service separation.

Run the three ACL tests separately with TMPDIR on an ACL-capable filesystem.
The existing broad fixture suite deliberately requires its sandboxes beneath
/tmp, so retain TMPDIR=/tmp for the full/race suites; its unsupported ACL cases
skip. Using /workspace for the broad suites is an invalid test configuration,
not a supported override of the fixture guard.

## Native gate requiring new authorization

No additional VM, branch push, release, channel promotion or system permission
change is authorized by these local results. The previous one-shot permission
was consumed. A useful next native iteration must first record bounded numeric
default/access ACL metadata for /opt and the Pi parent chain, effective npm umask,
actual creation modes and the objects' lstat identities. It must preserve the
existing report-before-guard and cleanup checks. The exact action, public branch,
workflow commit, one-run timeout, path/mode changes and cleanup obligations must
be reviewed by the parent before any trigger. Do not retry the old unchanged RC
test or publish another candidate to learn the cause.
