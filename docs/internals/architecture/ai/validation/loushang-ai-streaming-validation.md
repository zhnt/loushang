# Loushang AI Streaming Validation

## Scope

本文档记录 `loushang.ai` 在 streaming 与 cancellation 设计上的一次架构验证结论。  
它基于 `spikes/ai-streaming` 中的最小 Python 原型。

实验记录请参见：

- [AI Streaming Spike README](../../../spikes/ai-streaming/README.md)
- [AI Streaming Spike Results](../../../spikes/ai-streaming/RESULTS.md)

## Validation Goal

本次验证主要回答以下问题：

1. `AssistantMessageEventStream` 作为 public contract 是否可行
2. internal reader / writer 分离是否合理
3. `AbortSignalLike` 的最小语义是否足够
4. `aborted` 是否能稳定映射到最终 `AssistantMessage`
5. `await stream(); result()` 是否足以成为 `complete()` 的基础
6. 默认 `asyncio` 实现是否能与 runtime-neutral public contract 共存

## Validation Method

采用最小技术原型验证，而不是正式实现。

验证原型包括：

- 最小协议类型
- 最小 event stream
- 最小 writer companion
- 最小 assembler
- 最小 cancellation signal
- 一个包含多个场景的 demo

## Validated Results

### 1. Public Stream Contract Is Viable

已验证：

- `AssistantMessageEventStream` 对外只暴露：
  - 异步迭代
  - `result()`

该形态在 Python 中自然可用，能够支持：

- 流式消费事件
- 最终结果收敛

### 2. Internal Reader/Writer Split Is Viable

已验证：

- internal `(stream, writer)` 分离可行
- assembler 只依赖 writer 的最小写接口即可工作

因此，当前建议可冻结为：

- public 单对象
- internal reader/writer 分离

### 3. Minimal Cancellation Signal Is Viable

已验证：

- `signal.cancelled: bool` 足以表达取消语义
- 不需要把 `asyncio.Event` 写入 public contract

因此，当前建议可冻结为：

- 保留字段名 `signal`
- public 语义使用 `AbortSignalLike`
- `AbortSignalLike` 采用最小只读协议：
  - `cancelled: bool`

### 4. Aborted Mapping Is Viable

已验证：

- 当检测到取消时，可以稳定映射为：
  - `ErrorEvent(reason="aborted")`
  - 最终 `AssistantMessage(stop_reason="aborted")`

因此，取消应继续作为协议语义保留，而不是只作为 runtime 机制保留。

### 5. `complete()` Can Build on `await stream(); result()`

已验证：

- 即使先消费部分事件，再调用 `result()`，最终结果仍能正确收敛

因此，当前建议可冻结为：

- `complete()` 的核心实现可以建立在 `await stream(...); await stream.result()` 之上

### 6. Default Asyncio Implementation Is Compatible

已验证：

- 默认实现可基于 `asyncio`
- 同时不需要把 `asyncio.Event` / `asyncio.Task` 写进 public type surface

因此，当前建议继续保持：

- public contract runtime-neutral
- default implementation may use `asyncio`

## Architecture Decision Impact

本次验证支持以下设计继续向前推进：

1. `AssistantMessageEventStream` 保持为 `loushang.ai` 的 public streaming contract
2. internal streaming 采用三层结构：
   - provider SDK stream
   - raw part stream
   - assistant message event stream
3. raw assembler 负责 partial message / final message / event emission
4. `APIAdapter` 负责 SDK stream 到 raw parts 的翻译
5. `AbortSignalLike` 继续采用最小协议设计

## Issues Found

### Module Naming

在 spike 目录中，裸 `types.py` 与 Python 标准库 `types` 存在命名冲突。

这说明：

- spike 适合用裸目录做原型
- 正式实现应进入包命名空间，例如：
  - `loushang/ai/types.py`

### Validation Boundary

本次验证仅覆盖：

- text event path
- aborted path
- stream/result 协作
- smoke-level throughput

它尚未覆盖：

- tool call event path
- thinking event path
- image path
- 真实 provider SDK adapter
- 更复杂的取消传播

## Open Questions

虽然当前方向已被验证为可行，但仍有后续问题需要继续设计：

1. `APIAdapter` registry 的 Python 形态
2. `stream()` / `complete()` / `stream_simple()` / `complete_simple()` 的正式签名
3. raw part 的内部类型体系
4. tool call / thinking / image 在 assembler 中的完整事件矩阵

## Current Conclusion

本次架构验证的当前结论是：

1. streaming 模型可行
2. cancellation 模型可行
3. 当前 public contract 在 Python 侧应采用显式 async-start 变体
4. 可以继续进入 `APIAdapter` registry 与顶层签名设计阶段
