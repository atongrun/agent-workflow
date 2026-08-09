# Owner report path consistency implementation report

Date: 2026-08-09

## Problem

`derive_manifest` names implementation reports from the TaskCard identity, while dispatch names the
delivery/run identity from the task branch suffix. When those valid identities differ, dispatch
previously recompiled a second report path from the branch and rejected the owner RunManifest and
TaskCard before sending an event.

## Contract

An explicit report path already selected by the owner RunManifest is authoritative only when the
committed TaskCard declares that exact path as its sole `impl-report-*` allowed path. Both dispatch
and listener validation additionally require a forward-slash, repository-relative path under
`.awf/artifacts/`, reject traversal and drive/absolute paths, and retain a valid delivery task ID.

When no report path is supplied, the existing task-ID-derived default remains unchanged. The
delivery `task_id`, branch-derived run/ledger identity, payload schema, selection integrity,
checkpoint/outbox/ACK ordering, and Agent Bus behavior are unchanged.

## Regression coverage

- A TaskCard/owner report path based on a stable business task identity remains valid when the
  delivery task ID is a longer branch suffix.
- Dispatch and listener validators resolve the same exact report path.
- Unsafe paths, a second implementation-report source, or a TaskCard/delivery mismatch remain
  fail closed before model execution.

Full pytest, Ruff, and cross-platform validation is delegated to GitHub CI under the repository's
macOS test policy.
