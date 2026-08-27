# Loushang Coding Extension API v1 Design

## Status

Retired historical design. Current Extension ownership and authoring boundaries
are defined by the
[Harness Extension Runtime Core](../architecture/harness/extension-runtime-core-boundary.md),
[Extension Context Runtime](../architecture/harness/extension-context-runtime-boundary.md),
and [Plugin Architecture](../architecture/harness/plugin/architecture.md). The
remaining text is not a stable public API contract.

## Goal

Define the first stable `ExtensionAPI` for `loushang-coding` before writing extension examples.

The design target is:

- grow toward a large `pi`-style extension API
- keep `v1` small and runnable
- avoid binding examples to the current ad hoc object protocol

This design covers API shape, loader/runner split, hook contracts, compatibility, and example planning. It does not try to implement commands, UI widgets, or mode-specific extension surfaces.

## Why This Comes Before Examples

`loushang-coding` now has an extension-capable substrate:

- resource discovery
- filesystem-backed extension loading
- runner lifecycle
- resource contributions
- extension-contributed tools

But the current contract is still transitional:

- `build_extension()`
- `EXTENSION`
- direct object methods such as `session_start()` and `resources_discover()`

That is enough for internal progress, but not stable enough to teach as the long-term mental model.

If examples are written against the transitional object protocol, they will become migration debt. The API should be fixed first, then the examples should teach that API.

## Design Goal

The north star is a progressively expanding `pi`-style extension system:

- `ExtensionAPI`
- `ExtensionContext`
- `ExtensionLoader`
- `ExtensionRunner`
- clear load-time vs run-time responsibilities

`v1` should not be large and complete, but it should be structurally aligned with that target.

## Architecture

### Subsystem Split

The extension subsystem should be split into five explicit parts.

#### `DefaultResourceLoader`

Owns:

- discovering extension descriptors
- discovering prompts / skills / themes / `AGENTS.md`
- aggregating descriptors into `ResourceBundle`

Does not own:

- module loading
- session binding
- hook dispatch

#### `ExtensionLoader`

Owns:

- taking `ExtensionDescriptor` values and producing `LoadedExtension`
- module import / factory invocation
- converting registration calls into structured hook and tool registrations
- load-time diagnostics

Does not own:

- session lifecycle
- per-turn dispatch

#### `ExtensionAPI`

Owns:

- the author-facing registration surface used at extension load time

It exists so extension modules declare capabilities through a controlled API, instead of exposing arbitrary runtime objects.

#### `LoadedExtension`

Owns:

- the load-time result consumed by `ExtensionRunner`

It is the normalized representation of one extension after registration. It is not session-bound state.

#### `ExtensionRunner`

Owns:

- binding loaded extensions to a session/runtime
- dispatching lifecycle, resource, and tool hooks
- aggregating hook results
- run-time diagnostics

Does not own:

- extension discovery
- final session internals

#### `ExtensionContext`

Owns:

- the controlled runtime capability surface available to hook execution

It should expose a stable, restricted API rather than internal mutable objects.

### Lifecycle Split

The extension lifecycle should be explicitly separated into:

#### Load Time

1. `DefaultResourceLoader` discovers `ExtensionDescriptor`
2. `ExtensionLoader` creates `ExtensionAPI`
3. extension module calls `register(api)`
4. `ExtensionLoader` emits `LoadedExtension`

#### Bind Time

1. `ExtensionRunner` receives `LoadedExtension[]`
2. `ExtensionRunner` binds them to an `AgentSession`

#### Run Time

1. `ExtensionRunner` dispatches hooks
2. each hook receives `(event, ctx)`
3. hook results are aggregated or pipelined according to event type

This split matches the `pi` direction and avoids conflating declaration objects with runtime-bound extensions.

## Extension Module Contract

### Standard Export

The standard `v1` extension module entrypoint should be:

```python
def register(api: ExtensionAPI) -> None:
    ...
```

This is the recommended and documented contract.

### Compatibility Exports

`v1` should keep compatibility with the current transitional contracts:

- `build_extension()`
- `EXTENSION`

But these should be treated as compatibility inputs only. They should not remain the recommended shape in examples or primary docs.

### Compatibility Strategy

Compatibility exports should be normalized by `ExtensionLoader` into `LoadedExtension`.

That means:

- the standard runner input becomes `LoadedExtension[]`
- old object-method exports are adapted into hook registrations
- example authors are taught `register(api)` instead of legacy object protocols

## Extension API v1

### Registration Surface

`ExtensionAPI v1` should support:

- `api.on(event_name, handler)`
- `api.register_tool(tool_definition)`

This is enough to establish:

- lifecycle hooks
- resource hooks
- tool contribution
- tool interception

### Supported Events

`v1` should define these event names:

- `session_start`
- `before_agent_start`
- `session_shutdown`
- `resources_discover`
- `tool_call`
- `tool_result`

This is the smallest useful set that already covers the current architecture goals.

### Handler Signature

All handlers should use one consistent signature:

```python
def handler(event, ctx):
    return None
```

The important contract is:

- handlers receive `(event, ctx)`
- `event` is event-specific data
- `ctx` is `ExtensionContext`
- handlers return `None` or an event-specific result object

This keeps the mental model stable as the API grows.

## Event Semantics

### `session_start`

Role:

- observe or initialize extension-local state at session bind/start

Return:

- `None`

### `before_agent_start`

Role:

- the last extension-controlled point before the session starts the agent for a turn

Return:

- `BeforeAgentStartResult | None`

Recommended initial shape:

- `system_prompt_append`
- `extra_messages`
- `diagnostics`
- `block`
- `reason`

### `session_shutdown`

Role:

- observe shutdown and release extension-local resources

Return:

- `None`

### `resources_discover`

Role:

- contribute additional descriptors into the loader-discovered resource plane

Return:

- `ExtensionResourceContribution | None`

### `tool_call`

Role:

- inspect, block, or rewrite a pending tool call

Return:

- `ToolCallDecision | None`

Recommended initial shape:

- `block`
- `reason`
- `tool_name`
- `arguments`
- `diagnostics`

### `tool_result`

Role:

- inspect or rewrite a tool result before it returns to the agent/session flow

Return:

- `ToolResultDecision | None`

Recommended initial shape:

- `result`
- `diagnostics`

## Execution Rules

`v1` should make execution order and hook behavior explicit.

### Ordering

- hooks execute in extension load order

### Aggregation

- `resources_discover` is aggregating
- contributed descriptors are merged into the current `ResourceBundle`

### Pipeline

- `tool_call` is a pipeline
- each hook sees the latest rewritten `tool_name` and `arguments`
- `block=True` stops real tool execution

- `tool_result` is also a pipeline
- each hook sees the latest rewritten result

### Failure Isolation

Hook failures should degrade to diagnostics by default.

They should not crash the whole session unless a later explicit policy says otherwise.

## Extension Context v1

`ExtensionContext v1` should stay deliberately small.

### Expose

- `cwd`
- `resource_bundle`
- `session_manager` read-only view
- `model_registry`
- `active_tool_names`
- `get_system_prompt()`
- `get_model_selection()`

### Do Not Expose Yet

- arbitrary mutable access to `session_manager`
- direct mutation of `agent.state`
- commands
- UI dialogs
- widgets / overlays
- editor integration
- keybindings
- session switching / tree navigation / fork

The core rule is:

- extensions may observe, contribute, and intercept through controlled entry points
- extensions may not directly mutate core internals

## Data Objects

### `LoadedExtension`

`LoadedExtension` should carry at least:

- `name`
- `source_path`
- `entry_path`
- `hooks`
- `tool_definitions`
- `diagnostics`

It may later grow:

- `commands`
- `message_renderers`
- `flags`
- `shortcuts`
- `ui registrations`

### Hook Result Objects

`v1` should introduce explicit result objects instead of ad hoc dicts:

- `BeforeAgentStartResult`
- `ToolCallDecision`
- `ToolResultDecision`

This keeps the API extensible and testable.

## Compatibility Migration

### Recommended Public Contract

Examples and docs should treat this as the standard:

- `register(api)`

### Transitional Compatibility

Support:

- `build_extension()`
- `EXTENSION`

### Loader Behavior

`ExtensionLoader` should:

1. prefer `register(api)`
2. otherwise adapt `build_extension()`
3. otherwise adapt `EXTENSION`
4. otherwise emit load diagnostics

### Legacy Adaptation

The legacy adapter should map object methods into hook registration:

- `session_start`
- `before_agent_start`
- `session_shutdown`
- `resources_discover`
- `get_tools()`

This preserves compatibility while converging all runtime behavior onto `LoadedExtension`.

## Example Strategy

Examples should follow the stable API, not the transitional object protocol.

### Example Layout

- `examples/coding/`
  - main SDK path examples
- `examples/coding/extensions/`
  - extension-focused examples

### Main Path Additions

- `11_settings_and_loader.py`
- `12_runtime_session_replace.py`
- `13_extensions_basic.py`

### Extension Examples First Batch

- `01_lifecycle.py`
- `02_dynamic_resources.py`
- `03_custom_tool.py`
- `04_tool_guard.py`

### Design-Only Samples

At most one or two target-style sketches may exist, but runnable examples should dominate.

## Non-Goals For v1

This design intentionally does not include:

- slash commands
- UI context
- widgets / overlays
- message renderers
- editor components
- session tree actions
- fully general session mutation API

Those belong to later extension API versions.

## Success Criteria

This design is successful when:

- `ExtensionLoader` exists as an explicit service boundary
- `register(api)` becomes the recommended extension contract
- `LoadedExtension` becomes the normalized runner input
- `tool_call` and `tool_result` are part of `v1`
- examples can be written against `ExtensionAPI v1` instead of legacy object methods
