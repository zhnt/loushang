# Product Configuration Runtime Migration Plan

## Status

Implementation complete on the semantic branch
`harness/product-configuration-runtime` for integration into `lane/harness`.
The ownership transfer is complete when the validation gates below pass and the
branch is merged without restoring duplicate Coding mechanisms.

## Objective

Move the complete product-neutral configuration runtime into
`loushang.harness.config` in one coherent migration while preserving Coding's
configuration behavior and Product kernel.

The resulting boundary is:

```text
Harness owns reusable configuration and activation mechanisms.
Coding owns configuration meaning, compatibility, effects, and credentials.
```

See [Harness Product Configuration Runtime Boundary](../architecture/harness/product-configuration-runtime-boundary.md)
for the durable ownership decision.

## Completed Implementation

1. Make `LayeredConfig` transactional for compose, persistence, publication,
   reload preservation, issue collection, snapshots, and notifications.
2. Add Product-injected `ConfigFieldSpec` and `SchemaConfigCodec` mechanics for
   aliases, encode/decode rules, removed fields, recoverable errors, and
   unknown-field policy.
3. Add `ScopedConfigRuntime`, typed scopes, revisions, `ConfigChange` records,
   subscriptions, and non-persistent overrides.
4. Add literal, environment, and command-reference value resolution with an
   injected runner. Keep process and shell execution in Coding.
5. Add an explicit `ConfigActivationRuntime` DAG with stable ordering,
   selectors, refresh/cascade rules, reports, failure modes, rollback, and
   reverse disposal across synchronous and asynchronous entrypoints.
6. Cut Coding over to the Harness schema, scoped runtime, and value mechanism
   while preserving `ControlConfig`, public convenience APIs, paths, JSON
   compatibility, and diagnostic wording.
7. Express Coding bootstrap configuration effects as Product-owned activation
   steps without moving services, callbacks, model registration, or auth into
   Harness.
8. Add product-neutral Harness tests and focused Coding compatibility tests,
   then record the final boundary and migration inventory.

## Product Kernel Preserved

Coding continues to own:

- `ControlConfig`, fields, defaults, validation, normalization, paths, aliases,
  removed-setting compatibility, and convenience APIs;
- configuration diagnostic codes, messages, remediation, and presentation;
- effect selection, dependency order, callbacks, context, services, and
  lifecycle decisions;
- provider registration and persisted model selection. Request authentication
  interpretation remains AI-owned.

`ModelRegistry` is explicitly outside this migration. Request authentication
declarations and credential-to-header resolution remain in AI; Coding does not
own an authentication lifecycle. Harness does not execute shell commands and
does not store credentials.

## Activation Constraints

The activation runtime is an ordering and reporting engine. It is not a
service locator, dependency-injection container, Product manifest, or extension
manifest. The Product injects its config, context, selectors, callbacks, and
disposers. Dependency names establish order and refresh propagation only. A
runtime instance uses one sync or async lifecycle mode, rejects callback
reentrancy, binds a started lifecycle to one Product context, retries dirty
activation steps, and retains failed disposal state plus its dependencies for
an explicit retry. Failed or cancelled cleanup permits only disposal retry.
Scoped configuration serializes mutations, drains reentrant notifications in
revision order, and reports listener errors only after the queued fanout.

## Compatibility Requirements

- Existing Coding global, project, and session precedence remains unchanged.
- Existing JSON keys, aliases, removed-setting behavior, defaults, setters, and
  subscriptions remain compatible.
- Failed composition or persistence leaves the last published config intact.
- Existing config-value environment and `!command` behavior remains compatible,
  but only Coding supplies the shell runner.
- Coding bootstrap preserves package, resource, extension, diagnostic, audit,
  and model-refresh effect order.
- Harness imports no Product, AI, provider, Agent runtime, Method, Work, or TUI
  packages.

## Validation Gates

Run targeted checks first:

```bash
uv run pytest tests/harness/config -q
uv run pytest tests/coding/test_settings_manager.py tests/coding/test_control_services.py -q
uv run pytest tests/coding/test_bootstrap.py -q
```

Then run the merge gates:

```bash
uv run ruff check src/loushang/harness/config src/loushang/coding/control src/loushang/coding/bootstrap.py tests/harness/config
uv run pytest tests -q -m "not live"
git diff --check
```

Any focused Coding test filename that changes before integration should be
substituted with the repository's current equivalent. Live provider tests are
not part of this ownership migration.

## Completion Criteria

- Harness owns one production implementation of the shared mechanisms.
- Coding contains only Product semantics, injected effects, and compatibility
  adapters for this capability.
- Product-neutral tests exercise all Harness contracts without importing
  Coding.
- Coding behavior and effect-order tests pass without changed Product output.
- Architecture import rules and the full non-live suite pass.
- The boundary document and migration inventory agree with the implementation.
