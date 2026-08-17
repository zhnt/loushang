# Multi-Agent AgentInputFacade Boundary

> Status: **implemented**（已实现，与当前代码一致）。本文定义
> `loushang.harness.multiagent` 的 agent input facade 边界：通知合成、投递与
> `wait_agent` 等待原语。

## Scope

AgentInputFacade 是 session adapter 的统一同步原语：子 agent 完成通知、其他 agent
的消息、用户 steer 都经同一机制进入目标 agent 的运行，而 `wait_agent`
以"等待自己 input activity"为唯一等待语义。

本文定义：

- AgentInputFacade 的职责与用户队列 / system mailbox 的关系
- 消息类型与投递语义（steering / follow_up / mailbox 映射）
- 完成通知合成（终态 → 父 input）
- wait 原语（activity watch、超时、唤醒源）
- open / closed 投递规则（ARD-002）

本文不定义：

- 消息如何驱动新一轮 run（属 SubagentRunHandle）
- 终态如何推导（属 LifecycleProjection）
- 寻址与拓扑（属 AgentRegistry）
- 模型可见的 wait 工具参数面（属 ToolSurfaceAdapter）

## User Queue And System Mailbox

AgentInputFacade 不复制用户队列。harness 已有 `HostInputQueue`，原生支持：

- `QueueKind = steering | follow_up` 两种入队模式
- `snapshot()` / `drain()` / `has_pending()` 等账本操作
- 与 agent 内核挂点天然对齐：loop 在每个工具边界消费
  `get_steering_messages`，turn 结束消费 `get_follow_up_messages`

但完成通知不是用户输入，必须进入 Agent 内核的独立 system mailbox；
不得伪装成可编辑的 steering/follow_up。AgentInputFacade 统一绑定这两条
通道：

1. **来源标注**：每条输入携带 sender 与内部 kind；模型工具只能创建
   steering/follow_up，只有 Control 可创建 mailbox notice。
2. **activity 信号**：入队、steer 注入时发出 activity 通知，供
   `wait_agent` watch（HostInputQueue 本身无 watch 语义，门面补一层
   `asyncio.Condition` / watch channel 级别的活动信号）。
3. **通知合成**：终态事实 → 父 mailbox 的完成通知消息。

Agent loop 在首轮采样前和每个 tool/result 安全边界优先 drain mailbox，
再处理用户 steering；mailbox 不进入 HostInputQueue snapshot、TUI pending
preview 或可编辑队列计数。

## Message Types And Delivery Mapping

```text
AgentInputMessage
  sender: AgentPath | "user" | "system"
  kind:   "follow_up" | "steering" | "mailbox"  # mailbox 仅内部可创建
  text:   str                    # 消息正文（user-role 注入）
  payload: AgentInputPayload        # 结构化附加（终态摘要、usage 等）
```

投递映射（默认 DeliveryPolicy，产品可注入覆盖）：

| 消息 kind | 目标 running | 目标 idle/终态 |
|---|---|---|
| `follow_up` | 入 follow_up 队列，本轮结束后消费 | 驱动新一轮 run（ARD-002 唤醒） |
| `steering` | 入 steering 队列，下一工具边界注入 | 驱动新一轮 run（作为首条输入） |
| 独立 `AgentCompletionNotice` | 入 system mailbox，在下一采样安全边界消费 | 留在 mailbox；是否驱动新轮由显式 notice policy 决定 |

默认规则来自两家参考实现的对齐：

- Codex v2：send_message 不触发 turn（follow_up），followup_task 触发；
  完成通知 `trigger_turn=false`。
- cc：SendMessage 到 running agent "queued for delivery at its next tool
  round"（steering），到 stopped agent 自动 resume。

loushang 统一为：**消息的 kind 决定排队语义，目标状态决定是否唤醒**；
唤醒本身是 RunHandle 的 deliver 驱动，AgentInputFacade 只负责排队与标注。

## Completion Notice Synthesis

子 agent 终态时，Control 先发布独立的 `AgentCompletionNotice`；随后
AgentInputFacade 合成父 input 文本：

```text
completion_notice
  sender: 子 agent_path
  text:   人可读的完成摘要（终态消息截断 + 状态）
  payload:
    status:  completed | failed | interrupted
    final_message: str           # 终态消息全文
    usage:   { tokens, tool_uses, duration_ms }
    worktree / artifact refs     # 经 LifecycleProjection 丰富的事实字段（TerminalFactMapper 归 projection）
```

时序链：RunHandle 转接原始 result → LifecycleProjection 推导终态并
经 `TerminalFactMapper` 丰富事实 → AgentInputFacade 消费该事实合成
完成通知。facade 不直接调用 mapper。

纪律（cc gh-20236 教训）：

1. **先写终态事实**：LifecycleProjection 的状态转移先发生，
   `await_terminal` 的等待者立即解阻塞。
2. **再合成通知**：通知合成与投递不得阻塞状态转移；合成失败只影响
   通知内容，不反转状态。
3. 通知进入父 mailbox 后，父的 wait（若在等待）以 `AgentInputActivity`
   唤醒——**唤醒不等于消费**，父 agent 在自己的后续 turn 读到通知。
4. 默认 policy 是 `queue_only`；`wake_if_idle` 必须显式启用，且 root
   session 需提供自己的 wake callback。recipe 直接等待 terminal 时不得
   同时启用隐式父轮次。

## Wait Primitive

`wait_agent` 的语义：**等待自己 input activity，不轮询子状态**。

```text
wait_agent(timeout_ms?) -> WaitOutcome
  AgentInputActivity   # 有消息到达（含完成通知）；返回摘要，不返回内容
  Steered           # 用户 steer 注入打断了等待
  TimedOut          # 超时；返回 timed_out=true
```

规则：

1. **单一事件源**：完成通知、agent 消息、用户 steer 都唤醒 wait——
   模型不需要区分"等哪个 agent"，等待的是"我的 input 有动静"。
   （Codex v2 的 InputQueueActivity 模型。）
2. **唤醒只给摘要不给内容**：WaitOutcome 说明"哪个/哪些 sender 有
   更新"；内容在接收方的后续 turn 作为 user-role 消息自然出现——
   防止模型在 wait 结果里读到半截内容后绕过正常消息通道（Codex
   v2 的 wait 同样不返回内容）。
3. **超时边界**：timeout 有 min/max/default，由策略参数注入（产品
   可调）；超时返回是正常结果不是错误。
4. **steer 优先**：等待期间用户 steer 注入立即结束等待（
   `Steered`），保证用户输入永远不被 agent 间等待阻塞。

## Open / Closed Delivery Rules（ARD-002）

| 目标状态 | deliver 结果 |
|---|---|
| open + running | 按 kind 排队（steering/follow_up），返回投递回执 |
| open + idle/终态 | 排队 + 触发 RunHandle 新一轮 run（唤醒），返回回执 |
| closed | 结构化工具错误（不可寻址），**不**自动恢复 |
| 已回收（二期） | 透明重载后按 open 处理（Codex v2 语义；一期无此态） |

寻址解析（名字/相对路径 → agent_path）在 AgentRegistry；AgentInputFacade 只
消费解析后的 path。

## Product Injection Seams

AgentInputFacade 的机制写死，以下为产品/OEM 可注入的缝：

| 缝 | 注入内容 | 默认 |
|---|---|---|
| `DeliveryPolicy` | 消息 kind → 排队/唤醒的路由判定 | 上表映射 |
| `NoticeComposer` | 终态事实 → 完成通知文本的合成 | 标准模板（状态 + 截断终态消息 + usage） |
| `WaitTimeouts` | min / max / default 超时 | 策略参数（装配层注入，如 10s / 1h / 30s） |
| `ActivitySink` | activity 信号的额外消费者（如 UI 未读标记） | 仅 wait watch |

OEM 场景示例：替换 `NoticeComposer` 以本地化完成通知、或在通知中附
加其审计系统要求的字段——经扩展贡献注册，AgentInputFacade 机制不变。

## Ownership And Boundaries

拥有：

- 消息类型、来源标注，以及用户队列 / system mailbox 的通道路由
- activity 信号与 wait 原语
- 完成通知合成与投递
- open / closed 投递判定（closed 拒绝）

不拥有：

- 新一轮 run 的驱动（RunHandle）
- 终态推导与事实发射（LifecycleProjection）
- 寻址解析（AgentRegistry）
- 用户队列本身的账本操作（HostInputQueue）
- 通知的业务解释（是否构成"产物"由装配层/work 判定）

## Failure Semantics

- 投递到 closed：结构化工具错误（`agent_not_addressable`），返回给
  调用方作为正常工具结果。
- 通知合成失败：记录诊断，投递降级通知（仅状态，无终态消息全文），
  不阻塞、不重试。
- wait 期间目标 agent input facade 被 clear（如 session 重置）：以
  `AgentInputActivity` 唤醒并注明清空，由模型决定是否继续。
