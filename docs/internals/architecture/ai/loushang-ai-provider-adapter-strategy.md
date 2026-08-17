# Loushang AI Provider Adapter Strategy

## Scope

本文档讨论 `loushang.ai` 的 provider adapter strategy。

本文档只讨论：

- provider adapter 在 `loushang.ai` 内部的位置
- `openai-compatible` 与 `anthropic-messages` 两类基础应用协议族
- official SDK 与 `httpx-thin` 作为实现载体的取舍原则
- adapter、raw parts、assembler 的职责边界
- v0.1 应冻结的最小支持面

本文档不讨论：

- 某个 provider 的正式代码模块划分
- provider-specific option schema
- 真实 API payload 字段级映射
- 认证细节
- retry / fallback / load balancing policy

---

## Design Question

在 `API adapter registry` 与 physical system context 已明确后，当前需要继续回答：

1. `loushang.ai` 至少要承接哪几类上游应用协议
2. provider adapter 应优先依赖 official SDK，还是优先依赖薄 HTTP
3. `httpx-thin` 是临时兜底，还是长期一等实现路径
4. adapter 与 raw assembler 的正式边界应该画在哪里

如果这一层不先拍板，后续正式实现很容易出现两类问题：

- 一类是不同 provider adapter 各自长成不同风格，难以统一
- 一类是 public contract 被某家 SDK 的对象模型反向塑形

---

## Why This Matters

`loushang.ai` 的价值不只是“能调通模型”，而是：

1. 以稳定 public contract 暴露统一 AI 协议
2. 以可替换的 adapter 接入多个 provider API 语义
3. 以统一 raw parts 和 assistant event stream 隔离上游差异

因此，provider adapter strategy 的目标不是找一个“万能库”，而是：

- 先明确协议层
- 再明确实现载体选择原则
- 最后保证这些实现都不会污染 public contract

---

## Position In The Stack

在当前架构中，provider adapter 位于：

1. top-level AI API 之下
2. `API adapter registry` 之后
3. raw assembler 之前

主链路应保持为：

`await stream()/complete() -> API adapter registry -> provider adapter -> raw parts -> assistant event stream`

这意味着：

- top-level API 不关心 SDK 细节
- registry 不关心 payload 翻译细节
- assembler 不关心上游 provider 私有事件格式
- provider adapter 是唯一允许直接理解上游协议的层

---

## Reference Strategy

当前建议继续沿用已冻结的参考取舍：

- public contract 对齐 `reference AI SDK`
- internal streaming 结构吸收 `kimi-cli`
- lower-level provider adapter shape 参考 LiteLLM

落到 adapter strategy 层的具体含义是：

- 不把 official SDK 类型暴露到 public surface
- 允许 adapter 层做 provider-normalized 请求与 chunk 翻译
- 保持 raw parts 作为 provider stream 与 public event stream 之间的唯一中间层

---

## Core Recommendation

建议在 v0.1 冻结如下基础支持面：

1. `openai-compatible` 应用协议族
2. `anthropic-messages` 应用协议族
3. `httpx-thin` 作为通用薄实现载体

这里要强调：

- 前两项是应用协议族
- 第三项是实现载体

也就是说，当前要冻结的不是“三种协议”，而是：

- 两类必须承接的上游应用协议语义
- 一条必须长期保留的薄实现路径

---

## Application Protocol Families

### OpenAI-Compatible

这类协议族的特点通常包括：

- OpenAI 风格 request/response shape
- 常见的 chat / responses 系列语义
- 广泛的兼容生态

选择它作为一级支持面的原因是：

- 它已经不是单一 provider 私有接口，而是一个生态级兼容面
- 很多 provider 最终都会暴露与它近似的应用协议
- 它适合作为 `Api` 维度中的一个主要协议族来源

但需要保持克制：

- glossary 与 registry 的稳定识别单位仍应是具体 `Api` 值
- 不应把“openai-compatible”直接等同于某一个 SDK

### Anthropic-Messages

这类协议族应被视为独立一级支持面。

原因是：

- 它在消息、tool、thinking、streaming 语义上与 OpenAI family 存在稳定差异
- 它不适合被强行压扁成 OpenAI-compatible 的一个变体

因此，v0.1 应明确承认：

- `anthropic-messages` 是独立应用协议族
- 它需要独立 adapter 语义，而不是简单复用 OpenAI-compatible adapter

---

## Implementation Carrier Strategy

### General Rule

不建议先拍板为：

- “全部优先 official SDK”

也不建议先拍板为：

- “全部优先自己写 HTTP”

更稳的策略是：

- application protocol 与 implementation carrier 分层
- 每个 adapter 按协议族选择更合适的 carrier
- 同时长期保留 `httpx-thin`

### Official SDKs

official SDK 的优点包括：

- 认证与 client 组织较现成
- 某些 provider 的 streaming 封装更成熟
- 与上游 API 演进节奏更接近

风险包括：

- 事件模型可能过重
- 对取消传播的透明度可能不足
- 上游对象模型可能不利于映射到统一 raw parts
- 容易让内部实现不自觉围绕某个 SDK 的对象组织

因此，official SDK 更适合被建模为：

- adapter implementation carrier

而不是：

- public contract 的一部分
- 协议本身

### HTTPX-Thin

`httpx-thin` 建议被视为长期存在的一等实现载体。

原因包括：

1. 在事件模型需要精确控制时更可控
2. 在取消、超时、headers、base_url override 等问题上更透明
3. 可以避免被 SDK 私有对象模型绑定
4. 能作为某些 provider 或某些协议族的默认实现路径

因此：

- `httpx-thin` 不只是 fallback
- 它是 adapter strategy 的基础能力

---

## Selection Rule

对单个 adapter 的实现载体选择，建议采用如下规则：

1. 优先看应用协议族是否已经清楚
2. 再看 official SDK 是否能自然映射到 raw parts
3. 如果 SDK 事件模型过重、取消传播不清晰或封装过深，则优先 `httpx-thin`
4. 若 SDK 路径自然、稳定且不污染内部边界，则允许采用 SDK

也就是说，默认判断顺序应是：

- 先判断协议适配是否成立
- 再判断载体是否合适

而不是：

- 先看哪家 SDK 好不好用
- 再反过来决定协议怎么设计

---

## Adapter Responsibility

provider adapter 应只负责以下事项：

1. 接收统一 `Context + Model + CallOptions`
2. 将其映射为对应应用协议请求
3. 在 async-start 边界上选择并调用实现载体
4. 将上游 stream 翻译为 raw parts
5. 在调用前、流式循环中、收敛前检查取消

它不负责：

- 直接组装 public `AssistantMessageEvent`
- 维护最终 `AssistantMessage` 的生命周期
- tool orchestration
- top-level provider resolution
- registry 管理

这条边界非常关键，因为一旦 adapter 直接产出 public event，它就会重新把 provider 私有语义泄漏到 public contract。

---

## Raw Parts As The Normalization Boundary

建议继续把 raw parts 视为唯一标准归一化边界。

也就是说：

- provider SDK stream 不进入 public
- SDK / HTTP 响应块先变成 raw parts
- raw parts 再由 assembler 统一组装为 `AssistantMessageEvent`

这样做的价值在于：

1. provider 侧差异被隔离在 adapter 之前
2. public event 规则被隔离在 assembler 之后
3. adapter 与 assembler 可以各自独立演进

这也与现有 streaming 文档保持一致。

---

## Cancellation Rule

provider adapter strategy 需要明确承接当前已冻结的 cancellation 方向：

- public 使用 `CallOptions.cancellation`
- public 语义建模为最小取消信号对象
- adapter 是最关键的取消检查层之一

因此建议要求 adapter 至少在三个点检查取消：

1. 发起请求前
2. 流式迭代中
3. 收敛最终结果前

检测到取消后，adapter 应推动协议语义落到：

- `aborted`

而不是只把问题留给底层 SDK / task cancellation。

---

## V0.1 Non-Goals

本阶段明确不进入以下设计：

- provider fallback chain
- weighted routing
- automatic SDK/HTTP benchmarking selection
- multi-carrier competition
- capability negotiation matrix
- provider hot swap
- 完整 provider family matrix

这些都属于后续可能的扩展，而不是当前最小稳定策略。

---

## Current Provider Surface

当前实现已经把 provider support 分为两层：

1. catalog 层：`models.json` 记录 provider、endpoint、model、auth、capability、pricing、compat
2. adapter 层：`APIAdapter` 按 `endpoint.api` 接管真实请求

当前内置 adapter 覆盖：

- `openai-completions`
- `openai-responses`
- `anthropic-messages`

其中：

- Mistral 通过官方 Chat Completions 兼容面接入 `openai-completions`
- Google Gemini API 通过 OpenAI-compatible endpoint 接入 `openai-completions`
- Google Vertex 通过 OpenAI-compatible endpoint 接入 `openai-completions`
- Cloudflare AI Gateway / Workers AI 通过 OpenAI-compatible 或 Anthropic passthrough 接入
- ChatGPT Coding Plan 等产品场景通过 catalog route 复用 `openai-responses`，
  不形成新的 adapter family

### Model ID Normalization

本地三元组必须保持可解析：

`provider:endpoint:model`

因此 catalog 不直接暴露包含 `:` 的 model ID。规则是：

- 公开 `model.id` 将 `:` 替换为 `_`
- 真实上游模型 ID 存入 `model.upstream_id`
- provider resolver 输出 `ResolvedRequest.upstream_model_id`
- provider adapter 发请求时优先使用 `ResolvedRequest.upstream_model_id`

这个规则同时适用于 OpenRouter 的 `:free` 模型和 Bedrock 的 `:0` 模型。

### Remaining Limits

当前 Bedrock adapter 是轻量实现：

- 使用 Bedrock `Converse` 非流式 HTTP 调用
- 输出被投影为统一 raw parts
- 暂未完整支持 Bedrock streaming event stream
- 暂未完整支持 Bedrock tool use、image payload、Claude thinking/cache/interleaved thinking

当前 Vertex 认证是显式 token 模式：

- 通过 `GOOGLE_VERTEX_ACCESS_TOKEN` 注入 bearer token
- 尚未实现 ADC 或 service account 自动取 token

---

## Recommendation

建议冻结如下方向：

1. `loushang.ai` v0.1 至少承接 `openai-compatible` 与 `anthropic-messages` 两类基础应用协议族
2. `httpx-thin` 保持为长期存在的一等实现载体
3. official SDK 允许使用，但只作为内部 implementation carrier
4. adapter 的唯一标准输出是 raw parts，而不是 public assistant events
5. adapter 必须承接 cancellation 检查与协议语义映射责任
6. 协议设计先于 SDK 选型，不反过来

---

## Open Questions

在进入顶层 API 签名和最小 provider spike 前，仍有几个问题需要后续细化：

1. `openai-responses` 与 `openai-completions` 是否共享同一 carrier strategy
2. `anthropic-messages` 的 thinking / tool / streaming matrix 应如何落到 raw parts
3. `httpx-thin` 的最小公共 helper 面是否需要单独建模
4. provider runtime error family 应如何与 registry error / protocol error 分层

---

## Next Step

在此基础上，下一步最自然进入：

1. `stream()` / `complete()` 的正式签名设计
2. 一个最小 provider spike，用于验证 adapter strategy 能否落地
