# Loushang AI Top-Level API Signatures

## Status

Current invocation contract. The root package exposes three async entrypoints and one canonical options object.

## Public Entrypoints

```python
async def stream(
    model: Model,
    context: Context | Mapping[str, object],
    options: CallOptions | None = None,
) -> AssistantMessageEventStream: ...


async def complete(
    model: Model,
    context: Context | Mapping[str, object],
    options: CallOptions | None = None,
) -> AssistantMessage: ...


async def complete_structured(
    model: Model,
    context: Context | Mapping[str, object],
    output: StructuredOutputOptions | None = None,
    *,
    options: CallOptions | None = None,
) -> StructuredOutputResult: ...
```

Stable facts:

1. Invocation is `model + context + options`.
2. `options` must be `CallOptions | None`.
3. Provider adapter lookup uses the process default registry. Registry mutation is an advanced setup API, not a per-call public parameter.
4. `stream()` returns `AssistantMessageEventStream`.
5. `complete()` returns `AssistantMessage`.
6. `complete_structured()` reuses `complete()` and validates the result against explicit structured-output options.

## Call Options

```python
CallOptions(
    cancellation=None,
    auth=None,
    headers={},
    cache_retention=None,
    cache_key=None,
    max_output_tokens=None,
    temperature=None,
    timeout=None,
    retry=None,
    trace=None,
    pairing_mode="strict",
    reasoning=None,
    tool_choice=None,
    output=None,
)
```

`CallOptions.auth` accepts only `ApiKeyAuth` or `OAuthBearerAuth`. OAuth login, token refresh, expiry handling, and credential persistence remain outside the AI invocation path. `CallOptions.headers` carries explicit request-level headers.

Final headers are merged in this order:

1. Endpoint static headers.
2. Primary authentication header.
3. `OAuthBearerAuth.extra_headers`.
4. `CallOptions.headers`.

The last two sources may override ordinary headers but may not replace the primary authentication header.

`cache_key` is an opaque caller-provided cache key. It is not a session identifier and does not select endpoints or regions.

## Cancellation

Cancellation enters through `CallOptions.cancellation`. The runtime checks it before invocation, while consuming streams, and before final convergence. Cancellation maps to the public aborted/error contract rather than leaking raw transport exceptions.

## Provider Handoff

```text
complete() / stream()
    -> resolve call options and effective auth for the selected Model
    -> build ProviderRequest(model=selected model)
    -> normalize and validate context against model capabilities
    -> default adapter registry.get(model.api)
    -> adapter.invoke_raw(request)
```

The invocation path does not select another model, switch endpoint, replace `ProviderRequest.model`, or run product/session routing. Adapter registration is explicit through `loushang.ai.advanced.registry` and duplicate registration fails.

## Removed Surface

The root package does not expose simple-call wrappers, per-call registries, provider-specific option families, model-instance invocation facades, or OAuth lifecycle APIs. Unsupported explicit input fails before provider invocation.
