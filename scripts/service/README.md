# Listener service compatibility assets

The accepted lifecycle surface is profile-first:

```text
awf node install --profile <absolute-profile.json>
awf node start --profile <absolute-profile.json>
awf node status --profile <absolute-profile.json>
awf node logs --profile <absolute-profile.json>
awf node stop --profile <absolute-profile.json>
awf node restart --profile <absolute-profile.json>
awf node upgrade --profile <absolute-profile.json>
awf node uninstall --profile <absolute-profile.json>
```

The files in this directory are compatibility examples only. They accept one secret-free
`AWF_PROFILE` path and invoke the foreground listener contract; they must not assemble role, route,
tool, state, or remote arguments independently. New installations should use `awf node install`,
which renders a native launchd user agent, lingering systemd user unit, or Windows Task Scheduler
user task from the complete profile.

Tokens and other credentials remain in the profile-selected strict `dispatch.env`; no generated
unit, XML, command line, profile, or install record contains them.

## Windows prerequisites

The profile selects `lifecycle.mode=managed`, user scope, and `manager=auto` or
`task-scheduler`. The installing user must also own the active local Windows console session; an
RDP-only login is not in the current contract. The
generated task uses that user's existing `InteractiveToken` and a one-minute periodic reconcile
trigger. Its native definition explicitly selects `IgnoreNew` and unlimited action runtime. A non-zero listener exit
leaves desired state running so the next trigger recovers it; a clean Agent Bus shutdown records
stopped. It accepts no password, requires no operator-authored XML, and invokes no PowerShell.

## Persistence claims

- `lifecycle.mode=session` is an interactive local process. `awf node start` refuses to claim SSH
  durability and requires `--allow-session-bound` for an explicit temporary remote session.
- `lifecycle.mode=managed` is supervised by the native user manager. Agent Bus remains transport only;
  lifecycle commands never inspect, ACK, requeue, resend, or dispatch deliveries.
- Windows post-SSH durability is accepted only after the session A/B matrix in
  `docs/runtime-node-lifecycle-architecture.md`. CI or a same-session smoke is not that proof.

Agent Bus `control:shutdown` is the normal graceful remote stop. Local `awf node stop` remains an
independent exact-bound manager/process-tree action and does not require that control event.
