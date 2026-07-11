# 交接文档 — 给下一个 Agent（新 session）

> 更新于 2026-07-11 by Claude Code (Opus 4.8)。这是**最新断点**。本文档让你快速接手，不必重读聊天历史。
> **先读 AI Memory**（比本文件更权威、含私密值）：
> `ai-memory/topics/agent-workflow/CONTEXT.md` + `notes/2026-07-11-workflow-dogfood-and-tiering.md`，
> 以及 `topics/tailscale-mesh/CONTEXT.md`（三机 IP/SSH/token 位置）。

## 0. 一句话现状

Agent Workflow 已收缩为轻量方法层（markdown 契约 + 无状态薄 CLI），发布 **v0.2.0**（已推 GitHub）。
用它在 agent-bus 上真实跑通**三个**开发闭环（doctor、graceful-exit、poison-event），验证了
"强规划+弱执行+强 review 兜底"省 token 方案成立。`awf-dispatch` 派活器**已首次真实验证通过**
（用它派 poison-event 卡给本机 DeepSeek，端到端跑通，PASS）。下一步 = 跨机（Windows executor）。

## 1. 三个仓库

> 绝对路径、VPS IP、SSH 别名、token 位置等私密信息**不写在本文件**（本文件入库/公开）。
> 见私有 AI Memory：topic `agent-workflow`（环境事实）+ `tailscale-mesh`（三机拓扑/SSH/IP）。

| 项目 | 说明 |
|---|---|
| agent-workflow | 方法本体。核心=`constitution.md`；派活器=`scripts/awf-dispatch.sh` |
| agent-bus | 被开发的真实项目（runtime-agnostic 事件中继）。artifact 链在 `.awf/artifacts/`（已入库） |
| ai-memory | 跨 agent 长期记忆，**优先读**。私密值只在这里 |

## 2. Git 状态（未推送的分支，别丢）

- **agent-workflow**：`main` = v0.2.0，**已推 GitHub**（收缩 + TaskCard 模板 + §11 隐私纪律 + awf-dispatch 都在 main）。干净。
  - 本地文件 `CLAUDE.md` / `AGENTS.md` 已 gitignore，不入库。
- **agent-bus**：当前分支 `awf/abus-poison-003`，是一条**线性 stack**（4 个 commit，从旧到新）：
  `bc7c6ea` doctor → `c7a5aae` graceful-exit → `dea2e94` .awf artifacts 入库（PII 已清）→
  `00c2448` poison-event 保护（+回归测试，13 单测过）。**已 push 到 `origin/awf/abus-poison-003`**（备份）。
  **尚未合并 master、未开 PR。** 工作区干净。
  - ⚠️ **默认分支是 `master`（不是 main）**，且已与本 stack **分叉**：merge-base = `9d79109`；
    `master` 多 1 个 stack 没有的 docs commit `fc6b401`。合并**非 fast-forward**。
  - 冲突仅在 **docs**（`docs/guide/installation.md`）+ `scripts/windows-poll-listener.ps1`，
    **feature 代码（client/cli.py / tests / .awf）不冲突**。合并/开 PR 时才需处理这两处；跨机不依赖合并。
- **ai-memory**：已推至 `c246528`（含本会话 awf-dispatch 首验 + poison review 缺口 + token 注入法）。
- 默认不擅自 push / 开 PR。用户要才做。

## 3. 立即要做的下一步（跨机：Windows executor）

awf-dispatch 本机链已验通、poison 卡已交付。**下一步 = 跨机**：把 executor 换成 Windows。

- **先决（未做）**：push / 合并那条本地 stack（见 §2 分叉说明）——**等用户逐条拍板**，别擅自 push。
  合并 stack 到 `master` 需先解 docs + ps1 两处冲突（feature 代码不冲突）。
- **跨机做法**：只把 executor 从 local 换成 Windows。Windows 需先 clone agent-workflow 到其项目目录
  （路径见 AI Memory）。Windows 已确认：git 2.34 / opencode v1.17.13 / agent-bus 在、agent-workflow 无。
- ⚠️ **awf-dispatch 目前只支持 `--executor local`**；跨机要给它加 SSH 分支（`--executor windows` +
  `adapters` 走 ssh 到 Windows 跑 opencode）。这是跨机那步的主要待写代码。
- 三机拓扑/SSH/IP：见 AI Memory `topics/tailscale-mesh/CONTEXT.md`（Windows = `100.81.0.48`，常离线，
  用前先 `tailscale status` 确认在线）。

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
