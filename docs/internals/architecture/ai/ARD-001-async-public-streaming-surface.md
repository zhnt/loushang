# ARD-001: Async Public Streaming Surface

## Status

Accepted

## Context

`loushang-ai` 在早期设计中一度参考 `reference AI SDK`，倾向采用同步返回
stream handle，并额外提供一层简化调用包装。

- `stream(...) -> AssistantMessageEventStream`

也就是同步返回 stream handle，再由调用方异步消费。

但进入 Python 实现后，出现了一个明确问题：

- provider 启动需要真实 async 边界
- 若在同步 `stream()` 中隐式启动 producer task，会引入 event loop ownership 不清、`create_task()` 时机不稳、同步调用场景下行为不诚实等问题

因此需要明确决定：

- `loushang-ai` 的 public streaming surface 是否保持同步 shape
- 还是显式采用 async-start

## Decision

`loushang-ai` 采用 **async public streaming surface**：

- `async stream(...) -> AssistantMessageEventStream`
- `async complete(...) -> AssistantMessage`

并且：

- `complete()` 建立在 `await stream(); await result()` 之上
- `APIAdapter` 协议也采用 async-start 形态

## Alternatives Considered

### A. Sync Public Surface + Lazy Async Bridge

做法：

- `stream()` 保持同步
- 返回一个延迟启动的 `AssistantMessageEventStream`
- 在第一次异步消费或 `result()` 时启动 producer

优点：

- 更接近 `reference AI SDK` 的 public surface
- 调用形态更紧凑

缺点：

- Python 中仍需额外设计 lazy-start bridge
- stream object、provider、runtime 之间的启动 responsibility 更复杂
- 会把 event loop / task 启动时机问题转移到 stream internals

### B. Async Public Surface

做法：

- `stream()` 直接进入 async 边界
- provider 启动在 public contract 层面显式表达

优点：

- 对 Python 更自然、更诚实
- provider start、task creation、loop 使用时机更清楚
- 减少隐藏 runtime 前提

缺点：

- 与 `reference AI SDK` 的 public surface 不完全一致
- 调用方需要先 `await stream(...)`

## Rationale

最终选择 B，理由是：

1. Python 的 async 启动边界应显式表达，而不应隐藏在同步入口之后。
2. `provider` 的真实启动行为本来就是 async 行为，public contract 应诚实反映这一点。
3. 对 `loushang-ai` 这种 Python 实现来说，清晰的 loop / task ownership 比保持表面同步更重要。
4. `reference AI SDK` 的同步 surface 仍可作为语义参考，但不必机械复制到 Python。

## Consequences

### Positive

- `stream()` 调用语义更直接
- provider 启动模型更稳定
- 更容易避免同步上下文下的隐式 loop 问题
- 组件边界更清楚：
  - top-level API 进入 async 边界
  - provider adapter 负责 provider start
  - event stream 负责承载事件与最终结果

### Negative

- `loushang-ai` 与 `reference AI SDK` 的 public surface 产生明确差异
- 相关设计文档需要统一改为 async-start
- 上层调用方需要在更早位置进入 async context

## Impacted Documents

- `loushang-ai-top-level-api-signatures.md`
- `loushang-ai-component-interfaces-v1.md`
- `loushang-ai-component-interactions-v1.md`
- `loushang-ai-streaming-and-cancellation.md`
- `loushang-ai-provider-adapter-strategy.md`
- `loushang-ai-api-adapter-registry.md`

## Impacted Code

- `src/loushang/ai/api/streaming.py`
- `src/loushang/ai/api_registry.py`
- `src/loushang/ai/protocols/faux.py`
- `src/loushang/ai/protocols/anthropic_messages.py`

## Follow-up

- 后续与 `reference AI SDK` 对齐时，应将“sync/async public surface”视为明确、已接受的例外。
- 除这一点外，`loushang-ai` 仍应尽量对齐 `reference AI SDK` 的消息、事件、registry 与 provider semantic 边界。
