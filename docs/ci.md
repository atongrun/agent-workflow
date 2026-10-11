# Go Host checks

One daily Ubuntu workflow runs on pull requests and pushes to the current main
or supported Go/Linux development channels and the approved
`codex/pi-110-health` compatibility branch. The retired default branch is not
changed by publishing this branch. It runs all package race tests and
vet once, builds the two existing Linux command binaries, and checks the
portable package/bootstrap contracts. Source dependencies remain offline and
read-only. The Go compilation cache is keyed by platform, Go version and module
locks; it contains no runtime state or credentials.

The manual `Go Host release checks` workflow runs the existing native Go Windows
fixtures and existing PowerShell 5.1/7 install/consent/fresh-process guards on the
selected candidate revision. It cannot publish, deploy, update channels or
install the product. It has separate concurrency and is not cancelled by daily
CI. A cross-build or guard fixture is not a real published installation test.

Before an installer/lifecycle release, complete the applicable native
acceptance checklist in `docs/fresh-install.md` using a disposable approved
profile: real install/ACL/PATH identity, start/stop/update and busy-state guards,
then public transport/channel verification after publication approval. Real
Pi/model execution is also a separate opt-in acceptance boundary. No old RC
assets or historical channel harness is downloaded by daily CI.

The current source tree has no `.github` workflows, `internal/content`,
`cmd/awf-content` or old Linux RC harness to delete. Historical once-only
workflows remain in their old branches/Actions history; they are not imported
into this source or the daily/release entry points. No old branch, release,
user state, protocol guard or supported rollback version was removed.
