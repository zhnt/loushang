# ARD-003: AI Core Freeze Contract

## Status

Accepted

## Context

The `ai/quality-hardening-v2` branch produced a working AI package, but it also
left several transition shapes in the code and documentation: legacy compat
projection, simple API aliases, provider-specific core options, multiple request
resolution objects, and product-level provider services mixed into the core
model-call boundary.

The next branch, `ai/core-freeze-v1`, is not a capability expansion branch. Its
purpose is to freeze `loushang.ai` as a small lower-level package whose core job
is:

> Given a registered model and standard messages, reliably invoke the matching
> external API protocol.

The detailed execution sequence is the
[AI core freeze goal](../../plans/2026-06-24-loushang-ai-core-freeze-goal.md).

## Decision

`loushang.ai` keeps the simple function API and does not introduce `AIClient`,
manager, service, facade, container, event bus, plugin lifecycle, or dependency
injection abstractions.

The frozen core is governed by these decisions:

1. Public invocation remains `get_model(...)`, `complete(...)`, `stream(...)`,
   and `complete_structured(...)`.
2. `Model` remains a data object. It does not grow `model.complete()` or
   `model.stream()` facade methods.
3. There is one default global `ModelRegistry`, initialized lazily on first model
   lookup.
4. The default registry loads built-in `models.json` and stable-sorted user JSON
   files from `~/.loushang/models/*.json`.
5. A custom `ModelRegistry` remains available for advanced callers and tests, but
   no `DefaultModelRegistry`, `CustomModelRegistry`, or `RegistryManager` type is
   added.
6. Legacy compat, protocol/dialect projection, schema-version migration, and
   deprecated option aliases are removed instead of preserved.
7. `CallOptions` is the only core call-options contract.
8. Core provider adapters support both `complete` and `stream` invocation modes.
   `complete()` does not require `model.capabilities.stream`; `stream()` does.
9. Platform quota and provider account services move out of core. Core keeps only
   response `Usage` and cost calculation.

## Rationale

This branch prefers fewer concepts, shorter call chains, less public API, and
earlier failures over broader abstraction. The package is still allowed to keep
proven reliability mechanics such as raw parts, bounded queues, retry before
visible output, cancellation, typed errors, structured output parsing, tool-call
assembly, usage, trace redaction, and credential-store safety.

The intent is to make adding a model that uses an existing external API protocol
primarily a JSON change, not a Python adapter change.

## Consequences

Positive:

- The normal user path stays short and does not require understanding registries
  or provider internals.
- The model registry has one canonical runtime file format.
- Provider adapters receive one normalized request object for one selected API.
- Unsupported explicit options fail before provider calls instead of being
  silently ignored.

Negative:

- Older branch internals and deprecated aliases are intentionally removed.
- Some process and migration docs become historical and must not be treated as
  product documentation after the freeze.
- Users relying on old internal types need to move to the frozen public API.

## Impacted Documents

- `docs/internals/plans/2026-06-24-loushang-ai-core-freeze-goal.md`
- `docs/internals/architecture/ai/core-freeze-target-checklist.md`
- `docs/en/sdk/README.md`
- `docs/zh-CN/sdk/README.md`

## Impacted Code Areas

- `src/loushang/ai/__init__.py`
- `src/loushang/ai/api/`
- `src/loushang/ai/model/`
- `src/loushang/ai/provider/`
- `src/loushang/ai/protocols/`
- `src/loushang/ai/context.py`
- `src/loushang/ai/event_stream/`
- `src/loushang/ai/auth/`
