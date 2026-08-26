# RC.2 Phase 2C — Provider Smoke and Support Claim

## Task ID

RC2-P2C-PROVIDER-SMOKE-SUPPORT

## Goal

Record fresh real provider invocation evidence for the completed 3×3 conformance matrix and make
the unreleased RC.2 support table truthful.

## Scope

- Record exact fresh disposable smoke outcomes for all nine Provider/Role cells, including retained
  failed identities and their bounded successors.
- Update README to distinguish unreleased RC.2 main support from the published RC.1 release.

## Exclusions

- Provider code changes, replay/ACK actions, topology E2Es, business milestones, release/tag
  publication, session restoration, credential material, or modification of failed smoke evidence.

## Acceptance

- [ ] Every cell has deterministic conformance plus a real fresh CLI/model invocation or later
  topology E2E assignment.
- [ ] Failures remain documented as failures and no support claim depends on them.
- [ ] README names full 3×3 support as RC.2 main/unreleased, not as RC.1 release support.

## Verification

```bash
python -m pytest -q tests/test_runtime_provider_renderers.py tests/test_runtime_architect.py tests/test_awf_plan.py
git diff --check
```
