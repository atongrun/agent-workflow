# Review Report

## Machine Contract

<!-- Keep exactly one awf-review-report object. No extra or duplicate JSON fields. -->
<!-- awf-review-report
{
  "verdict": "PASS",
  "deterministic_failures": [],
  "blocked_reason": ""
}
-->

## Deterministic Failures
<!--
Required for REQUEST_CHANGES. Each machine-object entry has exactly:
{
  "evidence": {"kind": "criterion", "criterion": "exact failed criterion"},
  "required_correction": "bounded correction"
}
Evidence kind may instead be:
- {"kind": "command", "command": "exact command", "result": "exact failed result"}
- {"kind": "file_line", "file": "repo/relative/path", "line": 12}
-->

| # | Failed criterion or rule | Exact evidence | Required correction |
|---|---|---|---|
| | | | |

## Advisory Findings
<!-- Style, architecture preferences, and optional improvements. These never block completion. -->

| # | Severity | Finding | Suggestion |
|---|---|---|---|
| | | | |

## Acceptance Criteria Result

| Criterion | Met? | Evidence |
|---|---|---|
| | | |

## Scope and Regression Risk

- **Scope deviation:** [none or exact deterministic violation]
- **Regression risk:** [low | medium | high]
- **Rationale:** [evidence-based explanation]

## Blocked Evidence
<!-- Required for BLOCKED in both prose and the machine object's blocked_reason field. -->

[N/A or evidence, escalation reason code, and decision needed]

## Confidence

[low | medium | high] — [why]
