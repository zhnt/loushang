# ARD-002: AI Coverage Gate Scope

## Status

Accepted

## Context

The quality hardening charter requires:

- AI core statement coverage >= 90%.
- Provider adapter aggregate coverage >= 85%.

The package-level `pytest-cov` run also includes protocol adapters and auth
resolution. Those paths do not have the same release meaning as the runtime core:

- Real OAuth credentials and live-provider calls require external conditions
  that are not stable in the offline release gate.
- Provider adapters have their own aggregate threshold because their SDK event
  mapping risk differs from core model/runtime code.

Without a written scope, the numeric target can drift between "all files under
`src/loushang/ai`" and "runtime core", making the release gate hard to reproduce.

## Decision

`make check-ai` keeps the package-level coverage floor at 90% and adds explicit
target checks from `.artifacts/ai/coverage.xml`:

1. `ai-runtime-core >= 90%`
   - Includes the AI runtime, public API, model/catalog domain, context,
     messages, events, provider runtime/resolution, tools, structured output,
     usage, pricing, trace, and utility modules.
   - Excludes only `protocols/`.
2. `provider-adapters >= 85%`
   - Includes the retained production adapters and their shared helper modules:
     `protocols/anthropic_messages.py`, `protocols/_anthropic.py`,
     `protocols/openai_chat_completions.py`, `protocols/openai_responses.py`,
     `protocols/_openai_responses.py`, and `protocols/_helpers.py`.
3. `production-adapter-modules >= 85%`
   - Includes only the three retained production adapter modules:
     `protocols/anthropic_messages.py`,
     `protocols/openai_chat_completions.py`, and
     `protocols/openai_responses.py`.

The package-level 90% floor remains in place to prevent broad regression outside
the scoped targets.

## Rationale

This makes the charter's coverage requirements executable while keeping provider
coverage visible instead of hiding it inside a single package-wide percentage.

The coverage gate complements, but does not replace, behavior tests, contract
tests, offline examples, catalog checks, live smoke when credentials are
available, and final review.

## Consequences

Positive:

- The coverage target is reproducible with one command: `make check-ai`.
- Runtime core and adapter coverage can fail independently.
- Package-level coverage remains visible and enforced at 80%.

Negative:

- Adapter coverage has a separate aggregate threshold in addition to the
  package-level gate.

## Implementation

- `scripts/ai/check_coverage_targets.py`
- `Makefile` target `check-ai-coverage`
- `tests/ai/test_coverage_targets.py`
