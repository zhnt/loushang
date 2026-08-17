# Session RPC Operation Boundary

## Status

Status: implemented on `main`. The Coding RPC implementation and its former
`coding.mode` compatibility package are removed. Harness Host owns the Product
command wire, Harness Session owns standard session-operation semantics, and
Coding supplies Product runtime and projection bindings.

## Current Ownership

| Concern | Canonical owner | Product responsibility |
| --- | --- | --- |
| Strict JSON-line input, parse failure, and finite stdin lifecycle | `harness.host.jsonl_command_host` and `harness.host.rpc` | Supply the Product runtime and selected projections. |
| Explicit command routing and unknown-command fallback | `harness.host.rpc.routing` | None; the accepted legacy command vocabulary is implemented by the Harness RPC profile. |
| Strict response/error framing | `harness.host.rpc.output` and `harness.host.rpc.wire` | Supply domain values through typed or compatibility projection ports. |
| Background prompt/Bash task ownership and shutdown settlement | `harness.host.product_host.ProductHostTaskTracker` and RPC command groups | Product operations retain their own execution semantics. |
| Prompt, input, queue, lifecycle, identity, retry, and maintenance semantics | `harness.session.SessionOperationRuntime` | Bind the current Product session-control port and capability availability. |
| Standard RPC payload grammar | `harness.session.SessionRpcOperationBinding` | Preserve Product preflight and operation results. |
| Product event and diagnostic JSON | injected `RpcEventProjection` and `RpcDiagnosticsProjection` | Coding supplies the projection functions and vocabulary. |

The accepted wire remains the legacy Product RPC vocabulary for compatibility,
but its implementation owner is Harness. Coding does not retain a request
parser, response projector, mode facade, or compatibility import.

`harness.host` must not import Channel, Work, Coding, or a Product package.
`harness.session` may depend on stable Agent/AI value contracts where required,
but it does not depend on the RPC wire.

## Composition

```text
Product CLI composition
  -> RpcHost
     -> JsonlCommandHost
     -> JsonlCommandRouter
     -> Rpc command groups
        -> SessionRpcOperationBinding
        -> dynamically resolved SessionOperationRuntime
        -> current Product session
     -> Product event/diagnostic projections
```

The operation getter is intentionally dynamic. Session replacement, restore,
fork, and clone must resolve the new Session operation runtime rather than
retaining a control port captured at host construction.

The command groups are:

- `conversation`: prompt, steer, follow-up, abort, state, and prompt settlement;
- `session_lifecycle`: listing, create/restore/fork/clone, naming, and rebinding;
- `model_settings`: model, thinking, queue, tool, retry, and compaction settings;
- `transcript`: transcript queries and export;
- `command_catalog`: command inventory, completion, and direct execution through
  the current Product Session's admitted command dispatcher;
- `diagnostics`: diagnostic and error-report queries;
- `packages`: package inventory and lifecycle; and
- `bash_maintenance`: Bash execution and maintenance controls.

Each group may accept a narrow private Product protocol. It must not receive a
generic all-capabilities Session dictionary or add a second lifecycle engine.
Optional Product capability discovery is confined to private dynamic adapters
at the group boundary; handlers depend on semantic diagnostics, package, and
transcript protocols rather than performing reflection themselves. The host
uses the same pattern for session event subscription, extension-UI binding,
and tool-rendering context. These adapters resolve the current session on each
invocation or are rebuilt after lifecycle rebinding, so they do not capture a
stale Session.

`execute_command` accepts only a command name and string arguments. It invokes
the current Session's existing `execute_command_async` port and returns its
strict-JSON result; it does not interpret Product command names, invoke a model
turn, execute a shell command, or create a second command registry. Missing
commands and non-serializable results are explicit RPC errors.

## Prompt And Abort Semantics

`prompt` acknowledges only after Product preflight succeeds. The conversation
group owns its background task and the shared Product host tracker drains it
before transport teardown. `abort` acknowledges admission of the abort request;
the prompt task remains the settlement owner and waits for idle exactly once.

`SessionOperationRuntime.abort_turn()` does not clear queues or abort an active
command. Screen TUI composes those additional actions as one user intent;
remote and plain hosts may choose different visible behavior.

## Product RPC And Channel Are Separate

`harness.host.rpc` parses and frames Product command JSONL.
`channel.rpc_jsonl` encodes one `ChannelEnvelope` frame carrying a Work
operation, Work event, or runtime-event view. Channel correlation and
cancellation do not own Product RPC parsing, command routing, or prompt task
settlement.

The dependency direction is:

```text
Channel -> Work
Channel -> Harness
Harness -X-> Channel
Work ----X-> Channel
```

## Non-Goals

This boundary does not:

- replace the Product RPC vocabulary with Channel operation frames;
- define JSON as a Harness Session API;
- move Product model/provider policy, Work domain policy, or UI presentation
  into the RPC host;
- introduce AppService, a daemon, replay, or a second event bus; or
- extract a public protocol merely because the command table is large.

## Verification

- `harness.host.rpc.testing` provides structured, staged, and raw-line playback.
- Golden and concurrent Product tests preserve acknowledgement, abort,
  replacement/rebinding, package, Bash, extension UI, and projection behavior.
- The RPC package passes its focused type check.
- Architecture tests enforce that Harness imports neither Channel nor Work,
  Work does not import Channel, the retired Coding mode sources remain absent,
  and Product RPC framing is not delegated to Channel.
