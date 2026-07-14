# TaskCard: Terminate OpenCode file-array parsing before the prompt

## Goal

Repair the trusted runner's OpenCode executor and reviewer argv contract so OpenCode v1.17.13
receives each TaskCard through `--file` and receives the instruction text as the positional
`message`, even when no explicit model is configured.

This is a narrow bootstrap prerequisite for restoring the blocked Windows UTF-8 handoff. It
repairs the runner itself; it does not implement the UTF-8 task or fabricate any Agent Bus
completion event.

## Fixed baseline and evidence

- Repository: `atongrun/agent-workflow`.
- Branch: `codex/opencode-file-arg-boundary`, based on `origin/main@75a497e`.
- OpenCode Windows version verified on the trusted runner: `1.17.13`.
- `opencode run --help` declares both positional `message` and `-f/--file` as arrays.
- A real Windows parser smoke using the existing isolated checkout proved:
  - `-m invalid-provider/invalid-model -f <card> parser-bad` fails with
    `File not found: parser-bad`;
  - `-m invalid-provider/invalid-model -f <card> -- parser-ok` advances beyond file parsing and
    fails with `Model not found: invalid-provider/invalid-model`.
- The current `tool_opencode_exec()` and `tool_opencode_review()` append the prompt immediately
  after the last option. Without a following scalar option, OpenCode can consume that prompt as
  another file.
- Existing adapter tests only verify the credential-stripped environment; they do not lock the
  generated argv.

## Allowed paths

Only these files may change after this TaskCard commit:

1. `scripts/awf_role.py`
2. `tests/test_awf_role.py`
3. `docs/tasks/opencode-file-array-boundary-implementation-report.md` (create)

This TaskCard is already committed and must not be edited.

## Required implementation

### 1. Explicit option boundary

- In both `tool_opencode_exec()` and `tool_opencode_review()`, finish assembling all OpenCode
  options first, including the optional TaskCard and optional model.
- Insert the literal `--` immediately before the single prompt string.
- Preserve the TaskCard as the value of `-f/--file` and preserve the prompt as the positional
  `message`.
- Preserve current option spelling and ordering except for the smallest change needed to add the
  boundary. Do not move prompt text to stdin or a temporary file.

### 2. Focused argv regression tests

- Extend the existing executor and OpenCode-review adapter tests to capture the complete argv.
- Cover both adapters with an existing TaskCard and a non-empty model.
- Assert, without merely searching loosely, that:
  - the executable and `run --dir <repo>` prefix remain correct;
  - `-f` is followed by exactly the TaskCard path;
  - `-m` is followed by exactly the configured model;
  - `--` occurs after all options;
  - the prompt is the single final positional argument after `--`.
- Add the smallest no-model coverage needed to lock the incident path: the separator must still
  appear between the TaskCard and prompt when the model is empty.
- Keep the existing `model_env()` assertions intact.

### 3. Implementation report

Create the implementation report with files changed, the argv contract before and after, focused
and full verification results, Windows parser/test evidence, remaining risks, and final commit SHA
if available.

## Acceptance criteria

- Executor and OpenCode reviewer argv both terminate option parsing with `--` before prompt text.
- A TaskCard remains an attached file; prompt text cannot be consumed as a second file.
- Optional model selection remains an OpenCode option and is not swallowed by file parsing.
- The incident path without a model is protected by regression coverage.
- Existing credential stripping, closed-stdin behavior, postflight gates, and role behavior remain
  unchanged.
- Mac full tests, Ruff check, Ruff format check, and all resource validations pass.
- Windows runs the focused adapter tests and the real v1.17.13 parser smoke successfully.
- No dependency or out-of-scope feature is added.

## Forbidden work

- Do not modify Agent Bus, its events, ACK behavior, or queue contents.
- Do not implement the Windows UTF-8 TaskCard in this branch.
- Do not add push enforcement, remote-SHA verification, reviewer verdict routing, Agent Host,
  services, UI, idempotency, claim/lease behavior, or new dependencies.
- Do not reset, clean, or delete any historical checkout or dirty file.
- Do not weaken the postflight completion contract or model-process credential boundary.

## Required verification

```text
python -m pytest -v tests/test_awf_role.py
python -m pytest -v
python -m ruff check .
python -m ruff format --check .
python -m agent_workflow.cli validate roles
python -m agent_workflow.cli validate workflows
python -m agent_workflow.cli validate examples
```

Expected resource totals remain `6/6 roles`, `4/4 workflows`, and `3/3 examples`.
