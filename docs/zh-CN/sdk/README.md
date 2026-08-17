# AI SDK

[English](../../en/sdk/)

`loushang.ai` 是底层模型调用 SDK。它负责模型 catalog、请求归一化、协议 adapter、
流式事件、调用期认证、错误和 usage。它不负责 agent 编排、会话持久化、账号登录、
凭证续期、账号存储、配额控制或产品路由。

## 公开 API

普通应用代码使用根包：

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

调用前选择具体模型：

```python
model = get_model("moonshot", "openai-completions", "kimi-k2.6")
```

模型始终用 `provider:endpoint:model` 三元组定位。返回的 `Model` 已包含有效 API、
URL 声明、能力、默认值、auth、endpoint 静态 headers、adapter 配置和价格。
调用期不会切换 endpoint 或选择 fallback。

模型不存在或查询有歧义时，分别抛出 `ModelNotFoundError` 和
`AmbiguousModelError`。

## 完整返回

```python
message = await complete(
    model,
    {"messages": [{"role": "user", "content": "用一句话打个招呼。"}]},
    CallOptions(
        auth=ApiKeyAuth("..."),
        max_output_tokens=256,
        timeout_seconds=30,
    ),
)
```

`complete` 返回 `AssistantMessage`。

## 流式调用

```python
events = await stream(
    model,
    {"messages": [{"role": "user", "content": "数到三。"}]},
    CallOptions(auth=ApiKeyAuth("..."), idle_timeout_seconds=10),
)

async for event in events:
    if event["type"] == "text_delta":
        print(event["delta"], end="")

message = await events.result()
```

流必须且只能终止一次。provider 静默结束不会被自动转换为成功；error 或 aborted
terminal 之后不能继续产生成功。

## CallOptions

`CallOptions` 是冻结且在构造时严格校验的契约，字段如下：

- `cancellation`
- `auth`
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

`timeout_seconds` 是单次 attempt 的完整 deadline，覆盖请求创建、首个输出和完整响应
消费。`idle_timeout_seconds` 只约束流式 raw part 之间的空闲时间。

`pairing_mode` 默认是 `strict`。只有经过审计的历史 transcript 需要修复
tool-call/tool-result 时才使用 `repair`。

`cache_key` 是不透明的上游缓存键，不是 Loushang session ID。只有具备明确映射的
adapter 会消费它；`cache_retention="none"` 会在调用前移除该键。

## Reasoning 与结构化输出

```python
options = CallOptions(
    reasoning=ReasoningOptions(
        enabled=True,
        effort="medium",
        budget_tokens=2048,
        expose_summary=True,
    )
)
```

reasoning 只解析一次，并在调用前检查模型能力。adapter 将解析结果映射到具体协议。

```python
result = await complete_structured(
    model,
    {"messages": [{"role": "user", "content": "返回一个对象。"}]},
    StructuredOutputOptions(mode="json_object"),
)
print(result.parsed)
```

schema 模式支持 JSON Schema mapping 或 Pydantic-like 类型。模型能力或 adapter mapping
不支持时，会在 provider 调用前失败。

可运行示例：
[07_structured_output.py](../../../examples/ai/07_structured_output.py)。

## Tools 与 Context

Context 可以使用 dict 或公开 typed object。adapter 接收前，输入统一归一化为
`NormalizedContext`。

```python
context = {
    "messages": [{"role": "user", "content": "使用计算器。"}],
    "tools": [
        {
            "name": "calculate",
            "description": "计算表达式。",
            "parameters": {
                "type": "object",
                "properties": {"expression": {"type": "string"}},
                "required": ["expression"],
            },
        }
    ],
}
```

工具名、schema、参数、boolean flag、usage 值和消息 part 都严格校验。未知 Context
字段和不支持的 modality 会在边界失败。

图片输入使用公开的 `ImagePart` content 类型。所选模型必须声明 image input 能力；
不支持的图片输入会在 adapter 调用前失败。

## 认证

API key 可以显式传入，也可以从 catalog 声明的环境变量解析：

```python
options = CallOptions(auth=ApiKeyAuth("..."))
```

OAuth 调用只接收当前 bearer credential：

```python
options = CallOptions(
    auth=OAuthBearerAuth(
        access_token,
        extra_headers={"ChatGPT-Account-Id": account_id},
    )
)
```

model catalog 声明 primary auth header 名称和 prefix。最终请求 headers 的合并顺序：

1. endpoint 静态 headers
2. primary credential header
3. `OAuthBearerAuth.extra_headers`
4. `CallOptions.headers`

后两层不能替换 primary credential header。

provider、endpoint、model 的 auth 使用完整替换。model 声明优先于 endpoint，
endpoint 优先于 provider，不做跨层局部合并。

AI 包负责配置驱动的 OAuth 协议、callback、credential 存储与允许的 refresh；
上层调用 `auth.login(model)`、展示返回的 `authorization_url`，然后等待
`session.wait()`。AI 包不拥有产品 UI，也不会打开浏览器。
`auth.get_auth(model)` 只解析已有认证，绝不启动登录。

OpenAI Codex 当前不是 Loushang OAuth provider。当前支持只导入已有 Codex CLI
credential，不执行 ChatGPT OAuth login。live 示例不解析 token 文件，也不直接调用
实验 credential source；它调用 `get_auth(model)`，把结果传给请求，然后调用：

```python
get_model("openai", "coding-responses", "gpt-5.5")
```

详见
[openai_codex_live_example.py](../../../examples/auth/openai_codex_live_example.py)。

## 自定义 Catalog

内置 catalog 是 `src/loushang/ai/model/models.json`。自定义文件使用同一严格形状：

```json
{
  "providers": {
    "company": {
      "auth": {"apiKeyEnv": "COMPANY_AI_API_KEY"},
      "endpoints": {
        "openai-completions": {
          "api": "openai-completions",
          "baseUrl": "https://models.company.example/v1",
          "headers": {"X-Client": "company-app"},
          "adapter": {
            "developerRole": false,
            "maxOutputTokensField": "max_completion_tokens",
            "reasoningFormat": "openai"
          },
          "models": {
            "company-chat": {
              "capabilities": {
                "input": ["text"],
                "output": ["text"],
                "stream": true,
                "toolUse": true
              }
            }
          }
        }
      }
    }
  }
}
```

显式装载：

```python
from loushang.ai.model import load_model_registry_from_file

registry = load_model_registry_from_file(path)
model = registry.get_model("company", "openai-completions", "company-chat")
```

每个 endpoint 必须声明 literal URL 或 URL 环境变量。缺失、空值或未展开 URL 会在
SDK client 创建前失败。

catalog ID 与 wire model ID 不同时，model 可以声明 `upstreamId`。adapter 只读取这个
已经绑定的值，调用方不能在单次请求中覆盖。

## 自定义 Protocol Adapter

公共调用函数不接收 registry 参数。进程级自定义 adapter 接线属于高级边界：

```python
from loushang.ai.advanced.registry import (
    clear_api_providers,
    register_api_provider,
)

clear_api_providers()
register_api_provider(custom_adapter)
```

注册时一次性验证 `api`、`invoke_raw(request)` 和可选
`validate_request(request)`。重复注册同一 API 会失败。

内置生产 adapter：

- `AnthropicMessagesAdapter`
- `OpenAIChatCompletionsAdapter`
- `OpenAIResponsesAdapter`

## Error、Usage 与 Trace

`AIErrorInfo.code` 始终是 `AIErrorCode`。provider 异常会映射为 typed error，
并提供稳定的 retryable、status、request ID 和 JSON-safe details。

usage-only terminal chunk 和厂商 partial usage 会被正确归一化，reasoning token 不会
重复计数。缺少必要价格 metadata 时，cost 保持 unknown。

trace 使用字段白名单，不记录 headers、prompt、response 正文、文件路径或任意对象。
工具参数只保留参数名及 content/command 字符计数。异常消息不会进入 trace。

## 示例与验证

从 [examples/ai](../../../examples/ai/README.md) 开始。

`11_provider_matrix.py` 和 `12_provider_smoke.py` 展示 catalog 与 smoke 覆盖；
`custom_model_file.py` 展示自定义装载，`advanced/custom_catalog.py` 展示自定义 adapter
配置。

```bash
make test-ai
make check-ai
```

真实厂商测试必须显式设置 `LOUSHANG_AI_LIVE=1`。
