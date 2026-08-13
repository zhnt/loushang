# Loushang-AI Raw Part Design V1

## Scope

本文档定义 `loushang-ai` 中 raw part 的设计边界。  
raw part 是 `Provider Adapter Component` 与 `Raw Assembler` 之间的内部标准中间语义。

本文档只讨论：

- raw part 在整体结构中的位置
- raw part 的设计目标
- raw part 的建议分类
- raw part 与 provider event / public event / final message 的边界
- `Raw Assembler` 对 raw part 的消费契约

本文档不讨论：

- 最终 Python class / dataclass 定义
- provider-specific payload 字段
- public `AssistantMessageEvent` 的最终字段细节
- 真实 adapter 代码实现

---

## Input Documents

- [Loushang-AI Provider Adapter Strategy](/home/dev/workspace/loushang/docs/architecture/ai/loushang-ai-provider-adapter-strategy.md)
- [Loushang-AI Component Structure V1](/home/dev/workspace/loushang/docs/architecture/ai/loushang-ai-component-structure-v1.md)
- [Loushang-AI Component Interfaces V1](/home/dev/workspace/loushang/docs/architecture/ai/loushang-ai-component-interfaces-v1.md)
- [Loushang-AI Component Interactions V1](/home/dev/workspace/loushang/docs/architecture/ai/loushang-ai-component-interactions-v1.md)
- [Loushang AI Streaming and Cancellation](/home/dev/workspace/loushang/docs/architecture/ai/loushang-ai-streaming-and-cancellation.md)

---

## Why Raw Parts Matter

`loushang-ai` 现在已经冻结了两条主链路：

1. `Top-Level AI API -> API Adapter Registry -> Provider Adapter`
2. `Provider Adapter -> Raw Part -> Raw Assembler -> Assistant Message Event Stream`

第一条主链路已经基本明确。  
当前还需要补上的关键内部协议，就是第二条主链路。

如果 raw part 这一层不明确，后续实现很容易出现三种问题：

1. provider adapter 直接吐 public event
2. assembler 被迫理解 provider 私有事件格式
3. raw part 过厚，提前携带了 public event 或 final message 的生命周期语义

因此，raw part 不是“临时中间结构”，而是 `loushang-ai` 内部最关键的标准化边界之一。

---

## Position In The Stack

raw part 位于：

- `Provider Adapter Component` 之后
- `Raw Assembler` 之前

主链路应保持为：

`Provider Adapter -> Raw Part -> Raw Assembler -> AssistantMessageEvent / AssistantMessage`

这意味着：

- provider adapter 的直接输出目标是 raw part
- assembler 的直接输入目标是 raw part
- public event 不应直接成为 adapter 输出

---

## Design Goals

raw part 设计优先满足以下目标：

1. 对 provider 协议差异有足够承载力
2. 对 public contract 保持足够克制
3. 便于 assembler 做增量收敛
4. 不把 final message 生命周期过早前移
5. tool / thinking / multimodal 语义可渐进扩展

---

## Raw Part Is Not

raw part 不是：

- provider 原始 SDK event
- HTTP chunk
- public `AssistantMessageEvent`
- final `AssistantMessage`

raw part 也不是：

- 顶层 API 的返回值
- 调用方可见对象

因此 raw part 必须保持：

- 内部可用
- 外部不可见

---

## Normalization Boundary

raw part 应作为唯一标准归一化边界。

这意味着：

- 不同 provider adapter 都向 raw part 对齐
- `Raw Assembler` 只理解 raw part，不理解 provider 私有事件
- public event 统一由 assembler 生成，而不是由 adapter 直接生成

这条边界一旦模糊，后面最容易发生的退化就是：

- OpenAI adapter 长一套 event
- Anthropic adapter 长另一套 event
- assembler 变成一堆 provider-specific if/else

---

## Raw Part Categories

当前建议把 raw part 分成 5 类。

### 1. Lifecycle Parts

用于表达一次响应流的生命周期关键节点。

建议至少包含：

- `response_start`
- `response_done`
- `response_error`

作用：

- 让 assembler 知道响应何时开始、何时正常结束、何时异常结束
- 为 `usage`、`stop_reason`、`response_id` 收敛提供落点

注意：

- `response_done` 仍然不是 public `done` event
- 它只是 assembler 的内部收敛信号

### 2. Content Parts

用于表达 assistant 内容的原始增量。

建议至少包含：

- `text_delta`
- `thinking_delta`
- `image_part`

作用：

- 承载正文文本
- 承载 thinking/reasoning 内容
- 承载非文本内容部件

注意：

- 这里表达的是“内部归一内容语义”
- 不是最终的 content model，也不是 public event payload

### 3. Tool Parts

用于表达 tool call 相关增量。

建议至少包含：

- `tool_call_start`
- `tool_call_args_delta`
- `tool_call_done`

作用：

- 支持 tool call 从增量到完整对象的收敛
- 避免 assembler 直接理解 provider-specific tool event

注意：

- tool call 的最终完整对象由 assembler 负责收敛
- raw part 层只表达 tool call 的归一增量与边界

### 4. Metadata Parts

用于表达与内容平行、但不应混入内容流本身的附加元数据。

建议至少包含：

- `usage_delta`
- `response_id`
- `stop_reason`

作用：

- 为 usage / stop reason / response id 提供统一落点

注意：

- 这些信息不应依附在 text delta 上
- 也不应等到 final message 才突然出现

### 5. Control Parts

用于表达与运行控制有关、但需要进入 assembler 收敛路径的内部信号。

建议至少包含：

- `aborted`

作用：

- 将 runtime cancellation 收敛为协议级内部控制语义

注意：

- `aborted` 进入 assembler 后，才最终对外表现为：
  - `error(reason="aborted")`
  - `AssistantMessage.stop_reason = "aborted"`

---

## Why These Categories

当前这 5 类设计有两个好处：

1. 不把所有东西都压进 content delta
2. 不把 metadata / lifecycle / control 混成单一“事件流”

这样可以让 assembler 更清楚地做三件事：

- 组内容
- 收 metadata
- 决定结束方式

---

## Raw Part Granularity Rule

raw part 的粒度应比 provider event 更稳定，但比 public event 更细。

也就是说：

- raw part 不应该一一复制 provider event
- raw part 也不应该直接等于 public event

更具体地说：

- provider event -> raw part：是“归一”
- raw part -> public event：是“装配与对外表达”

因此，raw part 的理想粒度是：

- 足够细，能支持 assembler 做增量收敛
- 足够粗，不必保留 provider 私有细节

---

## Raw Part Fields Rule

当前建议 raw part 只携带 assembler 真正需要的最小字段。

例如：

- 文本增量带 `text`
- tool args 增量带 `delta`
- usage 带 normalized usage 数值
- stop reason 带 normalized stop reason

不建议 raw part 直接携带：

- SDK 原始 event 对象
- provider-specific chunk type
- HTTP response / request object
- public event-specific formatting 字段

---

## Raw Part And Public Event Boundary

raw part 与 public `AssistantMessageEvent` 的边界必须明确。

raw part 负责：

- 提供 assembler 可消费的中间语义

public event 负责：

- 提供上游调用方可消费的稳定流式表达

因此：

- raw part 可以是 `tool_call_args_delta`
- public event 更可能是 `tool_call_delta` 或更高层的对外事件

再比如：

- raw part 可以是 `response_done`
- public event 才是最终的 `done`

这条边界不能反过来。

---

## Raw Part And Final Message Boundary

raw part 绝不应提前携带 final message 生命周期。

也就是说，raw part 不应直接表示：

- “这里就是最终 AssistantMessage”
- “这里已经是完整 tool call list”
- “这里已经是最终 content list”

这些都应由 `Raw Assembler` 负责收敛生成。

---

## Assembler Contract

`Raw Assembler` 对 raw part 的消费契约建议冻结为：

1. 只消费 raw part
2. 不消费 provider 私有事件
3. 对不同类别 raw part 使用不同收敛路径
4. 最终统一产出：
   - public `AssistantMessageEvent`
   - final `AssistantMessage`
   - normalized `usage`
   - normalized `stop_reason`

这意味着 assembler 内部至少要有三类状态：

- 内容收敛状态
- tool call 收敛状态
- response metadata / lifecycle 状态

---

## Suggested Assembly Rules

### Text

- 连续 `text_delta` 累加为 assistant text content

### Thinking

- 连续 `thinking_delta` 累加为 thinking content
- 如有 encrypted/signature 信息，应由 raw part 显式表达，而不是藏在 text content 里

### Tool Call

- `tool_call_start` 建立 pending tool call
- `tool_call_args_delta` 逐步累加参数
- `tool_call_done` 关闭 pending tool call，并形成完整 tool call 语义

### Metadata

- `usage_delta` 更新 usage
- `response_id` 收敛到 response-level metadata
- `stop_reason` 收敛到 final termination semantics

### Abort

- `aborted` 直接进入终止收敛路径
- 最终产生 `aborted` 对外语义

---

## Minimal V1 Support Surface

为了支持第一阶段正式实现，当前建议 raw part v1 至少覆盖：

- `response_start`
- `response_done`
- `response_error`
- `text_delta`
- `tool_call_start`
- `tool_call_args_delta`
- `tool_call_done`
- `usage_delta`
- `stop_reason`
- `aborted`

而下面这些可以先作为 v1.1 / v2 扩展：

- `thinking_delta`
- `image_part`
- `audio_part`
- `video_part`
- 更复杂的 multimodal metadata

这并不意味着 thinking / multimodal 不重要，而是为了让第一阶段实现路径更稳。

---

## Why V1 Starts Small

raw part 这层是内部协议，一旦开太大，后面会出现两类风险：

1. 设计得太理想，导致实现迟迟无法启动
2. 一开始把不必要的复杂度塞进 assembler

因此 v1 更合理的策略是：

- 先保住 text / tool / usage / abort 主链路
- 再增量扩展 thinking / image / audio / video

---

## Open Questions

当前 raw part 设计还保留几个下一轮问题：

1. `thinking_delta` 是否需要与 signature/encrypted 信息完全拆开
2. `response_error` 与 `aborted` 是否最终共享一个更统一的 internal control shape
3. tool call 是否需要额外的 `tool_call_delta` 中间层，而不仅是 start/args/done
4. multimodal part 是否应统一为 content-part-like raw family

---

## Takeaway

`raw part` 这一层的关键结论是：

- 它是内部标准化边界
- 它既不是 provider event，也不是 public event
- 它的主要任务是让 assembler 能稳定工作

到这一步，`loushang-ai` 的关键设计已经基本收口到实现可用程度。  
如果继续往下，下一步更适合做两件事之一：

1. 把 `Raw Assembler` contract 再细化一版
2. 开始正式实现最小 text/tool/abort 路径
