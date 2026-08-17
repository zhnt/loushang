# AI Core Verification

Date: 2026-07-18

Branch: `refactor/ai-package`

## Result

The converged `loushang.ai` offline release gate passes locally. Live-provider behavior is not part of this reproducible gate and no CI result is claimed here.

## Validation

| Check | Result |
| --- | --- |
| Ruff | Passed |
| Mypy | Passed: 56 AI source files |
| Catalog | Passed: 12 providers, 13 endpoints, 19 models |
| Import boundaries | Passed |
| Offline examples | Passed: 13 examples |
| AI/protocol/example tests | Passed: 701; 8 live tests deselected |
| Package coverage | Passed: 90.65% (minimum 90%) |
| AI runtime core | Passed: 90.93% (minimum 90%) |
| Protocol adapters | Passed: 89.99% (minimum 85%) |
| Production adapter modules | Passed: 91.01% (minimum 85%) |

Primary command:

```bash
make check-ai
```

## Removed Surface

Production source no longer contains the deleted simple-call wrappers, endpoint transport/routing objects, generic request-body overrides, product-specific providers, OAuth lifecycle/store APIs, or the former provider-adapter package path. Negative tests still construct selected legacy names dynamically to verify they are rejected or absent.

## Scope

This verification covers only `loushang.ai`, its protocol adapters, AI examples, AI tests, and AI validation scripts. Full-repository compatibility is recorded separately because dependent packages are outside this refactor's allowed edit scope.

The full `uv run pytest tests -q` collection currently stops with 67 errors in
`tests/coding` and one `tests/method` module. Those packages still import removed
AI lifecycle/storage types and the former multi-header credential type. They
must migrate in their own worktree lanes; this AI change does not edit them.
