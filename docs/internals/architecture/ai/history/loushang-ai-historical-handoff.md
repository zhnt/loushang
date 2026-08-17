# Loushang AI Historical Handoff Summary

> 历史快照：本文保留当时的命名与设计语境，不代表当前正式术语；当前代码统一使用 `APIAdapter`。

## Goal

当前在设计 `loushang.ai`，优先做 `public API / types / streaming / cancellation`，暂不进入正式实现代码。

## Architecture Position

- `loushang.ai` 的职责不超过 `reference AI SDK`
- 它是模型接入与统一流式协议层
- 不负责：
  - `Agent`
  - `AgentLoop`
  - `AgentEvent`
  - tool orchestration policy
  - channel boundary protocol

## Naming Decision

- Python import path 方向倾向于 `loushang.ai`
- 语义严格对齐 `reference AI SDK`
- 表达轻度 Python 化
- 函数名/字段名用 `snake_case`
- 协议字面值保留 `reference AI SDK` 语义，例如：
  - `toolCall`
  - `toolUse`

## Public API Direction

根入口建议只暴露稳定核心：

- `stream`
- `complete`
- `stream_simple`
- `complete_simple`
- model registry 查询
- api registry 查询/注册
- 核心类型

不建议先暴露：

- provider-specific option types
- provider 实现类
- utils/helpers
- oauth/env helpers

## Type System Decisions

已建立文档：

- [Loushang AI Glossary](../../glossary/loushang-ai.md)
- [Loushang AI Types](../../glossary/loushang-ai-types.md)

已冻结的核心方向：

- `Model`
- `Context`
- `Tool`
- `UserMessage`
- `AssistantMessage`
- `ToolResultMessage`
- `TextContent`
- `ThinkingContent`
- `ImageContent`
- `ToolCall`
- `Usage`
- `StopReason`
- `AssistantMessageEvent`
- `StreamOptions`

## Streaming and Cancellation Decisions

已建立文档：

- [Loushang AI Streaming and Cancellation](../loushang-ai-streaming-and-cancellation.md)

当前冻结结论：

- `loushang.ai` 绑定 Python async iteration
- `loushang.ai` 不把 `asyncio` 深度写入 public contract
- 默认实现允许基于 `asyncio`
- cancellation 是协议语义，不只是 runtime 机制
- `signal` 字段名保留
- `AbortSignalLike` 当前建议最小语义：
  - `cancelled: bool`

## AssistantMessageEventStream Decisions

当前冻结结论：

- public：单一只读对象
- public methods：
  - `__aiter__()`
  - `result()`
- internal：reader / writer 分离
- internal factory：
  - `(stream, writer)`
- writer 最小接口：
  - `push(event)`
  - `finish(message)`
  - `fail(message)`

## Internal Streaming Layers

当前建议三层：

1. provider SDK stream
2. raw part stream
3. assistant message event stream

取舍结论：

- public contract 对齐 `reference AI SDK`
- internal streaming 结构吸收 `kimi-cli`
- provider adapter lower-level shape 可参考 LiteLLM

## Validation Status

已建立：

- [AI Streaming Spike README](../../spikes/ai-streaming/README.md)
- [AI Streaming Spike Results](../../spikes/ai-streaming/RESULTS.md)
- [Loushang AI Streaming Validation](../validation/loushang-ai-streaming-validation.md)

已通过验证：

- normal completion
- aborted mid-stream
- mixed consumption
- reader/writer separation
- 10,000 text_delta throughput smoke test

验证结论：

- 当前 streaming 模型可行
- 当前 cancellation 模型可行
- 当前 public contract 不需要推翻

## Key Documents

重要文档包括：

- [Loushang Strategy](../../../strategy/strategy.md)
- [Architecture Overview](../../architecture-overview.md)
- [Loushang Subsystems](../../subsystem.md)
- [Loushang Subsystem Diagram](../../subsystem-diagram.md)
- [Loushang Agent](../../glossary/loushang-agent.md)
- [Loushang Agent Types](../../glossary/loushang-agent-types.md)
- [Loushang Channel Boundary Protocol](../../loushang-channel-boundary-protocol.md)
- [Loushang AI](../../glossary/loushang-ai.md)
- [Loushang AI Types](../../glossary/loushang-ai-types.md)
- [Loushang AI Streaming and Cancellation](../loushang-ai-streaming-and-cancellation.md)
- [Loushang AI Streaming Validation](../validation/loushang-ai-streaming-validation.md)

## Next Step

下一步进入：

- `ApiProvider` registry 设计
- `stream()/complete()/stream_simple()/complete_simple()` 顶层签名设计

暂时不要：

- 直接进入正式实现
- 扩展到 `AgentLoop`
- 提前设计真实 provider 细节
