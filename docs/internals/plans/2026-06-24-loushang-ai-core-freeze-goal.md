# Loushang AI Core Freeze Goal

> **用途**：作为本地 Codex `/goal` 的唯一执行文档。
>
> **基线分支**：`ai/quality-hardening-v2`
>
> **编写时观察到的基线 HEAD**：`7f5810a263cdb58960dfed3998d9a0aefaeb4574`
>
> **建议工作分支**：`ai/core-freeze-v1`
>
> **核心目标**：不再扩展能力面，通过删除式重构把 `loushang.ai` 固化为简单、清晰、可靠、易于增加模型的底层 AI 包。

---

## 0. 给 Codex 的总指令

本轮不是继续“设计一个更完整的平台”，也不是继续增加 Provider、模型、管理器、门面或扩展框架。

本轮只做以下事情：

1. 删除历史兼容代码和过渡结构。
2. 消除同一事实的多种表达。
3. 缩短从 `complete()` / `stream()` 到协议适配器的调用链。
4. 保留已经验证有价值的可靠性能力。
5. 固化模型定义、注册、调用、错误、流式事件和认证边界。
6. 让新增使用现有外部 API 协议的模型，主要只需要修改 `models.json` 或用户自定义模型 JSON。
7. 为每项修改补充对应单元测试和场景示例。
8. 每个 Goal 单独提交、单独测试、单独只读评审。

### 0.1 最高优先级原则

当多个实现方案都能满足需求时，按以下顺序选择：

```text
更少概念
> 更短调用链
> 更少代码
> 更少公开 API
> 更少隐式状态
> 更强类型和更早失败
> 更抽象、更通用的设计
```

### 0.2 明确禁止

禁止引入：

- `AIClient`
- 新的 Manager / Service / Facade / Container
- 依赖注入框架
- 事件总线
- 插件生命周期框架
- 动态远程模型市场
- 自动 Provider 安装
- 浏览器打包相关设计
- 仅为未来可能需求预留的抽象
- 新的 schema 版本迁移体系
- 新的 legacy compatibility 层

禁止为了“兼容过去分支”而保留：

- deprecated alias
- 双字段输入
- schema v1/v2 双轨
- URL 或 Provider ID 猜测
- 旧 Compat 转换器
- 旧格式 round-trip 序列化
- 已经没有调用方的 wrapper

当前处于初版开发阶段。只保证本轮固化后的 API；旧分支内部接口可以直接删除。

---

# 1. 本轮最终定义：什么是 Loushang AI 小核心

`loushang.ai` 的职责只有一句话：

> 给定一个已经注册的模型和一组标准消息，使用对应外部 API 协议可靠地完成一次模型调用。

## 1.1 属于 AI 包的能力

- Built-in 模型定义 `models.json`
- 用户自定义模型 JSON 的读取、校验和注册
- 默认全局 `ModelRegistry`
- 可选的自定义 `ModelRegistry`
- Provider / Endpoint / Model 数据类型
- Context、Message、Tool、Usage、Error 数据类型
- 消息归一化和工具结果配对
- 模型能力检查
- API Key / OAuth 认证材料解析
- 三个核心外部 API 协议适配器：
  - OpenAI Chat Completions
  - OpenAI Responses
  - Anthropic Messages
- `complete()` 和 `stream()`
- Retry、Timeout、Cancellation、资源关闭
- RawPart、流式事件、最终 AssistantMessage 组装
- Structured Output
- 图片输入
- Tool Calling 与并行 Tool Call 组装
- Token Usage 和 Cost
- Trace 与 Secret Redaction

## 1.2 不属于 AI Core 的能力

- Agent Loop
- 工具执行
- 会话持久化
- 会话压缩
- RAG 和 Memory
- UI / TUI / RPC 行为
- 项目工作区模型目录发现
- 企业配置中心
- 账户套餐额度查询
- Provider 市场
- 动态远程模型列表刷新
- 浏览器打包和 Tree Shaking

## 1.3 不要求本轮统一目录结构

不要为了让目录看起来更漂亮而大规模移动文件。

只有当删除旧层后某个文件明显失去存在价值时，才合并或重命名。目录整理不能成为新的重构主线。

---

# 2. 已确认的架构决定

以下决定已经确认，不再重新讨论。

## 2.1 不引入 AIClient

普通使用方式保持简单函数 API：

```python
from loushang.ai import ApiKeyAuth, CallOptions, complete, get_model, stream

model = get_model("moonshot", "openai-completions", "kimi-k2.6")
message = await complete(model, context, CallOptions(auth=ApiKeyAuth("...")))
events = await stream(model, context, CallOptions(auth=ApiKeyAuth("...")))
```

`Model` 最终保持数据对象，不再承担 `model.complete()`、`model.stream()` 等调用门面。

## 2.2 保留一个默认全局 ModelRegistry

普通调用只使用一个默认全局 Registry：

```python
get_default_model_registry()
get_model(...)
list_models(...)
```

默认 Registry：

1. 延迟初始化；
2. 加载 Built-in `models.json`；
3. 加载 `~/.loushang/models/*.json`；
4. 完成校验和索引；
5. 正常运行期间只读；
6. reload 时构建新 Registry 后整体替换。

导入 `loushang.ai` 时不得访问用户目录。只有首次调用模型查询相关 API 时才加载。

## 2.3 保留自定义 Registry，但不作为普通路径

高级调用方和测试仍可显式构建：

```python
registry = load_builtin_model_registry()
registry.merge(load_model_registry_from_file("company-models.json"))
```

不要新增 `DefaultModelRegistry`、`CustomModelRegistry`、`RegistryManager` 等类型。只保留一个 `ModelRegistry` 类。

## 2.4 AI 包保留用户模型目录读取能力

`loushang.ai` 负责：

- 默认读取 `~/.loushang/models/*.json`
- 读取显式文件
- 读取显式目录
- 稳定排序
- 解析、校验、合并
- reload

上层应用负责：

- 当前项目目录发现
- 工作区 `.loushang/models`
- CLI 参数和环境变量策略
- 企业配置中心

## 2.5 模型文件

运行时只保留：

```text
src/loushang/ai/model/models.json
```

当前 `models.curated.v2.json` 重命名为 `models.json`。

当前阶段不使用：

```json
{"schemaVersion": 2}
```

也不保留 schema 1/2 双轨逻辑。

## 2.6 历史巨型模型文件

保留一份离线备份：

```text
backup/ai/
├── README.md
├── models-legacy-full.json.gz
└── models-legacy-full.sha256
```

要求：

- 不进入 Python package data；
- 不参与运行时加载；
- 不参与模型校验；
- README 记录来源 commit、原路径、SHA 校验和恢复方式。

## 2.7 Evidence 不属于运行时契约

删除“每个 Provider 必须有 evidence markdown”的门禁。

- Built-in 模型由项目维护者决定是否官方支持；
- 用户自定义模型不需要 evidence；
- Model Registry 不理解 evidence；
- 缺失 evidence 不能阻止注册；
- 官方资料可记录在 Issue、PR 或可选文档中。

## 2.8 不强制所有模型支持 Streaming

最终语义：

```text
complete(): 不要求 model.capabilities.stream
stream(): 要求 model.capabilities.stream == true
```

三个协议适配器均支持两种调用模式：

```python
mode: Literal["complete", "stream"]
```

非流式上游响应也转换成 RawPart 序列，继续复用同一 Runtime 和 Assembler。

---

# 3. 目标调用链

最终调用链只允许包含以下步骤：

```text
get_model()
    ↓
complete() / stream()
    ↓
normalize_context_once()
    ↓
validate_model_capabilities()
    ↓
resolve_auth()
    ↓
build ProviderRequest
    ↓
select adapter by model.api
    ↓
adapter.invoke_raw(request)
    ↓
ProviderRuntime
    ↓
RawAssembler
    ↓
AssistantMessageEventStream / AssistantMessage
```

不得继续存在：

```text
Compat
→ Protocol projection
→ Dialect projection
→ Compat projection
→ Adapter options projection
→ Runtime config resolver
```

也不得继续存在：

```text
resolve endpoint
→ bind model
→ resolve endpoint again
→ resolve request
→ normalize request for API
```

每个调用只能：

- 归一化一次；
- 解析认证一次；
- 构造请求一次；
- 选择协议适配器一次。

---

# 4. 模型定义与注册的目标结构

## 4.1 核心概念

只保留：

```text
ProviderDefinition
EndpointDefinition
Model
Capabilities
AuthConfig
Pricing
ModelDefaults
AdapterConfig
ModelRegistry
```

其中 `AdapterConfig` 是以下三个配置的联合类型：

```python
OpenAICompletionsConfig
OpenAIResponsesConfig
AnthropicMessagesConfig
```

不要保留一个空的 `AdapterRuntimeConfig` 基类。

## 4.2 Endpoint 的正式适配配置

删除旧 `Compat`，但保留真实的兼容适配能力。

模型 JSON 示例：

```json
{
  "providers": {
    "company": {
      "displayName": "Company AI",
      "auth": {
        "apiKeyEnv": "COMPANY_AI_API_KEY"
      },
      "endpoints": {
        "openai-completions": {
          "api": "openai-completions",
          "baseUrl": "https://ai.company.example/v1",
          "adapter": {
            "maxOutputTokensField": "max_tokens",
            "developerRole": false,
            "streamingUsage": true,
            "reasoningFormat": "deepseek",
            "extraBody": {
              "custom_flag": true
            }
          },
          "models": {
            "company-reasoner": {
              "upstreamId": "internal/reasoner-v3",
              "displayName": "Company Reasoner",
              "capabilities": {
                "input": ["text"],
                "output": ["text"],
                "contextWindow": 131072,
                "maxTokens": 8192,
                "reasoning": true,
                "stream": true,
                "toolUse": true,
                "structuredOutput": true,
                "temperature": true
              }
            }
          }
        }
      }
    }
  }
}
```

### Adapter 配置约束

- 字段集合必须由当前三个核心协议适配器的真实需求推导；
- 不允许为当前没有使用场景的字段预留；
- 不允许 Provider ID 或 URL 判断；
- `extraBody` 仅允许 JSON-safe 静态值；
- `extraBody` 不得覆盖 SDK 控制字段，例如 `model`、`messages`、`input`、`stream`、`tools`；
- 未知 adapter 字段在模型注册时直接报错；
- 模型级 adapter 配置若确有需要，只允许对 Endpoint adapter 做浅字段覆盖，不做递归任意 deep merge。

## 4.3 Model 应携带完整调用信息

Loader 完成继承后，Registry 返回的 `Model` 必须可独立调用，不需要在调用阶段重新查询 Endpoint。

建议模型对象包含：

```python
@dataclass(frozen=True, slots=True)
class Model:
    id: str
    provider_id: str
    endpoint_id: str
    api: ApiName
    base_url: str | None
    base_url_env: str | None
    auth: AuthConfig | None
    adapter: AdapterConfig
    upstream_id: str | None
    name: str | None
    capabilities: Capabilities
    defaults: ModelDefaults
    pricing: Pricing | None
```

可以保留独立 Endpoint 查询对象供 CLI 展示，但 Model 不再持有：

- `_endpoint_ref`
- `_auth_inherited`
- `_compat_overrides`
- `_transport_legacy_raw`
- `_routing_legacy_raw`
- `_raw_source`
- `with_endpoint()`
- `with_contract_overrides()`

## 4.4 所有模型统一校验

同一解析器和校验器适用于：

- Built-in `models.json`
- `~/.loushang/models/*.json`
- 显式 custom model JSON

### 结构校验

- 根节点、Provider、Endpoint、Model 都必须是对象；
- ID 必须是非空字符串；
- 未知字段直接报错；
- `baseUrl`、Auth、Adapter、Capabilities、Pricing 类型正确。

### 引用与唯一性校验

- Endpoint 必须属于 Provider；
- Model 必须属于 Endpoint；
- 同一 Provider 下 Endpoint ID 唯一；
- 同一 Endpoint 下 Model ID 唯一；
- 完整模型标识为 `provider:endpoint:model`；
- 同一个 Model ID 不得在多个 Endpoint 同时标记 preferred。

### 数值校验

- `contextWindow > 0`
- `maxTokens > 0`
- 默认输出长度不得超过 `maxTokens`
- 价格不得为负
- 未知价格为 `null` 或省略
- `0` 只能表示官方明确免费

### 能力一致性校验

- 当前只允许 `text`、`image`；
- `structuredOutput=true` 时，当前 Adapter 必须存在正式映射；
- `reasoning=true` 时，Adapter 配置必须能表达推理请求或该协议有明确默认；
- `stream=false` 时允许 complete，但 stream 必须提前失败；
- 没有正式类型和实现的能力不得出现在模型定义中；
- 删除 `attachment`，直到有正式 `FilePart` 和协议映射。

### 协议配置校验

根据 `api` 选择唯一 Adapter 配置 Schema：

```text
openai-completions → OpenAICompletionsConfig
openai-responses   → OpenAIResponsesConfig
anthropic-messages → AnthropicMessagesConfig
```

Anthropic Endpoint 不能出现 OpenAI 专用配置，反之亦然。

## 4.5 合并规则

默认 Registry 加载顺序：

```text
Built-in models.json
→ ~/.loushang/models/*.json（文件名稳定排序）
```

允许：

- 添加新 Provider；
- 在已有 Provider 下添加新 Endpoint；
- 在已有 Endpoint 下添加新 Model。

冲突规则：

- 相同 `provider:endpoint:model` 默认报错；
- 同一 Endpoint 的 `api/baseUrl/auth/adapter` 重复定义默认报错；
- 不做任意 deep merge；
- 不静默覆盖 Built-in；
- 本轮不增加 `replace=True`。

坏文件必须让默认 Registry 加载失败，并在错误中包含准确文件路径和字段路径。不得静默跳过。

---

# 5. Provider 协议与请求对象

## 5.1 只保留一个 Provider 请求对象

删除 `ResolvedEndpoint` 和 `ResolvedRequest`。

最终请求对象：

```python
@dataclass(frozen=True, slots=True)
class ProviderRequest:
    call_id: str
    mode: Literal["complete", "stream"]
    model: Model
    context: NormalizedContext
    headers: Mapping[str, str]
    max_output_tokens: int | None
    temperature: float | None
    timeout: TimeoutOptions
    retry: RetryOptions
    reasoning: ReasoningOptions | None
    tool_choice: ToolChoice | None
    structured_output: StructuredOutputOptions | None
```

只有真正被 Adapter 使用的字段才能进入该对象。

## 5.2 Provider 接口

将误导性的 `stream_raw` 改为：

```python
class ApiProvider(Protocol):
    api: str

    def invoke_raw(
        self,
        request: ProviderRequest,
    ) -> AsyncIterator[RawPart]: ...
```

### complete 模式

Adapter 发出非流式上游请求，将完整响应包装为 RawPart：

```text
response_start
text_delta / thinking_delta / tool_call_*
usage_delta
stop_reason
response_done
```

### stream 模式

Adapter 发出流式上游请求，实时转换为 RawPart。

Runtime 不关心上游是否流式，只消费统一 RawPart 序列。

## 5.3 三个核心 Adapter

Core 只保留：

```text
openai-completions
openai-responses
anthropic-messages
```

要求：

- 共享 ProviderRuntime；
- 不自行创建公共 EventStream；
- 不自行实现 Retry；
- 不根据 Provider ID 或 Base URL 分支；
- 只读取 `request.model.adapter`；
- 不读取 Compat、Protocol、Dialect、Routing；
- 支持 complete 和 stream 两种模式；
- 所有异常进入统一 AIError 分类。

OpenAI Codex 保持 contrib，自行拥有其专用 transport/runtime config，不污染 Core 请求对象。

---

# 6. Public API 与 Options 精简

## 6.1 根包稳定 API

普通用户路径只保留：

```text
get_model
list_models
complete
stream
complete_structured

Model
Context
Message 类型
Tool 类型
CallOptions
ReasoningOptions
RetryOptions
TimeoutOptions
StructuredOutputOptions
AIError / AIErrorCode / AIErrorInfo
Usage
AssistantMessageEventStream
```

Registry 管理、模型 Loader、OAuth 管理、Provider 注册和 contrib 位于子包。

## 6.2 只保留一个 CallOptions

删除：

- `ModelCallOptions`
- `StreamOptions`
- `ProviderStreamOptions`
- `SimpleCallOptions`
- `SimpleStreamOptions`
- `ThinkingBudgets`
- `simple_options_to_call_options`
- `complete_simple`
- `stream_simple`

删除重复字段和历史输入：

| 删除 | 保留 |
|---|---|
| `signal` | `cancellation` |
| `max_tokens` | `max_output_tokens` |
| `retries` | `retry` |
| `max_retry_delay_ms` | `RetryOptions.max_delay_seconds` |
| 数字 `timeout` | `TimeoutOptions` |
| 字符串 reasoning | `ReasoningOptions` |
| `reasoning_summary` | `ReasoningOptions.expose_summary` |
| `hooks` | 删除 |
| 未使用 `metadata` | 删除 |

最终字段必须遵循：

> 至少一个 Core Adapter 或 ProviderRuntime 实际消费，并且有测试或示例；否则删除。

允许保留的其他字段，例如 cache/session/region，必须先通过上述实际使用审计。Contrib-only 字段只能留在 contrib options 中。

## 6.3 删除 Provider-specific Deprecated Options

删除：

```text
loushang.ai.advanced.options.AnthropicOptions
loushang.ai.advanced.options.OpenAICompletionsOptions
loushang.ai.advanced.options.OpenAIResponsesOptions
```

Core Provider 不再兼容这些旧属性。

## 6.4 参数不支持时明确失败

任何显式提供但当前 Model / Adapter 不支持的参数：

- 必须在调用 Provider 前抛 `UnsupportedCapabilityError`；
- 不得静默忽略；
- 错误 details 包含 capability 和 model ref。

---

# 7. Context 与消息归一化精简

## 7.1 Context 只表达会话数据

稳定 Context 只包含：

```python
@dataclass
class Context:
    system_prompt: str | None
    messages: list[Message]
    tools: list[Tool] | None
```

字典输入只接受：

```text
system_prompt / systemPrompt
messages
tools
```

未知顶层字段直接报错。

删除通过任意字段名猜测能力的代码：

```text
response_format
response_model
json_schema
output_schema
files
attachments
file_ids
```

Structured Output 只能从 `CallOptions.structured_output` 进入。

Attachment 能力本轮删除；未来需要时以正式 `FilePart` 重新设计。

## 7.2 简化 NormalizedContext

目标：

```python
@dataclass(frozen=True, slots=True)
class NormalizedContext:
    system_prompt: str | None
    messages: tuple[Message, ...]
    tools: tuple[Tool, ...]
```

删除：

- `_FrozenList`
- `_FrozenDict`
- Mapping 模拟接口
- arbitrary extras
- `NORMALIZED_CONTEXT_MARKER`
- `normalization_key`
- 模型/Endpoint/PairingMode 匹配逻辑
- 递归修改 frozen dataclass 的 freeze 逻辑

归一化时只做必要复制：

- list → tuple
- dict message → dataclass message
- Tool parameters 做普通 copy

ProviderRequest 只能接收 `NormalizedContext`。Provider 层不得再次调用 normalize。

## 7.3 归一化只执行一次

Public API：

```text
raw Context → normalize_context_result() → NormalizedContext
```

Provider invocation：

```python
assert isinstance(request.context, NormalizedContext)
```

不得调用 `ensure_normalized_context()` 做第二次 fallback。

## 7.4 Diagnostics 不新增新 Hook 概念

保留 `NormalizationResult` 和 `NormalizationDiagnostic`。

普通调用链发生 diagnostics 时：

- 使用已有 Trace 机制发出 `normalization:diagnostic`；
- 同时写入 observability debug/warning；
- 不增加 `on_diagnostic`、事件总线或通用 Hook 框架。

`repair` 仍必须显式启用。

---

# 8. Runtime、事件和错误

## 8.1 必须保留

- RawPart 中间协议
- ProviderRuntime
- 有界 Event Queue
- 首个可见输出前 Retry
- Retry-After
- Cancellation
- 上游 `aclose/close`
- Exactly-one-terminal
- Typed AIError
- Parallel Tool Call Buffer
- Structured Output 解析
- strict/coerce Tool Validation

这些是经过验证的真实工程能力，不属于过度设计。

## 8.2 Pre-visible Buffer 有界化

将：

```python
pending: list[RawPart]
```

改为：

```python
deque[RawPart]
```

并设置简单上限：

```text
最大 part 数
最大估算字节数
```

上限作为模块常量，不增加配置对象。

超限抛出：

```python
AIProviderProtocolError
```

不得通过无限缓存支持 Retry。

## 8.3 Runtime 不增加新状态机框架

现有 loop 可以保留。只做：

- 去重；
- 边界修复；
- 有界化；
- 终止语义测试。

不要引入 RuntimeState、Transition、PipelineStage 等新类。

## 8.4 RawAssembler 实现去重

可以增加普通私有方法：

```python
_ensure_started()
_ensure_text_started()
_ensure_thinking_started()
```

禁止为此引入通用状态机或 Handler Registry。

## 8.5 Trace

保留一个版本化 Trace 格式和 Secret Redaction。

每次调用生成一个 `call_id`，所有 Runtime Trace 至少包含：

```text
callId
api
provider
endpoint
model
```

Retry 事件还应包含：

```text
attempt
maxAttempts
delayMs
reason
statusCode（若有）
requestId（若有）
```

Secret Redaction 与 AIError JSON-safe 逻辑应共享一个小工具函数，避免维护两套敏感字段判断。

不要增加 Span、Tracer、Context Propagation Framework。

## 8.6 错误

保留当前 AIError taxonomy，除非某个类型完全无调用方且无测试价值。

所有 Provider 异常必须归一化为：

```text
code
message
source
retryable
provider
endpoint
model
statusCode
requestId
details
```

不得把 SDK 原始异常或响应对象暴露给公共 API。

---

# 9. Auth 精简

## 9.1 只保留一个 AuthConfig

当前 Model Domain 的 `Auth` 与 auth/support 的 `AuthConfig` 合并为一个类型。

该类型负责描述：

```text
kind
api_key_env(s)
header
prefix
extra_headers
```

Loader 完成 Provider → Endpoint → Model 的简单继承，Model 持有最终 AuthConfig。

调用时不再通过 Registry 查 Endpoint 解析认证。

## 9.2 保留 Credential Store 的可靠性

必须保留：

- 原子写
- fsync
- 私有目录/文件权限
- 并发更新保护
- 损坏文件明确错误
- 显式 credentials 默认不落盘
- OAuth refresh 失败不得静默 fallback

跨平台文件锁应使用一个小的后端函数或成熟轻量依赖，不要设计 CredentialStore 插件框架。

## 9.3 精简 OAuth Facade

Registry 类本身直接提供：

```text
register
get
list
clear
```

删除为每个 Registry 方法再包装一层的重复全局函数。

保留主要操作：

```text
get_default_oauth_registry
register_builtin_oauth_providers
oauth_login
oauth_refresh
```

Contrib OAuth 逻辑留在 contrib。

---

# 10. Usage 与非核心能力

## 10.1 Core 只保留响应 Usage 和 Cost

统一为一个公开类型：

```python
Usage
```

删除 `Usage = UsageObservation` 双名称，或只保留一个兼容名称；本轮不保留历史 alias，优先保留 `Usage`。

未知价格：

```python
usage.cost is None
```

不得返回全零假装免费。

## 10.2 Platform Quota 移出 Core

以下内容不属于通用模型调用：

- Kimi `/usages`
- 账户 limit / remaining
- `KimiCLI/1.5` User-Agent
- EndpointQuotaQuery
- PlatformQuotaTransport

移动到：

```text
loushang.ai.contrib.moonshot
```

或上层应用。

不要为一个 Provider 的账户接口设计通用 Core Quota Framework。

## 10.3 Codex Runtime Config 留在 Contrib

删除 Core 空基类：

```text
AdapterRuntimeConfig
AdapterRuntimeConfigResolver
```

OpenAI Codex 的 WebSocket、originator、conversation id 和专属缓存选项全部由 `loushang.ai.contrib.openai_codex` 自己拥有。

Core ProviderRequest 不引用 Codex 类型。

---

# 11. Registry 与默认加载

## 11.1 默认 Registry

```python
get_default_model_registry()
```

行为：

```text
第一次调用：
    读取 Built-in models.json
    读取 ~/.loushang/models/*.json
    校验
    合并
    构造 Registry
    缓存
```

`reload_default_model_registry()`：

- 构造一个全新的 Registry；
- 全部成功后原子替换全局引用；
- 加载失败时保留旧 Registry。

## 11.2 显式 Loader

建议保留：

```python
load_builtin_model_registry()
load_model_registry_from_file(path)
load_model_registry_from_directory(path)
load_default_model_registry(user_dir=None)
```

删除大量 `*_with_diagnostics` 双入口；旧格式 diagnostics 删除后，这些入口不再有存在必要。

## 11.3 Provider Registry

默认协议 Adapter Registry 同样延迟初始化，只包含三个 Core Adapter。

普通 API 参数中的 `registry` 改名为：

```python
provider_registry
```

避免和 ModelRegistry 混淆。

高级调用方可传入自定义 Provider Registry；普通用户不需要接触。

Contrib 注册可以默认注册到全局 Provider Registry，也必须允许显式传 Registry。注册动作必须由调用方显式触发，导入 contrib 不得自动修改全局状态。

---

# 12. 测试策略

测试目标是证明行为，不是锁定文件数量、代码行数或开发流程。

## 12.1 单元测试

重点覆盖纯逻辑：

- 模型 JSON 解析
- 所有注册校验
- Registry 合并和冲突
- 默认用户目录加载
- 消息 canonicalization
- Tool pairing
- Tool strict/coerce validation
- Capability validation
- Auth precedence
- Error classification
- Retry delay / Retry-After
- Structured Output parsing
- Pricing / Cost
- Trace redaction

## 12.2 协议适配器接口测试

三个 Adapter 必须通过同一套接口规则：

- 只接收一个 `ProviderRequest`；
- `invoke_raw()` 返回 AsyncIterator[RawPart]；
- complete 和 stream 都可映射；
- 文本、推理、工具、usage、错误映射一致；
- 取消后关闭上游；
- 不泄漏 Secret；
- 只产生一个 terminal。

## 12.3 负面测试

必须覆盖：

- 未知模型 JSON 字段；
- 错误 adapter 字段；
- 协议与 adapter 类型不匹配；
- 重复模型冲突；
- 非法价格和 token limit；
- stream=false 的模型调用 stream；
- 显式不支持参数；
- 错误 Tool pairing；
- 可见输出后不得 Retry；
- 重复 terminal；
- RawPart 顺序非法；
- pre-visible buffer 超限；
- Credential Store 损坏和并发写；
- Secret Trace 泄漏。

## 12.4 删除脆弱测试

删除：

- 测试文件数量快照；
- Example 文件数量快照；
- “Compat 债务数量”快照；
- 61 个 Plan-ID 的产品 Contract Test；
- 仅为 migration-v2 服务的测试；
- 保护 deprecated API 的测试。

开发流程脚本可以有自己的轻量测试，但不能作为 AI SDK 行为契约。

## 12.5 Live Tests

真实 Provider 测试继续：

```python
@pytest.mark.live
```

默认 CI 不运行，不得因为没有凭据阻塞离线固化。

Live 结果只记录实际通过的 Provider。

---

# 13. 示例策略

示例从场景出发，不展示内部抽象。

建议主示例保持在 8–10 个：

```text
01_basic_complete.py
02_streaming_output.py
03_tool_call_loop.py
04_parallel_tools.py
05_reasoning.py
06_structured_output.py
07_image_input.py
08_retry_and_errors.py
09_custom_model_file.py
10_model_switch.py
```

要求：

- 每个示例独立运行；
- 默认离线 Faux/Recorded Provider；
- 解释实际使用场景；
- 只导入稳定根 API；
- 不导入 compat、resolution、provider runtime；
- 不硬编码 Provider Payload；
- 主示例全部由 CI 执行。

高级示例只保留：

```text
自定义 Provider Adapter
OAuth / Credential Store
OpenAI Codex contrib
Trace 检查
```

删除只为旧架构、迁移层或内部类型展示而存在的示例。

---

# 14. 文档精简

最终保留：

```text
docs/en/sdk/README.md
docs/zh-CN/sdk/README.md
模型 JSON 格式说明
自定义模型说明
Core Adapter 简介
关键场景示例索引
```

删除或归档本轮完成后失去长期价值的过程文档：

- `migration-v2.md`
- `final-scorecard.md`
- `final-owner-review-*.md`
- `catalog-evidence/*`
- `curated-provider-matrix.md`
- 旧 compat 架构文档
- 旧 quality-hardening 临时结论

执行计划本身可以留在 `docs/internals/plans/`，但产品文档不能依赖过程文档才能理解 API。

重写 `src/loushang/ai/TODO.md`，删除已经移出 Built-in 的 OpenRouter、Cloudflare、Vertex、Mistral 等旧任务；只保留真实未完成项。

---

# 15. 不得破坏的现有优点

删除式重构不能牺牲以下能力：

- 当前 11 个 Built-in Provider 和 17 个模型均可注册；
- 用户自定义 OpenAI-compatible / Anthropic-compatible 模型可通过 JSON 注册；
- OpenAI Chat / Responses / Anthropic 三协议；
- complete / stream；
- reasoning；
- tools；
- parallel tool calls；
- structured output；
- image input；
- usage 和 cost；
- typed errors；
- retry / timeout / cancellation；
- bounded queue；
- credential store 安全写入；
- OpenAI Codex contrib；
- 双语 SDK 文档；
- 场景示例。

若某个旧能力本身只存在于类型或 metadata 中、没有真实实现和测试，应删除声明，而不是继续保留假能力。

---

# 16. 分阶段 Goal 清单

每个 Goal 必须单独 commit、单独测试、单独 review。Codex 不得将多个 Goal 合并成一个“close remaining issues”提交。

---

## Phase A：建立精简目标和可失败契约

### AIF-001：记录 Core Freeze 决策与目标契约

**提交标题**：

```text
docs(ai): define core freeze architecture
```

**工作**：

- 将本 Goal 复制到仓库计划目录；
- 增加一份短 ADR，记录：
  - 不引入 AIClient；
  - 默认全局 ModelRegistry；
  - 保留用户模型目录；
  - 删除 Legacy Compat；
  - 一个 CallOptions；
  - complete/stream 双模式；
  - Platform Quota 移出 Core。
- 增加目标架构检查列表，不实现功能。

**验证**：

```bash
git diff --check
```

**Review**：`ai_architect`、`ai_reviewer`

---

### AIF-002：增加最终目标测试，删除错误 baseline

**提交标题**：

```text
test(ai): replace debt snapshots with core freeze contracts
```

**工作**：

- 删除文件数量、Example 数量、Compat 债务数量、Plan-ID 产品测试；
- 增加预期失败的目标测试：
  - 无 Compat 类型；
  - 无 schemaVersion；
  - 无 Simple API；
  - 无 Deprecated Provider Options；
  - 模型文件名为 `models.json`；
  - 默认 Registry 加载 Built-in + 用户目录；
  - complete/stream mode 契约；
  - Model 可独立调用，不依赖 Registry lookup。

本提交允许目标测试暂时失败，但必须只标记为清晰的 `xfail(strict=True)`，并在对应后续 Goal 中移除 xfail。不得永久留下。

**验证**：

```bash
uv run pytest tests/ai/test_core_freeze_contracts.py -q
uv run ruff check tests/ai/test_core_freeze_contracts.py
```

**Review**：`ai_test_reviewer`、`ai_architect`

---

## Phase B：模型定义和 Registry 收敛

### AIF-003：重命名 Built-in 模型文件并整理历史备份

**提交标题**：

```text
chore(ai-models): establish single runtime models file
```

**工作**：

- `models.curated.v2.json` → `models.json`；
- 删除 runtime schemaVersion；
- 移动历史巨型模型备份到 `backup/ai/`；
- 更新 package data；
- 删除旧 archive runtime/文档路径；
- 删除 evidence 强制门禁；
- `check_catalog.py` 只做真实注册校验，不做 Provider/Model 数量上限和 evidence 检查。

**验证**：

```bash
uv run python scripts/ai/check_catalog.py
uv run pytest tests/ai/test_curated_catalog.py tests/ai/test_model_catalog.py -q
uv build
```

**Review**：`ai_catalog_reviewer`、`ai_test_reviewer`

---

### AIF-004：用简单 AdapterConfig 替代 Compat/Protocol/Dialect

**提交标题**：

```text
refactor(ai-models): replace compat layers with adapter configs
```

**工作**：

- 定义三个小型 Adapter Config；
- 从当前 17 个模型实际字段反推最小字段集合；
- 修改 `models.json`；
- 删除 `Compat`、`SupportStatus`、`EndpointProtocol*`、`EndpointWireDialect`；
- 删除 `compat_schema.py`；
- 删除 protocol/dialect 与 compat 的往返投影；
- 未知 adapter 字段注册时报错。

**硬约束**：

- 不新增第四层抽象；
- 不保留 legacy translator；
- 不增加 schemaVersion；
- 不允许 URL/Provider 猜测。

**验证**：

```bash
rg -n "Compat|SupportStatus|EndpointProtocol|EndpointWireDialect|compat_schema" src/loushang/ai tests/ai tests/providers
uv run pytest tests/ai/test_model_domain.py tests/ai/test_model_loader_schema.py tests/ai/test_compat_boundaries.py -q
```

预期 `rg` 仅允许历史备份 README 中的自然语言，不允许生产代码命中。

**Review**：`ai_architect`、`ai_catalog_reviewer`、`ai_reviewer`

---

### AIF-005：简化 Model、Endpoint 和 Loader

**提交标题**：

```text
refactor(ai-models): simplify model loading and inheritance
```

**工作**：

- 删除 Model/Endpoint 的 `_legacy_raw`、`_explicit`、`_raw_source`、contract override；
- Model 展开有效 Endpoint/Auth/Adapter 信息；
- 删除 `with_endpoint()`、`with_contract_overrides()`；
- Loader 只解析当前格式；
- 校验和构造合并为一条解析路径；
- 删除 `*_with_diagnostics` 模型 Loader 双入口；
- 删除旧格式 diagnostics。

**验证**：

```bash
uv run pytest tests/ai/test_model_domain.py tests/ai/test_model_loader_schema.py tests/ai/test_model_registry_resolution.py -q
uv run mypy
```

**Review**：`ai_architect`、`ai_test_reviewer`

---

### AIF-006：固化默认 Registry、用户目录和冲突规则

**提交标题**：

```text
refactor(ai-registry): make default model loading deterministic
```

**工作**：

- 默认 Built-in + `~/.loushang/models/*.json`；
- 延迟初始化；
- reload 原子替换；
- 显式 file/directory loader；
- 相同完整模型 ID 冲突报错；
- 不做任意 deep merge；
- 坏文件包含路径和字段路径；
- 测试不得读取真实开发者 Home，必须 monkeypatch 临时目录。

**验证**：

```bash
uv run pytest tests/ai/test_model_catalog.py tests/ai/test_model_registry_resolution.py -q
```

**Review**：`ai_catalog_reviewer`、`ai_test_reviewer`

---

## Phase C：调用 API 和 Provider 边界收敛

### AIF-007：合并请求解析对象

**提交标题**：

```text
refactor(ai-provider): collapse request resolution into provider request
```

**工作**：

- 删除 `ResolvedEndpoint`、`ResolvedRequest`；
- 构造单一 `ProviderRequest`；
- 删除 `resolve_provider_request()` 的二次投影；
- Model 直接提供静态 Endpoint/Adapter 信息；
- 认证、CallOptions 在 API 层解析一次；
- `registry` 参数改名为 `provider_registry`。

**验证**：

```bash
uv run pytest tests/ai/test_api_streaming.py tests/ai/test_provider_resolution.py tests/ai/contracts -q
```

**Review**：`ai_architect`、`ai_reviewer`

---

### AIF-008：统一 complete/stream Provider 调用模式

**提交标题**：

```text
refactor(ai-provider): support complete and stream invocation modes
```

**工作**：

- `stream_raw` → `invoke_raw`；
- ProviderRequest 增加 `mode`；
- 三个 Core Adapter 实现非流式和流式请求；
- 非流式响应转换为 RawPart；
- `complete()` 不检查 stream capability；
- `stream()` 检查 stream capability；
- 删除“complete 表面非流式、实际固定 stream=true”的契约冲突。

**验证**：

```bash
uv run pytest tests/ai/test_api_streaming.py tests/providers -q
```

必须新增三类 Adapter 的 complete-mode mapping 测试。

**Review**：`ai_reviewer`、`ai_test_reviewer`、`ai_architect`

---

### AIF-009：收敛 CallOptions 和根 API

**提交标题**：

```text
refactor(ai-api): reduce call options to one canonical contract
```

**工作**：

- 删除 Simple API；
- 删除 Options alias；
- 删除 Deprecated Provider Options；
- 删除重复字段；
- 审计每个剩余字段是否被 Core 消费；
- 更新根 `__all__`；
- 删除 Model 实例调用方法；
- 所有示例迁移到根函数。

**验证**：

```bash
uv run pytest tests/ai/test_options.py tests/ai/test_baseline_contracts.py tests/agent/test_public_api.py -q
uv run mypy
```

**Review**：`ai_architect`、`ai_docs_reviewer`、`ai_test_reviewer`

---

## Phase D：Context、Runtime 和非核心清理

### AIF-010：简化 Context 归一化

**提交标题**：

```text
refactor(ai-context): normalize context once with strict fields
```

**工作**：

- 简化 NormalizedContext；
- 删除 FrozenList/FrozenDict/Mapping 模拟；
- 删除 normalization key；
- 未知 Context 字段报错；
- 删除 structured/attachment 字段名猜测；
- 删除 attachment capability；
- Provider 层不得二次 normalize；
- diagnostics 通过现有 Trace 发出。

**验证**：

```bash
uv run pytest tests/ai/test_context.py tests/ai/test_api_streaming.py tests/ai/test_tool_transform.py -q
```

**Review**：`ai_reviewer`、`ai_test_reviewer`

---

### AIF-011：精炼 ProviderRuntime 与 Trace

**提交标题**：

```text
refactor(ai-runtime): bound retry buffering and unify call tracing
```

**工作**：

- pending list → deque；
- 增加 part/bytes 上限；
- 超限 typed protocol error；
- 所有 Trace 带 call_id 和请求身份；
- Retry Trace 补齐上下文；
- Trace/Error 共用 Secret Redaction 工具；
- RawAssembler 仅做普通方法去重；
- 不引入新状态机。

**验证**：

```bash
uv run pytest tests/ai/test_provider_runtime.py tests/ai/test_event_stream_assembler.py tests/ai/test_trace.py tests/ai/test_errors.py -q
```

**Review**：`ai_reviewer`、`ai_test_reviewer`

---

### AIF-012：精简 Auth 和 OAuth API

**提交标题**：

```text
refactor(ai-auth): unify auth configuration and registry operations
```

**工作**：

- 合并 Auth/AuthConfig；
- Model 持有有效认证配置；
- 删除调用时 Endpoint Registry lookup；
- 精简 OAuth facade；
- 保留 Credential Store 可靠性；
- 完成跨平台锁；
- 不引入存储插件框架。

**验证**：

```bash
uv run pytest tests/ai/test_auth_storage.py tests/ai/test_auth_support.py tests/ai/auth -q
```

**Review**：`ai_reviewer`、`ai_test_reviewer`

---

### AIF-013：将 Provider 专属非核心能力移出 Core

**提交标题**：

```text
refactor(ai-core): move provider-specific services to contrib
```

**工作**：

- Platform Quota 移到 Moonshot contrib 或应用层；
- Core usage 只保留 Usage/Cost；
- 删除 UsageObservation 双名称；
- AdapterRuntimeConfig 全部移到 Codex contrib；
- Core 不引用 Codex runtime 类型。

**验证**：

```bash
uv run pytest tests/ai/test_usage.py tests/ai/auth/test_openai_codex_oauth.py -q
```

**Review**：`ai_architect`、`ai_reviewer`

---

## Phase E：测试、示例、文档与固化

### AIF-014：重构测试矩阵

**提交标题**：

```text
test(ai): align tests with simplified core contracts
```

**工作**：

- 删除迁移层和 deprecated 测试；
- 增加 Parser/Registry/Adapter/Runtime 负面测试；
- 增加用户目录、冲突、complete-mode、buffer limit 测试；
- 保持覆盖率门禁；
- 不测试文件数量和过程治理。

**验证**：

```bash
make check-ai
```

**Review**：`ai_test_reviewer`、`ai_reviewer`

---

### AIF-015：整理场景示例和长期文档

**提交标题**：

```text
docs(ai): document the frozen core through runnable scenarios
```

**工作**：

- 主示例收敛为场景示例；
- 增加 `custom_model_file.py`；
- 更新中英文 SDK README；
- 增加当前模型 JSON 格式说明；
- 删除 migration-v2、scorecard、evidence 和旧架构文档；
- 重写 TODO；
- 所有主示例可离线执行。

**验证**：

```bash
uv run python scripts/ai/check_examples.py
uv run pytest tests/examples/test_ai_examples.py -q
```

**Review**：`ai_docs_reviewer`、`ai_test_reviewer`

---

### AIF-016：执行 JSON-only Add-Model Drill

**提交标题**：

```text
test(ai-models): prove json-only model extension path
```

**工作**：

在测试临时目录中创建一个使用现有协议的企业自定义模型 JSON，并证明：

- 只写 JSON；
- 不修改 Python；
- 可读取；
- 可与 Built-in 合并；
- 可查询；
- 可用 Faux/Recorded Adapter 完成 complete；
- 可按 capability 判断 stream；
- 错误 adapter 字段会注册失败；
- 重复完整模型 ID 会失败。

不要为了该测试增加专用生产代码。

**验证**：

```bash
uv run pytest tests/ai/test_custom_model_extension.py -q
```

**Review**：`ai_catalog_reviewer`、`ai_test_reviewer`、`ai_architect`

---

### AIF-017：最终全分支评审和冻结

**提交标题**：

```text
docs(ai): record core freeze verification
```

**工作**：

- 运行全部门禁；
- 对 base..HEAD 进行只读多 Agent Review；
- 生成 review index；
- 记录实际测试和覆盖率；
- 不编造 Live Provider 结果；
- 清理临时 xfail；
- 确认无 P0/P1；
- P2 只保留明确非阻塞项。

**最终验证**：

```bash
git diff --check
make check-ai
uv run pytest tests -q
uv build
```

并检查：

```bash
rg -n "Compat|SupportStatus|EndpointProtocol|EndpointWireDialect|ResolvedRequest|ResolvedEndpoint|SimpleCallOptions|complete_simple|stream_simple|schemaVersion" src/loushang/ai tests/ai tests/providers
```

生产代码不得命中。

**Review**：全部 Reviewer；最终 P0=0、P1=0。

---

# 17. Git、Commit 和 Review 强制流程

## 17.1 开始

```bash
git switch ai/quality-hardening-v2
git pull --ff-only
BASE_HEAD="$(git rev-parse HEAD)"
git switch -c ai/core-freeze-v1
```

若实际 HEAD 与本文不同，记录新 HEAD，不得回退用户提交。

## 17.2 每个 Goal 的步骤

```text
1. 读取当前 Goal。
2. 先运行相关测试并确认当前状态。
3. 只修改该 Goal 范围。
4. 补单元测试或场景示例。
5. 运行 focused tests。
6. 运行相关 ruff/mypy。
7. git diff --check。
8. 提交一个原子 commit。
9. 对 HEAD^..HEAD 运行只读 Agent Review。
10. 有 P0/P1 时，用新的 fix commit 修复并再次 review。
11. 无 P0/P1 后进入下一 Goal。
```

## 17.3 Commit 格式

```text
<type>(ai): <single purpose summary>

Goal-ID: AIF-NNN
Tests:
- <actual command and result>
```

不得在未执行时写“passed”。

Review 在提交后运行，报告保存：

```text
.artifacts/ai-reviews/<commit-sha>.md
```

不要 amend 已评审 commit。

## 17.4 每 Commit Reviewer

至少：

- `ai_reviewer`
- `ai_test_reviewer`

根据范围增加：

- Model/Registry：`ai_catalog_reviewer`
- 架构/API/Runtime：`ai_architect`
- Docs/Examples：`ai_docs_reviewer`

## 17.5 Review 规则

- P0：立即停止后续 Goal；
- P1：必须在下一独立 commit 修复；
- P2：优先修复；确实不值得修复时在最终 ledger 说明原因；
- Reviewer 不得只复述改动；必须检查简洁性、重复概念、历史包袱和负面测试。

Reviewer 固定问题：

```text
1. 本提交是否减少了概念和代码？
2. 是否产生新的双重事实源？
3. 是否保留了不必要的旧 API？
4. 是否存在为了未来假设而增加的抽象？
5. 是否能用更直接的实现完成？
6. 是否有静默忽略或隐式 fallback？
7. 单元测试是否验证行为而不是实现细节？
```

## 17.6 Phase Gate

每个 Phase 完成后：

```bash
make check-ai
git diff --check
```

并对该 Phase 的 commit range 运行：

- `ai_architect`
- `ai_reviewer`
- `ai_test_reviewer`

下一 Phase 开始前必须关闭所有 P0/P1。

---

# 18. 最终验收标准

## 18.1 概念与代码

- [ ] 无 Legacy Compat 生产代码。
- [ ] 无 schemaVersion 双轨。
- [ ] 无 Protocol/Dialect/Compat 往返投影。
- [ ] 无 ResolvedEndpoint/ResolvedRequest 双层请求。
- [ ] 无空 AdapterRuntimeConfig Core 基类。
- [ ] 无 Simple API 和 Options alias。
- [ ] 无 Deprecated Provider Options。
- [ ] 无 Model 实例调用门面。
- [ ] Normalization 只执行一次。
- [ ] Core 不含 Provider 账户额度特判。
- [ ] 一个认证配置类型。
- [ ] 一个公开 Usage 类型。

## 18.2 模型和 Registry

- [ ] Built-in 运行时文件为 `models.json`。
- [ ] 历史大文件位于 `backup/ai`，不进入 package。
- [ ] 默认 Registry 延迟加载 Built-in + 用户目录。
- [ ] 显式 file/directory loader 可用。
- [ ] Built-in 与用户模型使用相同 Parser 和校验。
- [ ] 冲突明确报错。
- [ ] 没有 evidence 强制门禁。
- [ ] JSON-only add-model drill 通过。

## 18.3 调用能力

- [ ] complete 使用非流式上游调用。
- [ ] stream 使用流式上游调用。
- [ ] stream capability 只约束 stream。
- [ ] 三个 Core Adapter 都支持两种 mode。
- [ ] 现有 tools/reasoning/structured/image 能力不退化。
- [ ] 不支持的参数调用前失败。

## 18.4 可靠性

- [ ] Retry 只发生在可见输出前。
- [ ] Pre-visible buffer 有界。
- [ ] 取消关闭上游。
- [ ] Event queue 有界。
- [ ] Exactly-one-terminal。
- [ ] AIError 稳定且 Secret-safe。
- [ ] Credential Store 原子、安全、跨平台锁定。
- [ ] 未知价格为 None。

## 18.5 工程质量

- [ ] `make check-ai` 通过。
- [ ] 全仓测试通过。
- [ ] sdist 和 wheel 构建通过。
- [ ] 主场景示例全部离线执行。
- [ ] 中英文文档同步。
- [ ] 所有 AIF commit 均有 review 报告。
- [ ] 最终 P0=0、P1=0。
- [ ] GitHub Actions 实际通过后才可宣称 CI 通过。

---

# 19. 停止条件

遇到以下情况，不得继续增加抽象，先重新评估：

1. 为删除一个旧类型，新增了两个以上替代类型；
2. 同一个配置值在两个对象中重复保存；
3. 新增 Manager/Resolver/Facade 仅包装一个函数；
4. 新增通用 Hook 但只有一个调用方；
5. 为单一 Provider 特判设计 Core Framework；
6. 为兼容旧测试而保留 deprecated 代码；
7. 新增模型仍需要修改 Python Adapter；
8. 调用链中再次出现两次 normalize 或两次 resolve；
9. 一个 commit 同时跨越两个以上 Phase；
10. 测试通过依赖放宽阈值或删除负面测试。

此时应优先删除或内联，而不是继续封装。

---

# 20. 完成后的预期形态

普通用户：

```python
from loushang.ai import CallOptions, complete, get_model

model = get_model("deepseek", "openai-completions", "deepseek-v4-pro")
message = await complete(
    model,
    {"messages": [{"role": "user", "content": "你好"}]},
    CallOptions(),
)
```

企业用户只增加文件：

```text
~/.loushang/models/company.json
```

程序下次 reload 后即可：

```python
model = get_model("company", "openai-completions", "company-reasoner")
```

新增使用现有协议的模型，不修改：

- Provider Adapter
- Runtime
- Public API
- Error 类型
- Message 类型
- 专门模型测试代码

只需要：

1. 写正确的模型 JSON；
2. 通过统一注册校验；
3. 运行现有数据驱动测试和场景 smoke。

这就是本轮 Core Freeze 的最终完成标准。
