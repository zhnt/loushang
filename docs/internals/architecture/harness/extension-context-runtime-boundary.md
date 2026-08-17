# Harness Extension Context Runtime Boundary

## Status

Status: implementation complete for integration into `lane/harness`.

`loushang.harness.extensions.context` owns the standard extension context
contract and extension-session lifecycle records. The concrete bound/unbound
context implementation continues to use Harness runtime binding leases; it is
not a Coding session object.

## Harness Ownership

Harness owns:

- `ExtensionContext`, `ExtensionCommandContext`, and
  `ReplacedSessionContext` capability protocols;
- `ExtensionUiContext`, with portable snake_case notification, state, editor,
  and dialog operations;
- neutral extension session start, shutdown, refresh, switch, fork,
  compaction, and tree event records plus generic decision records;
- the opaque `ExtensionRuntimeBindings` capability record and the existing
  Harness generation lease, bind, refresh, and invalidation mechanics;
- safe unbound defaults and stale-context failures for bound contexts.

The contracts carry opaque model, command, transcript, and context values.
Harness does not select models, resolve credentials, interpret a Product's
summary type, own UI rendering state, or call an AI provider.

## Coding Adapter

Coding imports the common context contracts and session lifecycle events from
`loushang.harness.extensions.context`. The legacy `coding.extensions.types`
module is removed; Coding does not define a parallel context protocol,
lifecycle record family, or runtime-binding subclass.

Coding retains:

- `ExtensionAPI` additions for Coding messages, model/thinking policy, labels,
  and provider registration;
- model registry and authentication resolution;
- Coding command descriptors, code-tool semantics, permission defaults, and
  Agent tool-call result adaptation;
- compaction and branch-summary content/prompt decisions;
- RPC, terminal, HTML, and TUI presentation projection.

## UI Naming Contract

The extension UI API is snake_case only:

```python
context.ui.set_status("phase", "running")
context.ui.set_title("Review")
context.ui.set_editor_text("next task")
choice = await context.ui.select("Target", ["local", "remote"])
```

Pi-style aliases such as `setStatus`, `setWidget`, `setTitle`,
`setEditorText`, `getEditorText`, `onTerminalInput`, theme setters, working
indicator setters, footer/header/component setters, and tool-expansion setters
are removed from the protocol, Harness bound/unbound context, and Coding RPC
wrapper. They are not compatibility APIs.

This does not change the JSONL wire schema. A channel may continue to emit
wire fields such as `method: "setStatus"`; that is transport projection, not a
Python extension method name.

## Dependency Direction

```text
Coding extension/session adapters
  -> harness.extensions.context
  -> harness.runtime binding leases
  -> Harness resources, tools, and channel ports
```

`harness.extensions.context` does not import Coding, an AI provider, Agent
runtime, Channel implementation, or UI implementation. Products inject their
capabilities through `ExtensionRuntimeBindings` and interpret opaque values at
their own boundary.

## Validation

The migration verifies that:

- Coding re-exports have identity with the Harness context contracts;
- a product-shaped binding can execute standard context methods and stale
  leases fail after invalidation;
- remote UI dialog correlation and JSONL projection remain intact;
- Pi-style UI methods are absent from both bound contexts and RPC contexts;
- focused Coding, Harness, Channel, and architecture import-boundary tests
  remain green.
