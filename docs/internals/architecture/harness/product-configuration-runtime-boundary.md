# Harness Product Configuration Runtime Boundary

## Status

Implementation complete for integration into `lane/harness` on the semantic
branch `harness/product-configuration-runtime`.

The reusable runtime lives under `loushang.harness.config`. The optional
`loushang.harness.config.agent` profile now owns the standard settings used by
Agent-backed products, including their common field codecs and accessors.
Coding adopts that profile directly, alongside its config-value adapter and
explicit bootstrap activation steps.

## Purpose

Products need the same reliable configuration mechanics while retaining their
own fields, defaults, compatibility rules, side effects, credentials, and model
policy. This boundary separates those concerns:

```text
Harness: layer, transact, decode, scope, notify, resolve, order, report
Product: define, validate, locate, authorize, activate, diagnose, present
```

Harness supplies configuration mechanisms and may supply explicitly selectable
cross-product profiles. It does not define one universal Product configuration
or own the services affected by a configuration change.

## Harness Ownership

### Transactional Layered Configuration

`LayeredConfig[T]` owns:

- deterministic low-to-high layer composition;
- recursive patch merge, replacement, snapshots, and defensive copies;
- injected storage and optional per-layer persistence;
- reload, update, and replace transactions;
- issue collection with layer, code, and optional key provenance;
- value subscriptions after a successful state publication.

Updates and replacements compose the complete candidate before persistence and
publish it only after persistence succeeds. A composition or store failure does
not expose a partial in-memory value. Reload validates loaded candidates and
keeps the last valid patch when a persistent layer cannot be loaded or applied.

### Declarative Product Schema Adapter

`ConfigFieldSpec[T]` and `SchemaConfigCodec[T]` own the reusable mechanics for:

- mapping one Product attribute to accepted input keys and an output key;
- invoking injected field decoders, encoders, getters, and replacers;
- reporting Product-declared recoverable field errors as structured issues;
- handling aliases, removed keys, and unknown-key policy;
- encoding only values that differ from a Product default;
- applying and encoding nested dataclass patches through shared helpers.

The field specifications are supplied by the Product. Harness does not decide
what a field means, which values are valid, which aliases remain compatible, or
what diagnostic text a rejected or removed field should use.

### Optional Standard Agent Settings Profile

`loushang.harness.config.agent` composes the existing configuration components;
it is not another configuration engine. Its `SettingsManager` delegates all
layering, persistence, scope transactions, publication, snapshots, and issue
collection to `SettingsRuntime`, `ScopedConfigRuntime`, and `LayeredConfig`.

The profile owns settings shared by Agent-backed products: model and thinking
selection, queue modes, compaction and retry, resources and packages, tool and
approval preferences, terminal/presentation preferences, and method selection.
It also owns their standard getters, setters, collection mutations, codecs, and
cross-product defaults. A Product may use the profile unchanged or bind a
different configuration profile when it needs additional domain fields.

This optional profile may depend on stable Agent and AI value types. The neutral
`loushang.harness.config` core outside `config.agent` remains free of Agent and
AI imports, and the complete config package remains free of Product imports.

The implemented Agent-profile internals have one-way ownership:

- `types.py` owns immutable settings records and defaults;
- `_settings_codec.py` owns the persistent schema, aliases, removed fields,
  field decoding/encoding, and complete `ControlConfig` serialization;
- `_settings_patch.py` owns the `UNSET` command distinction, typed update
  record, typed-update-to-layer-patch conversion, and removed session override
  preparation;
- `manager.py` owns scopes, paths, listeners, collection commands, permission
  ceiling checks, and the stable getter/setter facade.

`SettingsManager` imports only the explicit codec/patch ports. It does not own
field-level serializers. Persistent removed fields remain in the raw stored
scope patch and report schema issues; removed session overrides are dropped
before application and report adapter errors. These are deliberately different
compatibility semantics.

### Scoped Configuration Runtime

`ScopedConfigRuntime[T]`, `ConfigScope[T]`, and `ConfigChange[T]` own:

- named typed views over configured layers;
- scope paths, base directories, persistence flags, and patch snapshots;
- revisioned reload, update, replace, and non-persistent override operations;
- change records containing the operation, layer, previous value, and current
  value;
- separate change and value subscriptions;
- structured issue draining from the layered engine.

Layer names and paths are constructor inputs. Harness does not prescribe a
global, project, session, user, workspace, or organization layout.

Mutations and revision allocation are serialized. Listener-triggered mutations
are committed immediately but their notifications enter a FIFO queue, so every
subscriber observes monotonically increasing revisions and each value event
matches its `ConfigChange.current`. Listener notification is post-commit: an
exception does not roll back an already composed and persisted configuration.
The runtime finishes the current FIFO fanout, including reentrant commits, then
propagates the first listener exception to the outer publisher.

### Configuration Value Resolution

`ConfigValueResolver` and `ConfigCommandResult` own the reusable mechanism for:

- literal values and environment-name lookup;
- command-reference parsing for values prefixed with `!`;
- injected runner invocation with a timeout argument;
- command-result normalization and cache management.

Harness never starts a process or executes a shell. Without an injected runner,
a command reference resolves to no value. Coding retains the `subprocess` runner
and its compatibility convenience functions, including the process-wide cache.

### Configuration Activation

`ConfigActivationStep` and `ConfigActivationRuntime` own:

- stable dependency ordering over an explicit directed acyclic graph;
- duplicate, missing-dependency, self-dependency, and cycle validation before
  any Product effect runs;
- Product-supplied selectors, apply callbacks, dispose callbacks, and an
  explicit opaque context;
- changed, always, forced, and dependency-cascade refresh decisions;
- stop or continue failure modes with applied, skipped, blocked, and failed
  result records;
- synchronous and asynchronous start, refresh, and reverse-order disposal;
- optional reverse-order rollback after startup failure;
- revisioned reports and idempotent repeated disposal;
- dirty-step retry after an apply or cascade failure;
- retryable disposal state when a Product disposer fails, while keeping its
  dependency resources active until cleanup succeeds.

Each runtime instance binds to either synchronous or asynchronous entrypoints on
first use. Mixing modes is rejected, and callbacks cannot recursively invoke a
lifecycle operation on the same runtime. A lifecycle also binds to the exact
context object passed to `start`; duplicate starts and cross-context refresh or
disposal are rejected until disposal completes. Failed or cancelled cleanup
enters a cleanup-only phase: refresh is rejected until the same context retries
disposal successfully. Cancelled activation marks its current step dirty for a
later refresh. This keeps one state machine behind one serialization model
while allowing Products to choose the appropriate API.

The activation graph describes effect order only. It is not a service locator,
dependency-injection container, Product manifest, or extension manifest.
`depends_on` never resolves or stores a service. Products construct the context,
hold all service instances, select the steps, and implement every callback.

## Product Ownership

Coding and future Product adapters retain:

- Product-only configuration records and fields not admitted to a shared
  profile;
- Product overlays that intentionally change standard defaults, validation, or
  enabled field groups;
- global and project settings paths, scope names, and file conventions;
- Product-only compatibility methods, commands, and UI;
- configuration effect selection, dependency order, callback implementation,
  context construction, failure escalation, and lifecycle integration;
- diagnostic codes, wording, severity, remediation, and CLI/TUI projection;
- provider registration, model selection policy, and persisted model-selection
  behavior. Request authentication interpretation remains in AI.

Coding's bootstrap may use `ConfigActivationRuntime` to preserve and make
explicit its package, resource, extension, audit, and model-refresh order. The
callbacks remain Coding code and operate on Coding-owned services. Moving the
ordering mechanism does not move those effects or services into Harness. The
initial Coding adoption is a one-shot startup graph; existing session
controllers continue to own runtime reload behavior.

## Model, Authentication, And Credential Boundary

`ModelRegistry`, provider registration, and model selection remain Product
concerns. Request authentication declarations and credential-to-header
resolution remain AI concerns. Coding does not own an `AuthManager`, login or
logout commands, credential persistence, or credential refresh.

Harness configuration never stores credentials. It may carry opaque values
provided by a Product, but it must not discover secrets, serialize credential
objects, choose a provider, resolve an account, or invoke model/auth services.

## Coding Adoption

Coding adopts the shared runtime without surrendering Product semantics:

- `harness.config.agent.SettingsManager` supplies the standard `ControlConfig`
  factory and field specifications to `SchemaConfigCodec`, then delegates
  scopes and revisioned mutations to `ScopedConfigRuntime`;
- Coding imports the shared manager and value types directly. Its public exports
  retain type identity without preserving duplicate implementation modules;
- the existing validation, aliases, removed-setting messages, JSON shape, and
  setter behavior remain unchanged by the owner move;
- `harness.config.subprocess_values.SubprocessConfigValueResolver` provides the optional
  local-shell resolver over the neutral injected-runner contract; Products may
  use the shared default or inject a different runner without adding a facade;
- `coding.bootstrap` declares Product-owned activation steps and callbacks over
  an explicit Coding state object while retaining the existing effect order.

No second configuration implementation remains in Coding where the Harness
profile is sufficient. Product paths, `ModelRegistry`, policy, and
presentation remain Product-owned.

## Import And Validation Rules

- `loushang.harness.config` must not import Coding, AI, Agent runtime, Method,
  Work, TUI, providers, or Product storage packages.
- Harness configuration tests use Product-neutral fixtures and injected fake
  stores, runners, contexts, and effects.
- Coding tests preserve field behavior, JSON compatibility, paths, diagnostics,
  config-value behavior, bootstrap effect order, and model/auth integration.
- Transaction failure tests must prove that invalid composition and persistence
  failures do not publish partial state.
- Activation tests must cover graph validation, refresh selection, failure
  modes, rollback, reverse disposal, and sync/async callback handling.
- Ruff, architecture import checks, focused Harness and Coding tests, and the
  full non-live suite remain merge gates.

## Explicit Non-Goals

This migration does not:

- define a universal Product configuration schema or manifest;
- make activation a service locator or dependency-injection framework;
- move Product setting fields, defaults, validation, paths, compatibility, or
  convenience APIs into Harness;
- move Product effect order, callbacks, services, or diagnostic wording into
  Harness;
- execute shell commands or store credentials in Harness;
- move `ModelRegistry`, provider registration, persisted model selection, or AI
  request authentication into Harness.
