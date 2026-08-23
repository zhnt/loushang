# Session RPC Operations Boundary

## Decision

`loushang.harness.session.operations` owns typed, reusable capability-grouped
operations over an already-bound `SessionControlPort`. It is a capability runtime, not an RPC
protocol. A Product decides which capability groups to bind and maps its own
transport requests, response schema, error wording, and task lifecycle to the
runtime.

The standard groups are:

- input: prompt, steer, and follow-up submission;
- queue: pending message reads and queue clearing;
- lifecycle: continue, abort, and idle waiting;
- identity: session id/name reads and display-name update;
- retry: retry inspection, abort, and waiting;
- maintenance: auto-retry/compaction settings and compaction control.

`SessionPromptRequest` is a typed application request. It does not contain a
JSON command name, a correlation id, Pi aliases, or a response envelope.
`SessionOperationAvailability` is explicit: an unbound group fails with
`SessionOperationUnavailableError`, rather than relying on an optional method
or an implementation-specific `getattr` check. Within the input group,
`SessionInputCapabilities` separately declares steer and follow-up delivery.
The standard Session guarantees both; restricted bindings may expose either
action, and `SessionOperationRuntime` enforces the declaration before invoking
the control port. Queue modes such as `all` and `one-at-a-time` remain
delivery-drain policy and do not select a UI submit action.

`SessionOperationResolver` carries the immutable input declaration as binding
metadata. Adapters may inspect it without resolving an active Session; calling
the resolver remains reserved for actual session operations.

## Ownership

Harness owns operation grouping, typed input values, dispatch through
`SessionControlPort`, and capability admission. It does not own:

- JSONL parsing or response/error framing;
- host background-task tracking or request correlation;
- model/auth selection, bash execution, package lifecycle, extension UI, or
  Product command catalogs;
- product state, event, diagnostic, or HTML projection.

Channel remains a separate Work/runtime-view boundary and accepts injected
operation ports. It may depend on selected Harness Host/event-view contracts,
but Harness and Work never import Channel. `harness.host.rpc` maps the accepted
Product RPC vocabulary onto this runtime. Coding supplies its concrete Product
session plus event and diagnostic projections; it does not retain another RPC
mapping layer.

## Verification

- Harness tests use an independent `SessionControlPort` fake to exercise each
  standard group and unavailable-capability behavior.
- Channel tests preserve their distinct envelope/frame contract and one-way
  dependency on selected Harness contracts.
- Coding RPC regressions preserve existing wire responses through the Harness
  RPC host and public playback API.
