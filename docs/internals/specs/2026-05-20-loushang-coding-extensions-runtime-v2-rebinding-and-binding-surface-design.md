# Loushang Coding Extensions Runtime V2 Rebinding And Binding Surface Design

## Status

Retired historical design. Current Extension generation, binding, and disposal
are governed by the
[Extension And Resource Generation Lifecycle](../architecture/harness/extension-generation-lifecycle-boundary.md),
[Extension Runtime Core](../architecture/harness/extension-runtime-core-boundary.md),
and [Plugin Architecture](../architecture/harness/plugin/architecture.md). The
remaining proposal does not override those boundaries.

## Goal

Promote `loushang-coding`'s extension runtime from a small hook dispatcher into a reload-aware, session-bound runtime surface that is structurally aligned with `pi`.

This design should:

- add a real extension binding lifecycle owned by `session`
- distinguish `hard rebind` from `soft refresh`
- define a richer runtime binding surface for extensions
- keep `ExtensionAPI` definition-first
- align with `pi`'s extension runtime semantics without importing its full command/UI surface yet

## Scope

### In Scope

- runtime rebinding owned by `AgentSession`
- binding application to `ExtensionRunner`
- `hard rebind` lifecycle
- `soft refresh` lifecycle
- richer runtime bindings:
  - `cwd`
  - diagnostics sink
  - shutdown hook
  - session action callbacks
  - resource refresh request
  - active tool query
  - model selection query
- a lightweight `session_refresh` extension event
- explicit alignment with `pi`'s runtime binding model

### Out Of Scope

- command registration surface
- keyboard shortcuts
- CLI flags
- UI context
- message renderers
- plugin/package management
- methodology runtime
- a large new event family beyond what is needed for rebinding

## Why This Comes Next

`loushang-coding` now has:

- a stable `ExtensionAPI v1`
- extension loading
- extension-contributed tools
- resource contribution hooks
- session/tool lifecycle hooks
- stronger `session`, `tools`, and `resource loader` substrates

The remaining gap is no longer "can extensions run at all?" The gap is that extensions still do not have a robust runtime binding lifecycle.

Compared with `pi`, the current extension runtime is still missing:

- a true `bindExtensions(...)`-style lifecycle
- explicit rebinding on `new / resume / fork / reload`
- runtime-bound context values instead of a mostly fixed context shell
- an explicit distinction between:
  - rebuilding extension runtime bindings
  - refreshing runtime state

This design closes that gap first, before expanding to commands/UI/plugin surfaces.

## Pi Alignment

Relevant `pi` references:

- [agent-session.ts](/home/dev/workspace/pi-mono/packages/coding-agent/src/core/agent-session.ts:2024)
- [agent-session-runtime.ts](/home/dev/workspace/pi-mono/packages/coding-agent/src/core/agent-session-runtime.ts:143)
- [extensions/types.ts](/home/dev/workspace/pi-mono/packages/coding-agent/src/core/extensions/types.ts:994)
- [extensions/runner.ts](/home/dev/workspace/pi-mono/packages/coding-agent/src/core/extensions/runner.ts:525)

The target alignment is:

- `session` owns extension binding lifecycle
- extensions receive runtime-bound context instead of raw session internals
- `new / resume / fork / reload` cause a rebinding lifecycle
- runtime state changes can refresh extension-visible state without rebuilding the whole runner

This is semantic alignment, not full surface parity.

### Intentionally Aligned With `pi`

- session-driven extension binding lifecycle
- runtime-bound extension context
- reload-aware extension resource discovery
- explicit rebinding entrypoints
- separation between load-time extension registration and run-time extension binding

### Intentionally Simpler Than `pi`

- no command surface yet
- no UI bindings yet
- no shortcut/flag/message-renderer APIs yet
- no attempt to land the entire `pi` event catalog in this phase

## Architecture

### Current Split To Preserve

The current load-time split remains correct:

- `DefaultResourceLoader`
  - discovers extension descriptors
- `ExtensionLoader`
  - turns descriptors into `LoadedExtension`
- `ExtensionAPI`
  - captures author-facing registrations
- `ExtensionRunner`
  - dispatches run-time hooks

This design does not collapse those boundaries.

### New Runtime Split

`v2` adds a clearer runtime split:

- `AgentSession`
  - owns extension runtime lifecycle
  - decides when to hard rebind or soft refresh
- `ExtensionRunner`
  - owns current runtime bindings
  - exposes binding application/refresh operations
- `ExtensionContext`
  - becomes a runtime-bound capability surface, not just a thin event helper

## Binding Lifecycle

### Hard Rebind

`hard rebind` should happen when the session/runtime identity is meaningfully rebuilt:

- `new`
- `resume`
- `fork`
- explicit `reload`

`hard rebind` means:

1. build a new binding object from current session/runtime state
2. apply bindings to `ExtensionRunner`
3. emit `session_start`
4. if extensions contribute resources, run `resources_discover`
5. rebuild any session/resource state that depends on the extended resource set

This is the closest `loushang` equivalent to `pi`'s `bindExtensions(...)` plus runtime recreation flow.

### Soft Refresh

`soft refresh` should happen when extension-visible session state changes, but the runtime itself should not be rebuilt:

- active tools changed
- model selection changed

`soft refresh` means:

- update binding state visible through `ExtensionContext`
- do not rebuild `ExtensionRunner`
- do not emit `session_start`
- optionally emit a lightweight refresh event

## New Event

### `session_refresh`

Add one lightweight extension event:

- `session_refresh`

Role:

- notify extensions that runtime-visible state changed
- accompany soft refresh
- provide a stable seam for extensions that want to recompute local derived state

It should not mean:

- new session
- reload
- extension re-registration

It should not replace:

- `session_start`

## Runtime Binding Surface

### Goal

Extensions should be able to query and influence the active runtime through a controlled surface, without being handed raw mutable `AgentSession` internals.

### V2 Binding Fields

`v2` should bind the following runtime capabilities:

- `cwd`
- diagnostics sink
- shutdown hook
- session action callbacks
- resource refresh request
- active tool query
- model selection query

### Recommended Shape

The binding object should conceptually contain:

- environment bindings
- query bindings
- action bindings
- lifecycle bindings

Recommended conceptual split:

- environment
  - `cwd`
- queries
  - `get_active_tool_names()`
  - `get_model_selection()`
- actions
  - `set_active_tools(...)`
  - `set_model(...)`
  - `request_resource_refresh()`
  - `shutdown()`
- diagnostics
  - `record_diagnostic(...)`

The actual Python type may differ, but the surface should be stable and explicit.

## Session Actions

### Two-Layer Model

Internally, `loushang` may use a generic action dispatcher.

But extensions should see explicit named actions, not an untyped "send any action" bag.

That means:

- internal layer
  - generic dispatch is allowed
- public extension layer
  - explicit callbacks are preferred

### Initial Explicit Actions

`v2` should expose:

- `set_active_tools(...)`
- `set_model(...)`
- `request_resource_refresh()`
- `shutdown()`

This is enough to make extension runtime bindings materially more capable, without becoming a second command framework.

## Resource Refresh Trigger

### Rule

Extensions may request a resource refresh.

But they should not directly control the full reload lifecycle.

That means:

- extension can request refresh
- `session` decides whether and how to execute it
- full hard reload remains session/runtime-owned

This preserves control-plane ownership and avoids letting extensions directly drive runtime teardown/recreation.

## ExtensionContext V2

### Direction

`ExtensionContext` should become a runtime-bound context, not just a static helper wrapper created once with limited fields.

The important rule is:

- context values should resolve against current session/runtime state

This mirrors `pi`'s runner behavior, where context-accessors read current bound state instead of stale copies.

### Boundary

`ExtensionContext` should still not expose raw mutable session internals directly.

It should expose:

- queries
- explicit actions
- stable runtime metadata

It should not expose:

- unrestricted direct mutation of internal session data structures
- store internals
- arbitrary runtime objects

## Runner Surface

### New Responsibilities

`ExtensionRunner` should gain an explicit runtime binding surface.

Recommended operations:

- `bind_runtime(bindings)`
- `refresh_runtime(state)`

Semantics:

- `bind_runtime(...)`
  - used during hard rebind
  - replaces runtime-bound state
- `refresh_runtime(...)`
  - used during soft refresh
  - updates current runtime state without rebuilding the runner

### Existing Hook Surface To Preserve

Current supported events remain:

- `session_start`
- `before_agent_start`
- `session_shutdown`
- `resources_discover`
- `context`
- `tool_call`
- `tool_result`

`v2` adds:

- `session_refresh`

No other event expansion is required in this phase.

## Session Responsibilities

`AgentSession` should formally own:

- constructing extension runtime bindings
- performing hard rebind
- performing soft refresh
- deciding when resource refresh is allowed and how it is executed
- coordinating `session_start` versus `session_refresh`

This is the key `pi` alignment move.

The extension runner should not independently decide rebinding policy.

## Diagnostics

### Runtime Binding Failures

Binding and refresh failures should feed the existing diagnostics pipeline.

Expected categories include:

- failed bind application
- failed refresh event
- failed session action callback
- failed resource refresh request

This should extend the current diagnostics approach rather than inventing a parallel reporting system.

## Reload Semantics

### Hard Reload Path

An explicit reload should:

1. refresh or rebuild resources as session/runtime requires
2. rebuild extension runtime bindings
3. emit `session_start` with reload semantics
4. re-run extension resource discovery if applicable

### Soft Refresh Path

A model/tool-state refresh should:

1. update current binding state
2. emit `session_refresh`
3. avoid runner reconstruction
4. avoid repeating `session_start`

This is the central distinction that `v2` needs.

## Future Compatibility

This design intentionally prepares for later work:

- command surface
- UI bindings
- richer session actions
- methodology-aware extension runtime
- plugin-delivered extensions

It does so by stabilizing the lifecycle seam first, not by pre-building all those higher layers now.

## Recommended File-Level Shape

This phase should likely touch:

```text
src/loushang/coding/extensions/
  api.py
  runner.py
  types.py

src/loushang/coding/session/
  agent_session.py
```

Potential additions:

- richer runtime binding dataclasses/types
- explicit refresh event/result types

No new top-level subsystem is required.

## Implementation Phasing

### Phase 1

- add runtime binding data model
- add `ExtensionRunner.bind_runtime(...)`
- add `ExtensionRunner.refresh_runtime(...)`
- add `session_refresh`
- wire `AgentSession` hard rebind and soft refresh paths
- add diagnostics for bind/refresh failures

### Phase 2

- extend action/query surface if needed
- add richer resource refresh semantics
- prepare command/UI binding expansion

## Summary

`extensions/runtime v2` should not try to become all of `pi`'s extension system at once.

It should do the more important thing first:

- make extension runtime bindings real
- make rebinding session-owned
- distinguish hard rebind from soft refresh
- expose a richer but still controlled runtime binding surface

That is the most direct way to align `loushang-coding` with `pi`'s extension runtime architecture without over-expanding scope.
