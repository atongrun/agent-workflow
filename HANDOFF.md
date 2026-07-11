# 交接文档 — 给下一个 Agent（预计 Codex）

> 写于 2026-07-11 by Claude Code (Opus 4.8)。上一段工作：把 agent-workflow 收缩成"个人开发
> 方法+交接协议"，并用它真实推进 agent-bus 两个任务。本文档让你快速接手，不必重读全部历史。
> **先读 AI Memory**：`ai-memory/topics/agent-workflow/CONTEXT.md` 和
> `notes/2026-07-11-workflow-dogfood-and-tiering.md`（那是长期真相源，比本文件更权威）。

## 0. 一句话现状

Agent Workflow 已收缩为轻量方法层（markdown 契约 + 无状态薄 CLI）。已用它在 agent-bus 上真实跑通
两个开发闭环（doctor、graceful-exit），验证了"强规划+弱执行+强 review 兜底"省 token 方案成立。
现在收尾，交接给你继续。

## 1. 三个仓库 / 位置

> 具体绝对路径、VPS IP、SSH 别名、token 位置等私密信息**不写在本文件**（本文件入库）。
> 它们在操作者的私有 AI Memory 里：topic `agent-workflow`（本项目环境事实）和
> `tailscale-mesh`（三机拓扑/SSH/IP）。下个 agent 先读 AI Memory 取这些值。

| 项目 | 位置 | 说明 |
|---|---|---|
| agent-workflow | `<本地工作区>/agent-workflow` | 方法本体。核心=`constitution.md` |
| agent-bus | `<本地工作区>/agent-bus` | 第一个被开发的真实项目（事件中继） |
| ai-memory | `<本地工作区>/ai-memory` | 跨 agent 长期记忆，**优先读** |

## 2. 未提交/未推送的工作（重要，别丢）

- **agent-workflow**：分支 `refactor/shrink-to-method-contract`，已 commit（收缩 + TaskCard 模板改进），
  **未推送、未合并 main**。`CLAUDE.md` / `AGENTS.md` 是本地文件（已 gitignore，不入库）。
- **agent-bus**：分支 `awf/abus-exit-002`（含 doctor commit bc7c6ea + graceful-exit commit c7a5aae），
  **未推送、未合并**。基线分支是 `windows-poll-listener-workdir`。
- **ai-memory**：新增了 `topics/agent-workflow/` 和两篇 note，**未 git commit/push**（ai-memory 用 git 同步）。
- **artifact 链**：`agent-bus/.awf/artifacts/01..10`（baseline→decision ×2 轮），已 gitignore 不入 agent-bus 库。

> 收尾时若用户要，把这些 push / 开 PR。默认不擅自 push。

## 3. 方法怎么用（constitution 的落地）

Brownfield 路径：Baseline → 冻结架构(只冻下一里程碑需要的，≤3轮) → 一次一张 TaskCard → 执行 →
review(只标确定性失败) → 你 decide。artifact 存被开发项目的 `.awf/artifacts/`。

**TaskCard 要自包含**（constitution §6a/§6b）：带真实文件/行号锚点、真实验证命令、out-of-scope、
交卡前自查清单。让全新会话的弱模型照卡就能干，不依赖聊天历史。模板见 `templates/artifacts/task-card.md`。

## 4. 怎么派活给执行端（当前做法 + 已知坑）

当前：Claude(architect) 经 **VPS Agent Bus** 发事件 → coder listener → 触发 executor CLI 执行。
- VPS SSH 别名、Agent Bus URL、token 位置：见私有 AI Memory（topic `tailscale-mesh` + `agent-workflow`）。
  token 从环境变量读，**绝不写进代码或本文件**。
- executor CLI 可插拔（OpenCode / Codex / Claude Code / …），经 `scripts/adapters/<tool>.sh` 适配。
  例：OpenCode `opencode run --dir <repo> -f <card> [-m <model>] "$(cat prompt)"`。

**⚠️ 已知坑（务必避开）**：
- **prompt 绝不能内联进 shell**。一个 em-dash 就把 SSE 事件编码搞坏 → listener crash-loop（poison event）。
  **prompt 走文件 + OpenCode `@文件` 引用**。这正是待办 #17 `awf-dispatch` 要解决的。
- `--once` 会撞历史未 ACK 事件先退出；发新任务前先确认 coder pending 是否干净。
- listener 是独立进程，不会随你退出而退；跑完记得 kill 或用刚做的 `--exit-after-idle`。

## 5. 接下来干什么（优先级排序）

1. **[近] 做 `awf-dispatch` 轻量派活器**（task #17）。放 agent-workflow `scripts/`。固定脚本，只填 3 参数
   （卡文件 / 执行模型 / 事件类型）。prompt 用固定模板 + 卡文件 `@` 引用（**不内联**）。含 poison-event
   兜底（同事件失败 N 次跳过）。定位=方法的可选辅助工具，不进 core、不违反"core 只做校验"。
2. **[近] agent-bus 继续里程碑**（用 workflow + awf-dispatch）。Later 池里按 use-first 挑：
   poison-event 保护（P4 类）、工作队列/竞争消费者语义（P2，多机同名 worker 谁接）、worker 实例寻址
   （P2/P3 同根，coder@mac）。详见 `ai-memory/.../agent-collaboration/notes/2026-07-11-agent-bus-dogfood-findings.md`。
3. **[中] 省 token 分层继续校准**：下张卡可试"更精简的卡"，看弱模型返工率是否上升，定"规划该细到什么程度"。
4. **[大，"下个项目"] 跨机器终局**：GitHub PR 做 artifact 真相源 + `@code`/`@planner` 提及交接 +
   角色可插拔（Mac Claude Code / Hermes / Windows OpenCode 都是入口）。桥(@mention→唤醒 agent)选型待定。
   见 workflow note 的"跨机器终局架构"段。

## 6. 关键原则（别违背）

- Agent Workflow 不执行/不调度/不编排。执行是各 agent runner 内部的事。
- 一次只详细规划一个里程碑；Later 不阻塞当前。
- 弱模型执行必须配 review 兜底（真实抓到过 DeepSeek 的 bug）。
- 不擅自 push / 开 PR / 动用户 VPS 配置；破坏性操作先确认。
