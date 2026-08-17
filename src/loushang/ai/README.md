# `loushang.ai`

`loushang.ai` 是底层模型调用 SDK。它负责模型 catalog、调用参数解析、消息与工具
归一化、协议适配、流式事件组装、API key 与 OAuth credential 生命周期、错误和
usage。它不负责 agent 编排、会话持久化、登录 UI、浏览器交互、配额控制或产品路由。

## 架构

核心调用链只有一条：

```text
Model
-> CallOptions
-> resolve_auth
-> resolve_request_for_model
-> ProviderRequest
-> ProviderRegistry(provider, api)
   -> vendor-specific APIAdapter（精确命中）
   -> APIRegistry(api) 通用 APIAdapter（未命中时回退）
-> adapter.prepare_request
-> PreparedModelRequest（freeze/hash）
-> optional pre-transport commit
-> adapter.invoke_prepared_raw（同一冻结 payload）
-> raw parts
-> runtime / assembler
-> AssistantMessageEventStream
```

目录职责：

- `model/`：领域对象、严格 catalog loader、只读 registry 和 `models.json`。
- `provider/`：请求解析、adapter 调用边界、deadline、retry、取消和错误映射。
- `prepared_request.py`：最终模型可见 payload、invocation/attempt 身份和可选
  pre-transport commit port。
- `api_registry.py`：按 API 标识选择通用协议 adapter。
- `provider_registry.py`：按 `(provider, api)` 精确选择必要的厂商特殊 adapter，
  未命中时回退 `APIRegistry`。
- `protocols/`：三个生产协议 adapter 与离线 faux adapter。
- `event_stream/`：raw part 到统一事件和最终消息的组装。
- `auth/`：API key 解析、OAuth credential 生命周期和请求 auth 转换。
- `tool/`：工具 schema、参数校验和协议 payload 转换。
- `api/`：`stream`、`complete`、`complete_structured`。
- `context.py` / `messages.py`：严格输入归一化。
- `trace.py`：白名单 trace 正规化。

生产协议 adapter：

- `AnthropicMessagesAdapter`
- `OpenAIChatCompletionsAdapter`
- `OpenAIResponsesAdapter`

具体产品、账号或网关逻辑不进入协议 adapter。

## Model 与 Catalog

模型使用 `provider:endpoint:model` 三元组查询：

```python
from loushang.ai import get_model

model = get_model("moonshot", "openai-completions", "kimi-k2.6")
```

当前精简目录位于 `src/loushang/ai/model/models.json`；重构前的完整目录只作为历史
工件保存在 `backup/ai/models-legacy-full.json.gz`，运行时不会读取它。

loader 只读取 JSON、严格校验并构造原始 `Provider / Endpoint / Model` 树。
`ModelRegistry` 是唯一 model binding owner：它将 endpoint facts 一次性绑定到 model，
建立只读索引并提供查询。运行时不再次合并 catalog。

`ModelSelection(provider, endpoint_id, model_id)` 是 Endpoint 完整的轻量引用，三个字段
全部必填。`ModelRegistry.resolve_model_selection()` 将它解析为上述完整 `Model`。
`provider:model`（也接受 `provider/model`）只属于最外层输入简写：仅当
`provider + model_id` 恰好命中一个
Endpoint 时才补全；零候选报不存在，多候选报歧义，不使用 `preferred` 或候选顺序。

每个 endpoint 必须声明可解析的 `baseUrl` 或 `baseUrlEnv`。缺失、空值或未展开模板
在 SDK client 构造前失败，不允许 SDK 隐式回退到厂商默认 URL。

自定义 catalog 可在 model 上声明 `upstreamId`。adapter 从
`request.model.upstream_id or request.model.id` 取得真实上游 ID。

adapter 配置仅保留已实现且有测试的协议差异：

- `OpenAICompletionsConfig`
- `OpenAIResponsesConfig`
- `AnthropicMessagesConfig`

不存在通用请求体逃生字段、transport 抽象或 gateway 选择层。

## 公共 API

根包提供：

```python
from loushang.ai import (
    ApiKeyAuth,
    CallOptions,
    OAuthBearerAuth,
    ReasoningOptions,
    RetryOptions,
    StructuredOutputOptions,
    complete,
    complete_structured,
    get_model,
    list_models,
    stream,
)
```

公共调用签名不接收 registry 参数。自定义 adapter 属于高级进程级配置：

```python
from loushang.ai.advanced.registry import (
    APIRegistry,
    ProviderRegistry,
    clear_api_adapters,
    register_api_adapter,
    register_provider_adapter,
)

clear_api_adapters()
register_api_adapter(custom_adapter)
```

注册时一次性验证 `api`、`invoke_raw(request)` 和可选
`validate_request(request)` 契约。重复注册同一个 API 会失败。
`APIAdapter` 是唯一正式 adapter 术语，不提供旧名称兼容层。
只有通用协议无法表达的厂商差异才使用 `ProviderRegistry`；查找键固定为
`(provider_id, api)`，不检查模型名。

流式与非流式结果共用事件装配路径。每个 `AssistantMessage` 都包含 `api`、
`provider`、`endpoint`、`model`，因此可以还原完整的
`provider:endpoint:model` 响应来源。

## CallOptions

`CallOptions` 是冻结、严格校验的调用契约：

- `cancellation`
- `auth`
- `credential`
- `credential_file`
- `headers`
- `cache_retention`
- `cache_key`
- `max_output_tokens`
- `temperature`
- `timeout_seconds`
- `idle_timeout_seconds`
- `retry`
- `trace`
- `pairing_mode`
- `reasoning`
- `tool_choice`
- `output`
- `prepared_request_committer`

`timeout_seconds` 是一次 attempt 的完整 deadline，覆盖请求创建、首包和完整消费。
`idle_timeout_seconds` 只约束流式 raw part 之间的空闲时间。

`prepared_request_committer` 是高级组合端口。配置后，每次 transport attempt
都会先完成 provider-specific payload 映射，将结果冻结为
`PreparedModelRequest`，再等待 committer 成功；失败时不会调用 provider
transport。同一次逻辑调用共享 `invocation_id`，重试递增 `attempt`。没有配置该端口
时，AI 与 Agent 仍可独立运行；配置端口时，不实现 prepared-request seam 的自定义
adapter 会 fail closed。

未配置 committer 时，runtime 继续调用 adapter 自己的 `invoke_raw`，因此已有扩展对
该方法的覆写语义不变。配置 committer 后才要求并直接使用 prepared-request seam。
进入 provider runtime 的初始 `ProviderRequest.attempt` 固定为 `1`；runtime retry
在同一个 `invocation_id` 下递增它，避免 transport trace 与 commit identity 分叉。

高级组合方从 `loushang.ai.prepared_request` 导入
`PreparedModelRequest` 与 `PreparedRequestCommitter`；它们不扩大根包的稳定应用
调用 facade。

`pairing_mode` 默认是 `repair`。默认修复历史 tool-call/tool-result transcript 中
缺失的结果（例如一次运行在工具调用后、结果写回前被中断），补入 synthetic
error result 并继续，而不是让整个请求失败。需要严格校验（例如新会话的
消息流）时，调用方可显式选择 `strict`。

`cache_key` 是不透明协议缓存键，不代表 Loushang session。当前只有声明支持的 adapter
消费它；`cache_retention="none"` 会移除该键。

## ProviderRequest

最终请求边界只包含：

```python
ProviderRequest(
    model,
    context,
    options,
    base_url,
    headers,
    mode,
    max_output_tokens,
    reasoning_effort,
    reasoning_enabled,
    temperature,
    invocation_id,
    attempt,
)
```

静态 provider、endpoint、api、capabilities、defaults、adapter 和 upstream model facts
均从 `request.model` 读取，不在请求对象中复制。headers 是只读 mapping，base URL
必须已经完整解析。

## Prepared Request Barrier

生产 adapter 将调用明确拆成两个阶段：

1. `prepare_request(request)` 完成消息、工具、reasoning、structured output、cache
   和 provider-specific 字段映射，返回不可变且带 SHA-256 指纹的
   `PreparedModelRequest`；
2. commit 成功后，`invoke_prepared_raw(request, prepared)` 只从冻结 payload
   复制 transport 参数并发送，不再添加模型可见字段。

`PreparedModelRequest` 不包含认证 header、SDK client、回调或其他 transport metadata。
adapter 生成、会改变模型行为的协议 header（当前为 Anthropic beta feature header）
则作为 `model_visible_headers` 一并冻结和计算指纹。纯 transport 值可以在发送阶段
附加，但不能进入模型可见 payload。每次 retry 都重新 prepare 并 commit；相同
payload 和 model-visible headers 可以得到相同 `payload_hash`，但 attempt 身份始终不同。

resolved transport headers 已混合认证和调用配置，不具备可安全持久化的来源信息，
因此不会进入 `model_visible_headers`；Anthropic beta feature header 只从 typed adapter
配置和 reasoning 输入重新生成。Canonical JSON 为稳定 hash 对对象键排序，transport
则从冻结值复制，保留 adapter 原始键序。跨包组合测试可直接调用
`loushang.ai.provider.prepared_request_conformance.run_prepared_request_barrier_conformance`
验证 commit-before-transport 与 commit 失败零 transport 的契约。

## Auth

AI 包拥有 API key 解析和 OAuth credential 生命周期：

```text
catalog endpoint headers
-> primary credential header
-> OAuthBearerAuth.extra_headers
-> CallOptions.headers
```

后两层不能覆盖 primary credential header。

`ApiKeyAuth(value)` 和 `OAuthBearerAuth(access_token, extra_headers={...})` 是请求级
认证；`OAuthCredential` 是可保存、加载和刷新的生命周期 credential。认证 header
名称和 prefix 优先由有效 model 的 `Auth` 声明。
provider、endpoint、model 的 auth 采用完整替换：model 优先，其次 endpoint，最后
provider，不跨层拼接。

endpoint 静态 headers 是协议事实，不属于 auth。模型调用前，resolver 按显式 auth、
显式 credential、credential file、默认 store、独立 credential source、API key env
的顺序解析，并在需要时通过显式注册的 OAuth provider adapter 自动 refresh。

OpenAI Codex credential import 示例直接调用：

```python
get_model("openai", "coding-responses", "gpt-5.5")
```

`AuthResolver` 拥有标准 `apiKey`、`oauth`、`none` 能力。`AuthRegistry` 只在
`(auth kind, model provider, endpoint, optional model)` 精确路由上追加特殊能力，
先查 model 路由，再查 endpoint 路由，未命中就回到标准 resolver。它不支持
provider-only、通配符、正则或模型名称匹配。

实验 `OpenAICodexCredentialSource` 注册在
`oauth/openai/coding-responses` 路由，负责导入现有 `~/.codex/auth.json`；模型
catalog 不声明 credential source。它不是 OAuth provider，也不实现 login 或 refresh。
示例和上层不读取 token 文件。`AuthExtensionRegistry` 是 `AuthRegistry` 的兼容名。
完整 API、文件格式、credential source 与 provider 扩展方式见
`docs/auth/oauth.md`。

## 正确性契约

- OpenAI Chat Completions 的最终 usage-only chunk 会产生 usage delta。
- reasoning token 不会重复计入 output。
- Anthropic partial usage 只更新实际出现的字段。
- raw stream 必须且只能产生一个 terminal part。
- runtime 不为静默结束自动补成功。
- error 或 aborted terminal 后不会继续产生成功。
- OpenAI Responses 的 length incomplete 映射为截断成功，未知 incomplete 映射为错误。
- capability、modalities、options、context、tool arguments 和 usage metadata 均严格校验。

## Error 与 Trace

`AIErrorInfo.code` 必须是 `AIErrorCode`。根包 `get_model` 将缺失和歧义分别映射为
`ModelNotFoundError` 与 `AmbiguousModelError`。

trace 使用字段白名单。它不会记录 headers、prompt、response 正文、文件路径或任意
未知对象。工具参数只保留参数名以及 content/command 字符计数。异常只记录类型，
不记录异常消息。

## 验证

```bash
make test-ai
make check-ai
```

`make check-ai` 覆盖 Ruff、mypy、catalog、import boundary、离线示例和 90% coverage
门禁。真实厂商测试必须显式设置 `LOUSHANG_AI_LIVE=1`。
