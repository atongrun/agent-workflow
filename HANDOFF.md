# 交接文档 — 给下一个 Agent（新 session）

> 更新于 2026-07-12 by Claude Code (Opus 4.8)。这是**最新断点**。本文档让你快速接手，不必重读聊天历史。
> **先读 AI Memory**（比本文件更权威、含私密值）：
> `ai-memory/topics/agent-workflow/CONTEXT.md` +
> `notes/2026-07-12-cross-machine-windows-python.md`（**最新**，跨机+Python化全过程）+
> `notes/2026-07-12-event-driven-role-network.md`（本机两环）+ `notes/2026-07-11-workflow-dogfood-and-tiering.md`，
> 以及 `topics/tailscale-mesh/CONTEXT.md`（三机 IP/SSH/token 位置）。

## 0. 一句话现状

Agent Workflow 是轻量方法层（markdown 契约 + 无状态薄 CLI，v0.2.0）。派活器已从「单点 once-listener」
重构成**基于角色的事件驱动 listener 网络**：architect 发卡 → coder/reviewer 常驻 listener 监听→执行/review
→发下一环事件；VPS 可 `control:shutdown` 精确停某角色。**本机三角色两环**（coder=OpenCode、reviewer=Codex）
+ **跨机执行**（coder listener 搬到北京 Windows）都真跑通。为根治 Windows shell 问题，角色脚本已
**Python 化**（`scripts/awf_role.py`/`awf_listen.py`，替代 bash）——这也是「配置太复杂」调研的治本结论。
下一步 = 完整自动闭环重跑 + 清理旧 bash + agent-bus stack 合并（见 §3）。

## 1. 三个仓库

> 绝对路径、VPS IP、SSH 别名、token 位置等私密信息**不写在本文件**（本文件入库/公开）。
> 见私有 AI Memory：topic `agent-workflow`（环境事实）+ `tailscale-mesh`（三机拓扑/SSH/IP）。

| 项目 | 说明 |
|---|---|
| agent-workflow | 方法本体。核心=`constitution.md`；派活=`scripts/awf-dispatch.sh`；执行=`scripts/awf_role.py`+`awf_listen.py`（Python，跨平台） |
| agent-bus | 被开发的真实项目（runtime-agnostic 事件中继）。artifact 链在 `.awf/artifacts/`（已入库） |
| ai-memory | 跨 agent 长期记忆，**优先读**。私密值只在这里 |

## 2. Git 状态（未合并的分支，别丢）

- **agent-workflow**：`main` **已推 GitHub**（`8d087a9`）。含事件驱动网络的全部脚本：`awf-dispatch.sh`（发卡）、
  `awf_role.py`/`awf_listen.py`（Python 角色执行，跨平台）、旧 bash 版（`awf-listen.sh`/`roles/`/`executors/`/
  `adapters/`，**暂留待清理**——Python reviewer 侧验证后删）。干净。`CLAUDE.md`/`AGENTS.md` 已 gitignore。
- **agent-bus**：分支 stack（从旧到新，都已 push origin，**均未合并 master、未开 PR**）：
  `awf/abus-poison-003`（doctor→graceful-exit→.awf→poison）→ `awf/abus-pending-count-004`（+`pending --count`）→
  `awf/abus-send-dryrun-005`（+`send --dry-run`，DeepSeek **跨机**执行，18 测试过）。
  - ⚠️ 默认分支 `master`，与 stack 分叉；合并非 ff，冲突仅在 docs + `windows-poll-listener.ps1`（feature 代码不冲突）。
  - ⚠️ **Windows 侧 agent-bus remote 已改 SSH**（`git@github.com:...`，用 deploy key）；Mac 侧仍 HTTPS+代理。
- **ai-memory**：已推至 `b3d0807`（含本会话跨机+Python化 note）。
- 默认不擅自 push / 开 PR / 合并。用户要才做。

## 3. 立即要做的下一步（收尾批 B + 推进）

跨机核心已跑通（Windows Python listener + opencode 执行 + SSH deploy key push + architect 复核 18 测试过）。剩：

1. **`awf bootstrap` 脚本（下一步先做，凭证便携性）**：从 source of truth（VPS `/etc/agent-bus/.env` 的
   `AGENT_BUS_AGENT_TOKENS`）一键拉 token、组装本机 `~/.config/awf/dispatch.env`（chmod 600，不入库），
   跨平台（Mac/Windows 的 AWF_BUS_BIN/AWF_OPENCODE_BIN 路径不同）。**凭证永不落 git**。解决「每次换机/接手手动
   取 token 写 dispatch.env」痛点。可叠加 `awf handoff-check`（接手自检：dispatch.env 齐全/agent-bus 连得上+token
   scope/git 能 push/tool 在，输出 PASS/FAIL）。设计依据见 AI Memory
   `notes/2026-07-12-handoff-portability-and-secrets.md`。**先出设计再写。**
2. **完整自动闭环重跑**：认证/bug 都修了，重跑证明 handler 自己 commit→push→发 `task:awf-review`
   →Mac Codex reviewer 收→`decision:awf-ready` 一次连续跑通 + **验 Python reviewer 侧**（`awf_role reviewer` + codex）。
   Windows 先 `git pull`（拿 commit-check 修复）。
3. **清理旧 bash 脚本**（awf-listen.sh/roles/executors/adapters）——Python reviewer 侧验证后删，收敛配置。
4. **agent-bus stack 合并 / 开 PR**（线性 stack，未合并；合并需解 docs + ps1 冲突）。
5. **跨机 `control:shutdown` 真验**（VPS 停 Windows coder listener）——本机验过，跨机没单独验。
- 环境/路径/凭证/认证全坑：见 AI Memory `notes/2026-07-12-cross-machine-windows-python.md`。三机拓扑见
  `topics/tailscale-mesh/CONTEXT.md`（Windows=`100.81.0.48`，常离线，用前 `tailscale status`）。

## 4. awf-dispatch 设计（已实现部分）

`scripts/awf-dispatch.sh` + `scripts/adapters/<tool>.sh` + `scripts/executor-prompt.md`。
- **卡/prompt 走文件，绝不内联进 shell**（一个 em-dash 曾把 SSE 事件编码搞坏、listener crash-loop）。
- **executor CLI 可插拔**：加新 CLI 只加一个 `adapters/<tool>.sh`（已有 opencode）。dispatcher 不认识具体工具。
- **卡走 git（PR 分支），事件只带指针**。artifact 现已入库，机制成立。
- 现状：local executor + PR 传卡 + 工具适配器。Windows/SSH executor 待加。

## 5. 方法怎么用（constitution 落地）

Brownfield：Baseline → 冻结架构(≤3轮) → 一次一张自包含 TaskCard → 执行 → review(只标确定性失败) → 用户 decide。
- **TaskCard 自包含**（§6a/§6b）：真实文件/行号锚点、真实验证命令、out-of-scope、交卡前自查。模板 `templates/artifacts/task-card.md`。
- **§11 隐私纪律**：artifact 入库，**不含** token/IP/主机名/个人路径，用占位符+env；私密值只进 AI Memory；review 查泄密。

## 6. 关键原则（别违背）

- Agent Workflow 不执行/不调度/不编排——执行是各 agent runner 内部的事。
- 一次只详细规划一个里程碑；Later 不阻塞当前。
- 弱模型执行必须配 review 兜底（真实抓到过 DeepSeek 的 bug）。
- 派活 prompt 绝不内联；listener 是独立进程，跑完要 kill 或用 `--exit-after-idle`；发任务前确认 coder pending 干净。
- 不擅自 push / 开 PR / 动 VPS 配置 / 写用户隐私进公开文件；破坏性操作先确认。

## 7. Later 改进池（agent-bus，按 use-first 挑）

poison-event 保护（正在派的 #11）、工作队列/竞争消费者（P2，多机同名 worker 谁接）、worker 实例寻址
（coder@mac，P2/P3 同根）、事件 TTL。详见 `ai-memory/topics/agent-collaboration/notes/2026-07-11-agent-bus-dogfood-findings.md`。

## 8. 大方向（"下个项目"，未启动）

跨机器终局：GitHub PR 做 artifact 真相源 + `@角色` 提及交接 + 角色/入口可插拔（Mac Claude Code / Hermes / Windows executor 都是入口，
decider 永远是用户）。桥（@mention→唤醒 agent）选型待定。详见 workflow note 的"跨机器终局架构"段。
