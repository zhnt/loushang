# Multi-Agent Context Fork Boundary

> Status: **implemented**（已实现，与 `SubagentContextFactory` 代码一致）。本文定义
> `loushang.harness.multiagent` 的子 agent 上下文构造边界：隔离模型、
> fork 档位、历史过滤、审批冒泡装配。

## Scope

`SubagentContextFactory` 回答一个问题：**子 agent 出生时看到什么**。
它从父上下文构造子 agent 的 `AgentContext`（system_prompt、messages、
tools）与运行配置，是 multi-agent 中最复杂、安全问题最集中的组件。

本文定义：

- 默认隔离模型（什么隔离、什么可共享）
- fork 三档语义与历史过滤规则
- 语义确定性约束与可选的 prompt-cache 字节前缀
- 审批冒泡装配（复用 `ApprovalRequest` 管道）
- AgentRunSpec 的最终组装

本文不定义：

- spawn 流水线的协调顺序（属 MultiAgentControl）
- agent 类型的业务定义（类型只是注入的 `AgentTypeRecord`）
- 消息投递与唤醒（属 AgentInputFacade / RunHandle）
- 模型的提示词纪律文本内容（属 ToolSurfaceAdapter 的资源）

## Why This Component

cc 的 `createSubagentContext` 证明了这条边界的重要性：默认全隔离、
显式 opt-in 共享，但**任务注册必须穿透到 root**（否则后台 agent 的
子任务成为僵尸）。Codex 的 fork 过滤（`keep_forked_rollout_item`）
证明了另一件事：fork 不是"复制历史"，而是"按规则重建一份对子 agent
有意义的历史"。两条规则合并，就是本组件的契约。

## Isolation Model

构造子上下文时，按以下矩阵处理父上下文的每一部分：

| 父上下文部分 | 默认 | 可 opt-in 共享 | 说明 |
|---|---|---|---|
| messages（对话历史） | **隔离**（fresh spawn 为空） | fork 档位共享（见下节） | 核心决策点 |
| system_prompt | **替换**为类型系统提示 | fork 时透传父前缀 | 类型决定子 agent 的角色 |
| tools | **按类型裁剪**（白/黑名单） | 不可共享原表 | 递归防护也在此（类型不含 spawn 工具） |
| model / reasoning | **继承父** | spawn 参数显式覆盖 | fork 档不可覆盖（cache 约束） |
| 审批回调 | **冒泡装配**（见下节） | 不可继承父状态 | denial 计数等策略状态重置 |
| cancel token | **独立**（ARD-002 异步不链接） | 同步 spawn（二期）链接父 | 父 ESC 不杀后台子 agent |
| 任务注册 | **穿透到 root** | 不可隔离 | cc 僵尸进程教训：注册必须全局可见 |
| 文件状态缓存（readFileState 类） | **克隆** | 可共享只读 | 防止父子互相污染"已读文件"状态 |

纪律：**默认隔离，共享必须显式声明且逐条审查**。任何新增的上下文
部分默认落入"隔离"列，除非有明确理由。

## Fork Tiers

spawn 的 `fork` 参数决定子 agent 的消息历史来源：

| 档 | 语义 | messages | system_prompt | model 可覆盖 |
|---|---|---|---|---|
| `none` | 零上下文 | 空 | 类型系统提示 | ✅ |
| `all` | 全量 fork | 父历史（过滤后） | 父前缀 + 子追加 | ❌（保持父执行配置） |
| `last N` | 最近 N 轮 | 父历史末尾 N 轮（过滤后） | 父前缀 + 子追加 | ❌ |

- `none` 是默认档：子 agent 是"刚进门的同事"，简报（spawn prompt）
  是它的全部上下文。
- `all` / `last N` 用于：父希望子继承对话背景（如"接着调查这个
  问题"），同时保持 prompt cache 前缀一致。
- 档位的**边界单位是轮（turn）不是消息条数**：一轮 = 一组 user
  输入 + assistant 响应 + 其工具往返。`last N` 截断在轮边界。

## Fork History Source（与 session fork 的统一）

fork 档的父历史**以 harness transcript 为源**，不从内存
`AgentContext.messages` 读取。这是 Codex 统一路线的采纳：

- Codex 用一个 `fork_thread` 原语同时承载用户分叉与 spawn fork，
  差异只在快照策略；其关键是父的历史本就持久化在 rollout 里。
- loushang 的 harness transcript（`ConversationRecord` 图 +
  `path_to` / `fork_plan`）与 Codex rollout 同构，同样可以作为
  统一历史源。

因此 spawn fork 与 session fork 的关系是**底层共用、语义分层**：

| | session fork（已有） | spawn fork（本组件） |
|---|---|---|
| 历史读取 | `TranscriptRepository.path_to` / `fork_plan` | **复用同一机制** |
| 选择粒度 | entry_id + `fork_position` | 轮数（none/all/last N） |
| 内容处理 | 全量保留 | **过滤重建**（下节，独有） |
| 一致性约束 | branch 图完整性 | **watermark + 确定性映射/过滤** |
| 产出 | 新 TranscriptRepository（持久化分支） | 子 AgentRunSpec.messages（内存） |
| 驱动者 | 用户/产品 | agent |

共用带来两个直接收益：

1. **父回收场景天然解决**（二期）：父 agent 已被 LRU 回收时，
   其历史仍在 transcript 中，spawn fork 不要求父在线。
2. **不新写历史读取**：轮边界的截取映射为对
   `path_to` 结果的后处理，不另起一套。

约束：transcript 记录的 payload 是产品格式（`ConversationRecord[T]`），
因此“记录 → AgentMessage”的映射是**产品注入的缝**（见后文
`TranscriptMessageMapper`）；本组件不假设产品记录格式。

## History Filter Rules（fork 档适用）

fork 的历史**不是复制**，而是按规则重建。对父历史中的每条
消息（经 `TranscriptMessageMapper` 映射为 AgentMessage 后逐条判定）：

保留：

- `UserMessage`（用户输入）
- `AssistantMessage` 中属于**最终答复**的部分（无 tool_call 的纯文本
  助手消息；含 tool_call 的助手消息整体见下）
- system / developer 消息（保留，但剥离 multi-agent 控制提示，见下）

丢弃：

- **工具中间态**：`ToolResultMessage`、assistant 消息中的 tool_call
  部分——子 agent 不需要看到父如何调用工具的细节，只需要结论
- **multi-agent 控制消息**：spawn / send / wait 工具的调用与结果、
  agent 间通信标记——子 agent 不应看到父的编排痕迹（Codex 丢弃
  `InterAgentCommunication` 的同款规则）
- **usage hint 类注入**：父上下文中的 multi-agent 使用提示文本
  （Codex 过滤 usage_hint_texts 的同款规则）；子 agent 的系统提示
  由类型重新提供

重建后追加：

- 子 agent 自己的类型系统提示（作为前缀追加或独立 system 消息）
- spawn 简报（作为首条 user 消息）

## Fork Function（可参数化工具函数）

历史选择与过滤重建封装为一个纯、可参数化的工具函数，
供不同调用方（spawn 流水线、产品自定义流程、OEM 扩展）复用：

```text
fork_history(
  source: TranscriptSource,        # 父 transcript 引用（复用 path_to 读取）
  tier: ForkTier,                  # none | all | last(N)
  *,
  filter: HistoryFilter | None,    # 可注入；默认为下节规则
  mapper: TranscriptMessageMapper, # 可注入；记录 → AgentMessage，产品提供
  cache_prefix: RenderedPrefix | None,  # fork 档透传的父已渲染前缀
) -> ForkedHistory
  # ForkedHistory:
  #   messages: [AgentMessage]     # 过滤重建后的历史
  #   prefix_bytes: bytes | None   # 可用时透传；缺失只影响 cache 命中
  #   diagnostics: [Diagnostic]    # 降级与过滤记录（如历史为空降 none）
```

约束：

- **纯函数**：同一 watermark、档位、mapper 与 filter 必产生语义相同
  的输出；
  不得依赖时间、随机数、可变全局状态。
- **参数化**：过滤规则、记录映射、前缀透传均为参数，不内嵌
  产品逻辑；产品/OEM 经参数定制，不修改函数本体。
- 调用方不得绕过它直接拼装 fork 历史——确定性约束的维护
  集中在此函数。

这与 harness 现有的 `ForkProfile` / `ForkTargetResolver`模式一致：
harness 提供保守默认，产品通过注入扩展位置与解析器。

## Determinism And Optional Cache Prefix

`all` / `last N` 首先保证的是**可重建的语义历史**。当父运行时还能
提供已渲染请求前缀时，同一父 fork 出的多个子 agent 可以额外共享
prompt cache；前缀缺失不得让 spawn 失败。因此：

1. **优先透传父已渲染的 system prompt 字节**，不重新组装（cc 的
   `renderedSystemPrompt` 透传教训：重组装可能因状态变化产生字节
   偏差，击穿 cache）；无法取得时记录诊断并按确定性规则重建。
2. **历史过滤是确定性的**：同一父上下文 + 同一档位，过滤结果逐字节
   相同；过滤规则不得依赖运行时状态（时间、随机数、可变配置）。
3. **watermark 先于映射**：只读取 `records_to(watermark)`；父在
   spawn 之后提交的新记录不进入该子上下文。产品 mapper 若保留
   tool-call 结构，必须在 mapper 内保证消息配对完整。
4. **fork 档禁止 model 覆盖**：不同 model 的请求参数不同，前缀
   无法共享（cc 的 "Don't set `model` on a fork" 纪律）。

`none` 档不受此约束（无共享前缀可言）。

## Approval Bubbling Assembly

子上下文的审批回调（`can_use_tool` 类）在构造时**固定装配为冒泡
闭包**：

1. 子 agent 的高风险工具操作产生 `ApprovalRequest`（harness 既有
   值对象）；`SubagentApprovalResolver` 用独立 envelope 附加
   `AgentRef` 发起者与父链，不篡改原工具参数。
2. 请求经管道直达 **root 交互出口**——子 agent 无自己的交互出口，
   不得自行弹窗/询问（呈现由装配层决定：TUI 弹窗 / RPC
   interaction）。
3. 审批结果沿管道回传到子 agent 的工具执行。
4. 策略状态（denial 计数、allowlist 会话记忆）在子 agent 边界
   **重置**：子 agent 不继承父的"本会话已批准"状态（cc 的
   `localDenialTracking` 隔离）。

## Context Plan And Initial Delivery

工厂的最终产出是给产品 child factory 的不可变 context plan；spawn
简报不放进 plan，而由 session runtime 经 RunHandle 的 `deliver()`
统一投递，避免同一 prompt 同时进入 context 与 queue：

```text
SubagentContextPlan
  context:
    system_prompt = 类型系统提示（none 档）或 父前缀 + 子追加（fork 档）
    messages      = []（none）或 过滤重建后的父历史（fork 档）
    tools         = 类型裁剪后的工具集
  config:
    model         = spawn 覆盖（none 档）或 父继承（fork 档）
    can_use_tool  = 冒泡闭包（固定装配）
    signal        = handle 自有 AbortController（异步不链接）
    get_steering_messages / get_follow_up_messages
                  = AgentInputFacade 队列适配（由 RunHandle 接线）
SessionMultiAgentRuntime
  deliver(spawn 简报) -> RunHandle round 1 / mode="prompt"
```

后续轮由 RunHandle 以 `mode="continue"` 驱动，context.messages 在
运行中累积——工厂只负责首轮的出生状态。

## Product Injection Seams

| 缝 | 注入内容 | 默认 |
|---|---|---|
| `HistoryFilter` | fork 历史过滤规则 | 上述保留/丢弃规则 |
| `TranscriptMessageMapper` | transcript 记录 → AgentMessage 的映射 | 产品提供（记录 payload 是产品格式） |
| `TypeSystemPrompt` | 类型的系统提示文本 | AgentTypeRecord 携带 |
| `IsolationOverrides` | 隔离矩阵的逐条覆盖 | 默认隔离 |
| `ApprovalExitPort` | root 交互出口的适配 | 装配层提供（TUI / RPC） |

护栏：注入改变的是**策略与内容**（过滤哪些消息、提示文本、审批
出口呈现），不改变**结构不变式**（默认隔离、cache 字节约束、冒泡
必须到 root、任务注册穿透）。

## Ownership And Boundaries

拥有：

- 隔离矩阵与共享 opt-in 判定
- fork 档位语义与历史过滤重建
- cache 字节一致性约束的维护
- 审批冒泡闭包的装配
- 首轮 AgentRunSpec 的组装

不拥有：

- spawn 协调顺序（Control）
- 类型的业务定义与编译（装配层 / method）
- 多轮驱动与 context 跨轮传递（RunHandle）
- 审批请求的策略判定与呈现（harness approval / 装配层）
- 消息投递（AgentInputFacade）

## Failure Semantics

- fork 档历史为空或过滤后为空：降级为 `none` 档语义（仅简报），
  记录诊断，不报错——fork 是优化，不是正确性依赖。
- 类型裁剪后工具集为空：构造失败，spawn 以结构化错误返回（类型
  定义非法，属装配期问题，不应拖到运行期）。
- cache 约束无法满足（如父前缀不可得）：降级为重组装并记录诊断，
  不阻塞 spawn——cache 击穿是性能损失，不是错误。
