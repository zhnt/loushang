# AppService Hosted Boundary With An Embedded TUI

[Architecture](../README.md) · [Drafts](README.md) ·
[Future Architecture v3](future-loushang-architecture-v3.md) ·
[Application Service Refactor](application-service-refactor.md)

## Status

- ID: `APP-DP-HOSTED-BOUNDARY`
- Kind: delivery plan
- Scope: AppService / application host
- Parent: Loushang
- Authority: normative target proposal
- Design status: proposed
- Implementation status: not-started
- Owner: Loushang application architecture
- Current evidence:
  - `src/loushang/harnesstui/`
  - `src/loushang/harness/session/facade.py`
  - `src/loushang/harness/session/operations.py`
  - `src/loushang/harness/host/rpc/`
  - `tests/harnesstui/`
  - `tests/harness/session/test_facade.py`
  - `tests/harness/session/test_operations.py`
  - `tests/coding/test_rpc_controls.py`
  - `tests/coding/test_rpc_wire_playback.py`

This proposed Target plan clarifies one deployment choice in the v3 target
architecture:

- the default native TUI remains an embedded, in-process Product surface and
  does not use `AppClient`;
- hosted and reconnectable surfaces use the versioned App Contract through
  `AppClient` and `AppService`; and
- both paths reuse Product-owned semantics and Harness contracts without
  making AppService part of the Harness Capability or Plugin runtime.

This document does not authorize implementation ahead of an accepted daemon,
external-client, or background-Session delivery requirement. It also does not
change the accepted Harness Capability graph, its implemented graph owners,
Plugin lifecycle, or provider-composition boundaries.

## Current, Target, And Delta

### Current facts

- the native TUI binds Product and Harness Session behavior in-process through
  Harnesstui and Product-owned adapters;
- `SessionFacade`, `SessionOperationRuntime`, and the legacy JSONL RPC host
  provide current typed Session and transitional remote-host boundaries; and
- there is no `loushang.appserver` package, App Contract, `AppClient`,
  `AppService`, daemon-owned live Session router, or reconnect protocol.

The Current claims above are bounded by the evidence listed in the status
block. The source and tests remain authoritative if this draft drifts.

### Proposed target

The Target is the two-profile boundary below: the default native TUI remains
embedded, while hosted or reconnectable clients use a versioned App Contract
and AppService. Because the design status is `proposed`, target-only names and
rules in this document are review inputs rather than accepted architecture or
current public APIs.

### Explicit delta

The Delta begins only after a hosted delivery trigger is accepted. It includes
an AppService architecture scope, minimal Product Session and Work ports, a
versioned client-safe protocol, hosted lifecycle and routing, reconnect and
delivery semantics, and the associated trust and conformance gates. Until
then, the embedded path and transitional RPC owners remain Current and no
placeholder AppService runtime should be introduced.

## Decision Summary

Loushang keeps two first-class process profiles:

```text
default local TUI
  Harnesstui
    -> Product conversation UI binding
    -> embedded Product runtime
    -> per-Session Harness runtime

hosted clients
  WebUI / IDE / mobile / remote TUI
    -> AppClient
    -> versioned App Contract
    -> Hosted Platform Host
         -> AppServer endpoint and transport lifecycle
         -> AppService
         -> resolved Product Session or Work port
         -> per-Session Harness runtime or Work runtime
```

The default TUI does not serialize commands through the App Contract and does
not depend on `AppClient`, `AppService`, or a daemon. A future remote TUI mode
may use `AppClient`, but that is a separate hosted composition selected at
startup rather than a replacement for the embedded fast path.

The optional in-process `AppClient` described by v3 remains available when a
Product explicitly elects an AppClient-backed profile. This plan declines that
option for the default native TUI; it does not remove the option from the
architecture.

AppService is the hosted application coordinator. It is not a universal UI
backend, a Capability provider, a Plugin manager, or a second Harness runtime.

## Why This Split

The embedded TUI needs low-latency access to terminal input, rendering,
playback, completion, interrupt, and Product-local interaction behavior. Making
every local action traverse a client protocol would add a second projection
boundary without providing process survival or reconnect semantics.

Hosted clients have a different problem. They need stable identifiers,
admission acknowledgements, ordered events, interaction correlation,
attachment and controller state, bounded delivery, snapshots, reconnect, and
version negotiation. These are AppService responsibilities and should not be
added to Harnesstui or the Harness Session facade merely to support a remote
surface.

The split therefore shares execution semantics but not presentation plumbing:

- Product, Harness, and Work retain their existing semantic authority for
  Product behavior, Session/turn/transcript/Approval/tool mechanisms, and
  durable Work truth respectively;
- embedded Harnesstui binds those semantics directly through existing
  Product-owned adapters;
- AppService projects the same authoritative facts into a client-safe hosted
  state model; and
- no mutable embedded Session is transferred into a daemon.

## Boundary Vocabulary

| Name | Meaning | Explicit exclusion |
| --- | --- | --- |
| App Contract | Versioned, client-safe request, response, event, snapshot, and interaction values | Not serialized Harness, Product, Plugin, or widget objects |
| AppClient | Transport-neutral client contract for hosted surfaces | Not required by the default embedded TUI |
| AppService | In-process hosted application coordinator | Not a transport, Product runtime, Harness Capability, or Plugin manager |
| AppServer | Hosted process profile inside a Platform Host; owns endpoints and transport lifecycle | Not a second Platform Host, Product router, or owner of Product/Work semantics |
| Product Session port | Narrow Product-provided Session operations consumed by AppService | Not a universal Product interface or service locator |
| Product Work port | Narrow Product-provided durable Work submission and observation operations | Not a synonym for every turn |
| Harnesstui Product binding | Embedded adapter from Product-neutral TUI ports to one Product runtime | Not an App Contract adapter |

The exact Product Session and Work port names remain deferred until the first
hosted vertical slice proves the minimum methods. The implementation must not
create a speculative universal application port merely to make the two process
profiles look structurally identical.

## Ownership And Dependency Direction

The required source direction is:

```text
Embedded Product composition root
  -> Harnesstui public ports                    # embedded profile
  -> Product runtime and Harness public ports

Hosted Platform Host composition root
  -> admitted Product Registry / Router / Factory
  -> AppServer endpoints and transports
       -> AppService
       -> injected Product Session / Work / optional Channel ports

Harness -X-> AppService / AppClient / App Contract / Harnesstui / Product
AppService -X-> concrete Product package / Harnesstui / Plugin internals
```

AppService may define the structural ports it consumes. A `ProductResolver` is
only a narrow adapter over the Platform Host's already admitted Product
Router/Factory; it does not own Product registration, Plugin discovery, OEM
selection, provider resolution, or trust policy. Concrete Product or
host-owned adapters implement the injected Session, Work, and optional Channel
ports and may call Product and public Harness APIs. This preserves dependency
inversion: AppService never imports `loushang.coding` or derives a Product
implementation from an import path.

The embedded and hosted factories may share immutable Product definitions and
configuration, but each invocation constructs independent mutable runtime
state. Sharing a factory does not permit sharing a live Session object across
processes.

## Plugin And Capability Non-Interference Contract

Harness owns Product-neutral discovery, composition, lifecycle mechanisms, and
the accepted target graph planner/binder/runtime/projector contracts. Product,
OEM, and Platform composition own trust, admission policy, Product-specific
provider selection, and Mount Policy. The runtime scope that binds a final
graph owns its leases and ordered disposal. AppService consumes only the final
Product-facing binding produced by those owners.

The top-level graph Planner, Binder, Runtime, and Projector are implemented
under `loushang.harness.capabilities`. That does not make them AppService
dependencies: AppService must not import or orchestrate the graph result,
binder, live Mount runtime, or projector. It may consume only the resulting
narrow Product-facing binding supplied by the owning composition root.

The following rules are mandatory:

1. AppService is not represented as a Capability ID, Capability Bundle,
   Mounted Capability, Plugin, Extension, provider candidate, or graph node.
2. AppService never imports Harness capability planner, provider registry,
   Plugin manager, Mount runtime, or private binding modules.
3. AppService never discovers Plugins, selects providers, interprets discovery
   priority, refreshes a Capability graph, or disposes an individual provider.
4. `ProductResolver` is supplied by the outer composition root. Resolving a
   Product returns an immutable definition and scoped factories, not a global
   mutable registry or service locator.
5. Product runtime activation may cause the owning Product/Host composition to
   bind a Capability graph. AppService sees only the resulting narrow Session,
   Work, event-projection, and interaction ports.
6. Capability and Plugin lifecycle remains owned by the runtime scope that
   bound it. AppService closes its hosted Session binding; it does not reach
   inside that binding to tear down Mounts or Extensions.
7. Plugin identity and provider provenance may appear only in an explicitly
   redacted, read-only diagnostic view produced by the authoritative Capability
   graph projector and supplied through a Product/Host port. AppService does
   not rebuild an effective graph from runtime events, and App snapshot
   revision does not replace graph generation or registration revision.
8. Authorization policy, credentials, and Product risk choices remain owned by
   Product/Host composition. AppService invokes an injected authorizer and
   enforces its decision at the application boundary. A Plugin cannot replace
   transport authentication enforcement, this application-authorization
   enforcement, attachment/controller admission, idempotency, or delivery
   invariants through ordinary Harness variation.

If the AppService workstream discovers a missing Harness contract, it must not
patch capability internals from the AppService branch. The missing contract is
proposed and landed through the Harness lane first, then consumed from `main`
after its public boundary and architecture gates are accepted.

## Embedded TUI Contract

The default embedded TUI preserves the current ownership shape:

- Harnesstui owns terminal input, layout, rendering, local dialogs, local
  completion, playback, and presentation state;
- the Product UI binding translates TUI intents into Product/Session
  operations and Product-specific projections;
- Harness owns Product-neutral Session, transcript, interaction, tool,
  cancellation, and execution mechanisms; and
- Product composition owns prompts, tools, policy choices, domain events, and
  final presentation semantics.

The embedded path must not acquire hosted-only concerns:

- App protocol version negotiation;
- attachment, device, or controller-lease records;
- remote idempotency keys;
- delivery cursors or reconnect buffers;
- client-safe wire DTOs; or
- daemon lifecycle.

An embedded Session is local-only and ends with its owning foreground process
unless the Product already has a separately accepted persistence contract.
Attach does not migrate it into AppService. A Product that needs background
continuity creates the Session in AppService from the beginning and uses a
hosted client composition.

The supported command shape may eventually be:

```text
loushang tui                 # embedded default; no AppClient
loushang daemon              # owns hosted Sessions and AppService
loushang tui --connect URL   # optional hosted/remote TUI; uses AppClient
```

The third command is deferred until a remote-TUI requirement is accepted.

## Hosted App Contract V1

The first contract should be small, typed, and explicitly asynchronous. It
borrows the useful mechanics of Codex app-server without copying its
Thread/Turn/Item domain model.

### Connection

- `initialize`: the first request on a connection; negotiate supported protocol
  versions, client identity summary, requested experimental capabilities, and
  Product capability summary. The response selects exactly one version.
- `initialized`: one-way client acknowledgement after successful
  initialization. Other application requests are rejected before it.
- A connection initializes exactly once. Repeated initialization, no compatible
  version, unknown requests, requests for non-opted-in experimental methods,
  and malformed values return typed errors. Within one stable major, unknown
  optional fields and unknown notifications are ignored for forward
  compatibility; an unknown request returns `MethodNotFound`.
- Authentication principal and authorization scopes come from the admitted
  transport context, never from an untrusted client payload.

AppServer owns transport authentication plus connection and resource
admission. AppService applies the injected application authorizer to Session,
Work, attachment, and mutation requests. Neither layer invents Product/OEM
authorization policy.

Errors use one typed envelope with a stable code, safe message, retryability,
and optional typed details. At minimum V1 distinguishes initialization,
version/capability, validation, authorization, not-found, conflict,
stale-state, overload, cancellation, and internal failures. Raw exceptions,
Product objects, paths, credentials, and Plugin/provider values never cross the
App Contract.

### Session

- `session/open`
- `session/attach`
- `session/detach`
- `session/snapshot`
- `session/close`

The live Session routing table is distinct from a persisted conversation
catalog. Listing stored conversations, reading one, and resuming one are
separate future operations; a filesystem directory is never the live registry.

The first in-process core may use one implicit controller connection. When the
multi-client capability is added, `session/attach` returns an `attachmentId`,
observer/controller mode, and controller generation. Typed acquire, release,
and takeover operations plus lease-change events are added in the same gated
slice; clients cannot claim a generation in an ordinary mutation payload.

### Turn

- `turn/start`
- `turn/steer`
- `turn/followUp`
- `turn/interrupt`

An App Turn is one admitted external Product/Agent execution. Agent-internal
model cycles are item or model-cycle events inside that App Turn; they do not
allocate additional App `turnId` values.

`turn/start` returns one typed admission outcome:

```text
Started(turnId, status = inProgress)
Consumed(result)                         # local/Extension/Product handling
Queued(queueItemId, behavior)            # steer or follow-up queue admission
Rejected(error)                          # represented by the typed error model
```

Only `Started` creates a client-visible App Turn and requires exactly one
terminal `completed`, `failed`, or `interrupted` event. The response is emitted
before `turn/started` and every other event for that Turn. `Consumed`, `Queued`,
and `Rejected` never create a phantom in-progress Turn.

The existing boolean preflight signal reports all three accepted cases and is
therefore insufficient as a hosted Turn admission contract. The first hosted
Product adapter supplies a typed admission result and execution handle. The
Product Session binding owns the execution task, cancellation, and completion;
AppService owns only protocol-operation tracking, `turnId` correlation, and
client projection. A shared Harness admission port is introduced later only if
the adapter cannot preserve these semantics or another host proves the same
public requirement. The settled `SessionOperationRuntime.prompt()` contract
remains unchanged.

`turn/steer` carries `expectedTurnId`. `turn/interrupt` carries `turnId` and
maps only to the existing turn-only `abort_turn` primitive: it does not clear
queues or abort selected command execution. The TUI's composite
`stop_active_interaction` remains a distinct host operation. `turn/followUp`
either carries `expectedTurnId` or is explicitly modeled as a Session queue
operation. Stale targets return typed `NoActiveTurn`, `StaleTurn`, or
`AlreadyTerminal` errors and cannot affect a newer Turn.

### Durable Work

- `work/submit`
- `work/read`
- `work/observe`

Work remains separate from a Session turn. `work/submit` means an accepted,
queryable business commitment; it is not used for every prompt merely because
the request arrived through AppService.

Work may be omitted from the first conversation-only protocol slice, but its
identifiers and event family must not later be overloaded onto `turnId`.

Cross-connection idempotency is added with the first externally retryable
mutation. Its key is distinct from a transport request ID and is scoped by at
least principal, operation, Product, and target Session/Work domain. Repeating
the same key and canonical payload returns the original admitted result;
reusing it with a different payload returns a typed conflict. AppService owns
request/admission deduplication. A Work operation key identifies the durable
business commitment and remains authoritative in Work; `work/submit` does not
collapse these two idempotency domains. The externally retryable slice defines
retention/expiry and in-flight-duplicate behavior before enabling retries.

### Interaction

- server request: `interaction/request`
- client response: `interaction/respond`

The envelope carries an `interactionId`, Session identity, optional controller
generation when multi-client control is enabled, deadline/fallback summary, and
one typed payload. `interactionId` is the opaque identity supplied by the
existing lifecycle owner. Approval projects its existing `action_id`; AppService
does not allocate a replacement identity or maintain a second mapping. It
validates routing, controller authority, generation, and response idempotency,
then forwards the answer to the existing interaction owner.

AppService never creates an Approval shadow future, timeout, fallback, or
replacement interaction ID. Approval lifecycle remains owned by the Harness
Approval resolver/broker.

In the first controller-generation contract, an interaction is pinned to the
generation that presented it. Controller loss closes that presenter lease and
settles pending Approval through the existing cleanup/fallback path. A new
controller cannot answer, replay, or inherit the old interaction; reassignment
requires a later explicit lifecycle contract.

### Events And Snapshots

The base event envelope contains:

```text
eventId
streamId
sequence
sessionId
turnId? / workRunId?
projectionRevision?
resumeCursor
eventType
payload
```

Core event families are typed: Session lifecycle, turn lifecycle, assistant
message deltas, tool lifecycle, interaction lifecycle, and Work lifecycle.
Product-specific event payloads use a Product-owned, namespaced extension
family rather than a generic command dictionary.

Snapshot and subscription are established under one Session coordination
boundary. The response returns both the client-safe projection revision and an
opaque high-water cursor in the retained App event stream:

```text
snapshot(projectionRevision = N, resumeCursor = C)
  + ordered AppEvents after C
```

Every retained AppEvent advances `resumeCursor`; an event that changes the
snapshot projection also records its resulting `projectionRevision`. An
attachment tracks its last delivered cursor, and a reconnect may resume after
that cursor while it is retained. If it is unavailable, AppService returns
`SnapshotRequired` and atomically establishes a fresh snapshot/cursor pair.

Projection revision, resume/delivery cursor, transcript revision, Work event
position, and transient runtime-event sequence remain distinct identifiers.
None is silently reused as another merely because its first implementation is
an integer.

## Concurrency, Ordering, And Backpressure

AppService uses separate coordination lanes per hosted Session:

1. Session mutation and turn admission are serialized.
2. In-flight control operations such as steer, interrupt, and interaction
   response can enter while a turn is running; they must not wait behind a lock
   held for the complete model/tool run.
3. Safe reads such as snapshot and inspection may execute concurrently against
   immutable or revisioned projections.

Independent Sessions run concurrently. Session close prevents new admission,
settles or rejects queued requests deterministically, and delegates runtime
disposal to the owner of the resolved Product binding.

Each attachment has bounded outbound delivery. Ephemeral deltas may be
coalesced or discarded after the attachment is marked lagged. The service must
never silently discard interaction requests, controller-lease changes, request
responses, or terminal Turn and Work events. Critical enqueue failure marks
only that attachment lagged and closes it; it does not block the Session event
source or another attachment. Closing a controller attachment also closes its
presenter lease and invokes existing interaction cleanup. Terminal state must
remain recoverable from a fresh snapshot. Response capacity is reserved or
isolated so notification pressure cannot make a request unanswerable. If the
retained cursor is unavailable, AppService returns `SnapshotRequired` and
requires convergence from a fresh atomic snapshot/cursor pair.

One ordered server-output writer per attachment prevents responses, events,
and server-initiated interactions from racing on the transport. Request IDs,
interaction IDs, event sequences, turn IDs, operation IDs, and revisions are
different domains and cannot be overloaded.

## Suggested Package Boundary

The first accepted implementation may use:

```text
src/loushang/appserver/
  protocol/          # typed values, codec, version, schema fixtures
  ports.py           # narrow structural Product/host ports consumed by service
  service.py         # hosted coordination only
  connection.py      # attachment, correlation, ordered output, close semantics
  transports/
    jsonl.py         # first external transport when daemon is accepted
```

`client.py` belongs here only when a real hosted client or contract-test driver
needs it. An in-process client may be useful for service contract tests, but it
is not the default Harnesstui backend and does not justify migrating the local
TUI.

The package must not import concrete Product, Harnesstui, Plugin-manager, or
private Harness capability modules. Product-specific adapters live in the
Product package or its outer composition root.

## Delivery Slices And Gates

These slices refine the matching phase gates in
[Application Service Refactor](application-service-refactor.md) for the selected
default-embedded deployment profile. They do not make its optional Harnesstui
AppClient phase mandatory. External retry, daemon continuity, and multi-client
control remain independently gated rather than being pulled into the first
in-process service core.

### Slice 0 — Accept The Boundary

Deliverables:

- accept or revise this decision;
- name the first hosted client and process-survival requirement;
- confirm that embedded-to-hosted migration is out of scope; and
- reserve `loushang.appserver` without adding runtime code.

Gate: no implementation starts merely because the target architecture contains
an AppService box.

### Slice 1 — Protocol Kernel

Deliverables:

- typed initialize, Session, Turn admission/result, event, interaction, and
  error values;
- codec round-trip, unknown-field, unknown-method, and version tests;
- generated or golden JSON schema fixtures; and
- no generic `dict[str, Any]` escape hatch for unmodeled operations.

Isolation gate:

- no changes under `src/loushang/harness/**`, `tests/harness/**`,
  `docs/internals/architecture/harness/**`, or Harnesstui;
- no imports from concrete Product packages; and
- no daemon or network transport.

### Slice 2 — AppService Core

Deliverables:

- injected fake Product resolver and Session binding;
- Session registry, one implicit single-controller connection, protocol
  operation tracking, interaction forwarding, and ordered output;
- typed `Started` acknowledgement followed by strictly ordered events; and
- bounded connection queues and deterministic close.

Gate: contract tests prove consumed/queued input cannot create a phantom Turn,
every Started Turn converges to exactly one terminal event, stale-target
steer/interrupt cannot affect a newer Turn, independent Session concurrency,
critical-queue cleanup, and no shadow Approval future. Cross-connection
idempotency, reconnect, and multi-client takeover remain out of this slice.

### Slice 3 — One Real Product Adapter

Deliverables:

- one Coding-owned adapter at the composition root;
- one hosted conversation flow using public Product/Harness contracts;
- Product-specific event projection; and
- parity tests for shared turn, interrupt, queue, and Approval semantics.

Gate: the adapter does not cause AppService to import Coding and does not add an
AppService dependency to Harness. Default embedded TUI behavior remains
unchanged.

### Slice 4A — First External Connection

Deliverables:

- AppServer lifecycle inside the hosted Platform Host;
- one local transport, preferably JSONL stdio or an accepted local IPC
  endpoint;
- deterministic initialization, typed transport errors, and bounded slow-client
  disconnect; and
- process-level authentication and resource admission appropriate to the
  transport.

Gate: direct service and transport adapters pass the same contract scenarios,
and a slow client cannot block a Session or another connection.

### Slice 4B — Daemon Continuity

Deliverables:

- daemon-owned hosted Session lifecycle;
- attach/detach plus atomic snapshot/resume-cursor convergence;
- cross-connection idempotency admission for externally retried mutations; and
- explicit restart behavior for live Session and durable Work state.

Gate: a hosted Session survives client disconnect and reconnect without
claiming embedded Session migration; cursor loss converges only through
`SnapshotRequired`; and a retried mutation cannot duplicate an admitted effect.

### Slice 4C — Multiple Clients

Deliverables:

- typed observer/controller attachment mode and attachment identity;
- controller acquire/release/takeover, lease generation, and change events;
- mutation and interaction responses fenced by attachment/generation; and
- presenter cleanup when a controller connection is lost.

Gate: observer, stale-controller, duplicate, late, and superseded-generation
responses are rejected, and a new controller cannot inherit an interaction
issued to an old generation.

### Slice 5 — External Surfaces

Add WebUI, IDE, mobile, WebSocket, remote TUI, or cloud tenancy only after a
named Product and delivery requirement accepts each surface. Security,
authorization, quotas, credentials, and reconnect guarantees are part of the
surface gate, not follow-up polish.

## Workstream And Branch Isolation

The planning work starts from `main` on a dedicated docs branch. Future
AppService implementation branches also start from current `main`, not from an
unfinished Harness capability/plugin task branch.

Recommended branch sequence:

```text
docs/appservice-embedded-hosted-boundary
appserver/protocol-v1
appserver/service-core
appserver/coding-hosted-adapter
appserver/daemon-local-ipc
```

Each branch has a disjoint primary ownership budget. Protocol and service-core
branches do not edit `src/loushang/harness/**`, `tests/harness/**`, or Harness
architecture documents. The Product adapter branch may consume only public
Harness contracts already landed on `main`.

If integration depends on ongoing Harness work:

1. record the missing public contract without copying unfinished implementation;
2. let the Harness work land through `lane/harness` and its normal gates;
3. merge the resulting `main` into the AppService task branch; and
4. add only the outer adapter and AppService consumption after the dependency
   is public and stable.

This sequencing prevents AppService deadlines from selecting Plugin providers
or freezing private capability-planner types into the App Contract.

## Verification Matrix

| Invariant | Required evidence |
| --- | --- |
| Embedded TUI does not depend on AppClient | import-boundary test and unchanged embedded startup smoke |
| Harness does not depend on AppService | architecture import test |
| AppService is Product-neutral | fake-Product contract tests and concrete-Product import denylist |
| AppService does not manage Plugins or Mounts | package import denylist and lifecycle tests at Product binding boundary |
| Turn admission is truthful | consumed, queued, rejected, and started outcomes cannot be confused |
| Turn start is asynchronous | response precedes `turn/started` and every later event; exactly one terminal event follows |
| In-flight control remains live and fenced | matching steer/interrupt succeeds while stale targets cannot affect a newer Turn |
| One interaction lifecycle owner | disconnect, stale controller, duplicate, late response, and timeout scenarios |
| Reconnect converges | atomic snapshot/cursor plus retained events, and `SnapshotRequired` after cursor loss |
| Slow clients cannot exhaust the host | ephemeral coalescing, critical-event disconnect, response-capacity, and per-attachment isolation tests |
| External retries are idempotent | same key/payload returns the admitted result and a conflicting payload is rejected |
| Sessions isolate execution | same-Session serialization and cross-Session concurrency tests |
| Protocol remains explicit | initialization, typed error, schema, compatibility/version, and no-generic-command tests |

## Non-Goals

This plan does not include:

- migrating the default TUI to AppClient;
- making App Contract a universal in-process command bus;
- moving terminal rendering or Product presentation into AppService;
- making AppService a Harness Capability or Plugin replacement surface;
- exposing capability-planner, provider, Mount, or Plugin internals to clients;
- changing the settled shared Harness Session operation solely for AppService;
  the first hosted adapter owns its typed admission handle, and any later
  Harness contract change uses a separate accepted Harness-lane task;
- routing every turn through Work or Method;
- automatic embedded-to-daemon Session or transcript transfer;
- durable replay storage in the first AppService slice; or
- WebSocket, P2P, relay, multi-tenant cloud, or mobile guarantees before their
  delivery gates are accepted.

## Acceptance Checklist

Before implementation begins, reviewers should be able to answer yes to all of
the following:

- Is there a named hosted client or background-Session requirement?
- Does the default local TUI remain embedded and independent of AppClient?
- Are Product Session and Work semantics still distinct?
- Is AppService outside Harness Capability and Plugin composition?
- Does AppService consume only explicitly injected Product ports?
- Is the first protocol slice typed, asynchronous, and smaller than the full
  future Product surface?
- Are Approval lifecycle and pending futures still owned by the existing
  Harness interaction owner?
- Can steer, interrupt, and interaction responses enter during a running turn?
- Are projection revision, resume cursor, event sequence, transcript revision,
  and Work position kept distinct and joined by an atomic snapshot boundary?
- Can the work land without editing the ongoing Harness capability/plugin
  implementation branch?
