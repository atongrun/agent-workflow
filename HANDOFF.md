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

**2026-07-12 下午新进展**：SSH 取 token 的痛点引出「curl 取 token」方向，已真实派卡给 Windows coder
(DeepSeek) 开发出 agent-bus `/bootstrap/token` 端点（9 测试过，分支 `awf/abus-bootstrap-token-006`
@`94e972e`，**未 push/未 review**）。过程暴露 **listener 环境 bug**（cmd.exe 起 handler git 命令莫名失败）。
用户据此要求「别自己攒架构、去调研成熟方案」，已用 workflow 完成**三端通用化调研**（结论：根因是
agent-bus `shell=True` 跑 handler；改 argv+shell=False + WinSW/launchd/systemd 守护 + justfile）。
**下一个 session 的大任务 = 按调研落地三端通用化**（见 §3 + AI Memory `2026-07-12-3os-reliability-research`）。

## 1. 三个仓库

> 绝对路径、VPS IP、SSH 别名、token 位置等私密信息**不写在本文件**（本文件入库/公开）。
> 见私有 AI Memory：topic `agent-workflow`（环境事实）+ `tailscale-mesh`（三机拓扑/SSH/IP）。

| 项目 | 说明 |
|---|---|
| agent-workflow | 方法本体。核心=`constitution.md`；派活=`scripts/awf-dispatch.sh`；执行=`scripts/awf_role.py`+`awf_listen.py`（Python，跨平台） |
| agent-bus | 被开发的真实项目（runtime-agnostic 事件中继）。artifact 链在 `.awf/artifacts/`（已入库） |
| ai-memory | 跨 agent 长期记忆，**优先读**。私密值只在这里 |

## 2. Git 状态（未合并的分支，别丢）

- **agent-workflow**：`main` 本地新 commit `c1e5db0`（三端 step1-2：awf_role/awf_listen 硬化 + fetch refspec），
  **未 push**。旧 bash 版（`awf-listen.sh` 等）暂留待清理；`awf-listen.sh` 有个 `AWF_BASH_BIN` workaround diff
  **未 commit**（被 argv+shell=False 取代的死胡同）；`awf_bootstrap.py`/`awf_handoff_check.py`（SSH 版）仍未 commit。
- **agent-bus**：分支 stack（都已 push origin，**均未合并 master**）：poison-003 → pending-count-004 →
  send-dryrun-005 → **`awf/abus-bootstrap-token-006` @`94e972e`**（本会话从 Windows 取回 push 到 origin，**review 已过**）
  → **`awf/abus-handler-argv-007` @`f5c68f3`**（三端 step3：handler argv+shell=False，**本地未 push**）。
  - ⚠️ 默认分支 `master`，与 stack 分叉；合并非 ff。
  - ⚠️ **Windows 侧 agent-bus remote 已改 SSH**（`git@github.com:...`，用 deploy key）；Mac 侧仍 HTTPS+代理。
- **ai-memory**：本会话 note `2026-07-12-3os-rootcause-fix-landed`（**未 push**）。
- 默认不擅自 push / 开 PR / 合并。用户要才做。

## 3. 立即要做的下一步

### 3.0 大任务（用户拍板）：三端通用化 Agent Bus — step1-3 已落地，step4-5 待做

用户目标 = Agent Bus 做成 **Linux/Mac/Windows 三端无缝接入、易用、稳定，但可以简单**（单人用）。
已用 workflow 完成调研，**别再自己攒架构，按调研落地**。完整选型见 AI Memory
`notes/2026-07-12-3os-reliability-research.md`；本次落地见 `2026-07-12-3os-rootcause-fix-landed`。

**✅ step1-3 根因修复已 commit（本地，未 push）**：
- step1 灭 gbk：`awf_listen` 进程树 `PYTHONUTF8=1`；`awf_role` capture/spawn 加 `errors='replace'`。
- step2 spawn env/cwd 硬化：`child_env()` inherit-and-augment（绝不 `env={}`）+ `AWF_REPO_DIR` 转绝对 cwd。
- step3 agent-bus `client/cli.py`：`render_command` 返回 **argv 列表**（`shlex.split` 一次）+ `run_handler(shell=False)`，
  删 `_quote_command_value`/`list2cmdline`（净减代码）。Mac 16 测试过 + 集成检查过 + Windows 真机验新路径 rc=0。

**⏳ step4-5 待做（本 session 用户明确不做）**：
- **服务守护**：Win=WinSW、Mac=launchd、Linux=systemd --user（替代手动 SSH 起 listener）。放 `scripts/service/`。
- **弱模型运维**：一个 `justfile`（doctor/up/down/status/logs/install-service，per-OS 分派 + 幂等）。
- 别碰：Ansible、自建 guardrail 框架（过度）。

### 3.1 待收尾 / 决策

1. **✅ review `/bootstrap/token` 已过（无 bug）**：本会话从 Windows 取回 `94e972e` push 到 origin，强 review 通过
   （对齐 TaskCard、15 测试过、安全探针全清；minor: compare_digest 长度泄漏/无 rate-limit 是卡里明列的 Later）。
   **决策：先不合 master，先做了 B。** 之后 bootstrap 脚本 SSH→curl 重写（curl 端点已就绪）。
2. **push/合并决策（用户）**：agent-workflow `c1e5db0` + agent-bus `awf/abus-handler-argv-007`(`f5c68f3`) +
   其下 `awf/abus-bootstrap-token-006`(`94e972e`) 都本地未 push。要不要 push / 合并 stack，用户定。
3. **旧 bash 脚本清理**（含 `awf-listen.sh` 那个未 commit 的 `AWF_BASH_BIN` workaround diff）+ agent-bus stack 合并。
- 环境/路径/凭证全坑：AI Memory `notes/2026-07-12-cross-machine-windows-python.md` +
  `2026-07-12-curl-bootstrap-and-listener-env-bug.md`。三机拓扑 `topics/tailscale-mesh/CONTEXT.md`
  （Windows=`100.81.0.48`，用前 `tailscale status`）。

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
