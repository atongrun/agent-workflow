# Fork/PR-aware Trusted Runner Implementation Report

## Summary

The operations runner now has an explicit v3 fork/PR publication contract. A contributor machine
fetches a configured upstream repository but pushes only to its configured fork. The trusted
runner, never the model, commits the verified delta, pushes the exact fork ref, freshly verifies its
SHA, creates or reuses one matching pull request, verifies the live pull-request tuple, and
persists that tuple before sending the reviewer handoff.

Windows upstream write permission is intentionally unnecessary. The runner neither pushes to nor
tests write access against the upstream remote.

## Versioned contract

Default operations routes are now:

- `task:awf-impl-v3`
- `task:awf-review-v3`
- `task:awf-rework-v3`

Every v3 payload binds these `awf.pr-provenance.v1` fields:

| Field | Meaning |
|---|---|
| `provenance_version` | Exact schema discriminator, currently `awf.pr-provenance.v1` |
| `upstream_repo` | Allowlisted GitHub `owner/repository` base identity |
| `base_ref` / `base_sha` | Exact upstream base ref and full commit |
| `head_repo` | Allowlisted contribution-fork identity |
| `head_ref` / `head_sha` | Exact fork ref and full commit |
| `pull_request` | Positive upstream PR number for review/rework; zero only before coder publication |

Repository identities and refs travel in payloads; remote names and remote URLs do not. Trusted
listeners receive `--upstream-repo`, `--upstream-remote`, `--head-repo`, `--head-remote`, and
`--base-ref` as local configuration. The runner verifies those remotes are canonical,
credential-free GitHub HTTPS URLs for the configured repository identities. Upstream and fork
repositories/remotes must be distinct, and every effective push URL must be the single validated
fetch URL; a separate or multiple `pushurl` is rejected before publication.

Legacy v1/v2 handler routes remain available only when explicitly selected. They retain their
single-origin behavior for deterministic backward compatibility. Default listeners no longer
subscribe to them, and v3 handlers reject missing or mixed-version provenance before model
invocation. No old event, pending payload, ACK, requeue, or redispatch was read or mutated.

## Trusted publication and review

The coder trusted path:

1. verifies configured upstream/fork remotes and the incoming tuple;
2. fetches the exact upstream base and contribution head;
3. runs the existing remote-free, credential-free model boundary;
4. imports and commits the verified delta in the trusted checkout;
5. pushes `HEAD` only to the configured fork ref;
6. freshly fetches that fork ref and requires exact SHA equality;
7. creates or reuses exactly one open PR through a bounded `gh` subprocess;
8. verifies PR number/state, upstream repo, base ref/SHA, head repo/ref/SHA;
9. persists `awf.outbox.v2` with the same tuple, then sends the reviewer event.

The reviewer freshly fetches both configured refs, verifies the PR tuple, checks out the exact
persisted head SHA, and only then starts a review model. Reviewer verdict outboxes also retain the
same tuple.

The GitHub CLI boundary uses fixed argv, no shell, no stdin, a timeout, and suppressed stdout/stderr
for state-changing calls. JSON reads request only non-sensitive PR metadata. Raw CLI diagnostics
are never copied into durable evidence or logs.

## Fail-closed and recovery behavior

Fork push failure, fork fetch failure, SHA mismatch, unavailable/failing GitHub CLI, ambiguous or
multiple matching PRs, PR create failure, closed/drifted PRs, incomplete provenance, untrusted
repository/remote/ref input, and outbox provenance drift all fail before reviewer delivery. The
handler persists a bounded categorical `fork_pr_rejected` reason and exits non-zero, so the source
event cannot be acknowledged.

Prepared, ambiguous, and sent v2 outbox replay validates the record and freshly revalidates the
exact fork/PR tuple. Prepared or ambiguous records resend their exact persisted payload. Sent
records do not resend. None reruns the model. A mismatch fails closed before delivery.

## Changed files

- `scripts/awf_role.py`
- `scripts/awf_listen.py`
- `scripts/awf-dispatch.sh`
- `scripts/awf_control_plane.py`
- `tests/test_awf_role.py`
- `README.md`
- `ROADMAP.md`
- `HANDOFF.md`
- `docs/tasks/fork-pr-trusted-runner.md`
- `docs/tasks/fork-pr-trusted-runner-implementation-report.md`

## Verification

Current local verification:

- focused role suite: `211 passed, 1 skipped`;
- complete suite: `261 passed, 1 skipped`;
- `ruff check .`: passed;
- `ruff format --check .`: all 78 files formatted;
- `bash -n scripts/awf-dispatch.sh`: passed;
- role/workflow/example validation: 6/6, 4/4, and 3/3 passed;
- `git diff --check`: passed;
- live read-only `gh pr view` schema probe confirmed all requested PR provenance fields are
  available.

The first independent native security/code review found and blocked a separate-`pushurl` bypass
and a v3 structured-rework hash omission. Both findings were fixed with Python/Bash remote
regressions and an exact v3 `REQUEST_CHANGES` delivery-hash regression. Re-review then found that
Python optimization could strip Bash's embedded `assert` checks; explicit fail-closed checks plus
a `PYTHONOPTIMIZE=1` regression closed that path. The final independent re-review returned
`APPROVED`. The PR URL and GitHub CI status are recorded after those gates complete.

## Explicitly not performed

- No live Agent Bus event or cross-machine proof.
- No historical payload, pending item, ACK, requeue, redispatch, or preserved event mutation.
- No upstream write probe or request for contributor upstream permission.
- No credential read, copy, logging, or documentation.
- No modification or expansion of draft PR #28.
- No merge of this feature PR.
