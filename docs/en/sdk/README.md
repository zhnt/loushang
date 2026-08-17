# AI SDK

[中文](../../zh-CN/sdk/)

`loushang.ai` is the low-level model invocation SDK. It owns model catalog
loading, request normalization, protocol adapters, streaming events, call-time
authentication, errors, and usage. It does not own agent orchestration, session
persistence, login flows, credential renewal, account storage, quota control, or
product routing.

## Public API

Normal application code uses the root package:

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

Choose a concrete model before invocation:

```python
model = get_model("moonshot", "openai-completions", "kimi-k2.6")
```

The tuple is always `provider:endpoint:model`. The selected `Model` already
contains the effective API, URL declaration, capabilities, defaults, auth,
static endpoint headers, adapter config, and pricing. Invocation does not switch
endpoints or select a fallback.

Missing or ambiguous model queries raise `ModelNotFoundError` or
`AmbiguousModelError`.

## Complete Calls

```python
message = await complete(
    model,
    {"messages": [{"role": "user", "content": "Say hello."}]},
    CallOptions(
        auth=ApiKeyAuth("..."),
        max_output_tokens=256,
        timeout_seconds=30,
    ),
)
```

`complete` returns an `AssistantMessage`.

## Streaming

```python
events = await stream(
    model,
    {"messages": [{"role": "user", "content": "Count to three."}]},
    CallOptions(auth=ApiKeyAuth("..."), idle_timeout_seconds=10),
)

async for event in events:
    if event["type"] == "text_delta":
        print(event["delta"], end="")

message = await events.result()
```

A stream must terminate exactly once. Provider silence is not converted into
success. Error and aborted terminals cannot be followed by success.

## CallOptions

`CallOptions` is frozen and validated at construction. Its fields are:

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

`timeout_seconds` is the complete deadline for one attempt, including request
creation, first output, and full response consumption.
`idle_timeout_seconds` applies only between streamed raw parts.

`pairing_mode` defaults to `strict`. Use `repair` only for audited historical
transcripts that require tool-call/tool-result repair.

`cache_key` is an opaque upstream cache key, not a Loushang session ID. Only
adapters with an explicit mapping consume it. `cache_retention="none"` removes
the key before invocation.

## Reasoning And Structured Output

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

Reasoning is resolved once and checked against model capabilities. Adapters map
the resolved values to their wire protocols.

```python
result = await complete_structured(
    model,
    {"messages": [{"role": "user", "content": "Return an object."}]},
    StructuredOutputOptions(mode="json_object"),
)
print(result.parsed)
```

Schema mode accepts a JSON Schema mapping or a Pydantic-like type. Unsupported
model capability or adapter mapping fails before provider invocation.

Runnable example:
[07_structured_output.py](../../../examples/ai/07_structured_output.py).

## Tools And Context

Contexts may be dictionaries or the public typed objects. They are normalized
into `NormalizedContext` before an adapter sees them.

```python
context = {
    "messages": [{"role": "user", "content": "Use the calculator."}],
    "tools": [
        {
            "name": "calculate",
            "description": "Evaluate an expression.",
            "parameters": {
                "type": "object",
                "properties": {"expression": {"type": "string"}},
                "required": ["expression"],
            },
        }
    ],
}
```

Tool names, schemas, arguments, boolean flags, usage values, and message parts
are validated strictly. Unknown context fields and unsupported modalities fail
at the boundary.

Image input uses the public `ImagePart` content type. The selected model must
declare image input capability; unsupported image input fails before adapter
invocation.

## Authentication

API key auth may be explicit or resolved from the environment variables declared
by the catalog:

```python
options = CallOptions(auth=ApiKeyAuth("..."))
```

OAuth calls receive a current bearer credential only:

```python
options = CallOptions(
    auth=OAuthBearerAuth(
        access_token,
        extra_headers={"ChatGPT-Account-Id": account_id},
    )
)
```

The model catalog declares the primary auth header name and prefix. Final request
headers merge in this order:

1. endpoint static headers
2. primary credential header
3. `OAuthBearerAuth.extra_headers`
4. `CallOptions.headers`

The last two layers cannot replace the primary credential header.

Provider, endpoint, and model auth use full replacement. A model auth declaration
wins over endpoint auth; endpoint auth wins over provider auth. Declarations are
not partially merged.

The AI package owns config-driven OAuth protocol, callback handling, credential
storage, and permitted refresh. Upper layers call `auth.login(model)`, present
the returned `authorization_url`, and await `session.wait()`; the AI package
does not own product UI and never opens a browser. `auth.get_auth(model)` only
resolves existing authentication and never starts login.

OpenAI Codex is not currently a Loushang OAuth provider. OpenAI Codex support
currently imports existing Codex CLI credentials. It does not perform ChatGPT
OAuth login. The live example does not parse tokens or call the experimental
credential source directly; it calls `get_auth(model)` and passes the result to
the request before calling:

```python
get_model("openai", "coding-responses", "gpt-5.5")
```

See
[openai_codex_live_example.py](../../../examples/auth/openai_codex_live_example.py).

## Custom Catalogs

The built-in catalog is `src/loushang/ai/model/models.json`. Custom files use the
same strict shape:

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

Load it explicitly:

```python
from loushang.ai.model import load_model_registry_from_file

registry = load_model_registry_from_file(path)
model = registry.get_model("company", "openai-completions", "company-chat")
```

Each endpoint must declare a literal URL or a URL environment variable. Missing,
empty, or unresolved URLs fail before an SDK client is created.

A model may declare `upstreamId` when its catalog ID differs from the wire model
ID. The selected adapter reads that bound value; callers do not override it per
request.

## Custom Protocol Adapters

The public invocation functions do not accept a registry argument. Process-level
custom adapter wiring is an advanced boundary:

```python
from loushang.ai.advanced.registry import (
    clear_api_providers,
    register_api_provider,
)

clear_api_providers()
register_api_provider(custom_adapter)
```

Registration validates `api`, `invoke_raw(request)`, and an optional
`validate_request(request)` once. Duplicate API registration fails.

Built-in production adapters are:

- `AnthropicMessagesAdapter`
- `OpenAIChatCompletionsAdapter`
- `OpenAIResponsesAdapter`

## Errors, Usage, And Trace

`AIErrorInfo.code` is always an `AIErrorCode`. Provider exceptions are mapped
to typed errors with stable retryability, status, request ID, and JSON-safe
details.

Usage-only terminal chunks and provider-specific partial usage are normalized
without double-counting reasoning tokens. Cost is unknown when required pricing
metadata is absent.

Trace uses an allowlist. It excludes headers, prompts, response bodies, file
paths, and arbitrary objects. Tool arguments are reduced to key names and
content/command character counts. Exception messages are never recorded.

## Examples And Verification

Start with [examples/ai](../../../examples/ai/README.md).

Catalog and smoke coverage is demonstrated by `11_provider_matrix.py` and
`12_provider_smoke.py`. Custom loading starts with `custom_model_file.py`; custom
adapter setup is in `advanced/custom_catalog.py`.

```bash
make test-ai
make check-ai
```

Live vendor tests are opt-in with `LOUSHANG_AI_LIVE=1`.
