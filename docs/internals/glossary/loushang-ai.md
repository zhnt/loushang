# Loushang AI Glossary v0.1

## 1. Scope

`loushang-ai` 是模型接入与统一流式协议层。

它负责：

- 模型与 provider 抽象
- 统一消息与内容块协议
- 统一流式事件协议
- API adapter 注册与调用入口
- usage / stop reason / thinking / tool call 等 AI 交互语义

它不负责：

- `Agent`
- `AgentLoop`
- `AgentState`
- `AgentEvent`
- tool orchestration policy
- turn lifecycle

---

## 2. Design Principles

1. `loushang-ai` 的职责不超过 `pi-ai`
2. 正式术语优先与 `pi-ai` 对齐
3. 与 runtime 的衔接通过兼容消息/流协议完成，而不是把 `Agent` 概念下沉到 AI 层
4. `model` 是核心术语，`llm` 不作为正式主术语
5. streaming 结果以标准事件流表达，而不是 provider 私有对象流

---

## 3. Model Layer

### Api

模型调用协议类型。

表示一次模型调用所依赖的上游应用 API 语义，例如：

- `openai-responses`
- `openai-completions`
- `anthropic-messages`

这些 `Api` 可按协议族理解，例如：

- OpenAI family
- Anthropic family

但 glossary 中的稳定识别单位仍应是具体 `Api` 值，而不是协议族标签本身。

`Api` 属于 `Endpoint`，不属于 `Model`。

它不等同于：

- `Provider`
- SDK 选型
- `HTTPS` / `SSE` 等传输层

### Provider

模型服务提供方。

表示模型所属的 provider，例如：

- `openai`
- `anthropic`
- `google`
- `kimi`

### Endpoint

Provider 下的一条完整模型接入通道。Endpoint 声明 `api`、地址、认证、headers、
adapter 配置、defaults 和 Model 清单。

Endpoint 是模型身份的一部分，不是调用时可以省略的附加配置。

### Model

统一模型描述对象。

典型属性包括：

- `id`
- `name`
- `provider_id`
- `endpoint_id`
- `base_url`
- `reasoning`
- `input`
- `context_window`
- `max_tokens`
- `headers`
- `pricing`

说明：

- `Provider` 提供服务
- `Endpoint` 表示一个具体调用入口，并携带 `api`
- `Model` 表示该 endpoint 下的可调用模型句柄
- 同一个模型名可以在多个 endpoint 下分别存在为不同的 `Model`
- `provider:endpoint:model` 是 Model 的完整、唯一标识
- `ModelRegistry` 返回的 Model 已包含 Endpoint 的生效配置；调用只传 Model

例如：

- `p1:e1:kimi2.5`
- `p1:e2:kimi2.5`
- `p1:e3:kimi2.5`

可以同时存在；它们的差异首先来自 endpoint，因此也来自 endpoint 绑定的 `api`。

### ModelSelection

Endpoint 完整的轻量模型引用，包含三个非空字段：

- `provider`
- `endpoint_id`
- `model_id`

它始终表示完整的 `provider:endpoint:model`，不是模型偏好。外层输入省略 Endpoint
时，只能在 `provider + model_id` 恰好命中一个 Endpoint 后立即补全；零候选报不存在，
多候选报歧义，不能用 `preferred`、默认值或候选顺序静默选择。

### Model Registry

模型注册表。

负责维护 `Provider -> Endpoint -> Model` 目录、把 Endpoint 生效配置绑定到 Model，并
按完整 `ModelSelection` 返回可调用 `Model`。

---

## 4. Request Context Layer

### Context

一次模型调用的统一上下文。

典型属性包括：

- `system_prompt`
- `messages`
- `tools`

### Tool

模型可调用的工具定义。

典型属性包括：

- `name`
- `description`
- `parameters`

### CallOptions

统一调用基础选项。

典型属性包括：

- `temperature`
- `max_output_tokens`
- `cancellation`
- `auth`
- `cache_key`
- `cache_retention`
- `reasoning`
- `retry`
- `timeout_seconds`
- `idle_timeout_seconds`
- `trace`

`cache_key` 是调用方提供的不透明缓存/亲和键；协议 adapter 可以把它映射为
上游字段或 header，但 AI 包不据此维护 session 或恢复历史消息。

### ReasoningOptions

推理/思考相关选项。

典型属性包括：

- `enabled`
- `effort`
- `budget_tokens`
- `expose_summary`

### RetryOptions

重试相关选项。

典型属性包括：

- `max_attempts`
- `max_delay_seconds`

`timeout_seconds` 是单次 provider attempt 的完整 deadline；
`idle_timeout_seconds` 是 stream 相邻 raw part 之间的最大空闲时间。

### ThinkingLevel

统一推理强度等级。

建议对齐：

- `minimal`
- `low`
- `medium`
- `high`
- `xhigh`

### CacheRetention

提示缓存保留策略。

建议对齐：

- `none`
- `short`
- `long`

### Provider-Specific Options

产品场景不通过专用 provider、contrib 或 options 类型进入 `loushang.ai` 根 public surface。调用方只传 `CallOptions`；endpoint 在 catalog 中选择已有协议适配器。

例如 ChatGPT Coding Plan 只提供 OAuth 凭证和 endpoint 路由，调用仍由通用 `openai-responses` adapter 执行。

---

## 5. Message Layer

### Message

统一消息抽象。

表示进入 AI 上下文或由 AI 生成的统一消息对象。

`Message` 负责定义模型输入输出语义，不直接承诺：

- 存储
- 传递
- 回放
- 会话态持久化

### UserMessage

用户输入消息。

典型属性包括：

- `role = "user"`
- `content`
- `timestamp`

### AssistantMessage

模型输出消息。

典型属性包括：

- `role = "assistant"`
- `content`
- `api`
- `provider`
- `endpoint`
- `model`
- `usage`
- `stop_reason`
- `error_message`
- `timestamp`

`provider:endpoint:model` 可以从消息中还原完整响应来源。流式 partial、流式 final
和非流式结果使用相同的来源字段。

### ToolResultMessage

工具结果消息。

典型属性包括：

- `role = "toolResult"`
- `tool_call_id`
- `tool_name`
- `content`
- `details`
- `is_error`
- `timestamp`

---

## 6. Content Layer

### Message Content

消息内部内容块集合。

`AssistantMessage.content`、`UserMessage.content`、`ToolResultMessage.content` 都由内容块组成。

### TextContent

文本内容块。

典型属性包括：

- `type = "text"`
- `text`

### ThinkingContent

思考内容块。

典型属性包括：

- `type = "thinking"`
- `thinking`
- `thinking_signature`

### ImageContent

图像内容块。

典型属性包括：

- `type = "image"`
- `data`
- `mime_type`

### ToolCall

工具调用内容块。

典型属性包括：

- `type = "toolCall"`
- `id`
- `name`
- `arguments`

---

## 7. Streaming Layer

### AssistantMessageEvent

助手消息流式事件。

建议对齐事件族：

- `start`
- `text_start`
- `text_delta`
- `text_end`
- `thinking_start`
- `thinking_delta`
- `thinking_end`
- `toolcall_start`
- `toolcall_delta`
- `toolcall_end`
- `done`
- `error`

### AssistantMessageEventStream

助手消息事件流。

可异步迭代，并在结束时收敛为最终 `AssistantMessage`。

### StopReason

助手消息停止原因。

建议对齐：

- `stop`
- `length`
- `toolUse`
- `error`
- `aborted`

### StreamFunction

标准流式调用函数签名。

输入：

- `model`
- `context`
- `options`

输出：

- `await` 后得到 `AssistantMessageEventStream`

---

## 8. Usage Layer

### Usage

模型调用用量信息。

典型属性包括：

- `input`
- `output`
- `cache_read`
- `cache_write`
- `total_tokens`
- `cost`

---

## 9. Registration Layer

### APIRegistry

API adapter 注册表。

负责维护 `api -> APIAdapter` 映射，并提供查询与注册能力。

### APIAdapter

按 `Api` 维度注册的统一调用适配单元。

它负责把统一调用翻译到对应 `Api`，并作为 registry 的 public registration unit 存在。

它不等同于：

- `Provider`
- SDK
- 外部 provider API

典型属性包括：

- `api`
- `invoke_raw`

### register_api_adapter

注册 API adapter。

### get_api_adapter

获取指定 API 的通用 adapter。

### ProviderRegistry

先按 `(provider_id, api)` 查找厂商专用 `APIAdapter`，未命中时回退
`APIRegistry.get_api_adapter(api)`。它保留双层 adapter 路由，但不拥有或选择模型。

### stream

统一流式调用入口。

### complete

统一非流式完成入口。

---

## 10. Boundary Rule

`loushang-ai` 到此为止。

以下术语属于 `loushang-agent`，不应进入 `loushang-ai` 的核心术语表：

- `Agent`
- `AgentLoop`
- `Turn`
- `AgentContext`
- `AgentState`
- `AgentLoopConfig`
- `AgentEvent`
- `AgentTool`
- `AgentToolResult`
