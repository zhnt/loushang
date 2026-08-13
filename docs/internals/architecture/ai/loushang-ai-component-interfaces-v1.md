# `loushang.ai` Component Interfaces

## Public API

The root package exposes:

- `async stream(model, context, options=None) -> AssistantMessageEventStream`
- `async complete(model, context, options=None) -> AssistantMessage`
- `async complete_structured(model, context, output=None, *, options=None) -> StructuredOutputResult`
- model lookup helpers that return typed missing/ambiguous errors

The public invocation surface does not accept a registry, endpoint selector, region selector, transport selector, product route, or provider-specific request body.

## Model Component

`model.loader` validates and returns raw catalog trees. `ModelRegistry` binds provider, endpoint, and model data once and owns all derived values:

- concrete base URL
- API family
- effective auth using Model > Endpoint > Provider replacement
- endpoint static headers
- effective capabilities/defaults/compatibility/adapter configuration

The selected `Model` is the complete invocation target. Runtime code must not rebind it or select an alternative endpoint.

`ModelSelection` is the complete lightweight reference `(provider, endpoint_id,
model_id)`. `ModelRegistry.resolve_model_selection()` resolves it directly. Input
shorthand without an endpoint is completed only when exactly one endpoint matches;
preferred metadata and candidate order never break ambiguity.

## Provider Runtime

`provider/` owns the stable execution contract:

- `ProviderRequest`
- context and option resolution
- capability validation
- retries and call deadlines
- cancellation
- typed provider error mapping
- stream terminal validation

`ProviderRequest` carries a selected model, normalized context, canonical options, invocation mode, and resolved request headers. It has no product, session, routing, or transport state.

## Protocol Adapter Registries

The default `APIRegistry` is process-level state. Built-in adapters are registered during bootstrap. Advanced applications may clear or register adapters before invocation through `loushang.ai.advanced.registry`; duplicate APIs fail immediately.

The root API first asks `ProviderRegistry` for an exact `(model.provider_id,
model.api)` vendor adapter. If absent, it falls back to the generic adapter in
`APIRegistry` keyed by `model.api`. It then invokes `invoke_raw(request)`.
Adapters do not access the model registry, and this lookup never changes the model.

## Authentication

`auth/` accepts only request-ready `ApiKeyAuth` and `OAuthBearerAuth`. It resolves endpoint static headers, primary auth, OAuth auxiliary headers, and call-level headers into one immutable view. Auxiliary headers cannot replace primary authentication.

OAuth login, callback, refresh, persistence, account selection, and entitlement are application concerns.

## Protocol Adapters

`protocols/` owns:

- Anthropic Messages payload/event mapping
- OpenAI Chat Completions payload/event mapping
- OpenAI Responses payload/event mapping
- Faux deterministic test behavior

Adapter configuration is a closed typed set of protocol switches. Unknown keys and unsupported values are rejected during catalog validation.

## Event Stream

The event stream consumes normalized raw parts, emits public assistant events, assembles the final message, tracks usage, and enforces one terminal outcome. Cancellation, malformed part order, duplicate terminal parts, and missing terminal parts fail explicitly.

Every partial and final `AssistantMessage` records `api`, `provider`, `endpoint`,
and `model`; the latter three restore the complete model identity.

## Structured Output

Structured output is a public completion projection. It validates model capability before invocation, supplies explicit output constraints, then parses and validates the completed assistant message. It does not add a second provider path.

## Trace

Trace hooks receive sanitized semantic events only. Header values, URLs, credentials, request/response bodies, and message content never enter trace payloads. Tool data is limited to argument keys and character counts.
