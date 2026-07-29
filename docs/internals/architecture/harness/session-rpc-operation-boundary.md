# Session RPC Operation Cutover Boundary

## Status

Status: implemented on `lane/harness`. The generic Host command-routing slice
and standard operation cutover are complete: Harness Host owns command input
and routing, Harness Session owns the standard operation binding, and Coding
remains the public protocol adapter.

## Problem

`coding.mode.rpc_mode.RpcMode` is the legacy Coding JSONL protocol adapter.
It still combines four different responsibilities:

1. strict JSONL input dispatch and unsupported-command handling;
2. scheduling and draining background prompt and bash tasks;
3. invocation and request grammar for standard session controls such as
   prompt, steer, abort, lifecycle replacement, retry, and compaction; and
4. Coding-specific RPC request aliases, camelCase responses, model/auth,
   package, bash, extension UI, event views, and session-state projection.

The third responsibility already has one canonical owner:
`harness.session.SessionOperationRuntime`. This wave must not create a second
RPC-shaped session executor merely to move code out of Coding.

## Ownership

| Concern | Canonical owner | Product responsibility |
| --- | --- | --- |
| Strict JSON line parsing and one-command dispatch | `harness.host.jsonl_command_host.JsonlCommandHost` | Bind an RPC schema and response projection. |
| Explicit command route registration and unknown-command fallback | `harness.host.jsonl_command_router.JsonlCommandRouter` | Register Product handlers and preserve Product error text. |
| Background task tracking and host lifecycle | `harness.host.product_host.ProductHostTaskTracker` / `ProductHostRuntime` | Choose which Product operations run in the background. |
| Typed prompt, input, queue, lifecycle, identity, retry, and maintenance operations | `harness.session.SessionOperationRuntime` | Bind a session control port and choose capability availability. |
| RPC payload grammar and lifecycle rebinding for standard operations | `harness.session.SessionRpcOperationBinding` | Select exposed commands and project operation results. |
| Coding JSON field aliases and camelCase success/error frames | `coding.mode.rpc_mode` | Preserve the public Coding RPC contract. |
| Model/auth, package, bash, extension UI, event rendering, and state projection | `coding` | Retain domain policy and presentation. |

`harness.host` may depend on `protocol` and other lower Harness contracts, but
it must not import Channel, Work, Coding, or a Product protocol schema.
`harness.session` may depend on stable Agent/AI value contracts where required.

## Target Composition

```text
JsonlCommandHost
  -> Harness Host command router
     -> Coding RPC request parser and response projector
        -> SessionRpcOperationBinding
           -> SessionOperationRuntime
           -> bound Product session_control

     -> Coding-only model/auth/package/bash/extension handlers
```

The router is intentionally only a command-to-handler registry. It does not
define request fields, output frames, error wording, a session state schema, or
the lifecycle of an Agent session.

## Admitted Standard Operations

The cutover group is limited to operations already represented by
`SessionOperationRuntime`:

```text
prompt, steer, follow_up, abort
new_session, switch_session, fork, clone
compact, set_auto_retry, abort_retry, set_auto_compaction
```

`prompt` continues to acknowledge after Product preflight and run in the
background. The Channel task tracker owns task lifetime; Coding supplies the
legacy acknowledgement/error projection. Lifecycle replacement is rebound by
the Harness binding before Coding projects the result. Session naming remains
an existing direct Harness operation call because it has no distinct RPC
payload grammar in this slice.

The following remain Coding-owned in this wave:

- `set_model`, model discovery/cycling, and thinking policy;
- package source lifecycle and Coding package records;
- bash execution and Coding shell output;
- extension UI, legacy event aliases, tool rendering, and session-state JSON;
- session listing/index queries and Coding transcript presentation;
- Coding RPC command names, snake/camel input aliases, and response text.

## Delivery Slices

1. **Channel routing contract**
   - Add an immutable explicit JSONL command router under `harness.host`.
     Complete.
   - It receives `JsonlCommand`, dispatches only registered handlers, and
     delegates unsupported-command output to an injected Product callback.
   - `RpcMode` binds every current command through an explicit route table;
     reflection is no longer part of its dispatch path.
   - Add a fake Product test with no Coding, Channel, or Work import.

2. **Standard session-operation adapter**
   - Bind the admitted operation group through
     `SessionRpcOperationBinding` and the existing `SessionOperationRuntime`.
   - Keep response projection injected so the binding has no Coding wire
     fields, response envelopes, or Channel imports.
   - Lock prompt acknowledgement timing, lifecycle rebinding, capability
     availability, and command routing precedence.

3. **Coding cutover and deletion**
   - Replace `RpcMode` standard-operation parsing and calls with the Channel
     Harness Host router and Harness Session binding.
   - Delete duplicated standard input/lifecycle/maintenance parsing while
     retaining Coding response frames and product handlers.
   - Retain the Coding-only handlers listed above and add an import boundary
     proving Channel and Harness do not import Coding.

## Non-Goals

This wave does not:

- replace the existing Coding JSONL RPC protocol with the separate standard
  Channel operation-frame protocol;
- define a universal RPC payload union or make JSON a Harness session API;
- move model/auth, package, bash, extension UI, or Coding event contracts;
- change prompt preflight acknowledgement timing, session replacement behavior,
  or the supported Coding RPC method names.

## Completion Gate

- Channel routing tests cover duplicate route rejection, unknown-command
  fallback, synchronous and asynchronous handlers, and no Product imports.
- A fake session-control port executes every admitted operation without Coding
  types or JSON fields.
- Existing Coding RPC tests preserve prompt acknowledgement timing, steer and
  follow-up images, abort, lifecycle rebinding, naming, retry, and compaction
  results.
- `channel` has no Harness/Coding import; `harness.session` has no Channel or
  Coding import.
- `SessionRpcOperationBinding` has no JSONL, response, or Product imports, and
  `RpcMode` delegates standard lifecycle/input/maintenance payloads to it.
- `RpcMode` no longer uses reflection dispatch for registered routes, and its
  remaining handlers are explicitly Product-owned.
