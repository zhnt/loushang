# Product Host Runtime Boundary

## Decision

`loushang.harness.host.product_host` owns the reusable lifecycle mechanics for an
injected Product-facing host. It provides three independent mechanisms:

- `ProductHostAction` and `ProductHostAdapter` for start, stop, input,
  event-rendering, idle waiting, session rebinding, state reads, and disposal;
- `ProductHostRuntime` for asynchronous, line-oriented input until EOF, stop,
  or one terminal handler failure; and
- `ProductHostTaskTracker` for draining Product-started background tasks during
  orderly host shutdown;
- `ProductHostStreams` and `dispose_product_host(...)` for process stdio
  binding and explicit Product-selected shutdown fallback.

These mechanisms do not define a client wire schema. `ChannelHost` continues
to own the standard Channel JSONL operation protocol; a Product's legacy RPC
or terminal host may use the lower-level runtime without becoming a Channel
operation protocol implementation.

```text
stdin
  -> ProductHostRuntime
  -> Product adapter input handler
  -> Product session / work runtime

Product tasks
  -> ProductHostTaskTracker
  -> orderly host shutdown
```

## Product Binding

A Product supplies:

- input parsing and the output/error representation;
- a state reader for its own Product state projection;
- session binding, operation admission, prompt/model/tool behavior, and
  cancellation policy; and
- all Product command names, argument validation, and response payloads.

The runtime supplies neither an Agent session protocol nor a generic command
registry. A Product that needs Agent controls binds its own `SessionControlPort`
or equivalent outside this package.

## Coding Adoption

Coding preserves `ModeAction`, `ModeAdapter`, and `dispatch_mode_action` as
compatibility names. Their generic lifecycle semantics delegate to
`harness.host.product_host`; Coding retains `ModeConfig`, mode selection, Print
mode construction, work-specific options, and its `ModeState` projection.

Coding CLI resolves injected or process stdio through `ProductHostStreams` and
uses `dispose_product_host(runtime, session)` for the generic shutdown fallback.
Its `--mode`, `--tui`, `--render-tool-events`, and command flags remain Coding
grammar: Channel deliberately supplies no universal CLI parser.

`ChannelHost` uses `ProductHostRuntime` for standard Channel JSONL input.
`RpcMode` uses the same input runtime and task tracker, but remains the owner
of Pi command names, JSON responses, extension UI, model/tool/Bash/package
commands, Coding event projection, and rendered-tool payloads. Its private
background-task drain hook remains as a thin compatibility forwarder.

## Dependency Rule

`harness.host.product_host` may depend only on the Python standard library and
its sibling stdout guard. It must not import Work, Channel, Agent, AI, Coding,
Method, or TUI packages.

The runtime must not acquire sockets, HTTP, WebSockets, authentication,
capability negotiation, persistent subscriptions, replay/outbox storage,
session creation, model selection, UI dialogs, or a universal RPC command
schema.

## Verification

- Harness Host tests use an independent fake Product adapter to verify
  lifecycle action dispatch, line stopping, terminal failure handling, and
  task draining.
- Channel JSONL host tests prove the standard operation protocol still runs
  through the common input lifecycle.
- Coding RPC, Print mode, and Channel adapter regressions preserve existing
  commands, Pi projection, and background task behavior.
- Architecture tests prohibit Product, Channel, Work, or model-runtime imports
  from the runtime and
  require both ChannelHost and RpcMode to adopt it.
