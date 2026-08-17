# AI Package TODO

## Frozen Core Follow-ups

- Keep the core package focused on model calls:
  - model file loading and registry lookup
  - request normalization
  - auth material resolution
  - provider adapters
  - event stream assembly
  - response `Usage` and cost calculation

- Add provider or model coverage primarily through JSON:
  - use `src/loushang/ai/model/models.json` for built-in curated entries
  - use `~/.loushang/models/*.json` or explicit model files for local entries
  - use `upstreamId` when the provider-facing model id differs from the local id
  - keep protocol mapping in `adapter`

- Keep account and product control planes outside the package:
  - provider-specific login, refresh, credential storage, account, and quota
    flows should not enter `loushang.ai`
  - product-backed routes should reuse a protocol adapter and catalog data
    instead of introducing product-specific provider code

- Validation to run before publishing AI changes:
  - `make check-ai`
  - `uv run python scripts/ai/check_examples.py`
  - `uv run pytest tests/examples/test_ai_examples.py -q` when examples or docs change
  - live provider checks only when credentials are intentionally supplied

## Deferred Design Questions

- Whether long-tail provider catalogs should live in external packages.
  Do not add remote catalog discovery or provider marketplace behavior to core.

- Whether additional provider-specific adapters are needed.
  Prefer reusing `openai-completions`, `openai-responses`, or
  `anthropic-messages` with JSON `adapter` configuration first.
