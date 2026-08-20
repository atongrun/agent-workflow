# RTS-042 ImplementationReport

Status: **EXTERNAL_BLOCKED after the first live send; preserved-event boundary active**

## Candidate

- TaskCard: `runtime-v2-rts-042-cross-machine-acceptance`
- Candidate: `dac916c3cdc73a33f83fae4eb578e5001ecd6601`
- Pull request: `atongrun/agent-workflow#115` (Draft)
- Agent Bus: v0.3.0 at `6ca8f2812be0286607bbbe3f14cc51783637b0b5`
- Acceptance scope: `rts042-live-20260820-01`
- Windows state-root binding:
  `sha256:213fb243b6acc6ceaf503144723a61074c36528003d80075ebc1e5614f9267af`

The fixture remains within its 450 nonblank/noncomment line budget at 446 lines. The focused test
module remains at 236 lines. The branch changes only the frozen TaskCard, its fixture/test, and this
allowed Artifact. No Runtime Core, production handler, Agent Bus, workflow, dependency, default,
migration, release or compatibility path changed.

## Deterministic and CI evidence

- Local credential-free checks passed: compileall, direct bounded-child subprocess, Store/sender
  smoke, complete two-handler fake-CLI smoke, AST boundary, LOC and `git diff --check`.
- The first candidate CI exposed only Ruff layout and those L1 repairs received focused static
  validation.
- Windows then exposed host-newline-dependent child bytes. Candidate `dac916c` changed the child to
  emit a newline-free digest; the direct subprocess oracle passed on Mac.
- Exact-head CI run `32381960259` passed Linux, macOS, Windows, installed-wheel, Ruff, all tests,
  resource validation and workflow semantics. Windows ran 869 tests with the focused RTS-042 test
  passing.
- Exact-head Binary Feasibility run `32381960181` passed on attempt 2. Attempt 1's sole failure was
  the known external GitHub API `403 rate limit exceeded` while macOS ARM fetched
  python-build-standalone; only that failed job was rerun, without a code change.

## Fresh isolated setup

- A new Bus process, SQLite database, server state, three distinct role credentials, fresh Mac and
  Windows checkouts, Python 3.12 environments, installed packages, role state/evidence roots and
  listener identities were created only under the scope above.
- Exact candidate and Agent Bus SHAs matched on both worker hosts. Installed
  `agent_workflow.runtime` and Agent Bus client imports passed from an unrelated working directory.
- No production endpoint, queue, database, state, retained event or payload was queried or changed.
- The first short-host endpoint failed before any queue result or event. The isolated server's exact
  PID/cwd/local health was good; replacing only the disposable credential URL/NO_PROXY with its
  current Tailnet address restored cross-host access. No Bus, token, role, port or database identity
  was replaced.
- Payload-blind baselines were exactly `coder=0`, `reviewer=0`. Mac reviewer and Windows coder then
  registered only `control:awfv2-result-v1` and `control:awfv2-command-v1`, respectively, with
  structured argv, ACK-on-receive disabled, one-event lifetime and one persisted failure attempt.
- The initial PowerShell listener launch rejected malformed local `--on-argv` JSON before Bus
  connection or event consumption. A temporary native Python argv launcher preserved the same
  handler JSON as one token. The original Mac listener expired idle during that repair and was
  restarted under the same role/route before the first send. These were pre-send setup facts, not
  event retries.

## First-send result and mandatory stop

The architect fixture submitted the one authorized command and recorded explicit HTTP/CLI send
success. No second command send occurred.

The intended acceptance did **not** pass:

- the isolated database contains exactly one record, event `1`, route
  `control:awfv2-command-v1`, `architect -> coder`;
- its durable status is `failed`, `retry_count=1`, with a last-error fact present;
- there is no result event and no Windows target-completion evidence;
- the disposable Windows Store directory exists, and the handler's credential-safe marker reports
  `AcceptanceError`;
- both payload-blind pending counts are zero only because the command is terminal failed, not
  because two handler-success ACKs converged; and
- the outer one-shot listener process returned zero even though Agent Bus durably recorded the
  handler failure, so process exit alone is not acceptance or ACK evidence.

This is the TaskCard's explicit post-send stop condition. The run is `EXTERNAL_BLOCKED`. No resend,
manual ACK, requeue, replacement event, identity replacement, model, provider or business handler
was attempted. Diagnostics projected only payload-blind database fields, evidence-path existence
and boolean error markers; no payload content was emitted or copied into repository evidence. The
exact isolated server process was stopped only after PID/cwd/argv validation; its database, logs,
state and host evidence remain retained. Mac and Windows scoped evidence/resources also remain
retained. No production process or service command was issued.

## Gate consequence

RTS-042 is not complete, Phase 4A is not passed, and no TaskCard Gate Review, Phase 4B start,
production adoption, migration, default switch, launcher, release or cleanup is authorized. The
zero event-level retry budget prevents diagnosing by replaying or replacing this delivery. Any
fresh attempt requires a separately frozen identity and explicit owner authorization; the retained
failed event must never contribute to a future PASS.

## Root-cause analysis and classification

Read-only retained-state diagnosis closed the causal chain without replaying the delivery:

- Agent Bus delivered event `1` to the Windows coder listener. The listener launched the child
  handler process, which exited `2` after about `0.2s` with the fixture's credential-safe
  `AcceptanceError` marker.
- The handler did not launch its bounded proof child. The disposable state root contains no
  `authority.json`, journal, authorization, launch intent, provider result, validation effect,
  outgoing intent or transport-send observation. No target evidence exists.
- No result event was generated. Therefore no result was lost, rejected by the Mac consumer or
  left unreconciled by the local Runtime.
- The Windows Agent Bus listener called its normal `/events/1/fail` endpoint after the handler's
  nonzero return. The isolated Bus server's `record_failure` transaction incremented the prior
  count from zero to one and, because the listener was explicitly bounded to
  `max_event_attempts=1`, wrote terminal `status=failed`, `retry_count=1` and the last-error fact.
  Neither Runtime v2 nor the fixture wrote that Bus retry count.

Both hosts were on the exact same candidate Git commit, yet their working-tree byte hashes differed:

| Frozen input | Git blob / Mac SHA-256 | Windows working-tree SHA-256 | Windows CRLF lines |
| --- | --- | --- | ---: |
| TaskCard | `e0653b3442e3795e2ac3219d1de561e9e0528eb43ea1af613a42a0d5884f63b2` | `271ab8109bda79f19eae6f502fa2f7d8a251a150f1b21669cc23b1a53448039f` | 223 |
| Frozen semantic contract | `b54e55bd1cd7471b26d359eb8b630d330adadb8dea1b09378321658b7e31404b` | `c094043a99e3abf3c03f05cc2ee4bc0be7163b9527e44f0f21550db11ad37d36` | 453 |

The Windows Git blob bytes hash exactly to the Mac values. `make_spec` had read host-normalized
working-tree bytes, so Mac and Windows independently constructed different immutable RunSpec
identities. The command was rejected at exact-envelope comparison before the proof child and Store.

Failure classification: **(e) acceptance fixture**, specifically an L2 cross-platform
provenance-glue defect. Transport delivery succeeded; remote handler execution started and
failed closed before its bounded child; result return and local Runtime reconciliation never
began. This does not require or justify a Runtime authority, Agent Bus, ACK, ordering or Frozen
boundary change.

The bounded repair reads the two frozen inputs from their exact candidate Git blobs rather than
the platform-normalized checkout, retains the same RunSpec fields and SHA-256 semantics, adds one
focused regression, and leaves production code unchanged. Per the owner's diagnostic continuation,
the recommended next TaskCard/gate is exactly one fresh isolated acceptance identity,
`rts042-live-20260820-02`, after exact-head CI. The failed `-01` identity remains permanently
`EXTERNAL_BLOCKED / evidence preserved` regardless of the continuation outcome.
