# Linux TEST ONLY release

The user approved this separate public test release on 2026-10-05. It does not
approve production installation or establish native acceptance. Existing main,
awf/go-v1, archive/final, Windows RC9, old tags/assets and channels remain unchanged.

The only trigger is a push to `awf/linux-ci-test-v1.0.1-rc.1` in
`atongrun/agent-workflow`. There are no PR, pull_request_target, workflow_run or
default-branch triggers. Actions are pinned to verified full commit SHAs.
Build/test has `contents: read`; only the separate release job receives
`contents: write`. Checkout credentials are not persisted. The publishing step
uses the repository's short-lived `github.token`, never a personal token or
production secret.

The release tag `v1.0.1-rc.1` and compiled `BuildSourceCommit` point to the already
reviewed source `f0a2f98bbab111aed4cc612667e7387af5e4c7bf`. The workflow/packaging
commit is recorded separately in `PROVENANCE.json`. The compiler builds an exact
Git archive of that source twice, rather than silently including later changes.
Release source and retired default main have no `.github/workflows` entries.
This deliberately keeps the release target within the short-lived token's
Contents permission; it does not attempt to obtain Workflows write permission
or change default main for workflow_dispatch.

Authenticated paginated release listings include drafts during collision checks.
The version is reserved by creating only its new lightweight tag at the reviewed
source before draft creation. Existing tag or Release detection stops without
overwriting. The draft's source is checked
before uploading and before publication. Failures can leave the new tag and/or
draft for inspection;
there is no automatic deletion or replacement. A completed release is marked
prerelease and explicitly not latest.

## Actual distribution

The nine release assets are Host, extension, exact self-owned source archive,
bootstrap, manifest, `SHA256SUMS`, `PROVENANCE.json`, `TEST_ONLY.txt` and full
`THIRD_PARTY_NOTICES.txt` for Go code linked into the Host. The Host and extension
retain their strict two-file archive contracts. Go's LICENSE/PATENTS, its four
linked vendor-module notices and fiat-crypto notice are preserved. This grants
no new license for AWF's own code; its existing copyright/license status remains.

Node/npm, Pi, Magpie and npm cache tarballs are not redistributed in the release.
Users' installers fetch the exact canonical official inputs pinned in the
manifest. CI verifies all four upstream download byte counts and SHA256 without
running their lifecycle scripts or calling models. The existing installer
preserves Node's LICENSE and archive-provided package notices. It does not
require an added all-supply-chain license archive to run.

The separate local audit of six Pi packages and Magpie's dependencies identifies
upstream notice provenance questions. Reconstructing every upstream dependency's
notice archive is not a blanket prerequisite for distributing these AWF assets.
Any future third-party binary rebundling must reassess its actual distribution
obligations. Required Go notices for this release's own compiled Host remain part
of the asset set and release instructions.

## Checks and acceptance boundary

CI runs full Go tests, race, vet, both Windows compile checks, Python archive and
publication-boundary tests, and shell syntax. It builds with pinned Go 1.25.14,
checks repeat-build identity, validates asset boundaries, exact source/version,
official URLs and hashes, and publishes only after the build succeeds. Fixtures
and a hosted Ubuntu build do not establish native systemd or CloudCone acceptance.

The source/default Linux channel remains unpublished. Packaging binds only this
release's generated bootstrap to its canonical release-specific manifest and
records the exact template SHA256 and binding in provenance. Code outside the
four declared release stamps is byte-identical to the reviewed template. This
supports a single download command with explicit `--allow-prerelease`; an
explicit local `--manifest` remains supported. Verify `SHA256SUMS` and retain
the companion Go notices. Normal installer source verification
must succeed; no private test flag or guessed mirror is used. Native account,
fixed paths, service/socket ownership, start/stop, genuine same-install Pi update
and model-backed work remain separately identified acceptance gates. No CloudCone
or production machine is operated by this workflow.
