# ImplementationReport: Fail-closed reviewer verdict routing

## Commits and Baseline

- Merged product-contract base: `f759e34fa89aed5ded0ea870e261f3db30ac51c6`.
- Frozen TaskCard / execution starting commit: `c9eba77`.
- Final implementation commit: `1d80e41`.
- This report is committed separately after the implementation SHA is stable; the PR head is the
  authoritative report commit.

## Delivered Contract

The operations runner now carries an explicit repository-relative ReviewReport path from dispatch
through the listener and coder review handoff. Codex persists its final review response through
`codex exec review --output-last-message`; OpenCode receives an exact-path write instruction. The
trusted reviewer deletes stale ignored output, runs the reviewer, then reads, validates, normalizes,
and embeds the complete report before any verdict-dependent send.

The machine-readable Markdown block is `awf-review-report` with exactly these fields:

- `verdict`: exactly `PASS`, `REQUEST_CHANGES`, or `BLOCKED`;
- `deterministic_failures`: an array of bounded corrections with one structured evidence kind:
  exact acceptance criterion, command/result, or repository-relative file/positive line;
- `blocked_reason`: required only for `BLOCKED`.

The normalized object adds `format: awf.review-report.v1` and the complete Markdown report. Its
actual `send_event()` JSON representation must be at most 16 KiB. Missing, empty, malformed,
duplicate-field, unknown/lowercase verdict, unsafe path, tracked-path replacement, secret-bearing,
diff/patch-bearing, oversized, and insufficient-evidence reports fail before send.

## Event and Payload Contract

| Stage | Event | Recipient | Payload |
|---|---|---|---|
| Architect dispatch | `task:awf-impl` | coder | `task_id`, `branch`, `card`, `commit`, `tool`, `model`, `report`, `review_report` (local path) |
| Coder handoff | `task:awf-review` | reviewer | `task_id`, `branch`, `card`, `commit`, `tool`, `model`, `report`, `review_report` (local path) |
| Reviewer PASS | `decision:awf-ready` | architect | common verdict payload below |
| Reviewer REQUEST_CHANGES | `task:awf-rework` | coder | common verdict payload below |
| Reviewer BLOCKED | `decision:awf-blocked` | architect | common verdict payload below |

Every verdict event carries:

- `task_id`, `branch`, `card`, and reviewed `commit`;
- `report` (ImplementationReport provenance);
- `review_report_path` (local ReviewReport provenance);
- `review_report` (the complete validated normalized object, never only a path);
- original coder `tool` and `model` hints, so bounded rework remains actionable.

`task:awf-rework` is intentionally not a default listener subscription, so this task routes bounded
rework without automatically starting another implementation handler.

## Routing Matrix

| Verdict | Required evidence | Route | Forbidden behavior |
|---|---|---|---|
| `PASS` | valid bounded report; no deterministic failures | architect / `decision:awf-ready` | no coder rework or blocked event |
| `REQUEST_CHANGES` | at least one structured deterministic failure and correction | coder / `task:awf-rework` | no ready event; no automatic rerun |
| `BLOCKED` | non-empty escalation reason | architect / `decision:awf-blocked` | no ready event; no coder route or retry |

Exactly one route is selected. Every route checks `send_event()`. Missing configuration or a failed
send raises a non-zero handler exit, so the current `task:awf-review` event cannot reach listener
success/ACK.

## Files Changed

- `scripts/awf-dispatch.sh`
- `scripts/awf_listen.py`
- `scripts/awf_role.py`
- `scripts/reviewer-prompt.md`
- `templates/artifacts/review-report.md`
- `tests/test_awf_role.py`
- `docs/tasks/reviewer-verdict-routing-implementation-report.md`

No file outside the TaskCard Allowed paths changed after `c9eba77`.

## Verification

Final verification after rework:

- `python -m pytest -q tests/test_awf_role.py` — `123 passed`.
- `python -m pytest -q` — `160 passed`.
- `python -m ruff check .` — passed.
- `python -m ruff format --check .` — `14 files already formatted`.
- `python -m agent_workflow.cli validate roles` — `6/6 passed`.
- `python -m agent_workflow.cli validate workflows` — `4/4 passed`.
- `python -m agent_workflow.cli validate examples` — `3/3 passed`.
- `git diff --check` — passed.

Focused tests use temporary repositories, fakes, and monkeypatching. They do not contact Agent Bus,
GitHub, Codex, OpenCode, Windows, a VPS, or preserved historical events.

## Independent Review and Rework

The first independent strong review returned `REQUEST CHANGES` with no critical finding, one high
finalization finding (this required report had not yet been created), and one medium payload finding:
`task:awf-rework` lacked `card`, original coder `tool`, and original coder `model`, which made the
bounded rework packet incomplete even though it was not auto-consumed.

The verdict payload was corrected to include those fields while retaining the complete object under
`review_report` and the local pointer under `review_report_path`. Tests gained exact payload
assertions and a Unicode case proving the 16 KiB check matches the actual escaped event JSON. The
complete verification suite was rerun. Independent re-review returned `APPROVE` with zero remaining
critical, high, medium, or low findings.

## Remaining Risks and Deferred Acceptance

- No live cross-machine acceptance was run. Windows, VPS, real listeners, and Agent Bus were not
  connected or modified.
- Historical events `49`, `50`, `51`, and `52` were not read, consumed, ACKed, or requeued.
- The Codex argv was checked against the locally installed CLI help and by unit tests; a real Codex
  review invocation remains part of later live acceptance.
- `task:awf-rework` routing is deterministic and complete but deliberately has no automatic listener
  transition in this task.
- Agent Bus protocol, persistence, ACK/failure semantics, and authentication were unchanged.

