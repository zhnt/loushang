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
