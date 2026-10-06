# One-VM native acceptance of the Pi update umask candidate

Application source is frozen at `3c5ffcca9b432d71bf61739089646ac8856a8702`.
Packaging is frozen at `761e78c7ea1664fbc96cabc919868ab243ca7cbd` without
workflows. This checkout adds only the bounded acceptance harness and one push
workflow on `awf/linux-pi-umask-native-ci-v1`. One standard Ubuntu 24.04 job,
with a 30-minute maximum, builds and publishes new RC4/RC5 pending-acceptance
prereleases and performs both fresh native phases. Its 18 asset pins were fixed
from independently reproduced builds before the trigger. Existing tags/assets,
Windows RC9, main and archive remain untouched.

Phase A uses the public RC4 bootstrap, init/start/stop, official bare Pi update
under a root child shell's `0002` umask, and RC4 to RC5 AWF update. It verifies
the sole Pi prefix, safe root-owned modes, real version changes, configuration,
generated credentials, synthetic task and service-agent state preservation.
No provider authentication or model request is performed. Only `/opt` and
`/usr/local/bin`, both initially root:root physical `0777` directories, may be
temporarily changed nonrecursively to `0755`; the private write-ahead receipt
records the original inodes and restores them before either phase completes.

The workflow uploads a bounded safe JSON report after phase A and cleanup.
It waits at most ten minutes for an external control-plane review of that exact
report to publish the new independent `awf/linux-v1` channel with the fixed RC5
manifest. The workflow itself cannot broaden that channel condition. The
coordinator must stop channel publication on any acceptance, cleanup, restoration
or protected-reference failure. No remote command loader is involved.

Phase B uses the public default bootstrap with no version or manifest override,
then init/start/health, bare `awf update` no-op, stop and owned cleanup on the
same freshly cleaned VM. At least fifteen minutes of the bounded job deadline
must remain before this phase can change either parent directory. All native
commands run with a cleared environment; the short-lived publication token is
passed only to release metadata steps. Raw logs and private receipts are never
uploaded. A first unsafe Pi path/owner/mode or bounded static error classification
is included on failure.

Only after both phases, artifact uploads, cleanup and original inode/mode
restoration pass may the two new prerelease descriptions record native acceptance.
They remain prereleases and do not replace GitHub's latest release. RC2/RC3
upgrades to these candidates are unsupported. Ubuntu 22.04 acceptance remains
pending. A failed run does not authorize another VM or a workflow push retry.
