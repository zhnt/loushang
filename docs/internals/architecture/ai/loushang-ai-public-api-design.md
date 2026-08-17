# `loushang.ai` Public API Design

Status: current
Scope: `src/loushang/ai`

## Design Goal

The package exposes the smallest stable surface required to call one concrete
model. Product orchestration, account lifecycle, session state, quota control,
and endpoint selection stay outside the package.

The stable call path is:

```text
bound Model + Context + CallOptions
-> ProviderRequest
-> protocol adapter
-> raw stream parts
-> runtime and assembler
-> public events / AssistantMessage
```

## Root Package

The root package exports:

- `stream`
- `complete`
- `complete_structured`
- `get_model`
- `list_models`
- `Model`
- public context, message, tool, event, usage, options, auth, and error types

Advanced registry, loader, normalization, provider, pricing, tool transform, and
trace helpers remain in their owning subpackages.

Public invocation functions do not accept a registry object. Adapter registration
is process-level advanced configuration through `loushang.ai.advanced.registry`.

## Model Identity

A model is selected by the concrete tuple:

```text
provider:endpoint:model
```

A bound `Model` carries the effective endpoint facts needed for invocation:

- provider and endpoint identity
- API protocol
- base URL declaration
- region and lane metadata
- capabilities
- auth declaration
- endpoint static headers
- adapter config
- defaults
- pricing
- optional upstream model ID

Invocation never changes the selected endpoint.

## Catalog Loading And Binding

The loader has three responsibilities:

1. read JSON
2. validate every supported field strictly
3. construct the raw provider tree

`ModelRegistry` is the single binding owner. During construction it applies
endpoint facts to each model once, derives supported defaults, freezes indexes,
and exposes read-only queries.

Programmatic domain construction and JSON loading enforce the same boolean,
integer, modality, price, auth, adapter, and default constraints.

Every endpoint must declare a literal base URL or a base URL environment
variable. Runtime expansion must yield a non-empty, fully resolved URL before any
SDK client is created.

## CallOptions

`CallOptions` is a frozen strict dataclass:

```python
CallOptions(
    cancellation=None,
    auth=None,
    headers={},
    cache_retention=None,
    cache_key=None,
    max_output_tokens=None,
    temperature=None,
    timeout_seconds=None,
    idle_timeout_seconds=None,
    retry=None,
    trace=None,
    pairing_mode="strict",
    reasoning=None,
    tool_choice=None,
    output=None,
)
```

Validation occurs at construction. Runtime never silently accepts legacy shapes
or coerces invalid values.

`timeout_seconds` is authoritative for the full attempt.
`idle_timeout_seconds` is authoritative between raw stream parts.

## ProviderRequest

`ProviderRequest` contains only dynamic invocation state:

```python
@dataclass(frozen=True, slots=True)
class ProviderRequest:
    model: Model
    context: NormalizedContext
    options: CallOptions | None
    base_url: str
    headers: Mapping[str, str]
    mode: Literal["complete", "stream"]
    max_output_tokens: int | None
    reasoning_effort: str | None
    reasoning_enabled: bool | None
    temperature: float | int | None
```

Static facts are read from `request.model`. Request headers are read-only and
the URL is already resolved.

## Protocol Adapter Boundary

Production adapters are:

- `AnthropicMessagesAdapter`
- `OpenAIChatCompletionsAdapter`
- `OpenAIResponsesAdapter`

Each adapter implements exactly:

```python
def invoke_raw(request: ProviderRequest) -> AsyncIterator[RawPart]
```

An optional `validate_request(request)` hook may reject incompatible model
configuration before invocation. Adapter signatures are inspected once during
registration. Duplicate API registration fails.

Protocol adapters contain wire mapping only. They do not identify product token
types, derive account identity, select endpoints, or own credential lifecycle.

## Adapter Config

The supported adapter dataclasses are:

### OpenAICompletionsConfig

- `store`
- `developer_role`
- `streaming_usage`
- `max_output_tokens_field`
- `reasoning_effort`
- `reasoning_effort_map`
- `strict_schema`
- `assistant_reasoning_content`
- `reasoning_format`

### OpenAIResponsesConfig

- `developer_role`
- `max_output_tokens`
- `prompt_cache_key`
- `long_cache_retention`

### AnthropicMessagesConfig

- `fine_grained_tools`
- `interleaved_thinking`
- `long_cache_retention`

Unknown config keys fail validation.

## Authentication Boundary

The invocation layer accepts only:

- `ApiKeyAuth(value)`
- `OAuthBearerAuth(access_token, extra_headers={...})`

The effective model auth declaration defines the primary header and prefix.
Auth inheritance is full replacement:

```text
model auth
else endpoint auth
else provider auth
else no auth declaration
```

Final headers are merged in this order:

```text
endpoint static headers
-> primary credential header
-> bearer extra headers
-> call headers
```

No later layer may replace the primary credential header.

The package does not perform login, browser interaction, credential renewal, or
credential storage.

## Context And Capability Validation

All contexts become `NormalizedContext` before provider handoff. Validation is
strict for:

- top-level context keys
- message roles and parts
- tool names and schemas
- tool argument mappings
- boolean fields
- usage token counts and cost values
- tool-call/tool-result pairing

The default pairing mode is strict. Repair is explicit and emits diagnostics.

Capability validation uses the effective model and rejects unsupported stream,
tool, reasoning, structured output, temperature, attachment, and image requests
before adapter invocation.

## Stream Contract

A raw provider stream must emit exactly one terminal part:

- success
- error
- aborted

The runtime does not manufacture success for a stream that ends silently.
Terminal state is immutable; no event may change error or aborted into success.

OpenAI Responses length-related incomplete states are successful truncation.
Unclassified incomplete states are protocol errors.

## Usage

Usage normalization follows these rules:

- usage-only final chunks produce usage updates
- reasoning tokens are not added to output twice
- partial provider usage changes only fields actually present
- provider totals are preserved when valid
- final message usage and cost are assembled once

Unknown required pricing keeps cost unknown.

## Errors

`AIErrorInfo.code` is typed as `AIErrorCode`. Raw provider codes are mapped at
the provider boundary; unknown raw codes remain in JSON-safe details.

The root model query maps missing and ambiguous lookup failures to dedicated
typed exceptions.

## Trace

Trace is allowlist-based. Safe identity, status, retry, token count, and character
count fields may be recorded.

Trace excludes:

- request headers and credentials
- prompts and response bodies
- file paths
- arbitrary nested payloads
- exception messages
- tool argument values

Tool arguments are summarized as key names and content/command character counts.

## Verification

The AI gate runs:

- Ruff over source, tests, examples, and scripts
- mypy over `src/loushang/ai`
- offline pytest over AI, protocol, and example tests
- catalog, import-boundary, and example checks
- total coverage at or above 90%

Live vendor tests require explicit opt-in.
