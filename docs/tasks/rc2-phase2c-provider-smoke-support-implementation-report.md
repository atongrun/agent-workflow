# RC.2 Phase 2C Provider Smoke Evidence

## Result

PASS for the nine-cell real CLI/model smoke gate. All successful identities used a new disposable
Git repository with no configured remote, no Agent Bus delivery, no commit/push, and no trusted
Git/merge authority. The code baseline for the smoke program was `main@bec9abf`.

| Role | Codex | Pi | OpenCode |
|---|---|---|---|
| Architect | PASS: `local-temp/awf-rc2-codex-architect-mC6VEa`, Codex CLI 0.149.0, `exec -C --sandbox read-only --ephemeral`, output SHA `f9002ec38ae6cc732bfb68a7d95bc88b98f1babce8600902a61035d0bbc7cf13`, seven-field parser PASS | PASS: `local-temp/awf-rc2-pi-architect-58ZMaj`, Pi 0.84.2 / openai-codex OAuth, no-session read-only tools, output SHA `68e7ea435ec65a2e5ad1497338a087a3b9879af9e96266fbdfe4e6968cbcbdc4`, seven-field parser PASS | PASS: `bj-win/awf-rc2-opencode-architect-smoke-r2-20260826`, OpenCode 1.18.18, `run --dir -f --`, output SHA `dae392040fc863a0a5ced704fb1e4b813b585f161d56326c7c3ee1035e646fde`, strict JSON fields observed |
| Coder | PASS: `local-temp/awf-rc2-codex-coder-bjpaxR`, Codex CLI 0.149.0, `exec -C --sandbox workspace-write --ephemeral`, file SHA `6bf54304794dbfec583c1803a48b575e8ebbcae31cb0c67f49a47ab49c312635` | PASS: `local-temp/awf-rc2-pi-coder-r3-1bOiNm`, Pi 0.84.2 / openai-codex OAuth, no-session no-bash write allowlist, file SHA `7f2f0b973e7609b76cc531fa80b6cc710ede65779dd311637f5698cd6db8153f` | PASS: `bj-win/awf-rc2-opencode-coder-smoke-20260826`, OpenCode 1.18.18, one-file result SHA `7f2f0b973e7609b76cc531fa80b6cc710ede65779dd311637f5698cd6db8153f` |
| Reviewer | PASS: `local-temp/awf-rc2-codex-reviewer-Aorir3`, Codex CLI 0.149.0, read-only ephemeral output SHA `dd9942160bf288fdc62a23d1495c71e0b684a85b02347497abe3f183f84d4bec` | PASS: `local-temp/awf-rc2-pi-reviewer-HJLOnl`, Pi 0.84.2 / openai-codex OAuth, no-session read-only output SHA `b259b2452b78a8753771d1264b91fa69c243858b7f23348671042ba28828a076` | PASS: `bj-win/awf-rc2-opencode-reviewer-smoke-20260826`, OpenCode 1.18.18, read-only output SHA `a9e2d8ee2c7cf4b3134457fc09fc9822e2bee3c20366b6975abf8c36092532ae` |

## Retained failures

- OpenCode Architect r1 (`bj-win/awf-rc2-opencode-architect-smoke-20260826`, output SHA
  `668d595a2c99051c477e6f257606159325da2752928f7988f86d9e7091db0edb`) invoked successfully
  but emitted nonconforming semantic JSON. It remains failed; the separate r2 identity above passed.
- Pi Coder r1 (`local-temp/awf-rc2-pi-coder-zGzsEX`, output SHA
  `d2a7f20921490e4875e871fd303023769134b1c5995bf7dfde6cf8f26bf14c60`) targeted the initiating
  workspace due to a smoke harness cwd error. The exact untracked file was removed; the r1
  disposable directory remains. Pi Coder r2 (`local-temp/awf-rc2-pi-coder-r2-z3YgIL`, file SHA
  `7f2f0b973e7609b76cc531fa80b6cc710ede65779dd311637f5698cd6db8153f`) omitted an optional
  newline. The separate r3 identity above passed.

## Boundaries

No failed identity was replayed. The retained disposable directories show no configured Git remote
and only the named untracked smoke artifacts; no smoke sent or acknowledged Agent Bus events,
committed, pushed, merged, published a release, or exposed credentials. The two official topology
E2Es remain distinct later acceptance gates.
