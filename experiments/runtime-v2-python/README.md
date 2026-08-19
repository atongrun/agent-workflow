# Runtime v2 Python Shared Slice

This directory contains the disposable RTS-020 Python experiment. It is a local
comparison slice only: it is not imported by the installed `awf` package, is not
selected by any production CLI, and does not migrate or write production Runtime
state.

The experiment exposes a small command protocol through `runner.py`:

- `run` compiles an immutable `RunSpec`, writes a prepared invocation journal
  before RunStore authorization, starts one scripted implement child process,
  validates/imports its allowed delta into a trusted no-remote local Git clone,
  starts one scripted PASS review child process, revalidates the exact trusted
  Git identity, and persists terminal completion.
- `status` projects the same local state without writing, starting providers,
  repairing Git, or executing the reported next action.
- `stop` records only an exact local stop for this slice after proving no
  invocation is active. This is unequal lifecycle evidence because the slice has
  no native manager and normally has no long-lived process.

Real local evidence:

- Python child processes use structured argv with no shell.
- Child processes receive a minimized allowlist environment; ambient sentinel secrets are tested not
  to reach the scripted provider.
- JSON state is written atomically with checksums.
- `RunStore` is the only writer for workflow phase, authorization, handoff
  intent, terminal and local stop facts.
- `InvocationJournal` is the only API for prepared records, launch intent,
  process observations, results and validation facts.
- Disposable Git clones remove remotes before provider or trusted effects.

Synthetic evidence:

- implementer and reviewer intelligence;
- delivery and downstream-intent observation;
- timestamps, provider identity and GitHub-shaped facts;
- transport, ACK, PR, CI, release and service-manager behavior.

The shared fault fixture is `tests/fixtures/runtime_v2_shared_slice_cases.json`.
The focused acceptance is `tests/test_runtime_v2_rts020_python_slice.py`.
