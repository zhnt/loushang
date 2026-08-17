# Loushang-AI Gap vs Reference AI SDK Round 1

## Scope

本文档总结当前 `loushang-ai` 相对 `reference AI SDK` 的主要差距。

本文档关注三类内容：

- 已经对齐的主骨架
- 当前仍明显缺失的能力面
- 哪些差异是有意接受的

本文档不讨论：

- `reference AI SDK` 的全部内部实现细节
- `loushang-ai` 的未来完整路线图
- 已经在单独 `ARD` 中拍板的 sync/async 取舍

---

## Current Alignment

当前 `loushang-ai` 已与 `reference AI SDK` 对齐或接近对齐的部分包括：

- top-level AI API 的四个入口概念
- model registry
- API adapter registry
- `APIAdapter -> Raw Parts -> Raw Assembler -> Event Stream` 主链
- `ToolResultMessage` 作为输入回流消息的定位
- public streaming event 的主输出族：
  - `text_*`
  - `thinking_*`
  - `toolcall_*`
  - `image_*`
  - `done`
  - `error`
- `thinking` 进入 `AssistantMessage.content`
- `aborted` 作为标准停止语义

说明：

- sync/async public surface 已通过 `ARD-001` 明确接受为例外，不计入本轮 gap 的主要问题。

---

## Main Gaps

### 1. Provider Coverage

这是当前最大的 gap。

`reference AI SDK` 已覆盖：

- `anthropic`
- `openai-responses`
- `openai-completions`
- `openai-codex-responses`
- `azure-openai-responses`
- `google`
- `google-gemini-cli`
- `google-vertex`
- `mistral`
- `bedrock`

当前 `loushang-ai` 只覆盖：

- `FauxAdapter`
- `AnthropicMessagesAdapter`
- `OpenAIChatCompletionsAdapter`
- `OpenAIResponsesAdapter`

也就是：

- 一个测试 provider
- 一个真实 `anthropic-messages + httpx-thin` adapter
- 一个真实 `openai-completions + httpx-thin` adapter
- 一个 `openai-responses + httpx-thin` 最小协议实现

需要特别说明：

- `openai-completions` 已在 Kimi OpenAI-compatible 端点上完成真实验证
- `openai-responses` 当前只完成了最小协议实现与本地 contract 测试
- `openai-responses` 尚未在 Kimi 真实端点上验证通过，当前合理判断是 Kimi 端点暂不支持该协议

### 2. Provider-Specific Options / Config Families

这一项已经从“缺失”进入“最小已实现，但仍不够完整”的状态。

当前 `loushang-ai` 已形成最小 provider-specific options family：

- `StreamOptions`
- `AnthropicOptions`
- `OpenAICompletionsOptions`
- `OpenAIResponsesOptions`

相对 `reference AI SDK` 的剩余差距主要是：

- 字段覆盖面仍更窄
- 尚未扩到更多 provider family
- 顶层 public API 仍保持 `options: object | None` 的宽口签名

### 3. Variation Absorption Components Are Not Yet Fully Formalized In Code

当前 `loushang-ai` 的设计已经明确识别出三类关键变化吸收对象：

- `Model Capability Resolver`
- `Auth Support`
- `Transport Strategy`

当前状态是：

- `Model Capability Resolver` 已接入 top-level fail-fast 主链
- `Auth Support` 已接入 provider 主链
- `Provider Boundary Support` 已开始吸收 endpoint / compat / defaults

剩余差距主要在：

- `Transport Strategy` 仍未真正进入运行主链
- 这些组件的 shared logic 深度仍低于 `reference AI SDK`

### 4. Auth / OAuth Integration

`reference AI SDK` 已有：

- env api key resolution
- OAuth types
- provider-specific OAuth integration
- token refresh helpers

当前 `loushang-ai` 只有最小 API key 输入路径，尚未形成完整 auth 支撑层。

### 5. Validation / Overflow / Helper Layer

`reference AI SDK` 已提供：

- validation helper
- overflow handling
- JSON parsing helper
- schema helper

当前 `loushang-ai` 还缺：

- context overflow / truncation handling
- structured validation helper
- 通用 helper 层

### 6. Semantic Completeness

当前 `loushang-ai` 已补齐基础 message/content/event 面，但仍有语义 gap：

- `ToolCall.arguments` 已结构化，且最小 tool replay/validation 与 model-aware tool-call ID normalization 已接入主链；当前 gap 已主要收敛到更复杂的 multi-tool-call / provider roundtrip 语义
- real provider-produced thinking signature / encrypted continuity 尚未实现
- multi-tool-call / complex pairing 仍未实现
- audio / video 尚未建模
- real provider image output path 仍未落地，当前 image output 主要由 faux path 验证

### 7. Built-In Adapter Ecosystem

`reference AI SDK` 的 built-in provider registration / loading 生态更成熟。

当前 `loushang-ai` 虽已有最小 `bootstrap`，但仍只够支撑：

- faux
- anthropic-httpx
- openai-completions-httpx
- openai-responses-httpx

还未形成更完整的 built-in adapter 层。

---

## Intentional Differences

当前明确接受的差异：

### Async Public Streaming Surface

`loushang-ai` 采用：

- `async stream(...)`
- `async stream_simple(...)`

而不是 `reference AI SDK` 的同步 surface。

这是有意接受的 Python 实现差异，详见：

- [ARD-001: Async Public Streaming Surface](../ARD-001-async-public-streaming-surface.md)

---

## Priority Order

如果按后续推进优先级排序，当前最值得补的 gap 是：

1. `openai-compatible` adapter
2. `Transport Strategy` 与 `Provider Boundary Support` 的进一步正式化
3. provider-specific options / config family 的深化
4. validation / overflow / helper layer
5. auth / oauth integration

---

## Conclusion

当前 `loushang-ai` 相对 `reference AI SDK` 的差距，已经不再主要体现在：

- message/content/event 的基础协议骨架

而主要体现在：

- provider 覆盖面
- options family
- auth / validation / overflow 等成熟支撑层

换句话说，`loushang-ai` 当前的主骨架已经成立；下一阶段更重要的是补 capability surface，而不是继续打磨最小协议骨架。
