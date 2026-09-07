# Foreground Stdio Hosted App G14

[Architecture](../README.md) · [AppServer](README.md) ·
[G13 continuity](../apphost/durable-hosted-application-continuity-g13.md)

## Status

- ID: `FOREGROUND-STDIO-HOSTED-APP-G14`
- Scope: AppServer connection / optional AppHost foreground edge / Product entrypoint
- Parent: Loushang application architecture
- Authority: accepted delivery design
- Design status: accepted following the three-view design review below
- Implementation status: partial — connection kernel/client implemented; Product composition and delivery pending
- Activation status: target explicit foreground stdio command only
- Tracking: [issue #564](https://github.com/zhnt/loushang/issues/564)

## Outcome, Facts And Delta

G14 makes the existing hosted application usable across a real process
boundary. An installed, explicitly selected Coding command constructs real
Coding Sessions and a G13 recoverable application. A transport AppClient can
drive the existing Harnesstui Hosted Mux controller without importing Coding
or AppService. Closing this foreground connection stops its application.

Current facts: G11 supplies strict JSON values, AppClient, in-process
AppService and the Hosted Mux controller. G12 owns explicit Product admission
and ordered application settlement. G13 persists desired mux/member state,
resumes canonical Sessions and releases its writer lease last. None currently
opens a transport or installs a hosted application command.

Target delta: framing, negotiation, concurrent request correlation, bounded
transport ownership, executable Product composition and subprocess evidence.
This is not a daemon, reconnectable listener, background launcher, automatic
restart or a default-owner migration. A later reconnect profile must make its
own disconnect, authentication and mutation-deduplication decisions.

## System Context And Responsibility

```text
client process                         foreground application process
Harnesstui Hosted Mux                   explicit Coding composition root
  -> AppClientV1                         -> canonical Coding Session factory
  -> StdioAppClientV1                    -> G13 recoverable AppHost application
  -> framed inherited pipes <-------->  -> AppServerConnectionV1
                                           -> injected AppClientV1
                                           -> AppService -> Product Session
```

`->` denotes a dependency, not ownership transfer. The outer launcher owns
the child process, pipe endpoints and exit status. AppServer accepts injected
byte IO and semantic ports; it neither spawns a process nor constructs an
AppService. The optional AppHost edge orders connection and application
shutdown. Only the outer Product command resolves trusted filesystem/config
inputs. Application records never select executable code or an entrypoint.

The inherited pipe pair is the authority boundary: possession is granted by
the parent. G14 has no network listener and makes no remote-user
authentication claim. All messages are still untrusted bounded input.

## Component Identification And Allocation

| Candidate function | Decision / final owner | Excluded responsibility |
| --- | --- | --- |
| Wire values, validation, result variants | keep in AppServer protocol | Session implementation, IO |
| Framing, negotiation, request IDs, dispatch limits | one AppServer connection subsystem | mux policy, recovery, process supervision |
| Async streams and inherited stdio byte transfer | AppServer transport adapters | semantic dispatch, filesystem discovery |
| Connection-before-application settlement | optional AppHost foreground edge | protocol schema, Product construction |
| Settings, exact storage scopes, real Session projection and approvals | Coding outer composition and binding | generic server policy, duplicate Session store |
| Hosted actions and presentation | existing Harnesstui mux subsystem using AppClient | Product imports, application/process ownership |

No new top-level package is needed. Hosting remains a reusable OS mechanism
for a future launcher; this foreground entrypoint does not acquire service or
daemon semantics merely by using stdio. Split byte transport from dispatch
because a future socket adapter must not rewrite the semantic client.

## Dependency Contract

```text
appserver.connection -> appserver.client + appserver.protocol + stdlib
appserver.stdio -> appserver.connection byte ports + stdlib
appserver.remote_client -> appserver.client + protocol + byte ports
apphost foreground edge -> appserver.connection + apphost.application/continuity
Coding foreground command -> Coding bindings + optional AppHost edge + exact-root store
Harnesstui Hosted Mux -> appserver.client + protocol

AppServer -/-> AppService / AppHost / Hosting / Harness / Coding / UI
AppHost core -/-> transport / Product / UI
AppService -/-> AppHost / transport / Product / UI
Hosting -/-> application semantics
```

Existing A0.4 structural ports, embedded Coding/TUI entrypoints, G12 and G13
library activation contracts remain unchanged. New imports are exact optional
edge additions, not exemptions for their entire parent packages.

## Connection Contract

### Wire and negotiation

Each frame has a four-byte unsigned big-endian byte length followed by one
UTF-8 JSON object. The payload is nonempty and at most 1 MiB. Reject zero or
oversized lengths before allocating/reading their body; reject truncated
headers/bodies, invalid UTF-8, duplicate keys, non-finite numbers, excessive
nesting, unknown fields/operations and incompatible versions. Encoding obeys
the same limit. No line splitting, permissive JSON-RPC extension or pickle.

The server sends a versioned `foreground-stdio/v1` ready hello only after G13
recovery and Product composition complete. The client validates it and sends
the exact matching hello before requests. This negotiates the connection
profile as well as the existing `loushang.app/v1` semantic version. Hello has
a finite deadline. It is not a health promise for subsequent operations.

Existing typed requests/responses remain the semantic algebra. Add the
explicit `attachment/read_events` request and bounded event-batch result to
complete the transport-neutral AppClient surface. Polling may return fewer
than the requested limit, including zero. No unsolicited event stream or
second transport mailbox is introduced in G14; AppService remains the owner
of attachment lag and snapshot-required semantics.

### Concurrency, ordering and bounds

Requests carry decimal positive IDs, strictly increasing within a connection
and bounded to 63 bits. Responses may arrive out of order and echo exactly
one admitted ID. Repeated/decreasing IDs are protocol faults, not retries.
The client allocates the ID and writes its frame in one serialization region.
This keeps duplicate protection constant-space.

At most 16 ordinary operations run concurrently; four additional control
slots are reserved for interrupt, interaction response, detach and event
poll. Exhaustion returns a safe unavailable failure without invoking a
semantic operation. Long-running prompt completion must not block control
admission. Admission counters include response writes. No unbounded task,
pending-future or output queue is permitted.

One write serialization owner prevents interleaved frames. Finite write and
settlement deadlines include waiting for that owner, so a peer that stops
reading cannot keep an application alive indefinitely. A connection fault
closes admission and wakes every pending client call with a redacted error.
Unexpected application exceptions become safe unavailable failures; raw
exception text, paths, credentials and stack traces never enter protocol
stdout. Cancellation is not automatically retried. A lost response means an
unknown mutation outcome, not evidence of rollback.

Cancelling one client await does not silently cancel a remote mutation. Its
bounded pending slot remains until the matching response or connection close.
Interrupt is an explicit semantic operation. Snapshot/event batches that
cannot fit the wire limit fail closed; they are never silently truncated and
acknowledged as complete. Transcript projection must bound its public view.

## Foreground Lifecycle

```text
construct explicit owner -> acquire G13 lease -> admit current Product
  -> recover canonical Sessions -> publish complete application
  -> server ready -> peer hello -> concurrent interaction
  -> EOF / protocol fault / write failure / explicit close
  -> fence connection admission -> cancel and settle connection work
  -> G12 service/AppHost/Product settlement -> release G13 lease last
  -> close owned IO -> process exit status
```

EOF is terminal in this profile, including EOF during a prompt. Detaching a
mux is not EOF and does not stop an application. No attachment, in-flight
request, approval or event cursor is persisted. Shutdown failure produces a
nonzero process outcome; it must not claim that cleanup or durable mutation
completed. Ownership is published before any recovery/IO effect and retained
on partial startup failure. Cleanup is bounded and observes every spawned
task. Native blocking stdio adapters must not put uncancellable reads in
asyncio's default executor, whose shutdown could prevent process exit.

The inherited-stdio adapter is an explicit, single-use process-lifetime
claim. It borrows standard descriptors from the foreground command and uses
at most two daemon IO workers, each with a single-job queue. Close fences new
IO and wakes async waiters; an already-blocked native syscall is released by
peer closure or process exit. It does not claim that a parked worker has been
joined. The subprocess exit gate is therefore part of ownership evidence,
not an optional transport smoke test. Reusable client pipes use the separate
asyncio stream adapter and remain owned/reaped by their outer launcher.

The real parent closes child stdin to request graceful shutdown, drains
stdout/stderr, waits a bounded interval and may terminate its own child on
timeout. AppServer itself has no terminate/kill authority. Stdout belongs
exclusively to protocol bytes; diagnostics/help use stderr or run before IO
activation. Windows binary mode must preserve exact bytes.

## Coding And Harnesstui Integration

The new explicit installed foreground command is a distinct route; existing
`loushang`, `loushang-tui`, SDK and embedded behavior stay the default.
Configuration includes a trusted workspace, exact application continuity
root/key and Product-owned cwd/user-home canonical Session scope bindings.
Client scope fingerprints and Session IDs are selectors, not paths or
authorization grants. They must match admitted scope facts; mismatch fails
closed. Recovery calls the same canonical resume path as normal opening.

The production binding creates a real Coding AgentSession from the claimed
canonical Session candidate, maps public RuntimeEvents/snapshots to bounded
client values, owns the approval request/response correlation, and closes the
Session through its existing lifecycle. G13 records do not replace its
transcript or replay active work. Model, tool and credential choices remain
Product settings, never arbitrary remote factory/module names.

Tests inject only model responses and explicitly safe tool behavior at the
trusted composition seam. A scripted test model is not the installed product
implementation. An installed-entrypoint smoke test and a real subprocess
Session test are both required; a fake service echo alone is insufficient.

Harnesstui's existing Hosted Mux profile receives the transport AppClient.
It does not spawn the server or read Product state. Prove snapshot, streamed
projection, interaction response and interrupt through that same controller,
not a second UI-specific wire API.

## Requirements And Evidence Plan

| ID | Acceptance evidence |
| --- | --- |
| `G14-WIRE` | fragmented/coalesced frames, all typed methods, invalid input, size/depth limits and handshake mismatch |
| `G14-CORRELATION` | out-of-order replies, strict IDs, cancelled waiter, unexpected result, EOF wakes all pending calls |
| `G14-CONTROL` | blocked prompt + interrupt/approval/poll, saturated ordinary slots with reserved control admission |
| `G14-BACKPRESSURE` | non-reading peer, bounded writes/tasks, redacted failures, no stderr-to-stdout leakage |
| `G14-OWNERSHIP` | startup failure, EOF mid-turn, shutdown debt, pipe closure and child reap with bounded deadlines |
| `G14-PRODUCT` | installed command help/startup plus real Coding Session and Harnesstui remote-controller interaction |
| `G14-RECOVERY` | fresh child restores stable mux/member/session IDs and canonical transcript; fresh attachments; stale authority rejected |
| `G14-PLATFORMS` | Linux/macOS/Windows native subprocess gates without platform skips; actual remote run links before claiming delivery |
| `G14-BOUNDARIES` | AST import gates and installed-route inventory; embedded/default and G13 continuity ownership retained |

Delivery order: design/inventory/gates; protocol/connection with deterministic
regressions; transport client; actual Product/foreground composition; native
subprocess integration; three-view code review and fixes; final delivery.
Baseline `make check-appservice`: 134 passed before G14 edits.

## Three-View Design Review

This is a three-perspective design review, not a claim of independent agents.

1. Architecture/authority: direct AppServer construction of AppService would
   create a forbidden reverse dependency. Resolved by injected AppClient and
   an optional AppHost lifecycle edge. Scope/path discovery and real Product
   factory stay in the outer Coding composition. No new default route.
2. Lifecycle/concurrency: serial request handling would deadlock interrupt
   behind a prompt; a single shared capacity could starve control. Resolved
   by bounded concurrent dispatch, separate reserved control capacity, one
   bounded writer and explicit EOF settlement. Default-executor stdin reads
   are prohibited because cancellation cannot unblock their native read.
3. Contract/evidence: the existing wire contract lacks `read_events`, large
   snapshots can exceed a byte limit despite field limits, and a fake child
   does not prove a usable product. Resolved by a typed polling extension,
   symmetric frame limits/fail-closed output and separate installed/real
   Product/Harnesstui/restart evidence on all three native platforms.

The design is accepted for implementation with these resolutions. Passing
design review does not certify code correctness or cross-platform readiness;
implementation findings and native results must be recorded at delivery.

## Connection Implementation Review (Partial Delivery)

- Architecture: moved shared negotiation/capacity/ID policy into a pure
  protocol profile, so the remote client does not import server dispatch.
  AST gates enforce sibling-only dependencies and exhaustive typed dispatch.
- Lifecycle: distinguish clean boundary EOF from truncated frames/IO faults;
  remote decode failures wake all pending callers and close outgoing IO.
  Caller cancellation retains a bounded pending slot until reply/close.
  A native subprocess regression keeps stdin open through handshake timeout
  to prove that a parked read cannot block foreground process exit.
- Contract: outgoing JSON is encoded incrementally within the same 1 MiB
  bound as input. Excessive nesting and unexpected result variants fail
  closed. Safe semantic error codes preserve the connection; raw exception
  details are not serialized. Polling returns at most one event per frame.

This review covers only the connection slice. Real Coding/Harnesstui/G13
integration, complete code review and native Windows/macOS evidence remain
open under issue #564. The local AppService gate passed 162 tests, including
the added ownership/architecture regressions. The first combined
typecheck exited with code 139 while another platform typecheck shared its
cache; a rerun using an isolated cache passed all 31 checked source files.
A later sandboxed checker traceback identified a cache `disk I/O error`;
the final no-cache AppServer check passed all 14 source files. Final focused
AppServer tests passed 56 cases and architecture documentation passed 5.
