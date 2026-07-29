# JSONL Command Host Boundary

## Decision

`loushang.harness.host.jsonl_command_host` owns the reusable input half of a
line-oriented JSON command host. It reads input, rejects invalid JSON and
non-finite values, validates a JSON-object command with an optional string
`id` and a required string `type`, and dispatches a `JsonlCommand` to an
injected Product port.

It deliberately owns no command vocabulary, response schema, event schema,
operation lifecycle, or output stream. The Product receives a structured
`JsonlCommandHostError` and chooses how that error appears on its own public
wire surface.

```text
stdin JSONL
  -> JsonlCommandHost
  -> JsonlCommandPort             Product adapter
  -> Product runtime/session

Product response/event projection
  -> Product output writer
  -> stdout JSONL
```

The standard `ChannelHost` remains the host for `ChannelOperationRequest` and
`ChannelEventDelivery` frames. `JsonlCommandHost` is not a second standard
Channel protocol: it is the reusable command-input runtime for products that
have a separately versioned JSONL surface.

## Contract

`JsonlCommandHost` provides:

- injected `TextIO` input, including thread offload for file-descriptor
  streams;
- exactly one JSON object per nonblank input line;
- strict JSON validation, including rejection of `NaN` and infinities;
- a stable `JsonlCommand(command_id, command_type, payload)` object;
- explicit parse, validation, and Product-dispatch error reasons; and
- graceful stop after the current command completes.

The optional `command_name` changes diagnostics only. It lets a Product retain
an existing public validation path such as `rpc_command.timeoutSeconds`; it
does not create a product-specific Channel protocol.

The Product port owns command dispatch. An unsupported command is not a host
error: the Product projects it with its established response schema. A Product
handler exception becomes a `handler_failure` observation, but its response
and process-exit policy remain Product-owned.

## Remote UI Context

`loushang.harness.host.remote_ui.RemoteUiContext` owns remote-dialog request IDs,
response resolution, timeout defaults, and a small state snapshot for
headless hosts. It accepts an injected mapping emitter and does not define a
Channel frame, extension manifest, widget vocabulary, or client UI protocol.

Products decide the emitted message type and any additional presentation
methods. This keeps a generic remote interaction mechanism reusable by Coding,
Research, Design, PPT, OEMs, and trusted plugins without freezing Coding's
legacy widget or extension API as a Channel contract.

## Coding Adoption

`coding.mode.RpcMode` is now a Product adapter over `JsonlCommandHost`:

- Coding retains its legacy command table, session/runtime calls, model and
  package semantics, event selection, rendered-tool enrichment, and response
  fields;
- Coding maps host errors back to its existing `response` JSON shape;
- Coding's `RpcExtensionUIContext` wraps `RemoteUiContext` and translates the
  generic emitted request into the existing `extension_ui_request` wire type;
- Coding-only extension errors and the remaining legacy UI aliases stay in the
  wrapper, making their eventual API retirement local and explicit.

No legacy RPC client needs to change for this extraction. New products should
prefer the standard `ChannelHost` when their public operations fit
`WorkOperation`; they may use `JsonlCommandHost` only when they intentionally
own a distinct, versioned command schema.

## Dependencies and Exclusions

The Harness Host helpers may depend on `loushang.protocol` and the Python
standard library. They must not import AI, Agent runtime, Channel, Coding,
Method, Work, TUI, or a Product extension package.

This boundary does not add a common RPC response envelope, command registry,
Work-operation mapping, sockets, HTTP/WebSocket transport, durable delivery,
cross-process exactly-once guarantees, capability negotiation, or a universal
UI widget protocol.

## Verification

- Harness Host tests cover valid command dispatch, strict JSON failures, handler
  failures, stop behavior, UI state, dialog response, and timeout behavior.
- Coding RPC regressions assert unchanged parse errors, strict-JSON field
  paths, legacy responses, extension UI request/response behavior, and event
  projection.
