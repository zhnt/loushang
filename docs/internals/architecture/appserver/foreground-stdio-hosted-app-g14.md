# Foreground Stdio Hosted App G14

[Architecture](../README.md) · [AppServer](README.md) ·
[G13 continuity](../apphost/durable-hosted-application-continuity-g13.md)

## Status

- ID: `FOREGROUND-STDIO-HOSTED-APP-G14`
- Scope: AppServer connection / optional AppHost foreground edge / Product entrypoint
- Parent: Loushang application architecture
- Authority: accepted delivery design
- Design status: accepted following the three-view design review below
- Implementation status: partial — explicit executable and real Product subprocess integration implemented; complete native-platform validation and delivery pending
- Activation status: target explicit foreground stdio command only
- Tracking: [issue #564](https://github.com/zhnt/loushang/issues/564)

## Outcome, Facts And Delta

G14 makes the existing hosted application usable across a real process
boundary. An installed, explicitly selected Coding command constructs real
Coding Sessions and a G13 recoverable application. A transport AppClient can
drive the existing Harnesstui Hosted Mux controller without importing Coding
or AppService. Closing this foreground connection stops its application.

Pre-G14 facts: G11 supplies strict JSON values, AppClient, in-process
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

`apphost.foreground.HostedForegroundRuntimeV1` now implements the optional
connection-before-application edge over a ready G13 runtime and injected IO.
Connection settlement fences byte IO first; inherited descriptors remain
borrowed until the outer process exits. Failed/timed-out cleanup retains the
same owner/task for retry, and application close cannot overtake unfinished
connection work. Unit evidence covers EOF mid-turn, cancellation or explicit
close during handshake, failed application disposal, and a timed-out close
joined without duplicating its in-flight task. This is lifecycle evidence,
not yet the required real Product subprocess or native-platform delivery.

Three-view review of this edge: the architecture gate permits only the exact
optional AppHost module and keeps the core facade independent; lifecycle tests
prove connection cleanup debt prevents application close, and a retained
timeout task is joined on retry; contract tests preserve handshake faults as
failures even after successful cleanup. Seven focused lifecycle cases and 33
AppHost/ownership architecture cases passed locally. A typecheck initially
rejected the broad awaitable callback passed to `create_task`; its contract
now explicitly requires the native coroutine supplied by these close owners.
The full AppService gate subsequently passed 190 cases and checked 37 source
files; the architecture documentation gate passed five cases.

## Coding And Harnesstui Integration

### Explicit installed command

`loushang-hosted` is now installed as `loushang.coding.cli.hosted:main`.
It requires `--workspace`, `--application-root`, `--cwd-sessions`, and
`--home-sessions`; `--application-id` defaults to `coding.default`. These are
trusted outer inputs, not new wire fields. The three storage roots must be
separate and non-overlapping; the workspace and application-root parent must
exist. G13 creates the private application leaf or rejects unsafe existing
permissions. This first explicit profile does not redirect existing default
Session roots, migrate legacy transcripts, or select a daemon automatically.

Adding `--describe` returns path-free scope fingerprints and application/Product
identity without acquiring a lease or writing files. An outer launcher can use
that description to construct `SessionOpenSpecV1` without importing Coding into
Harnesstui. The launch arguments stay the same for describe and actual launch.
The stdio mode requires pipes and is not a directly interactive terminal UI.

The installed command uses the existing Product global/project settings paths,
actual Session factory, model selection, tool surface and policy configuration.
It installs interactive approval with a deny fallback, not a headless blanket
grant. Inherited stdout is reserved for framing; incidental Python stdout and
diagnostics are routed to stderr. A cleanup-incomplete result is a nonzero
process exit, not a claim that G13 settlement succeeded. On that fatal path the
outer command exits without entering asyncio's unbounded final cancellation
join; reusable library owners retain their normal retryable close contract.

Admission pins identify one imported installed Product/profile generation for
this process. There is no hot replacement path, Worker launcher, filesystem
sealing claim, or new plugin generation authority. Model response and safe-tool
injection are trusted library-only test seams; the installed argv accepts no
model transport, module or factory name.

The first complete native Product tests found that canonical candidate facts
must be class-defined properties for AppHost's static admission boundary, not
ordinary mutable instance fields. The owner now conforms without weakening
AppHost. Native tests separately verify the installed default command's
help/start/EOF and the real Product's cwd/home recovery using synthetic model
responses. Both use the existing server, client, G13 runtime and Harnesstui
controller. A launcher's ready-wait budget includes cold Product imports and
recovery; the server's finite hello deadline begins only after readiness.

### Product and client responsibilities

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

### Product Persistence And Scope Decision

The real Coding edge adds a canonical catalog and a real AgentSession binding.
These remain separate from the command's configuration/path resolution and
AppHost's application lifetime. Their source paths are enumerated in inventory
v7 and the exact optional-consumer architecture gates.

Canonical routing and create-idempotency facts are persisted under
`coding.hosted` in the existing Coding transcript header. There is no second
Session registry. Hosted create uses a deterministic SHA-256 identity and
filename from Product/creator-scope/operation identity; the existing transcript
store owns atomic create. Repeated or concurrent same-key requests recover
that exact Session, and changed continuity/compatibility intent conflicts.
Candidates hold a real transcript owner, verify a hashed file-authority
revision before claim, and transfer that owner once into the real AgentSession.
Canonical reads retain the existing transcript owner's bounded, stable,
regular-file checks, including reparse rejection, instead of using the
POSIX-only legacy migration adapter.

Generic Transcript creation gains two explicit options: additional immutable
header metadata that cannot overwrite reserved Product/runtime metadata, and
`defer_materialization=False` to create an empty durable Session before a
hosted membership commit. Existing callers still defer empty Session writes.
These options carry no AppHost, Coding or application semantics in Harness.
Ordinary/legacy TUI transcripts without the canonical header are not silently
adopted. Their existing entrypoints remain unchanged.

The cwd scope fingerprint includes the admitted workspace. The user-home
scope fingerprint depends on its admitted global Session root, so it remains
discoverable from another workspace. Both execute in the workspace explicitly
selected at this foreground launch; a persisted header's historical cwd is
descriptive and does not grant path authority. Root/scope mismatch fails
closed. G14 does not yet provide a multi-workspace execution manager.

The real Session binding projects public Agent events and a visibly bounded
recent transcript view. Canonical transcript content is never truncated.
Approval presentation uses the existing ApprovalBroker's registered waiter,
fresh opaque interaction tokens and the existing `allow_once`/`deny`/`abort`
response path. It neither grants persistent permissions nor bypasses policy.
Tests use the explicit synthetic-model annotation at the test composition
seam; the production factory retains the standard durable-model constraint.

Three-view review of this refinement: authority remains in the canonical
Product/Harness owner (no new index or path-bearing wire field); lifecycle
requires eager empty-Session persistence and single owner transfer; evidence
must include concurrent create, stale-candidate rejection, cross-cwd global
discovery, real message persistence and actual ApprovalBroker resolution.
Those focused cases now pass locally; the subprocess Product/entrypoint and
native cross-platform acceptance remain pending.

The Product slice's three-view code refinement also preserves each scope's
bounded candidate snapshot independently, so home discovery cannot evict an
in-flight cwd resume. Bound-source restoration keeps the selected file leaf
for Store no-follow checks instead of re-running alias discovery. Construction
retains the claimed cleanup owner until the complete real Session binding
transfers, including retry after a disposal failure. Local verification:
327 Coding/Transcript regression cases and the expanded AppService gate's
182 cases passed; the latter also checked 36 source files with mypy.

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

## Executable Integration Review (Native Delivery Still Pending)

This is a three-perspective implementation review, not an independent-agent
or completed cross-platform review claim.

1. Architecture/authority: the installed command is the sole new composition
   edge. Exact consumer gates retain the default CLI/TUI and AppHost core
   boundaries. Native admission exposed mutable instance attributes in the
   real canonical candidate adapter; these were corrected to the class-defined
   properties required by AppHost, without relaxing its static validation.
2. Lifecycle/concurrency: actual child tests exercise EOF during a running
   Agent turn, interrupt, a competing installed writer and a real AgentSession
   disposer fault. The fault exits nonzero without an unbounded Runner join;
   a fresh process subsequently recovers the committed canonical transcript.
   The child owns no parent process and claims no successful cleanup on that
   fatal path. G13 retains its existing lease-last close contract.
3. Product/contract evidence: both cwd and user-home restore stable mux,
   member and Session IDs, messages and fresh attachments through the existing
   Harnesstui controller. An authorized in-memory preview tool proves the real
   policy/ApprovalBroker allow and deny paths. Product tool settings now feed
   the policy evaluator as in the normal Product entrypoint. Synthetic model
   input handles canonical text parts; production accepts no synthetic argv.

Local verification: all 202 AppService tests passed, including nine real
Product/installed subprocess cases; 39 exact architecture cases passed;
Ruff and mypy over 38 source files passed; the documentation gate passed five
cases. During development a test used the wrong mux-list field, a synthetic
model omitted text-part input, and one ready wait expired while full-tree
checks occupied the local CPU. Those were corrected/revalidated; the native
parent now explicitly gives cold imports plus recovery a bounded 30-second
ready budget, independently of the server's post-readiness hello deadline.
Native macOS/Windows CI evidence and the final delivery-wide review remain
required before marking G14 complete.

## Delivery-Wide Review Follow-up (In Progress)

The first PR CI on `ed773a71` passed the Linux/macOS AppService gates but
failed seven real Product cases on Windows: each stalled while opening a
member, before a turn. This is unresolved native runtime evidence, not a
successful three-platform delivery. Child thread dumps and captured stderr
are now retained on subprocess test failures to locate the blocked owner.

Architecture review found stale exact inventories in the older G9/Hosting
gates. The live entrypoint inventory is now v4 and describes the separate G14
command and existing mux/connection libraries; default Worker ownership and
the G9 `RETAIN` decision are unchanged. G14's three Product adapters account
for 1,224 lines and have an independent 1,300-line ceiling, following the
existing G10--G13 slice budgets. The core remains at 33,786 lines under its
unchanged 33,800-line limit. Shared logic has not been moved into another
package merely to evade a Product budget. All 41 associated regression cases
passed after reconciliation.

Lifecycle review found that client close could wait indefinitely for its
reader when an injected IO owner ignored cancellation. A regression first
proved the unbounded wait. Client close now fences admission and pending
calls immediately, retains a single stream/reader settlement task, and
reports `cleanup_incomplete` at the configured phase deadline without
cancelling or duplicating that task. A later close joins the same owner.
This does not grant AppServer process-termination authority. The native
Product matrix also now covers EOF while the actual approval broker waits,
followed by a fresh process without restored approval or active-turn authority.

On `3548ecda`, the full local AppHost gate passed 420 cases (one unrelated
existing skip). A separately built non-editable wheel, installed with the
locked production dependencies into a fresh virtual environment, passed all
ten real Product subprocess cases with source-path injection disabled. Module
origin and distribution `direct_url.json` confirmed imports from the installed
wheel, not the worktree. This is additional Linux evidence, not Windows proof.

The diagnostic Windows run
[`34124630815`](https://github.com/zhnt/loushang/actions/runs/34124630815)
located the member-open stall in the existing Foundation runtime-identity Git
probe, inside the unbounded Windows `communicate()` used by `subprocess.run`
after its two-second timeout. The probe inherited the application's stdin.
Git identity/status probes now explicitly receive `DEVNULL`, never the Hosted
protocol pipe. A regression first proved the inherited-stdin defect; the
Foundation regression is included in both AppHost and three-platform
AppService gates. Native revalidation remains required before claiming that
this change resolves the observed Windows stall.

Native run
[`34125635750`](https://github.com/zhnt/loushang/actions/runs/34125635750)
on `9660cb94` verified that the real Product member-open stall is resolved:
all ten Product subprocess cases passed on Windows. The overall Windows job
was still red (206 passed, four failed) because the newly included legacy
Foundation tests expected native backslashes instead of the collector's
existing normalized POSIX-form path strings. Only those expected strings are
corrected; no production path contract or platform skip is changed.

## Final Three-View Code Review

Scope: the complete G14 delta from `1919c57f`, including the generic Transcript
options, protocol/connection/client/stdio, Product catalog and Session binding,
optional foreground owner, installed command and the causal diagnostic fix.
This is a three-perspective review by one reviewer, not an independent-agent
review claim. Full-head platform and integration delivery gates are still
required after the final test corrections.

1. **Architecture and authority:** AppServer remains standard-library-only
   and accepts semantic and byte ports; it does not import AppService,
   AppHost, Hosting, Harness or Products. AppHost's foreground edge is exact
   and optional. Coding alone binds trusted scopes, settings, canonical
   transcript identity and the real AgentSession. Header metadata is immutable
   and cannot override reserved runtime/Product keys; default empty Sessions
   remain deferred. No application registry becomes a second Session store,
   no client path is executable authority, and no default owner is changed.
   Stale inventories and the missing independent Product budget were fixed
   without broad import or size exemptions.
2. **Lifecycle and concurrency:** typed request dispatch reserves control
   admission separately from ordinary calls; cancellation retains a bounded
   pending slot until response/close. EOF fences and settles connection work
   before application/Product shutdown and the G13 lease. Failed construction
   retains cleanup ownership; failed/timed-out close stays retryable. Client
   close's unbounded reader join was reproduced and fixed with single-flight,
   retained, bounded-wait settlement. Native fault cases distinguish clean
   exit from fatal cleanup and verify fresh recovery. Git diagnostics no
   longer borrow the protocol's stdin; Windows native evidence confirms the
   observed startup stall is gone.
3. **Behavior and evidence:** installed help/start/EOF, real prompts and
   streamed Harnesstui projection, real policy approval/denial, interruption,
   EOF during an active turn or approval, conflicting writers, fatal cleanup,
   cwd/home recovery and fresh attachment rejection are covered. A new
   connection-level regression also exercises all 15 public AppClient methods
   through framing, decoding and exact semantic dispatch; it verifies the
   deliberate one-event wire poll independently of Product tests. A standalone
   wheel passed all ten native Product cases outside the source import path.
   Windows path-expectation corrections preserve the collector's existing
   contract. Remaining work is final-head gate evidence and delivery, not an
   unresolved code finding from these three perspectives.
