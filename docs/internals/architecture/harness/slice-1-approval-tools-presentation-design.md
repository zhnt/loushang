# Harness Slice 1 Design: Approval, Tools Core, Presentation

## Status

Implemented on `lane/harness` as the Slice 1 boundary design.

> Historical compatibility notes in this document are superseded by
> [Tool Facade Extinction Boundary](tool-facade-extinction-boundary.md):
> `loushang.coding.tools` no longer exists and consumers import Harness owners
> directly.

The closure audit and migration status are recorded in
[Slice 1 Closure Status](slice-1-status.md). This document remains the boundary
reference for approval, tools-core, tool-contribution, and presentation
ownership. Follow-on slices still require separate design before migrating
runtime context, dynamic extension registration, concrete tools, command
semantics, prompt/resource semantics, TUI state, AI provider behavior, or agent
loop behavior.

## Goal

Extract product-neutral approval, tool-core, and presentation mechanisms from
`loushang.coding` into `loushang.harness` without changing coding behavior.

Slice 1 validates the OEM and extension contribution model while avoiding the
agent loop, AI provider/model/auth layer, TUI render loop, command/slash
semantics, prompt templates, coding session store, and work/method/channel
implementations.

## Design Rule

Slice 1 is a split, not a file move.

Current `loushang.coding` modules often mix reusable mechanism with coding
policy, Pi-compatible protocol projection, AI content conversion, concrete tool
behavior, or UI/session integration. Only the product-neutral contract or
mechanism may move into harness. Coding-owned behavior remains in coding
adapters and compatibility modules.

Harness may depend on stable `loushang.agent` primitives. Harness must not
import `loushang.coding`, `loushang.tui`, `loushang.work`, `loushang.method`,
or `loushang.ai`.

Do not add Slice 1 types to top-level `loushang.harness.__all__`. Consumers
should import from focused modules.

## Target Modules

Slice 1 introduces or fills these focused modules:

- `loushang.harness.approval`
- `loushang.harness.tools.core`
- `loushang.harness.tools.contribution`
- `loushang.harness.presentation`

No new top-level packages such as `loushang.workspace`, `loushang.context`,
`loushang.memory`, `loushang.session`, `loushang.product`, or
`loushang.runtime` are introduced.

## Approval Boundary

### Harness Owns

`loushang.harness.approval` owns neutral approval contracts and headless
resolver mechanics:

- `ApprovalRequest`
- `ApprovalDecision`
- `ApprovalResolver`
- `DenyApprovalResolver`
- `HeadlessApprovalResolver`
- `resolve_approval`
- a local `MaybeAwaitable` helper if needed

`ApprovalRequest` may carry product policy context only as opaque metadata.
For example, a current `policy_decision` field must become `object | None` or
a neutral metadata mapping. Harness must not import Coding policy modules; the
neutral value is owned by `loushang.harness.policy.PolicyDecision`.

Approval contracts should fail fast on invalid neutral values. In Slice 1,
`ApprovalDecision` validates its disposition, and `resolve_approval` validates
that resolvers return an `ApprovalDecision` after awaiting sync or async
resolver output. This is contract hardening only; product policy semantics,
approval audit payloads, and UI behavior stay outside harness.

### Coding Keeps

`loushang.coding.policy` keeps coding policy and UI integration:

- `PolicyDecision`
- `PolicyEngine`
- destructive command/path heuristics
- `enforce_tool_policy`
- approval audit payload shape
- `PolicyEnforcementError`
- `InteractiveApprovalResolver`
- persisted or UI-specific approval behavior

`InteractiveApprovalResolver` stays coding-owned in Slice 1 because the current
implementation owns pending futures, presenter payload shape, and product UI
behavior. A later slice may define a neutral approval broker if it can be
expressed without importing UI callbacks or product payload semantics.

Coding compatibility paths re-export harness-owned approval contracts where
they were already part of the coding surface. Those shims preserve import paths;
they do not change class ownership, add new top-level SDK exports, or move
`InteractiveApprovalResolver` into harness.

## Tools Core Boundary

### Harness Owns

`loushang.harness.tools.core` owns neutral tool definition, schema, registry,
and agent-adaptation mechanics:

- `ToolDefinition`
- `ToolRenderCall`
- `ToolRenderResult`
- `ToolRenderOutput`
- schema helpers such as `apply_schema_overrides`,
  `infer_schema_from_signature`, and `infer_schema_from_type`
- `DecoratedToolSpec`
- `DecoratedTool`
- `tool` decorator metadata
- neutral registry records and enable/disable/list mechanics
- adaptation from `ToolDefinition` to stable `loushang.agent` `AgentTool`
  primitives

`ToolDefinition.prompt_snippet` and `ToolDefinition.prompt_guidelines` are
opaque product-consumed metadata. Harness may store and preserve them, but must
not assemble prompts, validate prompt semantics, order prompt sections, or
render prompt guidance.

Render callback types may use stable `loushang.agent` result primitives, but
harness must not import AI content-part types directly.

### Coding Keeps

`loushang.coding.tools` keeps concrete tools and coding adapters:

- `read`, `ls`, `find`, `grep`, `write`, `edit`, and `bash`
- `factory.py`
- `builtins.py`
- default tool packs and activation order
- product-specific tool names and descriptions
- `ToolsOptions`
- concrete operation protocols for coding tools
- external tool download/installation policy
- Pi-style aliases and public coding SDK surface

`normalize.py` is split rather than moved. The current decorated-tool
normalization converts plain return values into AI text parts, so that portion
stays in coding. Harness may own decorator metadata and schema inference, but
plain return value to model content conversion remains a product adapter
concern unless a later neutral result adapter is designed.

Context binding is also split. Current `ToolContext` carries coding diagnostics
and product runtime fields. Harness may own registry and agent-tool adaptation,
but coding keeps `ToolContext`, `ToolContextProvider`, and context injection
unless the implementation introduces an opaque binder protocol with no coding
dependencies.

Provider schema projection is coding-owned in Slice 1. Harness may store a
secondary parameter schema as opaque metadata if needed for compatibility, but
the current behavior where runtime agent tools expose
`provider_parameters or parameters` stays in the coding wrapper until a neutral
provider-adaptation contract exists.

### Tool Contribution Resolver

`loushang.harness.tools.contribution` owns neutral tool contribution and
tool-pack resolution mechanics:

- `ToolContribution`
- `ToolPackDefinition`
- `ToolResolutionDiagnostic`
- `ToolResolutionResult`
- `ToolResolutionError`
- `resolve_tool_contributions`

The resolver supports deterministic ordering, transitive pack includes,
enable/disable filtering, duplicate tool or pack diagnostics, and missing
reference diagnostics. It preserves opaque `source_info` and metadata for
product adapters, but does not interpret task, expert, workflow, prompt,
connector, model, or UI semantics.

Coding remains responsible for concrete built-in tool registration, default
pack activation, user-facing labels, product-specific aliases, external tool
installation policy, and any migration from current coding registry paths.

Slice 1b may add a coding adapter verification path where
`loushang.coding.tools.ToolRegistry` projects its current registry state into
neutral `ToolContribution` records and calls the harness resolver. This path is
read-only: it must not change registration order, enable/disable state,
materialized runtime tools, built-in tool defaults, or prompt assembly.

Coding default tool-pack registration may also call the harness resolver after
coding has created product-owned `ToolContribution` and `ToolPackDefinition`
records. The pack names, built-in tool names, legacy order, factory options,
policy wiring, and default activation remain coding-owned; harness only resolves
the supplied neutral records.

Bootstrap-time coding extension tools may use the same resolver path. Coding
adapters project extension tool metadata into neutral `ToolContribution`
records, preserve opaque `source_info` for diagnostics, and register only the
extension contributions returned by the resolver. Concrete execution still
stays in coding through the existing extension runner and tool wrapper. Runtime
dynamic registration through extension callbacks remains coding-owned in Slice
1b; migrating that path requires a separate execution-context boundary because
it touches live session state and product runtime behavior.

## Presentation Boundary

### Harness Owns

`loushang.harness.presentation` owns neutral presentation records and renderer
mechanics:

- `ToolResultPresentation`
- ANSI stripping
- line-ending normalization
- generic text/image-like output extraction by duck typing
- generic line collapse helpers
- `ToolRenderContext`
- `ToolRenderResultOptions`
- `ToolDefinitionResolver`
- `ToolRenderRuntime` state, last-rendered, and invalidation mechanics

Harness presentation records should be neutral. They may describe text,
structured values, file references, or opaque artifact references, but they do
not decide terminal/web widgets or product transcript layout.

Renderer callbacks are optional and fail soft. `ToolRenderRuntime` returns
`None` when a resolver or renderer callback is unavailable or raises, and it
must not treat a failed render as the last rendered value. Product adapters may
log or trace renderer failures, but harness runtime does not own product
diagnostics or UI fallback wording.

### Coding Keeps

`loushang.coding.tools.presentation` and related modules keep coding-specific
projection and wording:

- `coding.tools.protocol` Pi-compatible detail projection
- artifact-path key conventions such as `fullOutputPath`
- `[Full output: ...]` labels
- truncation notice wording and size formatting policy
- `output_preview`
- `builtin_renderers`
- coding-specific collapsed preview limits
- command/path-oriented renderer text

The current builtin renderers know concrete coding tool names and argument
semantics, so they remain coding-owned.

Coding compatibility paths may re-export harness-owned presentation runtime
contracts such as `ToolRenderRuntime`, `ToolRenderContext`,
`ToolRenderResultOptions`, and `ToolDefinitionResolver`. Coding presentation
helpers remain product-owned because they project protocol details and produce
user-facing notices.

Render callback aliases (`ToolRenderCall`, `ToolRenderResult`, and
`ToolRenderOutput`) are tools-core contracts because they are fields on
`ToolDefinition`. They may reference presentation-owned context and options
types, but presentation runtime should avoid importing tools core at runtime by
using a small local protocol or type-checking-only imports.

## Compatibility Strategy

Slice 1 requires compatibility shims.

Existing public and internal imports from `loushang.coding` and
`loushang.coding.tools` must continue to work. Compatibility modules may
re-export or adapt harness-owned contracts while preserving current coding
behavior.

Required compatibility paths include:

- `loushang.coding.policy.approval`
- `loushang.coding.tools.types`
- `loushang.coding.tools.schema`
- `loushang.coding.tools.authoring`
- `loushang.coding.tools.wrapper`
- `loushang.coding.tools.registry`
- `loushang.coding.tools.rendering`
- `loushang.coding.tools.presentation`

Compatibility shims are temporary for internal imports but remain until the
public SDK surface decision is explicit. They can be deleted only when:

- in-repo imports have migrated to focused harness modules where appropriate;
- docs state that the old submodule path is not a supported SDK contract, or a
  replacement deprecation policy is accepted;
- focused compatibility tests are updated;
- downstream product, OEM, or extension users are not expected to import the old
  path.

Top-level `loushang.coding` and `loushang.coding.tools` exports remain stable
through Slice 1.

Compatibility lifecycle:

- internal-only shims should be deleted once all in-repo imports have moved to
  the focused harness owner module and no product adapter still needs the old
  submodule path;
- public SDK compatibility paths stay until a documented deprecation or
  long-term support decision is accepted for each path;
- Pi-style wrapper aliases stay in `loushang.coding.tools.wrapper` and must not
  be introduced as module-level aliases in neutral harness modules;
- harness-owned classes keep their harness `__module__`; coding compatibility
  shims preserve import paths, not class module identity;
- compatibility tests should cover both retained public paths and deleted
  neutral-surface aliases before any shim removal.

## External Reference: Hermes Agent

`~/workspace/hermes-agent` is useful as a boundary validation sample, not as a
template to copy.

Its tool registry demonstrates a contribution-record shape that is relevant to
`harness.tools.contribution`: tool name, schema, handler, toolset membership,
availability metadata, dynamic schema override hooks, registry snapshots, and a
generation counter. Slice 1 may borrow those mechanism concepts, but not the
Hermes implementation style. Hermes uses import-time singleton registration,
OpenAI-format tool definitions, plugin override policy, availability probing,
and JSON-string dispatch; those are product/runtime choices and remain outside
harness.

Hermes toolsets also validate that pack/include resolution is a shared
mechanism, while defaults remain product-owned. Harness defines neutral
tool-pack contribution and include resolution in `harness.tools.contribution`.
Coding still decides the default tool set, activation order, disabled platform
bundles, aliases, and user-facing names.

Hermes approval code reinforces that approval must be split instead of moved.
Its approval layer includes dangerous-command detection, YOLO/config handling,
context variables, gateway and CLI session behavior, plugin hooks, pending
queues, and smart approval through an auxiliary model. Those are adapter and
product policy concerns. Harness should keep only neutral request, decision,
resolver, and fail-closed mechanics. Product adapters map local approval
choices onto transport-specific wire decisions.

Hermes' rendering bridge is a useful presentation precedent: renderers are
optional and fail soft, allowing the UI surface to fall back when a Python-side
renderer is absent or fails. `harness.presentation` should follow that shape by
owning neutral records and renderer contracts while leaving terminal, TUI, web,
and transcript fallback behavior to product adapters.

Hermes' ANSI stripping helper is a good candidate reference for robust generic
text normalization. By contrast, Hermes schema sanitization for LLM backends,
tool output limits, write-approval pending stores, and terminal callback
plumbing are provider, store, runtime, or UI policies and should not enter
Slice 1 harness modules.

## Migration Sequence

### Step 1: Approval Split

Create `loushang.harness.approval` with neutral approval request/decision and
headless resolver contracts.

Update `loushang.coding.policy.approval` to use or re-export harness contracts
while retaining `PolicyEnforcementError` and `InteractiveApprovalResolver` in
coding.

Focused tests:

- `tests/coding/test_tool_policy_integration.py`
- `tests/coding/test_policy_engine.py`
- new harness approval tests
- `tests/architecture/test_import_boundaries.py`

### Step 2: Presentation Split

Create `loushang.harness.presentation` for neutral presentation records,
normalization helpers, and render runtime mechanics.

Keep coding protocol projection, artifact labels, truncation wording, and
builtin renderers in coding.

Focused tests:

- `tests/coding/test_tool_presentation.py`
- `tests/coding/test_tool_render_runtime.py`
- `tests/coding/test_tool_builtin_renderers.py`
- `tests/coding/test_tool_transcript_blocks.py`
- relevant session event and export rendering tests
- new harness presentation tests
- `tests/architecture/test_import_boundaries.py`

### Step 3: Tools Core Split

Create `loushang.harness.tools.core` for neutral tool definition, schema,
decorator metadata, registry mechanics, and agent-tool adaptation.

Create `loushang.harness.tools.contribution` for neutral contribution records,
tool-pack definitions, pack include resolution, enable/disable filtering, and
resolution diagnostics.

Keep decorated plain-return normalization, coding `ToolContext`, concrete tools,
tool factories, default tool packs, and public Pi-style aliases in coding.
Built-in coding tool registration and bootstrap-time extension tool
registration may use `harness.tools.contribution` as a neutral resolver, but
the supplied contributions, default pack choices, conflict policy, runner
binding, and concrete execution remain coding-owned.

Focused tests:

- `tests/coding/test_tool_schema.py`
- `tests/coding/test_tool_wrapper.py`
- `tests/coding/test_tool_authoring.py`
- `tests/coding/test_tool_registry.py`
- `tests/coding/test_tool_public_types.py`
- `tests/coding/test_prompt_assembly.py`
- extension tests that import `ToolDefinition`
- new harness tools-core tests
- new harness tool contribution tests
- `tests/architecture/test_import_boundaries.py`

### Step 4: Coding Compatibility Adapters

Preserve existing coding imports and behavior through thin shims or adapters.
Avoid a broad internal import rewrite until the harness owner modules are
tested and stable.

Focused tests:

- command catalog and command controller tests
- tool policy integration tests
- screen/surface focused tests for changed render paths
- SDK/public type tests

## Behavior Preservation

Coding behavior must remain unchanged:

- same default tool set and activation order;
- same concrete tool descriptions and argument schemas;
- same policy allow/deny/ask decisions;
- same approval audit details;
- same terminal/plain transcript rendering text;
- same command catalog and slash command behavior;
- same public imports from `loushang.coding` and `loushang.coding.tools`.

If a harness extraction requires changing any of those behaviors, it is out of
scope for Slice 1 unless separately accepted.

## Validation Matrix

Required validation before a Slice 1 implementation is considered ready:

- `uv run pytest tests/architecture/test_import_boundaries.py -q`
- focused coding tool tests for schema, wrapper, authoring, registry,
  presentation, render runtime, builtin renderers, and policy integration
- focused command catalog and session command controller tests
- focused screen/surface tests when render paths are touched
- harness-focused tests for each new owner module
- `uv run ruff check <changed files>`
- `git diff --check`

The architecture import-boundary test must show no harness import of
`loushang.coding`, `loushang.tui`, `loushang.work`, `loushang.method`, or
`loushang.ai`.

## Open Decisions

- Whether a later slice should introduce a neutral approval broker to replace
  the coding-owned interactive resolver.
- Whether prompt-related fields on `ToolDefinition` should remain named fields
  or move into a generic metadata mapping before non-coding products adopt the
  contract.
