# Fork/PR live-proof closeout — 2026-07-29

## Outcome

The post-merge Git/PR publication path passed across Mac and Windows. Windows operated as a
contributor: it fetched the read-only upstream, wrote only to `torin-sun/agent-workflow`, freshly
matched the fork ref, and created upstream proof PR #30. Mac then fetched the explicit persisted PR
provenance and reviewed exactly the recorded head SHA. No upstream push permission was required or
tested.

The Agent Bus portion ran but did not close. After the user authorized event handling, historical
coder events #97 and #100 were classified and terminally ACKed without executing their obsolete
product TaskCards. Fresh event #102 completed the Windows coder side through verified PR #31, but
its reviewer delivery is retained unACKed because the Windows send path is unavailable. The Mac
reviewer queue remained empty.

## Exact Git and PR evidence

- Merged fork/PR runner baseline:
  `88c70012697510c9959a7823d6af5529b5fe0395`.
- Contributor fork initial TaskCard commit:
  `e8701db57d9f9d0744b2f085fa258e1838e10f2a`.
- Trusted-runner implementation commit and freshly verified fork head:
  `fa4138af4a3d0acec1d26cec04335615c519c2fe`.
- Upstream PR: #30, base `main` at the merged baseline, head repository
  `torin-sun/agent-workflow`, and head ref `proof/fork-pr-live-20260729-a`.
- Mac reviewer routed `decision:awf-ready-v3` with `PASS` for that same head SHA and PR number.
- Agent Bus coder event #102 published fork head
  `eab746827484619d76ae577ed5e995abecff4b6b` in PR #31 with the same upstream base tuple.

The coder and reviewer adapters were deterministic proof subprocesses. Both ran in the production
no-remote model workspace boundary. They did not receive Git credentials or publishing remotes.
All commit, push, fresh fetch, PR inspection, and event construction actions remained in the
trusted runner.

## Fail-closed races found and corrected

GitHub accepted PR creation, but `gh pr list --head` remained empty while direct PR-number lookup
already returned the exact PR. The Windows handler failed closed after the fork push:

- no reviewer event was emitted;
- no input event was ACKed;
- durable evidence retained the completed postflight, commit, push, and failure state;
- the coder model was not restarted during recovery.

The follow-up correction captures only the canonical GitHub PR URL returned by trusted
`gh pr create`, strictly validates its repository path and positive number, then verifies that
exact PR's full tuple. It does not parse stderr, expose CLI output, weaken the exact tuple check,
or accept a branch-only handoff. Existing PR reuse still requires exactly one unambiguous match.

The live Bus attempt also proved that v3 initial implementation legitimately carries numeric
`pull_request: 0`. The control plane previously passed that integer to a bounded text field and
denied the run before model invocation. The follow-up normalizes the value to text at the context
packet boundary and locks `"0"` with a pre-model regression test.

## Verification contract

Regression coverage proves:

- PR creation uses the exact returned number without branch-list rediscovery;
- non-canonical, cross-repository, userinfo, query-bearing, or nonnumeric PR results fail closed
  without being logged;
- existing PR reuse still avoids creation;
- v3 initial PR zero persists through the control plane before model launch;
- reviewer fetches the explicit fork ref and verifies the persisted PR head before model launch.

The complete focused/full test, lint, role/workflow/example validation, independent review, and
GitHub CI results belong to the follow-up PR closeout.

## Remaining boundary

This is a complete Git/PR trust-boundary proof, not a complete Agent Bus lifecycle proof. Event
#102 must remain unACKed until its exact PR #31 reviewer handoff succeeds after Bus connectivity
returns. Do not restart the coder model or create another proof event.

Event #101 also exposed an existing recovery limitation: once a control-plane authorization is
recorded but a tool fails before any durable downstream outbox exists, replay of the same event is
rejected as a duplicate. That event was terminally closed under explicit event-handling authority.
The limitation remains a separate design risk; this follow-up does not weaken duplicate protection.
