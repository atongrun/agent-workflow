# Workflow facts, durable receipts and GitHub references

Task acceptance, native execution completion, request delivery and Pi's result
assessment are distinct facts. A completed OpenCode turn does not approve the
task. Chat text, command strings, commit messages, PR bodies and comments do not
advance the task lifecycle. Pi submits a typed verdict with native tool receipt
references; the Host checks identity, lifecycle and reference structure. It does
not independently judge the quality of the diff, tests or claimed remote SHA.

## Local durability and uncertain native effects

The state store serializes updates under its mutex and persists the complete
state. A new finish reservation commits the verdict and its own completed
request receipt in one `Store.Update`. Exact request retries retain the original
hash and do not replay the verdict. Historical split finish receipts can repair
only their receipt on an identical retry. Persistence failure before replacement
commits neither mutation. Failure after file replacement can leave the durable
outcome uncertain; this is not a transactional guarantee across external RPCs.

Native prompt settlement requires the original task, role, native Pi session
and process generation. `agent_settled` settles prompt receipts only; model,
compact and abort controls require their own replies. A new process's idle
observation cannot prove that an earlier process's control succeeded.

Persisted Requests are authoritative for unresolved controls. Session pending
queues are derived indexes: restart and live process closure rebuild the control
fence from the ledger. Stop checks the ledger even when its transient index is
missing. Unknown statuses fail closed; existing terminal receipts and explicit
native UI/cancel acknowledgements retain their established meanings. A restart
never turns an unknown control into success or permits its automatic replay.

Retain the original request ID and payload. Receipt GET and identical control
retries expose the recorded result without resending an uncertain effect.
There is no new reconciliation endpoint in this change: if the original native
reply cannot establish the outcome, the receipt remains `needs_verification`
and its fence remains. Clearing a pending list, restarting or sending a new
request ID does not establish the historical outcome. Process-bound caller
credentials, durable outboxes and database migrations are outside this change.

Execution budgets remain total observed active seconds and total reworks, not
wall-clock deadlines. Tightening preserves accrued counters, waits, execution
fingerprints and all other tasks' settings; no counter reset grants extra time.

## Current Git identity boundary

Tasks store a canonical repository owner/name, optional `repositoryId`, and
branch. Execution targets snapshot repository identity and target revision for
the execution. Pi's `remoteSha` is an assessment claim with hexadecimal schema
validation, not an independently fetched GitHub result. There are no dedicated
persisted commit, pull-request or check-run identity fields in this change.
`gitMerged` does not become proof of a merge. Git operations remain agent-owned.

## Future structured GitHub facts (design only)

A future read-only integration could retain repository ID, immutable head SHA,
optional PR number and check-run ID together with issuer, observation time,
status and conclusion. A check observation would match the exact repository,
head SHA and check-run identity; missing or mismatched facts remain unknown.
GitHub exposes typed check-run `head_sha`, `status`, `conclusion` and application
identity in its [Get a check run API](https://docs.github.com/en/rest/checks/runs#get-a-check-run).
PR identity can use the [Get a pull request API](https://docs.github.com/en/rest/pulls/pulls#get-a-pull-request).
No interpretation of commit messages, PR bodies or comments is needed.

An observed successful check is that check's result, not proof of all test
coverage, Pi's acceptance verdict or Task Done. Issuer/provenance and the user's
required checks would need explicit policy. Private check reads require the
appropriate repository Checks read permission; public resources can be read
without authentication under GitHub's documented API rules. This design adds
no permissions, API calls, GitHub Actions, PR routes, repository writes or
merge behavior. Any implementation requiring additional access remains a
separate approved scope.
