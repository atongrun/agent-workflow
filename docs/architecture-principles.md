# Architecture and reuse priorities

These are the user's development and review rules, recorded on 2026-10-07:

1. Pi native capabilities first.
2. Pi extensions and Skills next.
3. Custom services in Go only for a demonstrated remaining need.
4. Other approaches only when the first three cannot meet the requirement, with
   the reason stated.

Check the relevant published Pi capability before designing a replacement.
Language uniformity, completed code and passing CI do not justify copying Pi's
runtime. Unlaunched candidates impose no compatibility or old-job migration
requirement. Keep existing user data and unrelated Dash features.

## Durable-first agent boundary

The source review covered published `@earendil-works/pi-durable@1.0.4`, npm
`gitHead` `7c10bd4337495ee613f2224843ecdf349b80d1df`, on 2026-10-07. Its package
requires Node `>=22.19.0`. It remains experimental; do not treat the version
number as a stability guarantee or substitute current main for published source.
See the [published package](https://github.com/earendil-works/pi/blob/7c10bd4337495ee613f2224843ecdf349b80d1df/packages/durable/package.json)
and [README](https://github.com/earendil-works/pi/blob/7c10bd4337495ee613f2224843ecdf349b80d1df/packages/durable/README.md).

Prefer one native Durable Harness for conversations, model/tool tasks, committed
progress, checkpointing, native abort and resume. Do not retain the unlaunched Go
content attempt/execution/recovery state machine as a compatibility layer. The
preserved prototype is a reference, not the default architecture for new work.

## Responsibility decisions

| Requirement | Native capability or exact remaining gap | Smallest owner |
| --- | --- | --- |
| Agent session/context, model/tool tasks, progress, checkpoint and resume | Durable already supplies these. | Pi native; no parallel Go scheduler or execution ledger. |
| Business prompts, Skills, tool policy and typed content result | Generic Harness does not supply AWF's business behavior. | Pi extension/Skill; keep existing PRIVATE business code and expose its result. |
| Existing catalog/CAS model choice; freeze the chosen model for a job | Native agent configuration stores a model, but AWF's catalog authorization and preference are application-specific. | Existing PRIVATE catalog/CAS adapter; persist a job's selected model with its native conversation/application Doc. Future preference changes affect future jobs. |
| Same owner/requestId with a different payload must conflict | Native deduplication is conversation-scoped and checks submission type, not content equivalence. | Small application fingerprint/request-to-conversation Doc in Durable; no second task-state authority. |
| Public HTTP, authenticated owner scope and product routes | Harness APIs do not implement AWF's HTTP/authentication/business boundary. | Go service adapts native receipts and existing business/storage references. |
| Installation, systemd, single storage owner and forced termination | Release explicitly provides no cross-process storage lock; cooperative cancellation cannot force-stop arbitrary JavaScript. | Go machine/process lifecycle and an OS ownership boundary; no duplicated checkpoint scheduler. |
| Stronger disk commit policy | Default SQLite uses NORMAL. A public database facade can be configured before Harness open. | Configure and verify native SQLite FULL where required; no upstream fork or extra ledger for this setting. |
| Other technology | Must identify a requirement that Pi native, extensions/Skills and a Go service cannot satisfy. | Add only after recording that concrete reason. Existing unrelated Dash functions are not rewritten for language uniformity. |

The fingerprint gap is visible in
[native admission](https://github.com/earendil-works/pi/blob/7c10bd4337495ee613f2224843ecdf349b80d1df/packages/durable/src/harness/submissions.ts).
The storage/lifecycle limits are in the published README and
[specification](https://github.com/earendil-works/pi/blob/7c10bd4337495ee613f2224843ecdf349b80d1df/packages/durable/docs/spec.md).

## Thin adapter contracts

The trusted selected-model boundary takes the authenticated owner and returns
only an opaque `modelRef`. PRIVATE resolves it through its existing catalog/CAS
preference to native `{provider, modelId}`. Browser input must not override
provider URLs, credentials, executable/environment configuration or prompts.
Snapshot only at new admission; replay uses the saved choice. A separate job
conversation can retain its native model across all turns without a live global
model preference changing running work.

Store stable owner/requestId/fingerprint, selected-model snapshot, conversation
and business input/result references in a minimal application Doc/index where
needed. Native submission/task state remains authoritative. Creating a
conversation with agent configuration and init Doc is one commit; `submit()` is
a separate commit. Reuse the same saved conversation/input/requestId to finish
an interrupted admission. Public `Tx.createSubmission` is a raw record operation,
not the full admission/inbox/start-run API. Do not claim those two steps are
atomic or add a Go checkpoint ledger to reconcile them.

Use native conversation abort for running work; submission abort only withdraws
queued input. Cancelling a wait does not cancel the agent. Native tool replay is
safe only when the tool declares it safe; request deduplication does not make
external side effects exactly once. Single ownership, non-cooperative process
cleanup, authorization and business artifact validation remain host/application
boundaries. A long-lived Harness need not exit after each successful job.

## Validation and review

Source inspection supports this boundary, not production acceptance. Pin the
published package and integrity-verified dependencies. Before adopting the new
adapter, use a faux model and real local storage to verify reopen/crash behavior,
owner/payload conflicts, model freeze, native cancel/answer ordering, tool replay,
typed results and exclusive ownership. Check configured FULL and physical process
cleanup on an appropriate authorized native environment. Do not count tests of
the parked Go prototype as Durable acceptance or treat experimental APIs as
unconditionally reliable.

For each proposed custom component, record the requirement, Pi version/API
checked, native gap, why an extension/Skill cannot cover it when proposing a Go
service, and the validation needed. Prefer deleting a design obligation over
retaining redundant runtime machinery; actual code/data deletion and deployment
are separate from this local architecture decision.
