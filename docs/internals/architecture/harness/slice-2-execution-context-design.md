# Harness Slice 2 Execution Context Design

## Status

Slice 2A status: implementation complete for `lane/harness`.
Slice 2B status: eligible under the neutrality evidence gate; not yet
implemented.

This document defines the Slice 2 boundary for neutral execution context and
runtime contribution registration. Slice 2A implements runtime tool
contribution adapter verification without changing product behavior. No
neutral execution context API is introduced by Slice 2A; that contract remains
subject to the neutrality evidence gate defined in
[Refactoring Principles](refactoring-principles.md).

## Goal

Slice 2 should define a neutral execution context shape that lets product
adapters expose live runtime capabilities to tools and extensions without
moving product runtime state into `loushang.harness`.

The immediate pressure comes from runtime dynamic extension registration:

```text
ExtensionAPI._register_runtime_tool
-> ExtensionRuntimeBindings.register_tool
-> AgentSession._register_extension_runtime_tool
-> ToolController.register_runtime_tool
```

That path currently touches coding session state, active tool activation,
source information, prompt rebuild, runtime bindings, and extension execution.
Harness can define the neutral mechanism for describing runtime contributions,
but product execution adapter code must still own product behavior.

## Non-Goals

Slice 2 does not migrate:

- concrete coding tools
- command handlers or slash semantics
- prompt templates or prompt/resource semantics
- TUI controller/render loop or screen surface state
- coding session store
- AI provider/model/auth
- agent loop or tool-call orchestration
- work/method/channel implementations
- extension provider/model/session APIs
- connector authorization or product skill semantics

## Proposed Boundary

Harness should introduce a neutral execution context boundary only if it remains
product-agnostic.

Candidate harness-owned concepts:

- neutral execution context records carrying opaque ids, cwd, cancellation
  signal, metadata, and optional event sink
- neutral contribution registration requests for tools, renderers, or later
  capability kinds
- resolver integration through `harness.tools.contribution`
- source and diagnostic passthrough as opaque values
- product callback protocols that are typed by capability, not by coding
  session concepts

Product-owned concepts:

- product execution adapter
- active tool activation policy
- prompt rebuild behavior
- session state mutation
- extension runner lifecycle
- concrete execution, file, process, and model APIs
- UI diagnostics, status, footer data, and message append behavior
- coding-specific `ToolContext` and runtime binding fields

Product-owned behavior remains product-owned. Harness must not interpret
whether a runtime contribution should become active, how prompts are rebuilt,
or how a session records diagnostics.

## Current Coding Mapping

`loushang.harness.tools.authoring.ToolContext` is the restricted,
Product-neutral tool-time context. It currently contains:

- `tool_call_id`
- `cwd`
- diagnostics service
- signal
- model
- event sink

The context shape is Harness-owned, while each live value is supplied by the
Product/session adapter. Diagnostics, model, event, and execution services are
optional scoped ports rather than Product-global state. Their concrete
interpretation stays adapter-owned unless a separate neutral
diagnostics or model-reference contract is accepted.

`ExtensionRuntimeBindings.register_tool` is a product runtime callback. It
currently accepts a tool object and source info, then delegates into the live
session. Harness should not own this callback directly. Instead, coding can
adapt the callback into a neutral contribution registration request and then
apply product policy to resolver output.

`ToolController.register_runtime_tool` is coding-owned because it mutates live
registry state, checks allowed tool names, activates tools, and rebuilds prompt
and tool views. Harness may provide resolver mechanics, but this method remains
the product execution adapter for coding.

## Runtime Dynamic Extension Registration

Runtime dynamic extension registration should become a two-step product adapter
flow:

1. Project the extension tool into a neutral contribution.
2. Resolve contributions with existing registry state through
   `harness.tools.contribution`.
3. Let coding decide whether to register, reject, diagnose, activate, or defer
   the contribution.
4. Let coding update active tools and prompt views.

This keeps startup-time and runtime extension registration aligned without
moving concrete execution into harness.

The first implementation slice was adapter verification only:

- project runtime extension tools to `ToolContribution`
- include source info and metadata as opaque values
- call the resolver with existing registry contributions
- preserve existing conflict behavior and active-tool behavior
- keep `ToolController.register_runtime_tool` as the mutation point

No concrete tool execution should move in this slice.

## Slice 2A Closure

Slice 2A implements the runtime extension tool adapter described above:

- coding normalizes the runtime tool to a neutral `ToolDefinition`;
- coding projects that definition, source info, and opaque runtime metadata to
  a `ToolContribution`;
- `ToolController.register_runtime_tool` calls
  `harness.tools.contribution.resolve_tool_contributions` with current registry
  contributions plus the runtime contribution;
- coding registers resolver-selected runtime output when available and falls
  back to the projected runtime contribution when existing duplicate
  contributions win neutral first-match resolution;
- allowed-tool filtering, active-tool policy, prompt rebuilds, and registry
  mutation remain in coding.

The resolver diagnostics are advisory inputs to coding policy. Startup
extension registration may translate duplicate diagnostics into product
resource diagnostics and reject a conflicting extension tool. Runtime
registration deliberately preserves its previous replacement semantics, so
runtime duplicate overwrite behavior remains coding-owned.

Slice 2A does not add `loushang.harness.execution.context` or
`loushang.harness.execution.contribution`. It proves the existing focused
`ToolContribution` boundary before any broader runtime contribution envelope or
execution context is accepted.

## Proposed Slice 2B Modules

If Slice 2B proceeds after satisfying the neutrality evidence gate, use focused
modules under existing harness package boundaries:

- `loushang.harness.execution.context`
- `loushang.harness.execution.contribution`

Do not add new top-level packages such as `loushang.workspace`,
`loushang.context`, `loushang.memory`, `loushang.session`, `loushang.product`,
or `loushang.runtime`.

Do not export Slice 2 types from top-level `loushang.harness.__all__` unless a
separate public API decision accepts that surface.

## Error And Diagnostic Boundary

Harness diagnostics should stay neutral:

- duplicate contribution
- missing reference
- unsupported contribution kind
- invalid neutral request shape

Coding diagnostics stay product-owned:

- extension tool conflict messages
- startup/resource loading phases
- session ids
- UI status
- prompt rebuild or active-tool policy explanations

Harness may carry `source_info` and metadata but must not interpret extension
manifest semantics or product resource policy.

## Validation Strategy

Implementation slices that follow this design should validate:

- `tests/architecture/test_import_boundaries.py`
- new harness execution/context tests
- coding runtime extension registration focused tests
- `tests/coding/test_extension_runner.py`
- `tests/coding/test_extension_api.py`
- `tests/coding/test_bootstrap.py -k 'extension_tool or extension'`
- `tests/coding/test_tool_registry.py`
- command catalog and session command controller tests if active tool behavior
  is touched
- screen/surface tests if prompt/tool view state is touched
- `uv --cache-dir .uv-cache run --extra dev ruff check <changed files>`
- `git diff --check`

The architecture import-boundary test must continue proving that harness does
not import `loushang.coding`, `loushang.tui`, `loushang.work`,
`loushang.method`, or `loushang.ai`.

## Deferred Implementation Items

Deferred implementation items include:

- defining final names and exact dataclass/protocol shapes
- defining an independent contract probe that validates a neutral execution
  context without Coding runtime objects or vocabulary
- deciding whether runtime registration supports only tools first or a generic
  contribution-kind envelope
- deciding compatibility shim lifetime for any execution context aliases
- deciding how source diagnostics map from neutral resolver diagnostics to
  coding resource diagnostics

## Implemented First Slice: 2A

Runtime extension tool registration adapter verification is implemented as
Slice 2A.

The code slice does not introduce broad context APIs. It extracts the common
contribution projection/resolution path for runtime extension tools, proves
behavior is unchanged, and documents what remains product-owned.

Slice 2B must not begin by copying context types from Coding. It must first
define the mechanism/policy boundary, preserve a Coding adapter, and exercise
the proposed shape through an independent contract probe such as a minimal
reference adapter or product-neutral fixture. This permits anticipatory
extraction without turning current Coding fields into a generic runtime API.
