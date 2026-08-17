# ARD-002: Async-Only Execution And Message-Driven Recovery

## Status

Proposed（目标设计，待接受）

## Context

`loushang.harness.multiagent` 需要决定两个相互关联的执行语义：

1. **spawn 执行模式**：是否支持同步 spawn（父 agent 阻塞等待子结果作为
   工具返回），还是一期全异步。
2. **回收后恢复语义**：已完成/被回收的子 agent 再次收到消息时，如何
   恢复运行。

两个参考实现的做法：

- **Codex v2**：spawn 后立即返回（异步）；v1 的显式 `resume_agent` 工具
  在 v2 被废除，改为 `ensure_v2_agent_loaded`——LRU 回收（
  `V2Residency`）只卸载状态已外置的 idle 终态 agent，父子边保持 open，
  消息到达时透明重载，调用方无感知。close 后不可寻址。
- **Claude Code**：`SendMessageTool` 对停止的 agent 自动
  `resumeAgentBackground`（任务表内），甚至任务表淘汰后从磁盘
  transcript 恢复——同样消息驱动、调用方透明。cc 的 fork gate 趋势是
  所有 spawn 强制异步，统一 `<task-notification>` 交互模型。

两家共识：**异步 + 通知是终局形态；恢复是消息驱动的自动行为，不需要
显式 resume 工具**。差异仅在 Codex 有显式的 open/closed 区分（回收只
针对 open agent），cc 的边界更模糊。

loushang 一期的约束：

- 并发上限小（个位数），没有真实的容量压力源，LRU 回收不是一期需求。
- 全异步使 ToolSurfaceAdapter 只有一条路径（spawn → 注册 → 立即返回
  引用），无需阻塞聚合、同步转后台等机制。

## Decision

### 1. 一期全异步执行，不支持同步 spawn

- `spawn_agent` 工具总是立即返回结构化引用（agent path / 任务名），
  子 agent 在后台运行。
- 父 agent 获取结果的唯一途径是通知：子 agent 终态时经 AgentInputFacade 向父
  input 注入完成通知（user-role 消息进入后续 turn）；`wait_agent`
  等待自己 input 的 activity。
- 不实现：阻塞式 spawn、前台 run 注册、同步转后台 race。

后续若引入同步 spawn，作为增量设计（ToolSurfaceAdapter 增加阻塞聚合
路径），不改变本 ARD 的异步语义。

### 2. 恢复 = 消息驱动自动唤醒，无显式 resume 工具

- **open / closed 区分**（采纳 Codex v2 语义）：
  - `send_message` 到 idle / 已完成未关闭（open）的 agent = 自动驱动
    新一轮 run（等价 Codex `followup_task` 与 cc auto-resume）。
  - `send_message` 到已 close 的 agent = 结构化工具错误（不可寻址）。
- **一期不做 LRU 回收**：并发上限小，无容量压力；没有回收就没有
  "回收后恢复"问题，idle agent 的 send_message 即唤醒。
- **二期预留**：引入容量压力下的回收时，回收前状态必须已外置、父子
  边保持 open、send_message 透明重载（Codex v2 语义）；不引入显式
  resume 工具。

### 3. 取消传播双模式（配套规则）

- 全异步下所有子 agent 均为后台运行：**不链接**父 run 的取消——父被
  取消（如用户 ESC）不杀子 agent，只能显式 interrupt / close
  （cc 的后台 ESC 语义）。
- 子树取消是显式操作：close 父时递归 close 后代。

## Consequences

### Positive

- 一期路径唯一：ToolSurfaceAdapter / RunHandle 无同步分支，实现与测试
  面最小。
- 通知模型统一：完成、消息、steer 都是 input 事件，wait 语义单一。
- 恢复语义与两家参考实现的终局形态一致，避免发明第三种。
- 一期不回收使"状态外置"可以二期再落地，不阻塞一期。

### Negative / Costs

- 需要"等结果再继续"的场景必须由 spawn + wait + 通知组合表达，提示
  纪律需明确告知模型这一模式。
- 取消传播双模式在一期实际只有一种（异步不链接），规则文档先行，
  实现从简。

### Follow-ups

- ToolSurfaceAdapter 的提示纪律资源写明"spawn 立即返回、结果经通知
  到达、wait 等待活动"。
- 二期回收设计时，本 ARD 第 2 条三期预留语义作为输入。
