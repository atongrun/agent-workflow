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

The files in this directory are compatibility examples only. They now accept one secret-free
`AWF_PROFILE` path and invoke the same foreground contract; they must not assemble role, route,
tool, state, or remote arguments independently. New installations should use `awf node install`,
which renders a native launchd user agent, lingering systemd user unit, or WinSW definition from
the complete profile.

Tokens and other credentials remain in the profile-selected strict `dispatch.env`; no generated
unit, XML, command line, profile, or install record contains them.

## Windows prerequisites

The profile must select `lifecycle.mode=service`, include the absolute WinSW v2.12.0 binary path
and SHA-256, and name a pre-provisioned least-privileged `service_account`. Agent Workflow never
downloads WinSW, accepts a password, or falls back to `LocalSystem`.

The first install renders and registers a password-free service, then fails closed until an
administrator binds the account directly in SCM. Follow the exact `sc.exe config ...` instruction
printed by the CLI, rerun `install`, then use `start`. Grant only Log on as a service plus access to
the fixed wheel, profile, dispatch config, dedicated checkout, state, logs, and selected model CLI.

## Persistence claims

- `lifecycle.mode=session` is an interactive local process. `awf node start` refuses to claim SSH
  durability and requires `--allow-session-bound` for an explicit temporary remote session.
- `lifecycle.mode=service` is supervised by the native manager. Agent Bus remains transport only;
  lifecycle commands never inspect, ACK, requeue, resend, or dispatch deliveries.
- Windows post-SSH durability is accepted only after the session A/B matrix in
  `docs/runtime-node-lifecycle-architecture.md`. CI or a same-session smoke is not that proof.

Local stop is always a manager/process action. It does not require `control:shutdown`.
