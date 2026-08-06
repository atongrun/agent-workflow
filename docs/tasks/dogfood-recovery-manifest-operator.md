# Dogfood Recovery, RunManifest, and Serial Operator

## Recovery boundary

The trusted reviewer runner owns the `awf-review-report` machine envelope. A
single-line envelope is normalized once into the canonical multiline form and
then parsed before `model_imported`, `pr_tuple_verified`, or any outbox/PR
transition. Semantic or schema failure records `artifact_status=artifact_invalid`
on the same delivery, preserves the bound report SHA and provenance, and does
not invoke a model, requeue, ACK, or create a replacement event. A second
correction attempt is refused; an old checkpoint already beyond the replayable
model boundary requires an owner-authorized replacement delivery.

## RunManifest migration

`awf setup --repo . --card <path-or-id>` writes the owner-only,
credential-free `.awf/run-manifest.json`. It derives the task ID, branch,
routes, report paths, model selection, rework budget, and provenance slots from
the self-contained TaskCard. Existing `dispatch.env` remains a compatibility
input for secrets and runtime binaries; setup never writes or sources `.envrc`.
`awf run` and default `awf dispatch` load that owner manifest, verify its bound
TaskCard, and reject conflicting metadata. Explicit legacy dispatch flags remain
available only when an operator supplies a branch and no owner manifest exists.
The default run ID is `task-<branch-task-suffix>`, matching trusted listener
recovery. Manifests created by the initial migration with an empty tool must be
replaced explicitly with `awf setup --replace --tool <tool>` before dispatch.

## Serial operator

`awf run --card <path>` creates the durable run ledger at the configured state
root with the next legal action `clean_checkout`. `awf status --run <id>` shows
stage, checkpoint, listener/Bus/postflight health, queue attempts, first
failure, and next action; fields not yet persisted are rendered as
`not_recorded`. `awf resume --run <id>` is fail-closed: it reports only the one
protocol-authorized next action and never replays a model or requeues a
historical delivery.
