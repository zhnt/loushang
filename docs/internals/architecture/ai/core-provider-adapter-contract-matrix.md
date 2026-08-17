# Core Provider Adapter Contract Matrix

`loushang.ai` ships only protocol-level production adapters. Product and account
scenarios reuse them through model catalog routes; product-specific adapters do
not belong in the package.

## Production Adapters

| API | Module | Adapter | Protocol Boundary |
|---|---|---|---|
| `anthropic-messages` | `loushang.ai.protocols.anthropic_messages` | `AnthropicMessagesAdapter` | Anthropic Messages |
| `openai-completions` | `loushang.ai.protocols.openai_chat_completions` | `OpenAIChatCompletionsAdapter` | OpenAI-compatible Chat Completions |
| `openai-responses` | `loushang.ai.protocols.openai_responses` | `OpenAIResponsesAdapter` | OpenAI Responses |

These are the only adapters registered by `register_builtin_api_adapters`.
All registered entries must implement `APIAdapter` (`api` plus `invoke_raw(request)`).
Adapters that own non-core validation may additionally implement
`ProviderRequestValidator.validate_request(request)`, which is checked at
registration and runs before `invoke_raw(request)`.

The three production adapters also implement `PreparedRequestAdapter`:

- `prepare_request(request)` completes all model-visible protocol mapping and
  returns an immutable `PreparedModelRequest`;
- the AI runtime awaits the optional `PreparedRequestCommitter` once per
  transport attempt; and
- `invoke_prepared_raw(request, prepared)` sends only the canonical frozen
  payload and model-visible protocol headers, plus non-model-visible transport
  metadata.

One invocation keeps a stable `invocation_id`; retries increment `attempt` and
repeat prepare/commit. A configured committer fails closed for an adapter that
does not implement this seam. Without a committer, legacy custom adapters keep
their standalone `invoke_raw(request)` behavior.

A committer may additionally implement the Harness-neutral
`PreparedModelCallOutcomeRecorder`. After all runtime-owned retries reach one
terminal part, AI calls that observer once with invocation identity,
completed/failed/cancelled disposition, final usage, and typed error data. The
observer receives no Harness type and does not replace any per-attempt prepared
commit. Standalone committers that do not implement it remain supported.

## Core Support Modules

| Module | Role |
|---|---|
| `loushang.ai.protocols._anthropic` | Shared Anthropic request helpers |
| `loushang.ai.protocols.anthropic_messages_oauth_compat` | Anthropic OAuth compatibility payload helpers |
| `loushang.ai.protocols._openai_responses` | Shared OpenAI Responses conversion and stream parsing |
| `loushang.ai.protocols._helpers` | Shared provider runtime helpers |

## Test-Only

| Module | Boundary |
|---|---|
| `loushang.ai.protocols.faux.FauxAdapter` | Test/example-only adapter; not builtin |

Core does not ship Azure OpenAI or Amazon Bedrock adapters in this version.
