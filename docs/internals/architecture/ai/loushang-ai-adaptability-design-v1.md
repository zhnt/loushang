# Loushang AI Adaptability Design

## Status

This document records the implemented adaptability boundary for `loushang.ai`. Product, session, account lifecycle, and endpoint-selection policy remain outside the package.

## Stable Core

The stable core owns:

- `Model`, `Endpoint`, `Provider`, capabilities, defaults, compatibility, and pricing domain objects
- raw catalog loading and one-time registry binding
- `CallOptions`, `ProviderRequest`, context normalization, capability gates, retries, deadlines, errors, usage, and trace events
- the public `stream()`, `complete()`, and `complete_structured()` entrypoints
- process-level adapter registration through the advanced registry API

The loader validates and preserves the catalog tree. `ModelRegistry` is the only owner of binding and derived effective values. Effective auth uses complete replacement with priority Model > Endpoint > Provider.

## Protocol Adapters

Protocol mappings live under `loushang.ai.protocols`:

- `OpenAIChatCompletionsAdapter`
- `OpenAIResponsesAdapter`
- `AnthropicMessagesAdapter`
- `FauxAdapter`

Adapters translate the stable request into protocol payloads and normalize protocol output into public parts, events, stop reasons, errors, and usage. They do not select endpoints, read credential stores, implement login, refresh tokens, manage sessions, or encode product entitlement logic.

Adapter configuration contains only protocol mapping switches:

- OpenAI Chat Completions: storage, developer role, streaming usage, output-token field, reasoning mapping, schema strictness, and reasoning-content formats
- OpenAI Responses: developer role, output-token support, prompt-cache key, and long cache retention
- Anthropic Messages: fine-grained tools, interleaved thinking, and long cache retention

There is no generic request-body escape hatch and no transport/routing configuration layer.

## Authentication Boundary

Invocation accepts already usable request credentials:

- `ApiKeyAuth(value)`
- `OAuthBearerAuth(access_token, extra_headers={...})`

Endpoint static headers and `CallOptions.headers` are also supported. Header resolution is centralized before adapter invocation, and the primary authentication header cannot be replaced by auxiliary or call-level headers.

The AI package does not own browser login, callback handling, refresh, credential persistence, account switching, logout, subscription state, or workspace binding. Applications resolve those concerns before calling `loushang.ai`.

For a ChatGPT coding-plan request, the experimental `OpenAICodexCredentialSource` may import an existing Codex credential file, convert it to request auth, and call the ordinary OpenAI Responses adapter using `openai:coding-responses:gpt-5.5`. Upper layers do not parse the token file. This is a credential-source and endpoint distinction, not an OAuth provider or a new protocol family.

## Provider Request

`ProviderRequest` contains only invocation state required by every adapter:

- selected concrete `Model`
- normalized `Context`
- resolved `CallOptions`
- invocation mode
- resolved auth/header view

The selected model already contains its endpoint URL, API family, effective auth, defaults, compatibility, and adapter configuration. Adapters must not replace it or consult a model registry.

## Extension Rules

1. Add catalog data when the difference is provider, endpoint, model, capability, default, pricing, or static header metadata.
2. Add adapter configuration only for a protocol payload or stream-decoding difference.
3. Add a protocol adapter only for a genuinely different wire protocol.
4. Register custom adapters once through `loushang.ai.advanced.registry` before invoking the root API.
5. Keep product routing, session affinity, quota products, OAuth lifecycle, and account entitlement outside the package.

## Failure Contract

Unsupported capabilities, invalid options, unresolved base URLs, duplicate adapters, unknown catalog keys, and malformed provider output fail explicitly with typed errors. Streaming must emit one terminal outcome and then close; deadline and cancellation checks cover both request start and stream consumption.

## Observability

Trace output is a sanitized semantic view. It may include model/provider/API identifiers, timing, retry decisions, usage, stop reason, and tool argument keys/character counts. It must not include raw headers, URLs, payload bodies, credentials, or message content.

## Verification

Offline validation covers core behavior, all protocol adapters, public examples, catalog validation, import boundaries, type checking, lint, and coverage gates. Live tests require explicit `LOUSHANG_AI_LIVE=1` opt-in.
