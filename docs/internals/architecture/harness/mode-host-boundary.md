# Mode Host Boundary

## Status

Implemented on `lane/harness` by the mode host collapse wave.

## Ownership

The former `coding.mode` implementation and compatibility package are removed.
Coding's CLI/UI composition binds the shared hosts directly. The implementation
is split by responsibility:

| Capability | Canonical owner | Product binding |
| --- | --- | --- |
| mode lifecycle actions and state-reader contract | `harness.host.mode` | Product host factory |
| JSONL input validation, routing, task draining and response lifecycle | `harness.host.rpc` + `harness.host.jsonl_command_host` | RPC event/diagnostic projection |
| plain and JSON output loop, session state observation and tool-line rendering | `harnesstui.conversation.plain_mode` | Work execution binding and event projection |
| operation grammar, prompt/queue/lifecycle/model/diagnostic handlers | `harness.session` and `harness.host.rpc` | Product ports and protocol profile |
| Channel Work/runtime-view framing, correlation, cancellation and delivery | `loushang.channel` | Product operation port |
| Work operation facts and Coding domain mapping | `loushang.work` / `loushang.coding` | Coding domain binding |

The shared RPC host receives `RpcEventProjection` and
`RpcDiagnosticsProjection` ports. It does not import Coding or decide a
Product's event names, diagnostic wire fields, or Work domain. The shared
plain host receives equivalent event and Work ports.

There are two independent JSONL vocabularies. `harness.host.rpc` owns the
Product command wire and its line-oriented host. `channel.rpc_jsonl` owns
single-frame encoding for `ChannelEnvelope` values carrying Work operations,
Work events, or runtime-event views. Channel does not parse or frame Product
RPC commands.

`loushang.harness.host.rpc.testing` is the canonical test driver for this
wire. `play_rpc_wire(...)` covers finite golden traces; `RpcWirePlayback`
supports staged dispatch, snapshots, and final task settlement for concurrent
prompt/abort/bash scenarios. `play_rpc_lines(...)` preserves raw stdin
fragments for parser and framing regressions. Product-specific fake sessions
and expected payloads remain in Product tests rather than entering the Harness
package.

## Abort and settlement

An RPC `abort` response acknowledges that the turn-abort request was accepted;
it does not claim that the turn is already idle. The prompt task remains the
single settlement owner and performs exactly one idle wait. RPC host shutdown
drains tracked prompt/bash tasks before transport teardown.

The screen TUI keeps its established composite intent: abort the active turn,
clear queued input, and abort the active command. The presented action host
then waits for idle exactly once. `SessionOperationRuntime.abort_turn()` itself
does not clear queues, cancel commands, or wait, so other hosts can compose
their own visible behavior without inheriting TUI policy.

## Coding surface after cutover

Coding keeps only:

- the Coding Work profile and `domain="coding"` Method/Work binding;
- Coding event-view and diagnostics JSON projections;
- Product CLI/runtime factories and projection callbacks;
- Product UI application, surfaces, renderer, and wording.

There is no `RpcMode` or `PrintMode` Product adapter. Tests may use those names
as local aliases for `harness.host.rpc.RpcHost` and
`harnesstui.conversation.AgentPlainHost`; no production compatibility surface
is implied.

## Protocol rule

The shared contracts use the current snake_case session/runtime API. No Pi SDK
aliases or Pi-specific command projection are part of this boundary. A
Product may expose a separate versioned wire profile, but that profile must
remain outside the shared host implementation.

## Verification

The existing Coding RPC, plain-host, Channel, and JSON projection behavior
tests remain the regression suite. RPC golden and concurrency playback uses
the Harness testing API. Architecture tests verify the current top-level
dependency direction, the absence of retired Coding mode/policy sources, and
the independence of Product RPC and Channel framing.
