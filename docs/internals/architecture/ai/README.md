# Loushang AI Architecture

This directory keeps the current architecture notes for the frozen
`loushang.ai` core. Public usage and API examples live in
[`src/loushang/ai/README.md`](../../../../src/loushang/ai/README.md) and
[`examples/ai`](../../../../examples/ai).

## Active Refactor Inputs

- [AI Refactor Blueprint](./loushang-ai-refactor-blueprint.md)
  is the short entrypoint for the current AI package rebuild structure and
  document reading order.

## Current References

- [ARD List](./ARD-list.md)
- [ARD-001: Async Public Streaming Surface](./ARD-001-async-public-streaming-surface.md)
- [ARD-002: AI Coverage Gate Scope](./ARD-002-ai-coverage-gate-scope.md)
- [ARD-003: AI Core Freeze Contract](./ARD-003-core-freeze-contract.md)
- [Core Freeze Verification](./core-freeze-verification.md)
- [Core Freeze Target Checklist](./core-freeze-target-checklist.md)
- [Core Provider Adapter Contract Matrix](./core-provider-adapter-contract-matrix.md)
- [Trace Events](./loushang-ai-trace-events.md)

## Current Code Domains

- `src/loushang/ai/api/`
- `src/loushang/ai/model/`
- `src/loushang/ai/provider/`
- `src/loushang/ai/auth/`
- `src/loushang/ai/event_stream/`
- `src/loushang/ai/tool/`
- `src/loushang/ai/protocols/`
- `src/loushang/ai/messages.py`
- `src/loushang/ai/context.py`
- `src/loushang/ai/pricing.py`
- `src/loushang/ai/usage.py`

## Core Boundaries

- `model/` owns domain objects, model-file loading, and registry lookup.
- `api/` owns public `complete`, `stream`, and `complete_structured`.
- `provider/` owns `ProviderRequest`, request resolution, invocation guards,
  retry, cancellation, and provider request validation.
- `protocols/` owns the three core protocol adapters:
  `openai-completions`, `openai-responses`, and `anthropic-messages`.
- `auth/` resolves catalog API-key defaults or typed request auth such as
  `OAuthBearerAuth` into request headers. OAuth lifecycle and credential storage
  remain outside the package.
- Product-backed routes reuse the three protocol adapters through catalog data;
  they do not introduce product-specific provider modules.
- `usage.py` owns response usage payload helpers only; account or platform quota
  is outside core usage.

Historical design drafts and reference surveys may exist elsewhere under
`docs/internals`, but this index intentionally points only at the current frozen
core contract.
