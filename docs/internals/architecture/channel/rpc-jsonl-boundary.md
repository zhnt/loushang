# Channel RPC JSONL Boundary

## Decision

`loushang.channel.rpc_jsonl` is the reusable JSONL frame adapter.
`loushang.channel.host` owns the injected stdio host loop over those frames.
Neither surface reuses or wraps `loushang.coding.mode.RpcMode`.

The protocol has six frame kinds:

| Frame | Direction | Meaning |
| --- | --- | --- |
| `operation_request` | client to host | One `ChannelEnvelope(kind="operation")` and a client `request_id`. |
| `operation_accepted` | host to client | The host accepted the request. It contains the request, operation, and optional run id. |
| `event` | host to client | One `ChannelEnvelope(kind="event")`, optionally correlated to the source request. |
| `operation_cancel_request` | client to host | Request cancellation of one accepted operation. |
| `operation_cancelled` | host to client | Cancellation was accepted; completion remains an event fact. |
| `error` | either direction | A transport or acceptance failure, never a replacement for a `WorkEvent`. |

`operation_accepted` is deliberately only an ACK. Completion, cancellation,
failure, progress, and artifact facts remain `WorkEvent` messages.

## Ownership

Channel owns:

- JSONL frame encoding and exactly-one-frame decoding;
- request/event/error envelope validation;
- request correlation fields; and
- strict JSON transport projection for documented transport values.
- an injected stdio host loop that routes only standard Channel frames.

For Product-owned legacy JSONL command schemas, Channel also offers the
separate `JsonlCommandHost` input runtime and `RemoteUiContext` interaction
helper. Neither is a standard Channel frame or response contract; their
Product adapter owns dispatch and output projection.

Work owns operation, run, event, delivery-hint, and domain semantics. Products
own the conversion from their input into a `WorkOperation`, operation dispatch,
event projection, host policy, and rendering. Coding keeps its legacy RPC
command table, Coding event schema, and extension UI widget vocabulary.

The adapter may depend on `loushang.work` and `loushang.foundation.json` only.
It must not import AI, Agent, Harness, Coding, Method, or TUI runtime packages.

## Evolution

Frame decoders tolerate unknown additive fields. New frame kinds are rejected
until this adapter explicitly supports them. This preserves the existing Channel
rule: unknown Work kinds and payload fields may pass through, but the transport
frame grammar remains explicit.

No cross-process exactly-once delivery, replay, subscription persistence,
capability negotiation, or interaction/UI protocol is claimed by this batch.
