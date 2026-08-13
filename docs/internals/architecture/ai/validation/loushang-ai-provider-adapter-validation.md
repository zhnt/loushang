# Loushang AI Provider Adapter Validation

## Scope

本文档记录 `loushang.ai` 在 provider adapter strategy 上的一次架构验证结论。  
它基于 `spikes/ai-provider-adapters` 中的最小原型与真实兼容端点实验。

实验记录请参见：

- [AI Provider Adapters Spike README](../../../spikes/ai-provider-adapters/README.md)
- [AI Provider Adapters Spike Results](../../../spikes/ai-provider-adapters/RESULTS.md)

## Validation Goal

本次验证主要回答以下问题：

1. `APIRegistry -> APIAdapter -> raw parts -> event stream` 主链路是否可行
2. `anthropic-messages` 是否可以作为第一个真实协议验证入口
3. official SDK 是否可以作为可选 carrier
4. `httpx-thin` 是否能作为独立可行且长期保留的 carrier
5. cancellation 在真实端点路径中是否仍然可稳定映射为 `aborted`

## Validation Method

采用最小技术原型验证，而不是正式实现。

验证原型包括：

- 最小 model / context / options 类型
- 最小 API adapter registry
- 最小 top-level API
- 最小 raw parts / assembler
- 两条 adapter carrier 路径：
  - official `anthropic` SDK
  - `httpx-thin`
- 一个真实 Kimi Anthropic-compatible endpoint

## Current Environment Assumption

当前验证环境假设：

- 没有 OpenAI / Anthropic 官方 API key
- 已提供：
  - `ANTHROPIC_AUTH_TOKEN`
  - `ANTHROPIC_API_KEY`
  - `KIMI_API_KEY`
- 这些变量当前都指向同一个 Kimi API key

因此，本次真实端点验证不以“官方 provider 跑通”为目标，而以“真实兼容协议端点跑通”为目标。

## Validated Results

### 1. Main Invocation Chain Is Viable

已验证：

- mock / faux 路径可通过：
  - `stream()`
  - `complete()`
  - `stream_simple()`
  - `complete_simple()`

这说明当前最小主链路：

- top-level API
- API adapter registry
- API adapter
- raw parts
- assistant event stream

是可行的。

### 2. `anthropic-messages` As First Real Protocol Is Viable

已验证：

- Kimi 提供的 Anthropic-compatible endpoint 可以作为第一个真实协议验证入口
- 最小 text streaming / completion 路径已经跑通

因此，当前建议可冻结为：

- `anthropic-messages` 适合作为 `loushang.ai` 第一个真实 provider adapter 落地路径

### 3. Official SDK Carrier Viability

已验证：

- official `anthropic` SDK 可以通过：
  - `base_url=https://api.moonshot.cn/anthropic`
- 在真实兼容端点上跑通最小 text path

因此，当前建议可冻结为：

- official SDK 可以保留为 `anthropic-messages` 的可选 implementation carrier

### 4. `httpx-thin` Carrier Viability

已验证：

- `httpx-thin` 可在同一真实端点上跑通最小 text path
- 其结果不是 mock-level 可行，而是真实网络路径可行

因此，当前建议可冻结为：

- `httpx-thin` 应继续作为长期一等 implementation carrier 保留

### 5. Real-Endpoint Cancellation Mapping

已验证：

- 在 `httpx-thin` carrier 的真实端点路径中，中途取消后：
  - event stream 输出 `error`
  - `reason = "aborted"`
  - final `AssistantMessage.stop_reason = "aborted"`

因此，当前建议可冻结为：

- cancellation 的协议语义不仅在 mock/spike 层成立，也能在真实兼容端点路径中成立

## Architecture Decision Impact

如果验证通过，本次实验将支持以下设计继续向前推进：

1. `anthropic-messages` 可作为第一个正式实现路径
2. `httpx-thin` 继续作为长期一等实现载体保留
3. official SDK 继续只作为内部 implementation carrier
4. raw parts 继续保持为 adapter 与 public event stream 之间的唯一归一化边界
5. `complete()` / `complete_simple()` 不需要脱离 stream 根语义另起独立调用链
6. 真实端点路径中的 cancellation 继续保持协议语义建模，而不是退化为纯 runtime 异常

### Cancellation Semantics Compared To Runtime Cancellation

这次验证进一步支持一个重要判断：

- 对 `loushang.ai` 这一层来说，把取消最终建模为协议语义上的 `aborted`
- 比直接把 `asyncio.CancelledError` 暴露给上层更合适

原因不是 `CancelledError` 本身不可用，而是它的层级更接近：

- runtime 机制
- task 调度中断
- 协程执行取消

而 `loushang.ai` 当前要稳定暴露的是：

- AI protocol
- event stream contract
- `complete()` / `result()` 的统一收敛语义

因此，当前更合理的分层是：

- internal implementation 可以使用 `asyncio` 与 `CancelledError`
- 但 public contract 应继续收敛为：
  - stream `error(reason="aborted")`
  - final `AssistantMessage(stop_reason="aborted")`

这也说明：

- `kimi-cli` 风格的 runtime cancellation 更适合 app/runtime 层
- `loushang.ai` 的 `aborted` 协议收敛更适合 AI abstraction 层

## Issues Found

本节在实验完成后记录：

- 当前实验环境中的 key 放在 `.bashrc`
- `.bashrc` 对非交互 shell 直接 `return`
- 因此普通非交互命令默认无法读取真实端点验证所需环境变量

这说明：

- spike 执行层需要更稳定的环境注入方式
- 该问题属于实验环境约束，不是 adapter strategy 本身的反例

当前 carrier 行为差异包括：

- official SDK 路径最终文本：
  - `Hello! I'm Kimi, developed by Moonshot AI.`
- `httpx-thin` 路径最终文本：
  - `Hello! This is Claude, made by Anthropic.`

当前尚不能据此推出结构性兼容问题。  
它更可能说明同一兼容端点在不同 carrier 路径下返回的内容存在差异。

## Open Questions

虽然本次验证旨在回答 adapter strategy 的最小关键问题，但实验后仍可能保留以下开放问题：

1. `openai-compatible` 路径是否应紧接着做同类真实验证
2. `httpx-thin` 是否需要抽成最小公共 helper
3. `tool call / thinking / image` 是否在 carrier 之间存在结构性差异
4. 正式实现阶段是否需要分别保留 SDK carrier 与 `httpx-thin` carrier
5. `anthropic` SDK carrier 上是否也应补一轮真实取消验证

## Current Conclusion

当前结论是：

1. adapter strategy 的主方向可行
2. `anthropic-messages` 作为第一个真实协议入口可行
3. official SDK 与 `httpx-thin` 双载体策略有真实实验支撑
4. 真实端点路径中的 cancellation -> `aborted` 映射可行
5. 当前还不能冻结完整事件矩阵，因为真实端点验证仍只覆盖最小 text path、stop path 与 aborted path
