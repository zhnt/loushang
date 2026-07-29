# Loushang Channel Architecture

## Scope

`loushang.channel` owns boundary protocol primitives for clients, hosts, SDKs,
RPC surfaces, and future WebUI/AppUI adapters.

The implementation defines endpoint and envelope types that carry
`loushang.work.WorkOperation`, `loushang.work.WorkEvent`, and a projected
`loushang.harness.events.RuntimeEventView` across a boundary, plus a
deliberately narrow JSONL framing adapter for headless clients.

## Current Package Surface

Current code package:

```text
src/loushang/channel/
  __init__.py
  adapters/
    runtime_events.py
    session_work.py
  host.py
  json_codec.py
  rpc_jsonl.py
  types.py
```

Current public types:

- `ChannelEndpoint`
- `ChannelEnvelope`
- `ChannelEnvelopeKind`
- `ChannelPayload`

Current public codec helpers:

- `channel_envelope_to_json`
- `channel_envelope_from_json`

The `rpc_jsonl` surface provides:

- `ChannelOperationRequest` for a correlated operation submission;
- `ChannelOperationAccepted` for a minimal accepted ACK;
- `ChannelEventDelivery` for a correlated `WorkEvent` or `RuntimeEventView`
  delivery;
- `ChannelError` for transport or acceptance failure;
- strict `encode_rpc_jsonl_frame` / `decode_rpc_jsonl_frame` helpers that own
  one-frame JSONL encoding only.

Reusable Product-host lifecycle, strict JSON projection, Product-owned JSONL
command input, stdout protection, and remote UI correlation live in
`loushang.harness.host`. Channel uses those lower-level mechanics where needed
but does not own or re-export them.

`ChannelEnvelope` accepts two envelope kinds and three payload families:

- `kind="operation"` with a `WorkOperation`
- `kind="event"` with a `WorkEvent` or `RuntimeEventView`

`WorkEvent` remains the normalized work/audit event contract. A
`RuntimeEventView` is a Product-selected, transport-safe view of a transient
Host/Session fact. It preserves the source event id, stream, sequence,
timestamp, and source references, while carrying only an event type, view
name, delivery hint, correlation id, and strict JSON payload.

The two event families intentionally remain distinct. Work event JSON keeps
its current wire shape. Runtime views use `event_family: "runtime"` inside the
event payload, so decoders can reconstruct the view without interpreting it as
a Work event. This is additive to existing Work channels.

`json_codec.py` converts envelopes to and from JSON-compatible Python dicts.
`rpc_jsonl.py` maps those envelopes onto one JSONL frame at a time. It has no
socket, HTTP server, or Product command table. `host.py` supplies the standard
stdio JSONL loop over an injected `ChannelHostPort`: a Product port accepts a
`WorkOperation`, emits the accepted ACK, and later delivers `WorkEvent` or
`RuntimeEventView` frames. `request_id` supplies transport correlation while
`operation_id` and `run_id` retain Work ownership. See
[Channel Host Boundary](channel-host-boundary.md).

`adapters/session_work.py` owns the Work-to-Channel operation binding, so Work
does not import its transport. `adapters/runtime_events.py` owns the optional
Harness runtime-view projection. Neither adapter is imported by the Channel
package root.

[Product Host Runtime Boundary](../harness/product-host-runtime-boundary.md)
records the lower-level host lifecycle shared by standard Channel and
Product-specific hosts. [JSONL Command Host Boundary](../harness/jsonl-command-host-boundary.md)
records the separate Product-owned command input runtime.

## Ownership

`loushang.channel` depends on `loushang.work` because the channel boundary
carries work operations and work events. It depends downward on selected
Harness Host mechanics and event-view contracts. The optional runtime-event
adapter may consume Harness session projection functions; Harness never
imports Channel, and Work never imports Channel.

The package direction is:

```text
Channel -> Work -> Harness
Channel --------> Harness
```

`loushang.channel` must not depend on:

- `loushang.agent`
- `loushang.ai`
- `loushang.coding`
- `loushang.method`
- `loushang.tui`

Product packages remain responsible for turning domain-specific input into
`WorkOperation` objects, projecting `RuntimeEvent` into `RuntimeEventView`, and
projecting Work events into product or UI state.

## Not In Scope

The current channel package does not implement:

- HTTP, WebSocket, or in-process transport loops
- operation dispatch or a WorkRun state machine
- capability negotiation
- replay or audit storage
- UI layout, widgets, rendering, or a universal UI wire protocol
- direct agent loop or product session control
- a universal Product RPC command schema

Capability negotiation and interaction request/response contracts remain
future work. They must remain independent of legacy Coding RPC widget and
editor payloads.
