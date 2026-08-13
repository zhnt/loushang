# Loushang AI Types v0.1

## 1. Scope

本文档定义 `loushang.ai` 的核心类型定义。  
目标是与 `pi-ai` 保持语义严格对齐，并在表达上做最小限度的 Python 化。

本文档覆盖：

1. `Model` family
2. `Context` / `Tool` family
3. `Message` family
4. `Content` family
5. `Streaming` family
6. `Options` family
7. `Usage` family

本文档不覆盖：

- `Agent`
- `AgentLoop`
- `AgentEvent`
- tool orchestration policy
- channel boundary protocol
- provider 实现细节

---

## 2. Design Principles

1. **语义严格对齐 `pi-ai`**  
   核心对象边界、事件族、消息族与停止原因保持一致。

2. **表达轻度 Python 化**  
   函数名与字段名使用 `snake_case`，但协议字面值保留 `pi-ai` 语义，例如 `toolCall`、`toolUse`。

3. **值对象优先**  
   核心协议类型优先建模为稳定值对象，而不是带复杂继承关系的运行对象。

4. **AI 层不下沉 Agent 概念**  
   `loushang.ai` 只定义模型接入与统一流协议，不承载 agent runtime 生命周期。

5. **先冻结协议，再演进实现**  
   v0.1 先收敛 public types，后续实现仅在不破坏语义兼容的前提下演进。

---

## 3. Scalar Types

### KnownApi

内建支持的 API 类型集合。

建议保留与 `pi-ai` 对齐的命名风格，例如：

- `openai-completions`
- `openai-responses`
- `anthropic-messages`
- `google-generative-ai`

### Api

模型调用协议类型。

建议定义为：

- `KnownApi | str`

### KnownProvider

内建支持的 provider 类型集合。

例如：

- `openai`
- `anthropic`
- `google`
- `kimi`

### Provider

模型服务提供方类型。

建议定义为：

- `KnownProvider | str`

### ThinkingLevel

统一推理强度等级。

建议值：

- `minimal`
- `low`
- `medium`
- `high`
- `xhigh`

### CacheRetention

提示缓存保留策略。

建议值：

- `none`
- `short`
- `long`

### Cancellation Signal

Python 侧的最小取消信号协议。

说明：

- `CallOptions.cancellation` 承载取消信号
- Python 实现不要求复制 JavaScript `AbortSignal`
- cancellation signal 只表达“调用是否应被取消”的语义
- provider 与 streaming 层应在调用前、流式迭代中与结束前检查该信号
- 一旦检测到取消，应映射为 `aborted` 终止语义，而不是普通异常

建议：

- 将 cancellation signal 定义为 `loushang.ai` 内部最小协议类型
- 不在 v0.1 中绑定到具体事件循环或并发库

当前建议的最小语义为：

- `cancelled: bool`

说明：

- cancellation signal 优先建模为只读取消状态
- 不要求 `wait()`、不要求 awaitable 接口
- 不直接绑定 `asyncio.Event`
- 实现层可以适配 `asyncio.Event` 或其他取消对象

### StopReason

assistant message 停止原因。

建议值：

- `stop`
- `length`
- `toolUse`
- `error`
- `aborted`

说明：

- `toolUse` 保留 `pi-ai` 语义字面值
- 不建议改成 `tool_use`

---

## 4. Model Family

### ModelCost

模型定价信息。

建议字段：

- `input`
- `output`
- `cache_read`
- `cache_write`

### Model

统一模型描述对象。

建议字段：

- `id: str`
- `name: str`
- `provider: Provider`
- `endpoint: str`
- `base_url: str`
- `reasoning: bool`
- `input: list[Literal["text", "image"]]`
- `cost: ModelCost`
- `context_window: int`
- `max_tokens: int`
- `headers: dict[str, str] | None = None`
- `compat: dict[str, Any] | None = None`

说明：

- `api` 不是 `Model` 的稳定字段；`api` 由 `Endpoint` 提供
- `Model` 是 `provider + endpoint + model_id` 三元组下的调用句柄
- `base_url`、`context_window`、`max_tokens` 为 Python 化字段名
- `compat` 先保留为扩展口，不在 v0.1 中细分 provider-specific compat 类型

### Endpoint

模型服务入口对象。

建议字段：

- `id: str`
- `provider: Provider`
- `api: Api`
- `base_url: str | None`
- `region: str | None`
- `lane: str | None`

说明：

- `Endpoint` 是 `api` 的事实来源
- provider 路由应按 `endpoint.api` 解析
- 一个 provider 可以有多个 endpoint

---

## 5. Tool and Context Family

### Tool

模型可调用工具定义。

建议字段：

- `name: str`
- `description: str`
- `parameters: dict[str, Any]`

说明：

- `parameters` 先表示 schema object
- v0.1 不绑定具体 schema 技术栈

### Context

一次模型调用的统一上下文。

建议字段：

- `system_prompt: str | None = None`
- `messages: list[Message]`
- `tools: list[Tool] | None = None`

说明：

- `Context` 只表达输入上下文
- `api_key`、`cache_key`、`metadata` 等运行选项不进入 `Context`

---

## 6. Content Family

### TextContent

文本内容块。

建议字段：

- `type: Literal["text"] = "text"`
- `text: str`
- `text_signature: str | None = None`

### ThinkingContent

思考内容块。

建议字段：

- `type: Literal["thinking"] = "thinking"`
- `thinking: str`
- `thinking_signature: str | None = None`
- `redacted: bool = False`

说明：

- `redacted` 表示内容被安全策略隐藏
- `thinking_signature` 用于 continuity / opaque payload 传递

### ImageContent

图像内容块。

建议字段：

- `type: Literal["image"] = "image"`
- `data: str`
- `mime_type: str`

说明：

- `data` 表示 base64 编码内容
- `mime_type` 暂不缩窄为固定枚举

### ToolCall

工具调用内容块。

建议字段：

- `type: Literal["toolCall"] = "toolCall"`
- `id: str`
- `name: str`
- `arguments: dict[str, Any]`
- `thought_signature: str | None = None`

说明：

- 保留 `toolCall` 字面值
- `arguments` 表示已解析对象，而非 JSON 字符串

### Content Relationship

推荐关系如下：

```text
Content
├── TextContent
├── ThinkingContent
├── ImageContent
└── ToolCall
```

---

## 7. Message Family

### UserMessage

用户输入消息。

建议字段：

- `role: Literal["user"] = "user"`
- `content: str | list[TextContent | ImageContent]`
- `timestamp: int`

### AssistantMessage

模型输出消息。

当前字段：

- `role: Literal["assistant"] = "assistant"`
- `content: list[TextContent | ThinkingContent | ToolCall | ImageContent]`
- `api: Api`
- `provider: Provider`
- `endpoint: str`
- `model: str`
- `response_id: str | None = None`
- `usage: Usage`
- `stop_reason: StopReason`
- `error_message: str | None = None`
- `timestamp: float`

说明：

- `thinking` 不作为独立顶层字段暴露
- `thinking` 与 `text`、`toolCall` 一样进入 `content`
- `thinking_*` 事件中的 `content_index` 应指向 `partial.content` 中真实存在的 thinking block
- `provider:endpoint:model` 唯一标识响应来源；流式 partial 和 final 都保留该三元组

### ToolResultMessage

工具结果回流消息。

建议字段：

- `role: Literal["toolResult"] = "toolResult"`
- `tool_call_id: str`
- `tool_name: str`
- `content: list[TextContent | ImageContent]`
- `details: Any | None = None`
- `is_error: bool`
- `timestamp: int`

### Message

统一消息联合类型。

建议定义为：

- `UserMessage | AssistantMessage | ToolResultMessage`

### Message Relationship

```text
Message
├── UserMessage
├── AssistantMessage
└── ToolResultMessage
```

---

## 8. Usage Family

### UsageCost

用量成本对象。

建议字段：

- `input: float`
- `output: float`
- `cache_read: float`
- `cache_write: float`
- `total: float`

### Usage

assistant message 用量统计。

建议字段：

- `input: int`
- `output: int`
- `cache_read: int`
- `cache_write: int`
- `total_tokens: int`
- `cost: UsageCost`

---

## 9. Options Family

### CallOptions

统一调用基础选项。

建议字段：

- `temperature: float | int | None = None`
- `max_output_tokens: int | None = None`
- `cancellation: object | None = None`
- `auth: AuthCredential | None = None`
- `cache_retention: CacheRetention | None = None`
- `cache_key: str | None = None`
- `reasoning: ReasoningOptions | None = None`
- `retry: RetryOptions | None = None`
- `timeout_seconds: float | int | None = None`
- `idle_timeout_seconds: float | int | None = None`
- `trace: object | None = None`

说明：

- 使用 `cancellation` 以 Python 协议类型表达取消语义
- v0.1 不要求与 JavaScript `AbortSignal` 结构逐字段兼容
- provider 与 streaming 层应在调用前、流式迭代中与收敛结果前检查该信号
- 检测到取消后，应映射为 `aborted` 协议语义
- `cache_key` 是调用方提供的不透明缓存/亲和键，不是 AI 包管理的 session
- `timeout_seconds` 是单次 provider attempt 的完整 deadline
- `idle_timeout_seconds` 只约束 stream 相邻 raw part 之间的空闲时间

### ReasoningOptions

推理/思考相关选项。

建议字段：

- `enabled: bool | None = None`
- `effort: ThinkingLevel | None = None`
- `budget_tokens: int | None = None`
- `expose_summary: bool = False`

### RetryOptions

重试相关选项。

建议字段：

- `max_attempts: int = 1`
- `max_delay_seconds: float = 30.0`

### Provider-Specific Options

产品场景不通过专用 provider、contrib 或 options 类型进入 `loushang.ai` 根 public surface。

- 完整 OAuth 凭证由 `loushang.ai.auth` 持有；AI 调用只通过 `CallOptions.auth` 接收
  `OAuthBearerAuth(valid_access_token)` 或认证层完整派生的 `HeadersAuth`
- endpoint 在 catalog 中选择已有协议适配器
- 核心调用路径只消费 `CallOptions`

---

## 10. Streaming Family

### AssistantMessageEvent

assistant message 流式事件联合类型。

建议事件族包括：

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

### Event Shapes

建议事件对象按具体事件分拆，而不是建模为单个超大字典对象。

#### StartEvent

- `type = "start"`
- `partial: AssistantMessage`

#### TextStartEvent

- `type = "text_start"`
- `content_index: int`
- `partial: AssistantMessage`

#### TextDeltaEvent

- `type = "text_delta"`
- `content_index: int`
- `delta: str`
- `partial: AssistantMessage`

#### TextEndEvent

- `type = "text_end"`
- `content_index: int`
- `content: str`
- `partial: AssistantMessage`

#### ThinkingStartEvent

- `type = "thinking_start"`
- `content_index: int`
- `partial: AssistantMessage`

#### ThinkingDeltaEvent

- `type = "thinking_delta"`
- `content_index: int`
- `delta: str`
- `partial: AssistantMessage`

#### ThinkingEndEvent

- `type = "thinking_end"`
- `content_index: int`
- `content: str`
- `partial: AssistantMessage`

#### ToolCallStartEvent

- `type = "toolcall_start"`
- `content_index: int`
- `partial: AssistantMessage`

#### ToolCallDeltaEvent

- `type = "toolcall_delta"`
- `content_index: int`
- `delta: str`
- `partial: AssistantMessage`

#### ToolCallEndEvent

- `type = "toolcall_end"`
- `content_index: int`
- `tool_call: ToolCall`
- `partial: AssistantMessage`

#### DoneEvent

- `type = "done"`
- `reason: Literal["stop", "length", "toolUse"]`
- `message: AssistantMessage`

#### ErrorEvent

- `type = "error"`
- `reason: Literal["aborted", "error"]`
- `error: AssistantMessage`

### EventStream

`AssistantMessageEventStream` 不在本文档中展开具体实现。  
它属于带运行行为的 streaming 对象，应在独立模块中定义。

但其公共语义建议冻结为：

- 对外是单一只读 stream 对象
- 支持异步迭代 `AssistantMessageEvent`
- 支持 `result()` 收敛为最终 `AssistantMessage`
- 不将 `push()`、`end()`、writer-side 方法暴露为 public contract

### StreamFunction

标准流式函数签名。

语义要求：

- 输入 `model`、`context`、`options`
- `await` 后输出 `AssistantMessageEventStream`
- 失败、中断、终止通过流内事件表达，而不是作为常规异常表达

---

## 11. Type Dependency Direction

建议依赖方向如下：

```text
Scalar Types
    ↓
Content / Usage / Model
    ↓
Message
    ↓
Tool / Context
    ↓
Options
    ↓
Streaming Events
```

更具体地：

- `Content` 不依赖 `Message`
- `Usage` 不依赖 `Message`
- `Model` 不依赖 `Message`
- `AssistantMessage` 依赖 `Content` + `Usage` + `StopReason`
- `Context` 依赖 `Message` + `Tool`
- `AssistantMessageEvent` 依赖 `AssistantMessage` + `ToolCall`

---

## 12. Python Representation Guidance

v0.1 建议的 Python 表达方式如下：

- 核心值对象优先使用 `@dataclass(slots=True)`
- 标量约束优先使用 `Literal` type alias
- 联合类型优先使用 `A | B | C`
- 不急于引入复杂继承树
- 不在 v0.1 中引入 Pydantic 作为 public types 前提

---

## 13. Compatibility Notes

为了保持与 `pi-ai` 的语义兼容，建议遵循：

1. 保留 `toolCall`、`toolUse` 等协议字面值
2. 允许字段名采用 Python 风格，例如：
   - `base_url`
   - `context_window`
   - `response_id`
   - `stop_reason`
3. 取消语义由 `CallOptions.cancellation` 承载，兼容层可在边界处把旧 `signal` 名称映射到该字段
4. 不在 AI 层引入 `Agent*` 概念
5. 不在 v0.1 中扩大职责边界到 tool orchestration 或 boundary protocol
6. `AssistantMessageEventStream` 的 public contract 保持只读，内部可读写分离

---

## 14. Current Runtime Mapping

以上类型已经由当前运行时实现：

1. `AssistantMessageEventStream` 位于 `loushang.ai.event_stream`。
2. `APIAdapter` Protocol、通用 `APIRegistry` 和厂商优先的 `ProviderRegistry` 已落地。
3. `stream()` / `complete()` 公共入口只接收已经绑定 Endpoint 配置的 `Model`。
