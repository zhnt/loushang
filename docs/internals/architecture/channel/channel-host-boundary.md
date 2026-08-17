# Channel Host Boundary

## Decision

`loushang.channel.host` owns the reusable JSONL host loop for the standard
Channel protocol. It reads one standard frame at a time, delegates operation
acceptance and cancellation to an injected Product port, correlates accepted
operations with later event deliveries, and writes strict JSONL frames.

The host is a transport coordinator. It does not create sessions, interpret an
operation kind, project runtime facts, select a model, or import a Product,
Harness runtime, Agent, or AI package.

```text
stdin JSONL
  -> ChannelHost
  -> ChannelHostPort             Product adapter
  -> operation/session runtime

Product event projection
  -> ChannelHostPort delivery
  -> ChannelHost
  -> stdout JSONL
```

## Standard Frames

The existing operation request, operation accepted, event, and error frames
remain unchanged. This boundary adds two explicit cancellation frames:

- `operation_cancel_request`: client request id plus the accepted operation id
  to cancel;
- `operation_cancelled`: acknowledgement that cancellation was accepted. A
  terminal Work or Runtime event remains the source of completion truth.

An accepted request is correlated to later events by `WorkEvent.operation_id`.
For a `RuntimeEventView`, a Product sets `correlation_id` to the operation id
when it wants the transport to correlate that observation to a request.

## Port Contract

`ChannelHostPort` supplies three Product-owned behaviors:

- accept one `ChannelOperationRequest` and return either the matching
  `ChannelOperationAccepted` or a `ChannelError`;
- accept one standard cancellation request and return either the matching
  cancellation acknowledgement or a `ChannelError`;
- subscribe a listener to already-projected `ChannelEventDelivery` or
  `ChannelError` values.

The Product owns admission, operation execution, run lifecycle, event
projection, retry policy, cancellation semantics, and all domain errors. The
host validates returned correlation fields and turns malformed input or port
contract violations into transport errors.

## Coding Adoption

Coding supplies a narrow `SubmitCodingTurn` port. It accepts a standard
`WorkOperation(domain="coding", kind="SubmitCodingTurn")`, validates the
Coding turn payload, invokes the Coding session, and projects selected runtime
events into `RuntimeEventView` values. It does not make the legacy Coding RPC
command vocabulary part of Channel.

`--mode rpc` remains a compatibility surface. `--mode channel` is the standard
Channel JSONL entrypoint for new clients. Legacy extension UI requests,
Pi-specific commands, model payloads, and rendered-tool schema stay owned by
Coding until a separately versioned API retirement.

## Exclusions

This boundary does not add sockets, HTTP, WebSockets, persistent
subscriptions, outbox/replay, authentication, capability negotiation, a
standardized UI-dialog or widget wire protocol, or cross-process exactly-once
delivery. `RemoteUiContext` may be used by a Product as an injected interaction
helper, but its emitted mappings are not standard Channel frames.
