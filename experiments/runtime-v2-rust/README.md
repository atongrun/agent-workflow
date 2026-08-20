# Runtime v2 Rust Shared Slice

RTS-022A is a disposable, repository-local native experiment. It does not import
or select the production Python package and it is removable by deleting this
directory, the dedicated workflow addition, and the two `.awf` artifacts.

The executable exposes three experiment-local user commands:

- `run --state <dir> --repo <repo> --run-id <id>`
- `status --state <dir> --repo <repo> --run-id <id>`
- `stop --state <dir> --repo <repo> --run-id <id>`

The hidden `provider`, `inject`, `verify`, and `measure` commands are test and
CI helpers. The provider is a child process of the same executable, still
launched through structured argv with no shell and a credential-minimized
environment. Git remains an external executable prerequisite and is invoked with
structured argv only.

The crate intentionally has zero direct production dependencies. It includes a
small strict JSON reader so trusted JSON with duplicate object keys is rejected
instead of silently accepting the first or last value.
