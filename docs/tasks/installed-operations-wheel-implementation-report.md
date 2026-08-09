# Installed operations wheel implementation report

## Outcome

The built wheel now contains the production operations surface and its runtime assets. Installed
`awf run` and `awf dispatch` resolve packaged operations rather than searching for a sibling
`scripts/` directory in the current checkout. Source and editable development retain a narrow
fallback to the canonical repository directories.

## Included resources

- listener, role, dispatch, preflight, bootstrap, config, control-plane, executor, network,
  handoff, service, delivery, TaskCard, and artifact-contract Python modules;
- Codex, OpenCode, and Pi adapters;
- default authority manifest and reviewer/executor prompts;
- model Git command guard, hooks, and cross-platform service wrappers/templates;
- canonical artifact templates.

No files are manually duplicated. Hatch maps the existing `scripts/` and `templates/` trees into
the wheel, so the repository remains the single maintenance source.

## Verification contract

CI builds a non-editable wheel on Linux, Windows, and macOS, installs it into a fresh virtual
environment, changes to an unrelated empty directory, and verifies:

1. all required operations assets exist under the installed package;
2. listener, role, dispatch, and control-plane modules import from that installed tree;
3. the installed `awf` entry point runs without a source checkout;
4. no `__pycache__` or `.pyc` build artifacts are intentionally included.

The existing full Linux/Windows suites, macOS runtime checks, schema distribution inspection, and
source-tree compatibility remain required. This change does not add node lifecycle management or
live status aggregation; those remain isolated follow-ups.
