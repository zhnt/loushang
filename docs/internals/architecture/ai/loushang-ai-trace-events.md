# Loushang-AI Trace Events

本文定义 `loushang-ai` Provider Runtime 层的 trace 事件，用于日志与指标接入。事件通过
`CallOptions(trace=callable)` 回调发出，也会进入统一 observability trace sink。

Trace 事件统一为版本化 envelope：

```text
schema = "loushang.ai.trace.v1"
type
source
name
data
```

`type` 使用 `source:name` 形式，例如 `runtime:request`；`source` 和 `name`
由 `type` 拆分得出。

## Runtime 事件

Core runtime 只定义以下事件：

- `runtime:request`
- `runtime:retry`
- `runtime:error`
- `runtime:cancel`

所有 runtime 事件的 `data` 至少包含：

- `callId`: string，同一次 `start_provider_runtime(...)` 调用内保持一致
- `api`: string
- `provider`: string
- `endpoint`: string | null
- `model`: string | null

`runtime:request` 额外包含：

- `attempt`: int，从 1 开始
- `maxAttempts`: int
- `upstreamModel`: string，可选

`runtime:retry` 额外包含：

- `attempt`: int，下一次要执行的 attempt
- `maxAttempts`: int
- `delayMs`: int
- `reason`: string
- `statusCode`: int，可选
- `requestId`: string，可选

`runtime:error` 额外包含：

- `reason`: string
- `retryable`: bool，若错误能归一化为 `AIErrorInfo`
- `statusCode`: int，可选
- `requestId`: string，可选

`runtime:cancel` 额外包含：

- `reason`: `"cancelled"`

Provider SDK payload inspection uses separate `sdk:*` events. These events share the
same versioned envelope and secret redaction rules, but they are provider-owned
payload summaries rather than runtime lifecycle events.

## 示例

一次 retry 后成功的 runtime trace：

```json
{"schema":"loushang.ai.trace.v1","type":"runtime:request","source":"runtime","name":"request","data":{"callId":"c1","api":"anthropic-messages","provider":"anthropic","endpoint":"anthropic-messages","model":"claude","attempt":1,"maxAttempts":2,"upstreamModel":"claude"}}
{"schema":"loushang.ai.trace.v1","type":"runtime:retry","source":"runtime","name":"retry","data":{"callId":"c1","api":"anthropic-messages","provider":"anthropic","endpoint":"anthropic-messages","model":"claude","attempt":2,"maxAttempts":2,"delayMs":0,"reason":"service_unavailable","statusCode":503,"requestId":"req_503"}}
{"schema":"loushang.ai.trace.v1","type":"runtime:request","source":"runtime","name":"request","data":{"callId":"c1","api":"anthropic-messages","provider":"anthropic","endpoint":"anthropic-messages","model":"claude","attempt":2,"maxAttempts":2,"upstreamModel":"claude"}}
```

一次 terminal provider error：

```json
{"schema":"loushang.ai.trace.v1","type":"runtime:request","source":"runtime","name":"request","data":{"callId":"c2","api":"openai-responses","provider":"openai","endpoint":"openai-responses","model":"gpt","attempt":1,"maxAttempts":1,"upstreamModel":"gpt"}}
{"schema":"loushang.ai.trace.v1","type":"runtime:error","source":"runtime","name":"error","data":{"callId":"c2","api":"openai-responses","provider":"openai","endpoint":"openai-responses","model":"gpt","reason":"authentication","retryable":false,"statusCode":401,"requestId":"req_401"}}
```

## Redaction

Trace redaction and `AIErrorInfo.to_dict()` share the same sensitive-key detection.
Secrets such as API keys, authorization headers, OAuth credentials, cookies, and
refresh tokens are redacted. Token accounting fields such as `input_tokens`,
`output_tokens`, `total_tokens`, and `maxOutputTokens` are not treated as secrets.

Tool argument payloads are summarized instead of emitted verbatim:

- `path` may be retained
- `content` is represented by `content_chars`
- `command` is represented by `command_chars`
- object keys are listed for debugging

## Provider-Owned Extension Events

Core runtime does not define transport, WebSocket pool, fallback, reconnect, span, or
tracer frameworks. Provider-owned integrations may emit additional `sdk:*` or
provider-specific events when useful, but those events must keep the versioned trace
envelope and redaction behavior.
