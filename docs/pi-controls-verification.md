# Pi controls verification

The menu's Host adapter is intentionally restricted to discovered prompt
commands and explicit stats/model/compact/stop capabilities of official Pi
1.0.0. Browser selection is not a mutation. Controls bind to native session and
Host process identity and use the existing durable request ledger.

Focused tests use a credential-free subprocess JSONL fixture for deterministic
stop/prompt ordering, concurrent duplicate controls, stale process responses,
unknown dispatch outcomes and Host restart. The opt-in installed official Pi
1.0.0 test separately verifies command/model/stats DTOs and an idle stop, without
submitting a model prompt, changing a configured model, or running compaction.
A successful model-backed compaction is not claimed by these tests.

The native transport now separates synchronous JSONL dispatch from waiting for
its reply. Host dispatch locks cover the write fence, not a compaction wait, so
Stop remains able to interrupt compaction. Stop cancels a reserved prompt that
has not crossed this fence and returns its text as an unsent draft. New prompts
are gated while a Pi control has an unresolved native receipt.

Unknown results are retained as needs_verification rather than retried as a new
operation. Native session/process replacement invalidates stale reads and
mutations. Model transport/header fields and source/session paths are excluded
from the new DTOs. Actual model authentication failure can still occur after a
model was listed; it is reported without exposing native diagnostic secrets.

Validation commands (use the installed official Go toolchain):

- go test ./...
- go test -race ./...
- go vet ./...
- AWF_PI_BINARY=<official Pi 1.0.0 CLI> go test ./internal/host -run TestNativePiHostIntegration -count=1 -v
- go build ./cmd/awf and ./cmd/awf-node
- GOOS=windows GOARCH=amd64 go build ./cmd/awf-node
- GOOS=windows GOARCH=arm64 go build ./cmd/awf-node

No push, deployment, authentication change, or model-backed test is included.

All listed Go tests, race tests, vet, real Pi 1.0.0 integration, Linux builds and
Windows amd64/arm64 cross-builds passed for this checkpoint. The final native
integration includes the bound HTTP idle-stop control as well as the sanitized
capability reads. Browser pixel validation belongs to the separate Dash change.
