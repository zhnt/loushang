# Application Service Refactor

## Status

Proposed. This document defines a staged refactor, not an instruction to build
a daemon, WebSocket transport, or new client protocol immediately.

The current delivery clarification is
[AppService Hosted Boundary With An Embedded TUI](appservice-embedded-tui-hosted-boundary-plan.md):
the default native TUI remains on the direct embedded path. References below
to an embedded `AppClient` or Harnesstui migration are optional Product
elections, not a prerequisite for AppService or the default local composition.

## Decision

Loushang will keep its current in-process path simple until a real external
client or daemon requires a stable application boundary.

Today:

```text
Harnesstui
  -> prepared conversation ports
  -> SessionOperationRuntime / SessionFacade
  -> SessionRuntime

legacy JSONL RPC
  -> RpcHost
  -> SessionOperationRuntime / SessionFacade
  -> SessionRuntime
```

The current refactor therefore consolidates the existing typed session
operations and host ports. It does **not** add an `AppService`, `AppClient`,
in-process message pump, or a second event bus.

When at least one extraction trigger is real, Loushang may introduce a
top-level `loushang.appserver` package. In that target architecture:

- `AppService` is the single application boundary above Harness and injected
  Work/Channel ports, while Product composition retains Method binding;
- `AppClient` is the client-facing contract;
- in-process, JSONL, and WebSocket connections are transport adapters over the
  same application protocol;
- `InProcessAppClient` is an adapter, not another business layer; and
- Channel remains the Work-operation boundary rather than becoming a universal
  UI command bus.

## Why The Boundary Is Deferred

The repository already contains most of the reusable in-process semantics:

- `SessionFacade` presents Product-neutral session capabilities;
- `SessionOperationRuntime` provides capability-grouped typed operations below
  RPC and Channel schemas;
- `SessionRuntime.subscribe()` provides the ordered runtime event source;
- Harnesstui prepared-run ports keep terminal mechanics independent from a
  concrete Session;
- `RemoteUiContext` owns remote dialog correlation for the legacy headless
  host; and
- the legacy RPC host is already split into lifecycle, routing, command groups,
  projection, output, and wire modules.

These owners are not yet wired uniformly. Harnesstui still duck-types concrete
Session methods, while several legacy RPC queries call `SessionFacade`
capability ports directly. Phase 0 is therefore a real adapter migration, not
a claim that TUI already runs through `SessionOperationRuntime`. It unifies
only shared primitive operations and leaves queries and host composites with
their existing explicit owners.

Adding another service object and two in-memory queues today would duplicate
these boundaries without adding a second real client. The architectural roles
remain useful, but they do not yet justify additional runtime objects.

## Extraction Triggers

`loushang.appserver` should be extracted only when at least one of these is an
accepted delivery requirement:

1. an IDE, desktop application, or supported SDK needs a stable client API;
2. a daemon must own sessions beyond one CLI process;
3. Harnesstui must connect to either a local embedded runtime or a remote
   daemon without changing its behavior;
4. more than one client must observe or control the same live session;
5. disconnect and reconnect must preserve a session or durable run; or
6. client and server releases need an explicitly versioned compatibility
   contract.

A speculative future client, a desire to rename RPC, or the existence of many
legacy commands is not by itself an extraction trigger.

## Target Dependency Direction

Once extracted, the target package is top-level because it coordinates several
lower layers:

```text
embedded Product composition root
  -> Harnesstui prepared ports
  -> Product Session binding -> Harness

hosted Platform Host composition root
  -> admitted Product Router / Factory
  -> loushang.appserver.service
       |-> injected Product Session port -> Harness
       |-> injected Product Work port -> Work -> Harness
       `-> injected Channel port -> Work / Harness

hosted clients, including an optional AppClient-backed Harnesstui profile
  -> appserver.client
  -> appserver.protocol

appserver transports
  -> appserver.protocol
```

Method selection, compilation, and `MethodPlan -> WorkPlanSpec` conversion
remain a Product-binding responsibility. `WorkPlanSpec` is a target design
value, not a current implementation type: the current Coding path submits
Method-prepared turns and metadata through its `submit_plan` binding.
AppService receives the resulting Product/Work ports; it does not import Method
or create a second Method-to-Work binding.

Package-level import rules:

- `appserver.protocol` imports only the standard library and deliberately
  admitted low-level value packages;
- `appserver.client` imports `appserver.protocol`, not service internals;
- `appserver.transports` import protocol and transport mechanics, not Harness
  Session implementations;
- `appserver.service` may adapt injected Harness, Work, and Channel ports;
- Harness and Work never import AppServer; and
- Harnesstui never imports `appserver.service`.

The Product composition root is the one deliberate Product-side importer: an
allowlisted entrypoint such as Coding `ui.mode`, CLI bootstrap, or a future
daemon bootstrap may import `appserver.service` to inject Product factories
and ports. Product domain, Session implementation, tool, Policy, and
presentation modules do not import AppServer. AppServer never imports a
Product package.

This placement preserves the existing `Harness <- Channel` direction rather
than reintroducing `Harness -> Channel`.

## Target Package Shape

The first extracted package should remain small:

```text
src/loushang/appserver/
  __init__.py
  protocol.py
  client.py
  service.py
  in_process.py
  transports/
    __init__.py
    jsonl.py
```

Subpackages such as `protocol/`, `service/`, or `client/` are created only when
one of these files has multiple independently testable owners. WebSocket,
authentication, SDK code generation, and daemon supervision are not empty
placeholder modules.

## Responsibilities

### Existing Session Core

`SessionFacade`, `SessionOperationRuntime`, and `SessionRuntime` continue to
own or expose:

- prompt, steer, follow-up, interruption, queue, and idle semantics;
- model, command, package, diagnostics, transcript, and settings capabilities;
- runtime event ordering;
- Agent loop and transcript commit ordering; and
- Product-admitted capability implementations.

They do not acquire connection IDs, wire request IDs, JSON field aliases,
client roles, transport retry, or protocol-version policy.

`SessionOperationRuntime` currently owns only the admitted
input/queue/lifecycle/identity/retry/maintenance operation groups. Model,
command, package, diagnostics, transcript, settings, selected command
execution, and other queries remain explicit `SessionFacade` capability ports.
The refactor does not move all of them into `SessionOperationRuntime`.

The shared primitive and host-composite distinction is:

```text
abort_turn
  = SessionOperationRuntime.abort()
  = abort the active Session/Agent turn
  = do not implicitly clear queues or abort a selected command execution

stop_active_interaction
  = abort_turn
  + SessionOperationRuntime.clear_queue()
  + SessionCommandExecutionPort.abort()
  = current TUI interrupt/Esc behavior
```

The legacy RPC `abort` command retains `abort_turn` behavior. Harnesstui keeps
`stop_active_interaction` as an explicit host composite. A future App protocol
must expose distinct names rather than silently changing either behavior.
Bash/selected-command execution and Session command dispatch remain their
existing ports and are not added to `SessionOperationRuntime` merely to make
the TUI call graph look uniform.

### AppService

After extraction, `AppService` owns application coordination only:

- a registry of service-owned live Session handles;
- typed command dispatch onto injected Session and Work ports;
- client-safe snapshots and read-model projection;
- transport request/event correlation and routing of domain-owned interaction
  IDs;
- connection subscriptions;
- controller routing when several clients observe one Session;
- idempotency admission for externally retried side effects; and
- deterministic close and detach behavior.

It does not own:

- the Agent loop or model calls;
- tool execution or tool authorization;
- Policy and Approval decisions;
- Work scheduling semantics;
- Method selection, compilation, projection, or Method-to-Work conversion;
- transcript storage implementation;
- terminal rendering or widget layout; or
- JSONL, WebSocket, or operating-system daemon mechanics.

### AppClient

`AppClient` is a narrow asynchronous client contract. Hosted SDK/UI adapters
and a Product that explicitly elects an AppClient-backed Harnesstui profile
consume it without knowing whether the service connection is in-process or
remote. The default embedded Harnesstui profile does not consume it.

Conceptually:

```python
class AppClient(Protocol):
    async def request(self, request: AppRequest) -> AppResponse: ...
    def subscribe(self, listener: AppEventListener) -> Unsubscribe: ...
    async def respond(self, response: ClientInteractionResponse) -> None: ...
    async def close(self) -> None: ...
```

Product-specific convenience methods may wrap this contract outside the
protocol core. The initial contract should not mirror every method on
`SessionFacade`.

### In-Process Connection

`InProcessAppClient` implements `AppClient` against one `AppService`. It is a
connection adapter, not a domain layer.

Its implementation may use bounded typed queues when one ordered duplex stream
is required for parity with remote clients. Those queues are private transport
mechanics. They are not exposed to Harnesstui, Harness, Work, or Product code.

The minimum duplex message families are:

```text
client -> service
  request
  notification
  interaction_response

service -> client
  response
  event
  interaction_request
```

One ordered service-to-client writer preserves the relative order of runtime
events and interaction requests. Request and interaction responses are
correlated independently. Closing a connection settles all of its unresolved
futures.

A direct-call implementation is acceptable before ordered duplex behavior is
required, provided it implements the same `AppClient` contract and passes the
same semantic contract suite.

### Remote Transports

JSONL and a future WebSocket transport:

- encode and decode protocol values;
- maintain connection framing;
- preserve request and interaction correlation;
- apply transport-level limits; and
- report disconnects to AppService.

They do not contain Session command handlers, Product capability discovery,
approval policy, or read-model projection.

### Channel

Channel remains the boundary for `WorkOperation`, `WorkEvent`, and selected
runtime event views:

```text
App command
  -> AppService
  -> Product/Work adapter
  -> WorkOperation
  -> Channel

Channel delivery
  -> WorkEvent
  -> AppService projection
  -> App event
```

App protocol commands are not added to `ChannelEnvelope`. Channel does not
become the transport implementation behind every `AppClient` request.

## Protocol Model

The application protocol contains client-safe values rather than serialized
domain objects. It should begin with a small vertical slice:

- initialize and capability summary;
- session snapshot/open;
- turn start, steer/follow-up, and `abort_turn`;
- `stop_active_interaction` when the Harnesstui slice is migrated;
- ordered turn/tool/message events;
- one generic client-interaction request/response envelope, initially used by
  Approval and later usable by the legacy extension UI adapter without moving
  either lifecycle into AppService; and
- detach/close.

Each client request has a transport-independent request ID. Long-running work
also has its domain operation/run ID. Client interaction requests use a
separate interaction ID. These identifiers must not be overloaded.

Example:

```text
request_id      one request/response exchange
turn_id         one session turn
operation_id    one durable Work operation
interaction_id  one server-initiated question or approval
event_sequence  ordering within one service-owned stream
revision        snapshot/read-model version
```

Legacy RPC camelCase dictionaries and command names are compatibility inputs
to an adapter; they do not define the new application protocol.

## Approval Interaction Boundary

Approval already has one lifecycle authority: `ApprovalBroker`, normally
reached through `InteractiveApprovalResolver`. It owns pending futures,
timeout, fallback, decision validation, cancellation, and disposal. AppService
must not reproduce any of those behaviors.

Before an App protocol interaction is implemented, Phase 0 adds one explicit
optional Session capability over the existing resolver:

```python
class ApprovalPresentationLease(Protocol):
    def close(
        self,
        reason: str = "Approval presenter closed before approval was resolved",
    ) -> None: ...


class SessionApprovalInteractionPort(Protocol):
    def bind_presenter(
        self,
        presenter: ApprovalRequestPresenter,
        *,
        dismisser: ApprovalRequestDismisser | None = None,
    ) -> ApprovalPresentationLease: ...

    async def respond(
        self,
        action_id: str,
        *,
        outcome: ApprovalOutcome,
        reason: str | None = None,
    ) -> bool: ...

    def permissions_snapshot(self) -> ApprovalPermissionsSnapshot: ...

    def permission_profile_snapshot(self) -> PermissionProfileSnapshot: ...

    async def apply_permission_action(self, action: str) -> bool: ...
```

The Agent Product adapter implements this port by delegating to its existing
`InteractiveApprovalResolver`. It may be added as an optional
`SessionFacadePorts` capability; it is not implemented by `SessionFacade`
itself.

The binding contract preserves the existing presenter lifecycle:

- one Session has at most one active presenter lease;
- the Agent adapter retains its staged/active/closed approval state;
- binding a replacement presenter atomically supersedes the old lease without
  closing the approval Session;
- unresolved requests are replayed to the replacement with their existing
  action IDs and Broker-owned futures;
- a stale lease cannot unbind a later presenter generation;
- closing an active lease calls the existing resolver `close_session()` path,
  which denies **all** pending approvals for that Session and clears the
  presenter; and
- `abort` remains an explicit approval outcome and is not synthesized by
  presenter cleanup.

For an AppClient connection, AppService binds a presenter that projects an
existing approval request as an `interaction_request`. A client response is
forwarded to `respond()`. The existing resolver remains authoritative for
whether that action ID is pending and whether the response is valid.

Consequences:

- AppService never owns an approval future or timeout;
- transport disconnect closes the current presenter lease rather than mutating
  Broker state directly; this denies all pending approvals presented for that
  Session, not only one interaction;
- duplicate, late, observer-authored, and already-cancelled responses return a
  typed stale/not-controller result without changing the approval; and
- approval responses never enter prompt, steer, follow-up, or multi-agent
  message queues.

### Legacy Extension UI Interactions

`RemoteUiContext` currently owns a separate pending-future, timeout, and
response-correlation lifecycle for legacy extension UI select/confirm/input/
editor dialogs. It remains the sole lifecycle authority for those requests
while the legacy RPC surface exists.

When AppService is introduced, its interaction transport may carry both
Approval and extension UI requests, but it only routes the identifier supplied
by the existing lifecycle owner:

- Approval request lifecycle remains in `ApprovalBroker`;
- legacy extension UI request lifecycle remains in `RemoteUiContext`; and
- AppService does not allocate a shadow future, timeout, or replacement ID for
  either request.

If a future common interaction broker replaces `RemoteUiContext`, that cutover
must remove the old pending map in the same change. The two lifecycle owners
must never coexist for the same interaction request.

## State, Events, And Reconnection

AppService is authoritative for client-visible state. A client opens a Session
by receiving:

1. a snapshot at revision `N`; and
2. subsequent ordered events after that snapshot.

The first reconnect implementation may return a fresh snapshot. It does not
need durable event replay. If a client requests a revision no longer
available, the service returns `resync_required` and a new snapshot.

Durable event storage is introduced only when Work recovery or an external
client contract requires it. AppService must not create a second transcript or
Work audit store.

## Multi-Client Interaction

Multiple observers are allowed. Exactly one connection is the current
interaction controller for a Session. Only that connection may answer an
approval or another blocking client interaction.

This is a small ownership rule, not a general collaborative ACL system:

- observers receive snapshots and events;
- the controller may submit input and answer interactions;
- an interaction is pinned to the controller connection generation that
  received it;
- observer, duplicate, late, and superseded-controller responses are rejected;
  and
- controller disconnect runs presenter cleanup, so the existing Approval
  resolver denies all pending approvals for that Session. The first
  implementation does not transfer already-presented approvals to another
  connection.

A new controller may receive newly issued interactions after takeover. Pending
interaction reassignment is a later, separately justified feature.

No client response is inserted into the model input queue. Approval and UI
interaction remain separate from prompt, steer, follow-up, and multi-agent
mailboxes.

## Optional AppClient-Backed Harnesstui Profile

Harnesstui is not rewritten. Terminal rendering, surfaces, composer, history,
status, Markdown, playback, and screen-loop mechanics stay unchanged.

When a Product explicitly elects this hosted profile, the migration replaces
only that Product/runtime binding:

```text
before
  Agent binding -> concrete session/facade methods

after
  Agent binding -> AppClient
```

Presentation-ready events continue through the existing projection boundary.
Local-only UI operations, such as opening a help surface or changing focus,
remain inside Harnesstui and are not round-tripped through AppService.

The default embedded Harnesstui profile continues to consume prepared ports and
existing Session operations directly regardless of whether AppService exists.

Before an elected Product binding cuts over to AppClient, the migration keeps a
checked capability inventory. Every current Agent screen binding dependency is
classified as exactly one of:

| Capability | Target |
|---|---|
| prompt, steer, follow-up, abort turn, stop active interaction, pending queue | App protocol command/query |
| ordered conversation and tool activity | App event/read model |
| transcript history, resume, fork, clone, new session | App session capability |
| model/thinking selection | App selection capability |
| command catalog, completion, active tool definitions | App capability snapshot |
| approval request/response and permission snapshots/actions | App interaction capability |
| session status, usage, footer facts, settings | App read model/query |
| multi-agent tree and control | App multi-agent capability |
| help, focus, scrolling, local surface navigation | Harnesstui-local |

Diagnostics, packages, extensions, and other optional surfaces are included
only when the Product exposes them through the Harnesstui configuration being
migrated. A full cutover cannot retain a concrete Session side door for an
unmodeled server-backed capability. It also cannot hide missing coverage in a
generic dictionary command.

## Legacy RPC Migration

`loushang.harness.host.rpc` remains the legacy JSONL compatibility host during
the migration.

The order is:

1. command groups call `SessionOperationRuntime` and explicit query ports;
2. wire parsing and projection remain in the legacy RPC package;
3. after AppService exists, command groups may delegate to it through a
   compatibility adapter;
4. the new protocol is introduced under its own version and tests; and
5. legacy RPC is removed only after its actual clients have migrated.

The refactor must not create two authoritative command implementations.
AppService owns new application semantics; the legacy adapter owns only legacy
field aliases, response wording, and compatibility behavior.

## Refactor Plan

### Phase 0 — Consolidate Existing In-Process Boundaries

This phase may begin now and adds no AppServer package.

Implementation status (2026-07-30): implemented. TUI and legacy RPC now use
current-Session operation resolvers; turn-only abort and the TUI stop composite
are distinct; approval presentation uses the explicit interaction port and a
generation-safe lease; pending queue projection no longer discovers Session
methods dynamically. Shared prompt operations have one settled-return
contract across TUI, Scenario, and Work adapters, verified by a reusable
Product contract suite. Legacy RPC lifecycle, model/settings, transcript, and
Bash/maintenance, and command-catalog commands are separate command groups
while preserving the existing JSONL wire. Each newly extracted group accepts
a narrow private Product protocol instead of a shared all-capabilities RPC
Session interface. The final conversation group owns prompt/control/state and
prompt-task settlement. Harness supplies structured, staged, and raw JSONL
playback; Product tests contain no private RpcHost input/task-drain side door.
The complete RPC package passes mypy.

Phase 0 is closed. Further application-boundary extraction requires a Phase 1
trigger; file size or the existence of legacy commands is not sufficient.

1. Keep shared primitive input/queue/lifecycle mutations in
   `SessionOperationRuntime`; do not move command execution, Bash, catalogs, or
   query capabilities into it.
2. Have Product composition supply a current-session operation resolver
   (`Callable[[], SessionOperationRuntime]`) to TUI prepared callbacks and RPC
   command groups. It resolves or rebinds after new/restore/fork/clone rather
   than retaining one runtime bound to a stale Session.
3. Preserve two explicit interruption contracts: `abort_turn` is the shared
   Session primitive and legacy RPC behavior; `stop_active_interaction` is the
   TUI composite that also clears queues and aborts selected command execution.
4. Add the optional `SessionApprovalInteractionPort` over the existing
   `InteractiveApprovalResolver`; remove TUI approval `getattr` discovery.
5. Replace other dynamic session method discovery in TUI/RPC bindings with
   existing explicit capability ports where the operation is already shared.
6. Keep Harnesstui prepared-run contracts free of concrete Session types.
7. Continue splitting legacy RPC command groups without changing its wire.
8. Add dependency tests for Harness, Channel, Work, Harnesstui, and RPC.

Exit criteria:

- prompt/steer/follow-up/abort-turn primitives use the same
  `SessionOperationRuntime` semantics in TUI and RPC;
- TUI `stop_active_interaction` retains its queue-clear and command-abort
  behavior, while legacy RPC `abort` remains turn-only;
- ApprovalBroker remains the only pending-approval lifecycle authority;
- TUI and RPC resolve the current Product-bound operation runtime after every
  Session transition rather than retaining stale controls;
- Product-specific projection remains outside the session operation core;
- Harness and Work do not import Channel; and
- TUI playback and legacy RPC regressions pass;
- RPC async and framing tests use the public Harness testing API rather than
  private host methods; and
- the RPC package passes its focused type check.

### Phase 1 — Extract One Protocol Slice

Trigger: the first accepted external client or daemon implementation.

1. Create `loushang.appserver.protocol`.
2. Define initialize, session snapshot, turn control, event, and interaction
   values only.
3. Map the slice to existing session ports.
4. Add protocol schema and round-trip tests.
5. Leave unconverted legacy RPC commands on the compatibility path.

Exit criteria:

- the slice contains no Product, Session implementation, TUI, or wire-format
  objects;
- invalid request, cancellation, interaction, and close behavior are defined;
- no generic dictionary escape hatch is used to hide unmodeled commands.

### Phase 2 — Add AppService And In-Process Contract Tests

Trigger: the protocol slice needs a service-owned Session or more than one
client adapter.

1. Add the Session registry and thin AppService dispatcher.
2. Implement `InProcessAppClient`.
3. Run the same semantic scenarios against direct service and in-process
   client paths.
4. Implement one ordered server-output path and deterministic disconnect.
5. Keep daemon, WebSocket, and durable replay out of scope.

Exit criteria:

- service behavior is expressed through existing Session/Work ports;
- closing a client invokes approval presenter cleanup and the existing
  ApprovalBroker denies all pending Session approvals;
- event/approval/turn completion order is deterministic; and
- no Agent loop, Policy, Work scheduler, or presentation code moved into
  AppService.

### Phase 3 — Migrate Harnesstui

Trigger: the Product elects to make the embedded AppClient path its
authoritative Harnesstui binding. A remote transport is not required yet.

1. Complete the checked Harnesstui capability inventory.
2. Extend the typed protocol only for existing server-backed capabilities
   required by that inventory.
3. Bind the existing conversation adapter to `AppClient`.
4. Retain all presentation and terminal components.
5. Route approvals through interaction requests rather than normal input.
6. Run existing playback suites through the in-process client.

Exit criteria:

- Harnesstui imports no AppService implementation;
- the migrated Product binding has no concrete Session side door;
- local UI commands remain local; and
- transcript, command/completion, model/settings, queue, surface, status,
  approval, session lifecycle, and multi-agent playbacks pass.

### Phase 4 — Independently Gated Remote Slices

Phase 4 is not one mandatory feature bundle. Implement only the slice required
by an accepted deliverable, in this order where dependencies apply.

#### 4A — First Remote Client

Trigger: one IDE, desktop, or SDK client must connect across a process
boundary.

1. Add one remote transport, not several simultaneously.
2. Add the minimum transport authentication required by that deployment.
3. Run embedded-versus-remote semantic parity and Harnesstui playback suites.
4. Define bounded output and slow-client disconnect behavior.

Exit criteria:

- changing connection type does not change user-visible conversation order;
- bounded queues and slow clients have defined behavior; and
- remote clients cannot receive raw domain objects or secrets.

#### 4B — Daemon Ownership

Trigger: sessions must outlive one CLI/client process.

1. Add daemon lifecycle around AppService.
2. Define which Session state is persisted and what daemon restart restores.
3. Add idempotency admission for externally retried side effects.
4. Start reconnect with a fresh snapshot; add event replay only if required.

Exit criteria:

- daemon restart and Session/durable-run ownership are explicit;
- an external retry cannot duplicate an admitted side effect; and
- disconnect cannot strand a blocking interaction.

#### 4C — Multiple Clients

Trigger: more than one client must observe or control the same live Session.

1. Add observer/controller ownership.
2. Pin each interaction to one controller connection generation.
3. Reject observer, duplicate, late, and superseded-controller responses.
4. Close the Approval presenter lease when that controller disconnects, which
   denies all pending approvals for the Session; notify any other interaction
   lifecycle owner, such as `RemoteUiContext`, of the disconnect through its
   own adapter.

Exit criteria:

- exactly one response can resolve an interaction;
- controller disconnect denies all pending Session approvals through the
  existing resolver-owned close path;
- no AppService shadow future remains for Approval or extension UI; and
- a new controller cannot answer an interaction issued to the old controller.

## Testing Strategy

The refactor uses scenario parity rather than implementation-level equality.

Required suites:

- session operation contract tests with an independent fake Product;
- legacy RPC wire regressions;
- App protocol encode/decode and unknown-field/version tests;
- the same turn abort, composite stop, queue, and approval scenarios through
  each AppClient adapter;
- multi-client controller/observer tests when that feature exists;
- disconnect with a pending approval, observer response, stale-controller
  response, duplicate response, and late response;
- legacy extension UI request ordering, timeout, response, and disconnect
  tests while `RemoteUiContext` remains active;
- snapshot plus ordered-event convergence;
- Harnesstui playback for streaming, approval, `/agents`, surfaces, resize,
  abort turn, composite stop, and resume; and
- import-boundary tests for every arrow in the target graph.

In-process tests must not pass only because they bypass ordering or lifecycle
rules that the remote transport enforces.

## Explicit Non-Goals

This refactor does not:

- replace SessionFacade with a second facade;
- create a second approval future, timeout, fallback, or cancellation owner;
- shadow `RemoteUiContext` pending futures while the legacy extension UI
  lifecycle remains active;
- add a universal command dictionary;
- put application commands into Channel envelopes;
- add WebSocket, HTTP, daemon supervision, or SDK generation before a real
  client exists;
- move Policy/Approval into the transport;
- make every local TUI action a service round trip;
- promise exactly-once execution across process crashes; or
- introduce a general multi-user permission system.

## Review Questions

Review should remain constrained to these questions:

1. Does the dependency graph remain acyclic and preserve current ownership?
2. Does the plan reuse SessionFacade, SessionOperationRuntime, Channel, and
   Harnesstui prepared ports instead of duplicating them?
3. Are the AppServer extraction triggers concrete enough to prevent premature
   implementation?
4. Can each phase ship and be tested without implementing a later phase?
5. Are any listed responsibilities unnecessary for the stated future clients?
6. Do Session transitions re-resolve operation and presentation bindings
   without retaining a stale Session?
7. Are turn abort, composite TUI stop, ApprovalBroker, and RemoteUiContext
   lifecycles kept distinct and authoritative?
