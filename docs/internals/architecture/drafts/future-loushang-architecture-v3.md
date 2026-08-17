# Loushang Future Target Architecture v3

[Architecture](../README.md) · [Drafts](README.md) ·
[Open SVG](../future-loushang-architecture-v3.svg)

## Status

Status: proposed target architecture.

This document explains the decisions and invariants shown in the v3 diagram.
It is not a description of the current Python package or public API surface and
does not authorize creating AppService, a daemon, WebSocket transport, a relay,
or distributed state synchronization ahead of an accepted delivery
requirement.

Current code, tests, and accepted ARDs remain authoritative. When this document
conflicts with them, the live source wins until a later ARD explicitly accepts
the target decision.

![Loushang future target architecture v3](../future-loushang-architecture-v3.svg)

The overview deliberately shows only coarse Product and Harness Capability
boundaries. Product resolver/factory contracts and the explicit choice between
Session-turn and Work submission semantics remain in the prose below; they are
not repeated in the diagram. Capability-internal Binding Facets are also left
out of the overview.

## Purpose

The target architecture supports two operating shapes without creating two
execution models:

- a small local Product TUI may bind Harnesstui directly to one embedded Product
  runtime and Harness instance;
- a daemon or cloud application host retains live Sessions and admitted Work
  runs while TUI, WebUI, IDE, and P2P peers attach, disconnect, and resume.

Both shapes reuse the same Product definitions, factories, Harness contracts,
and Product-owned semantics. They do not share a mutable Session or Work runtime
instance across process boundaries.

The primary mobile story is:

```text
Local Daemon starts a Coding Session
  -> phone attaches through an AppClient
  -> phone submits work and later disconnects
  -> Session / Work continues in the Daemon
  -> phone reconnects from a new attachment
  -> AppService returns a snapshot plus subsequent events
  -> the current controller handles any new approval interaction
```

## Core Decisions

### 1. Share definitions and factories, not runtime instances

A Product composition root supplies immutable definitions, factories, and
capability descriptors. The host uses them to construct a fresh Product runtime
binding for each admitted Session or Work execution.

The embedded instance and hosted instance may be created by the same factory,
but each owns independent mutable state, cancellation, transcript bindings,
approval presentation, and lifecycle.

The Product registry is therefore a narrow `ProductResolver`, not a runtime
service locator and not a capability-routing god object. AppService consumes
resolved Product ports; it does not import Coding, Research, PPT, or Design.

The target type shape is deliberately small. The names below are conceptual,
not current public API:

```python
class ProductResolver(Protocol):
    def resolve(self, product: ProductKey) -> ResolvedProductDefinition: ...


@dataclass(frozen=True)
class ResolvedProductDefinition:
    identity: ProductIdentityView
    capabilities: ProductCapabilityView
    create_session_binding: Callable[
        [SessionActivationContext], ProductSessionBinding
    ]
    create_work_binding: Callable[
        [WorkActivationContext], ProductWorkBinding
    ]
```

Resolution returns one immutable typed definition, never `dict[str, Any]`.
Identity and capability views are safe to cache. Each factory invocation
creates a new runtime binding; it cannot return a process-global mutable
Session, executor, Approval presenter, or Work runtime. The exact Product
binding protocols should be named only when the first AppService vertical slice
proves their required methods.

### 2. Select Session or Work semantics explicitly

Loushang does not infer durable business meaning from implementation details
such as the number of prompts, whether an artifact was produced, or whether an
approval was requested. The caller selects one of two explicit application
operations:

| Operation | Meaning | Route |
|---|---|---|
| `session_turn` / `run_once` | A lightweight interaction with no durable business commitment | Product conversation binding -> Harness |
| `submit_work` | An accepted business intent requiring a queryable, replayable terminal outcome | Product work preparer -> Work -> Product executor -> Harness |

The standard Coding Channel `SubmitCodingTurn` adapter is a Work operation and
uses the second route. A local lightweight Coding prompt may use the first
route. Method enactment always uses Work.

This distinction follows the Work definition: Work is a persistent commitment,
not a synonym for every message, turn, Agent invocation, or in-process task.

### 3. Keep Product semantics in Product bindings

A hosted Product runtime binding contains narrow capabilities rather than one
universal Product interface:

- Conversation capability: prompts, admitted tool selection, policy, and Session
  operations;
- Work preparer: Product intent to `WorkOperation`, current `WorkRunSpec`, and a
  future frozen `WorkPlanSpec`;
- Work execution binding: the Product-owned `WorkDomainExecutor` that binds a
  Work step to Harness execution;
- event and interaction projection: Harness/Work facts and Product-specific
  views for application clients.

Product bindings retain domain language, prompts, model and provider policy,
tool selection, artifact content, validation, event vocabulary, and
presentation decisions. They do not reimplement AppService, Work, or Harness.

### 4. Match remote Agent contracts to interaction semantics

Remote placement does not imply a persistent Agent session. A remote Agent may
be exposed as one of three progressively stronger capabilities:

| Interaction semantics | Minimum contract | Architectural treatment |
|---|---|---|
| One-shot invocation | `invoke(request) -> result` | Ordinary admitted Harness tool/capability; not multiagent |
| One-shot asynchronous job | `submit(request) -> RunRef`, `await_result`, `cancel` | Job/delegation capability; no addressable collaboration actor |
| Stateful collaboration | `spawn`, `send`, `wait`, `list`, `interrupt`, `close` | Multiagent collaboration port with follow-up and steering semantics |

An execution may have progress without requiring one stateful server process,
and an asynchronous `RunRef` does not imply an attachable Agent session. Job
state may live in a queue or store and be served by interchangeable instances.
V3 therefore does not define one universal provider containing `invoke`,
`submit`, `attach`, `send`, `inspect`, `cancel`, and `close`.

The LSP analogy applies only to the local-client/remote-service boundary. The
model calls a stable admitted tool; its handler invokes an injected capability
client; a transport adapter calls the remote service. The model-visible tool
schema is not the wire protocol. The client adds protocol version, request and
caller identity, idempotency, authorization scope, and event cursor fields that
the model must not control.

```text
local Agent
  -> admitted tool
  -> capability client
  -> stdio JSON-RPC | IPC | HTTP | gRPC | A2A adapter
  -> remote capability service
```

The first collaboration implementation binds one explicitly selected provider
for a Session-scoped collaboration Capability: either the current local
`SessionMultiAgentRuntime` or one remote collaboration service behind the same
tool façade. If alternative providers are admitted, this is an Exclusive
Replacement surface: Plugin identity and discovery order are not selection
policy, although a Plugin may carry an admitted Extension provider. The first
implementation does not require per-child mixing of multiple local and remote
providers in one logical tree. That simpler choice keeps the remote service
free to own its child tree and mailbox while the local Host retains Capability
admission, authority, bounded result projection, and Product interaction
routing.

An internal `AgentExecutionPort` is optional and deferred. It is justified only
when the Host must transparently mix physical backends inside one logical tree
or provide attach, lease, fencing, checkpoint, orphan detection, and recovery
under one local control model. It is then extracted from at least two proven
backends. A remote `invoke` client, an asynchronous job service, or a
Session-level remote collaboration adapter does not by itself require that
port.

AppService is not a dependency of the capability client. Product/Host
composition admits and injects the client. Channel is not its worker transport,
and Work participates only when the invocation is also an accepted durable
business commitment. A2A may be one adapter for an independent external Agent;
a Loushang-controlled service may use a smaller worker protocol without
changing the tool contract. See
[Remote Agent Capability Boundary](../harness/multiagent/remote-agent-capability-boundary.md).
The implemented local CLI P0 is documented in
[One-Shot Agent Invocation Tool Boundary](../harness/agent-invocation-tool-boundary.md):
it proves the admitted-tool path without introducing an execution provider,
job lifecycle, or new multi-agent runtime abstraction.

### 5. Keep model-contingent cognition outside the stable substrate

Model capability may absorb more planning, decomposition, reflection, context
selection, generic verifier prompting, and tool-selection heuristics over time.
Those features are model-contingent cognitive scaffolds, not durable system
authority. V3 therefore does not grow the Agent loop or AppService around the
current limitations of a particular model generation.

The stable Loushang substrate owns invariants that remain necessary even when a
model becomes substantially more capable:

- authority, Policy, Approval, sandboxing, and least privilege;
- effectful tool execution, idempotency, cancellation, retry, and failure
  convergence;
- Conversation, transcript, Session, event ordering, persistence, and recovery;
- Product-owned Capability admission, tenant/workspace isolation, and secret
  boundaries;
- multi-agent communication, concurrency, and cross-process coordination
  contracts; and
- Work admission, authoritative events, artifacts, evidence, acceptance, and
  terminal outcome.

The low-level Agent loop remains a mechanical model/tool protocol engine. It
may expose narrow seams for context transformation, tool preflight, result
projection, events, and cancellation, but it does not own a planner, verifier,
plan mode, todo policy, memory policy, or Product semantics. Model-contingent
features belong in Product-owned strategies behind declared Capability Slots,
admitted Extensions or Skills, or explicitly selected Runtime Profile
bindings.

Planning and verification each have a durable and a disposable form:

```text
plan as cognitive aid
  -> replaceable model strategy

plan as coordination / approval / resume / audit contract
  -> Product binding and Work-owned fact after acceptance

self-verification prompt or fixed verdict format
  -> replaceable model strategy

compiler / test / scanner / independent-environment evidence
  -> Product-interpreted evidence correlated by Work
```

At the Method boundary, the durable rule is: **Method specifies what must hold;
the model decides how to achieve it.** Method owns reusable roles,
constraints, gates, expected artifacts, acceptance conditions, and evidence
requirements. Within that envelope the model may change its decomposition,
tool order, reasoning strategy, or use of subagents as model capability evolves.
When a plan must coordinate people or agents, gate approval, survive restart,
or support audit, the Product binds it into a run-specific contract and Work
accepts it as an authoritative fact. See [Method Architecture](../method/README.md).

Presentation invariants are also part of the stable substrate. Native TUI
playback scripts input, streaming, resize, surface, and control-flow events
through render planning and terminal-operation boundaries, while HarnessTUI
playback adds neutral conversation routing, state snapshots, and real
screen-loop fixtures. This playback is not a second transcript or Work replay
engine: it is an executable client contract proving that snapshots and events
produce bounded, cursor-safe, scrollback-safe, deterministic terminal effects.
The same playback substrate remains useful for embedded and AppClient-backed
profiles and across different Products. See [TUI Architecture](../tui/README.md)
and [Terminal Playback Harness](../tui/native-terminal-core/key-designs/KD-010-terminal-playback-harness.md).

An architectural feature should not become kernel ownership or an
irreversible persistent schema merely because today's models need it. A useful
test is: if a future model with materially stronger native reasoning could
remove the feature without weakening authority, evidence, persistence, or
coordination, the feature stays outside the stable substrate.

Model capability may swallow Agent cognition; it must not swallow authority,
effect control, evidence, persistence, coordination, or Work truth.

## Client And Process Profiles

### Embedded TUI profile

```text
Product TUI composition
  -> Harnesstui
  -> Conversation UI binding
  -> Embedded Product runtime
  -> per-Session Harness instance
```

The binding chooses its backend at startup. Harnesstui continues to own terminal
input, layout, rendering, local surfaces, and playback.

An embedded Product may persist a local transcript, but v3 defines no automatic
sync, merge, or runtime handoff to a daemon. The embedded profile is therefore
local-only and non-migratable. A Session that must survive the foreground
process or support multi-device attach uses AppService from the beginning,
possibly through an in-process `AppClient` before a daemon exists.
The default-native-TUI delivery choice in
[AppService Hosted Boundary With An Embedded TUI](appservice-embedded-tui-hosted-boundary-plan.md)
keeps this as an explicit Product election rather than the default local path.

### Hosted profile

```text
TUI / WebUI / IDE / P2P peer
  -> AppClient contract
  -> versioned App protocol
  -> endpoint adapter
  -> AppService
  -> resolved Product Session or Work port
```

The Application Host may be a local daemon or a cloud AppServer. Deployment
changes placement, isolation, admission, and credentials; it does not change
Product, Work, or Harness semantics.

Client processes own presentation and user interaction only. A P2P peer is a
remote application peer for pairing, attach, resume, and notification. It is
not `loushang.agent` and does not participate in the Agent loop.

## App Contract, Channel, And Transport

The diagram places App Contract and Channel as parallel semantic boundaries
above Transport. They do **not** define one mandatory serialization pipeline.

### App Contract

The App Contract is the stable client-facing application API. Its protocol
values cover, initially:

- initialization and capability summary;
- Session open, attach, detach, snapshot, and close;
- prompt, steer, follow-up, abort-turn, and selected capability operations;
- work submission and observation;
- ordered application events;
- interaction request/response, initially approval; and
- version negotiation and typed errors.

Protocol values are client-safe projections, not serialized SessionFacade,
Product runtime, or widget objects.

### Channel

`loushang.channel` remains a narrower operation/event boundary. It carries
`WorkOperation`, `WorkEvent`, and selected transport-safe
`RuntimeEventView` values. It may provide correlation, subscription, cursor,
resume, and delivery semantics for those families.

App protocol commands are not added wholesale to `ChannelEnvelope`. Channel is
not the transport behind every `AppClient` request and does not become a
universal UI command bus. AppService consumes injected Channel/Work ports where
the operation requires them and direct Session ports where it does not.

### Transport

In-process calls, local IPC, HTTP/WebSocket, P2P direct connections, and relay
fallback are transport adapters over admitted protocol values. They own
framing, connection lifecycle, limits, and delivery mechanics. They do not own
Session commands, Product discovery, Work state, approval policy, or UI layout.

### Duplex direction

Client input and server delivery are separate directions even when one duplex
connection carries both:

```text
client input
  AppClient -> transport -> endpoint -> AppService
    -> Product Session port -> Harness                  # session_turn
    -> Product Work port -> Work -> Product executor   # submit_work

server delivery
  Harness / Work facts -> Product projection -> AppService
    -> endpoint -> transport -> AppClient
       events / snapshots / interaction requests
```

Only payload families admitted by the Channel contract use a Channel endpoint.
Neither `session_turn` nor `submit_work` is forced through Channel merely
because the AppClient connection is remote. A standard Coding Channel adapter
does use Channel and Work by its own explicit contract.

## AppService Boundary

AppService is the single hosted application coordinator. It owns:

- principal and device context;
- attachment identity and the current control lease;
- idempotency admission for externally retried side effects;
- Session/Work routing through injected Product ports;
- client-safe snapshots and revisions;
- subscriptions and bounded delivery buffers;
- request, event, and interaction routing; and
- deterministic detach and close behavior.

AppService does not own:

- Agent loops, model calls, tool execution, or sandbox policy;
- transcript or Work lifecycle truth;
- Method selection, compilation, or Method-to-Work conversion;
- Product prompts, tools, artifact semantics, or event vocabulary;
- approval futures, timeout, fallback, cancellation, or decision policy; or
- terminal, WebUI, IDE, or mobile rendering.

Host infrastructure may add resource admission, a live Session routing table,
execution dispatch, workers, and bounded outbound delivery. Execution remains
serialized within one Session while independent Sessions may run concurrently.

At composition time AppService receives an explicit `ProductResolver` plus
host-owned providers for admitted Session, Work, and optional Channel ports.
The exact provider protocols remain part of the first vertical slice; the
invariant is that AppService never consults a global registry, imports a
Product implementation Python package, or performs provider discovery while
dispatching a request.

The host maintains a live Session routing table, not a filesystem directory or
persistent Session catalog.

## Method, Work, Harness, Agent, And AI

The semantic ownership chain is:

```text
MethodPlan
  -> Product Work Preparer
  -> WorkRunSpec / future WorkPlanSpec
  -> Work
  -> Product WorkDomainExecutor
  -> Harness
  -> Agent
  -> AI
```

Method owns reusable ways of working, constraints, expected artifacts, and plan
preparation. A MethodPlan returns to the Product work preparer because Product
owns the conversion from method vocabulary into an executable Work contract.
Method never executes Harness directly.

Work owns an accepted business commitment, idempotent operation admission,
run/plan/step lifecycle, terminal outcome, authoritative Work events, replay,
and Work-correlated `ArtifactRef` values. Work does not own an Agent turn.
Likewise, an Agent turn does not own a Work run.

Harness owns reusable Session, transcript, context, tools, approval integration,
retry, compaction, workspace, and sandbox mechanisms. Harness does not import
`loushang.work` or a Product implementation Python package. The Product executor
is the adapter that connects a Work step to Harness without reversing that
dependency.

Agent owns the execution loop and calls AI. Harness and Agent coordinate tool
execution through admitted tools and sandbox policy; the AI layer remains
independent of Harness and Product code.

### Product Capability Requirement resolution and scoped activation

The overview uses stable owner-level Capability IDs. Its initial Harness
boundaries are `harness.workspace`, `harness.resources`, and
`harness.session`; Product-owned examples include `coding.lsp` and
`coding.arch`. A Capability Plan node is an ID and its declared requirements,
while a live runtime node is a Mounted Capability bound to a concrete scope.
Product, Plugin, Package, and Extension identities remain composition,
provenance, delivery, or admission facts rather than graph nodes.

In Capability dependency diagrams, `A -> B` means A depends on B. Internal
providers, tools, permissions, and narrow injected facet views do not become
additional top-level nodes. The accepted
[Capability Dependency And Mount Lifecycle](../harness/capability-dependency-and-mount-lifecycle.md)
decision owns the detailed planning, binding, disposal, and diagnostic rules.

Method and Skill resources may declare opaque Product Capability Requirement
values, such as `coding.arch`. They do not name Harness `ToolPackDefinition`
values, register executable handlers, or grant themselves execution authority.
For structured work, the Product work preparer carries the requirement into the
run-specific Work contract and the Product executor resolves it through the
Product's admitted Capability catalog. For a lightweight Session turn, the
Product conversation binding performs the equivalent resolution without
creating a Work run.

A Product Capability Requirement may resolve to an admitted Capability Bundle
for one Capability ID. That resolution may separately activate related Product
Capability Bundle resources and one or more family-specific Capability Packs,
including a named tool pack. The Product retains the requirement mapping,
Capability Mount defaults, bundle activation, and policy; Harness retains
contribution resolution, allow-list enforcement, live tool rebinding, sandbox
and approval integration, and scoped activation mechanics. A Product may expose
`disabled`, `on_demand`, and `always` Mount Policy, but no mode may bypass or
widen host admission, delegated execution restrictions, Session allow-lists,
or tool policy.

Scoped activation is additive and owner-aware. Manual selection, Product
defaults, a Skill invocation, and a Method/Work step may independently request
the same capability. Releasing one activation removes only that owner's request;
completion, failure, cancellation, and runtime disposal must all release their
owned activation idempotently. This capability activation scope is distinct
from the AppService control lease that selects which attached client may mutate
a Session.

### Method visibility in clients

V3 does not add `MethodPlanStatus` or `MethodStepStatus` to the base App
protocol. When a Product first needs to render method progress, its projection
may derive a Product-facing application view from Method identity and
Work-owned plan/step facts. Harnesstui consumes that view without importing the
`loushang.method` Python package.

A stable Method editing, steering, or inspection protocol is added only after a
Product surface requires it and defines its compatibility needs. The target
does not pre-commit that future view to `RuntimeEventView`, `WorkEvent`, or a
new App protocol value family.

## State And Persistence

Authority remains with the semantic owner:

| State | Authority | Notes |
|---|---|---|
| Conversation records | Product-bound Harness transcript runtime | Product/Host supplies the codec, store, path, and retention policy; embedded local state is not automatically merged |
| Client snapshot and revision | AppService projection | Derived from authoritative Session/Work state; it is not a second transcript store |
| Work run, events, replay, and Work-correlated artifacts | Work event log | Required only for admitted Work |
| Method resources and reusable definitions | Method catalog | MethodPlan execution facts belong to Work |
| Workspace files and sandbox mechanism | Harness/workspace boundary | Product owns content and validation |
| Product artifact meaning and materialization | Product | A lightweight Session output need not become a Work `ArtifactRef` |
| Session approval audit events | Harness event source plus an optional Product/Host retention sink | Runtime delivery is observable but not durable by default |
| Attachment, lease, device, and idempotency records | AppService control plane | These are application coordination facts, not transcript facts |

There is no v3 state-merge protocol between an embedded Session and a hosted
Session. Import or migration, if later required, must be an explicit Product
operation with conflict and identity semantics; it must not be an accidental
side effect of attach.

## Events, Snapshots, And Reconnection

AppService exposes a client-visible state stream as:

1. a snapshot at revision `N`; and
2. ordered events after revision `N`.

Each attachment has a bounded delivery buffer and cursor. When the requested
cursor is no longer retained, AppService returns `SnapshotRequired`; the client
loads a fresh snapshot instead of guessing across a gap.

Attachment disconnect is not Session or Work cancellation. The daemon or cloud
host continues the admitted execution, subject to its resource and retention
policy. Reconnection creates a new attachment generation and control lease; it
does not resurrect transport-owned futures.

Durable Work replay and client delivery buffering are different mechanisms.
AppService must not create a second transcript or Work audit log merely to
support reconnect.

## Approval And Interaction Routing

`ApprovalBroker` remains the sole owner of pending approval futures, timeout,
fallback, cancellation, and resolution. AppService only projects an existing
request, validates the responding principal, attachment generation, control
lease, and idempotency key, then forwards the response to the bound Harness
approval interaction port.

An ordinary Session approval is correlated by Session, invocation, interaction,
and action identifiers. A WorkRun correlation exists only when the invocation
was admitted through Work. Harness currently emits session-scoped tool approval
request/resolution runtime events, so a lightweight approval is correlated and
observable without inventing a WorkRun.

Runtime events are not, by themselves, a durable audit log. V3 does not require
approval decisions to be inserted into transcript records, copied into every
client snapshot, or written to a second approval store. If a Product or
deployment requires historical compliance queries outside Work, it must bind an
explicit Session audit sink and retention policy to the existing approval audit
events. AppService may project retained session-scoped approval history, but it
does not become its authority or lifecycle owner.

Multiple observers may attach, but only the current controller may submit
mutating input or answer a blocking interaction. Observer, stale-generation,
duplicate, and late responses are rejected without changing Broker state.

## Cloud Trust And Accounting

A cloud AppServer applies tenant scope before resolving a Product runtime,
Session, store, workspace, or credential reference. The AppService
control/trust plane owns principal/tenant authorization policy and lease
admission. AppService, or an injected authorizer at its boundary, enforces that
decision on every route; it does not decide Product tool/policy outcomes.

Supported credential policies may include:

- principal-provided BYOK references; and
- host-managed secret references authorized for the tenant and Product.

Secret resolution belongs to the credential owner/resolver. Secret values are
not exposed as App protocol state. Usage collection and cost attribution belong
to Host Infrastructure and correlate provider/model usage with a principal,
tenant, Product, Session, and optional WorkRun as policy requires. Store
namespaces, workspace roots, artifact access, logs, caches, and worker placement
are all tenant-scoped in the cloud profile.

The exact authorization model, retention policy, quotas, billing export, and
secret backend require separate security and deployment decisions before a
cloud implementation is accepted.

## Explicit Non-Goals

The v3 target does not require:

- routing every Product turn through Work or Method;
- turning Channel into the universal App protocol;
- sharing mutable runtime instances across processes;
- automatic Embedded-to-Daemon transcript merge;
- AppService-owned approval or Extension-interaction futures;
- a public P2P relay in the first AppService release;
- a base App protocol for MethodPlan/MethodStep state before a Product needs to
  render, inspect, or steer it;
- treating every remote Agent call as a stateful collaboration Session;
- one universal remote-Agent interface or a mandatory `AgentExecutionPort`;
- Product imports inside AppService; or
- one universal Product runtime binding capable of arbitrary injection.

## Staged Delivery

The overview sequence below is subordinate to the detailed phase gates in
[Application Service Refactor](application-service-refactor.md):

1. Preserve the direct embedded Product/Harnesstui/Harness path, finish the
   narrow Product runtime contracts, and complete a checked inventory of every
   server-backed Harnesstui capability. Each item must map to an App command,
   read model/event, interaction, or explicitly local UI operation.
2. Extract the smallest versioned App protocol slice and its semantic contract
   tests. Do not hide unmodeled capabilities in a generic dictionary command.
3. Introduce AppService and `InProcessAppClient`; add one ordered server-output
   path only when duplex ordering requires it.
4. If a Product elects AppClient as its Harnesstui backend, migrate only after
   the capability inventory closes. The migrated binding retains no concrete
   Session side door.
5. Add the local daemon and IPC transport so Sessions outlive one foreground
   client and support attach/detach.
6. Add snapshot revision, bounded delivery, cursor handling, and
   `SnapshotRequired` before promising reliable mobile reconnect.
7. Add WebUI/IDE and managed-channel adapters over the same App Contract.
8. Add cloud tenant isolation, authorization, credential policy, usage
   attribution, quotas, and worker admission before multi-tenant deployment.
9. Add P2P direct transport and relay fallback only after identity, pairing,
   authorization, and reconnect semantics are stable.

Two capabilities have independent gates rather than mandatory phase numbers:

- Before exposing embedded-to-hosted transfer, each Product explicitly chooses
  `no migration`, export/import only, or a migration operation with identity and
  conflict semantics. Attach never implies merge.
- Before exposing Method progress, inspection, or steering, a Product identifies
  a consuming surface and defines the minimum Product-facing projection and
  compatibility contract.
- A remote Agent starts with the weakest sufficient contract: `invoke`, then an
  asynchronous job only when execution outlives one tool call, then
  collaboration only when steering or follow-up is required. Transparent mixed
  placement and a common execution port require a separate proven need.

Each phase must preserve the embedded fast path, Product neutrality, Work and
Harness dependency direction, and a single lifecycle owner for every pending
interaction.

## Related Decisions

- [Application Service Refactor](application-service-refactor.md)
- [AppService Hosted Boundary With An Embedded TUI](appservice-embedded-tui-hosted-boundary-plan.md)
- [Agent, Harness, And Product Adapters](../agent/ARD-001-agent-harness-and-product-adapters.md)
- [Harness Product Runtime Core Boundary](../harness/product-runtime-core-boundary.md)
- [Capability Dependency And Mount Lifecycle](../harness/capability-dependency-and-mount-lifecycle.md)
- [Capability Variation And Replacement Boundary](../harness/capability-variation-and-replacement-boundary.md)
- [Session Facade Boundary](../harness/session-facade-boundary.md)
- [Channel Architecture](../channel/README.md)
- [Work Architecture](../work/README.md)
- [Method Architecture](../method/README.md)
- [Remote Agent Capability Boundary](../harness/multiagent/remote-agent-capability-boundary.md)
- [One-Shot Agent Invocation Tool Boundary](../harness/agent-invocation-tool-boundary.md)
