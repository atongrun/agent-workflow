# Windows venv PID binding implementation report

## Root cause

On Windows, launching a virtual-environment `python.exe` can create a redirector process before
the real Python interpreter. `subprocess.Popen` returns the redirector PID, while `os.getpid()` in
`awf_listen.py` returns the interpreter PID. The node lifecycle previously required those values to
be equal, so it rejected a listener that had already acquired the correct role/repository lease and
connected to Agent Bus. Increasing the wait deadline could never make unequal PIDs converge.

A no-Bus, no-model process probe on the affected node directly observed unequal launcher and
interpreter PIDs. This also explains why unit and installed-wheel smoke tests passed: they simulated
one PID or checked CLI availability without starting a real venv child.

## Architecture correction

The lifecycle now separates three identities that the original implementation conflated:

- a random per-start `launch_id` binds the node process record to the listener lease;
- the listener's own PID remains the duplicate-listener and repository-conflict identity;
- the `Popen` PID remains the liveness and process-group signaling identity used by local stop.

Every node-managed start uses the same launch-identity contract on Windows, macOS, and Linux. The
listener accepts only the internal 128-bit hexadecimal form, and readiness/status/stop require its
exact match together with role, repository, and live launcher plus listener PIDs. Direct-PID
matching remains only for process records created before this field existed. Role/repository
identity alone remains insufficient. A stale lease cannot make a reused launcher PID signalable.
Conversely, a dead launcher with a still-live matching listener preserves its process record and
fails closed instead of declaring success, deleting evidence, or signaling the interpreter PID.

This avoids encoding a Windows parent-child special case in the common ownership contract. A
launcher may delegate through one or more processes without changing listener ownership, while
local stop still targets the process group deliberately created by the node.

## Regression contract

- Unit coverage proves exact launch-identity matching, rejects a different identity even when a PID
  happens to match, and retains direct-PID compatibility for old process records.
- Installed-wheel verification launches the wheel's real venv interpreter. Windows must observe a
  distinct interpreter PID whose observed parent is the `Popen` PID, while the lease carries the
  exact launch identity; POSIX must retain the direct PID observation with the same identity
  contract.
- Lifecycle tests prove start records and forwards the identity, and stop signals the launcher
  process group only after a differently numbered listener lease presents that same identity.
- Stale-listener regressions prove status is not `running` and stop does not signal when only the
  launcher PID appears live.
- Orphan-risk regression proves a live listener behind a dead launcher preserves the process record
  and produces a blocking diagnostic without signaling either PID.
- The child releases its own lease through the normal cleanup path; the test does not leave an
  orphan listener or manually mutate a lease.

Complete Linux, Windows, macOS runtime, and installed-wheel validation is delegated to CI under
the repository's macOS test policy.
