# AppHost Top-Level Placement

[Architecture](../README.md) · [Drafts](README.md) ·
[Product And Platform Host Glossary](../../glossary/loushang-product.md) ·
[AppService Hosted Boundary](appservice-embedded-tui-hosted-boundary-plan.md) ·
[Hosting Support Boundary](../hosting/key-designs/hosted-application-support-boundary.md)

## Status

- ID: `APPHOST-DP-TOP-LEVEL`
- Kind: package-placement decision
- Scope: Loushang
- Parent: none
- Authority: normative target proposal
- Design status: proposed
- Implementation status: not-started
- Owner: Loushang architecture

## Current, Target, And Delta

### Current

- The [Product glossary](../../glossary/loushang-product.md) defines one
  logical Platform Host that owns process-level Product discovery, OEM
  selection, Product routing, shared-service composition, and final Runtime
  release across CLI, TUI, RPC, Web, and embedded profiles.
- Product-specific entrypoints currently assemble those concerns directly.
- `loushang.harness.host` supplies Product-neutral single-Product stdio,
  line-input, mode, action, task-drain, and lifecycle mechanics. It is not the
  logical Platform Host and owns no Product catalog or deployment topology.
- There is no `loushang.apphost`, `loushang.appserver`, or
  `loushang.hosting` source package.

### Proposed target

The existing logical Platform Host receives one top-level physical owner:
`loushang.apphost`. AppHost supports independently elected embedded, hosted,
and daemon deployment profiles without creating a separate "Hosted Platform
Host" or a second Product registry.

### Explicit delta

Acceptance would introduce AppHost contracts, an admitted Product catalog and
router, scoped Product-runtime lifecycle, deployment-profile composition, and
outer launch/service adapters. It would not itself introduce AppServer,
Hosting, a daemon, or a GUI; those remain separately triggered dependencies.

This proposed placement does not reserve concrete public symbols. The names
below identify responsibilities that require component discovery before code
is added.

## Decision

```text
Product Package integration
  -> AppHost Product contracts
  -> Product public API
  -> Harness public runtime/composition contracts
  -> optional AppServer structural Product ports for a hosted adapter

loushang.apphost
  -> admitted Product catalog / router / scoped runtime lifecycle
  -> Harness public host and runtime mechanisms
  -> AppServer only in a hosted server profile
  -> accepted Hosting contracts only in an outer launcher or daemon-control profile

loushang.harness.host
  -> lower-level single-Product host mechanics
  -/-> AppHost / AppServer / Product packages
```

AppHost does not import a concrete Product package. Product Packages publish
descriptors, factories, and optional profile adapters through an admitted
registration boundary. Coding, PPT, Design, Research, Cowork, and OEM-defined
Products are peers. `loushang.harnesswork` is the canonical shared durable
Work subsystem used by Products; `loushang.work` is only its forwarding
compatibility facade. Work is not a Product unless a separately admitted
Product Package supplies its own Product Kernel and `product_id`.

## Product And Profile Axes

Product identity and delivery profile are orthogonal:

```text
Product identity
  Coding / PPT / Design / Research / Cowork / OEM Product

Host or presentation profile Plugin
  embedded TUI / desktop app / WebUI / remote client
```

A CodingTUI Plugin and a CodingApp Plugin may be installed, enabled, and
released independently while sharing the Coding Product Kernel, `product_id`,
Session semantics, tools, policy, transcript, and Product Factory. They become
different Products only if each supplies a distinct Product Kernel,
descriptor, factory, `product_id`, policy, and continuity identity.

These are canonical manifest-backed Plugin contributions, not a second AppHost
Plugin kind, manager, registry, or lifecycle. The existing Product/OEM Plugin
system owns manifest parsing, source trust, desired enablement, immutable
content identity, activation generation, update, retirement, and final
deletion. Product/OEM policy admits a profile contribution before any
executable entrypoint is imported. AppHost receives only an immutable admitted
profile descriptor and factory, selects one for the elected deployment
profile, and owns the resulting profile instance and lease.

Profile Plugins cannot replace AppHost Product admission, AppServer
authentication, AppService authorization, Hosting lifecycle invariants, or
another security owner. Daemon control is a built-in or OEM deployment profile,
not an ordinary Product Plugin contribution and not dynamically replaceable by
a Plugin.

## AppHost Responsibility Boundary

AppHost owns:

- Product contract vocabulary, catalog projection, selection, and routing;
- OEM/deployment admission orchestration over supplied policy;
- mapping a persisted `product_id` and Session context to a scoped Product
  Runtime handle;
- deployment-profile selection and assembly;
- process-local ownership and ordered release of Product Runtime handles; and
- outer launch/service-control adapters when those profiles are elected.

AppHost does not own:

- Product Kernel behavior, Product resources, or Product presentation;
- Product-internal Plugin, Capability, Resource, Tool, or Extension discovery
  and activation;
- Harness Runtime Profile resolution/binding or Product Runtime construction
  mechanics that a Product Factory already owns;
- App protocol, listeners, connections, framing, or delivery semantics;
- OS process, inherited endpoint, or service-instance mechanisms; or
- Session transcript, Blob, Work, log, trace, or artifact authority.

A Product Factory uses existing Harness mechanisms and returns one narrow,
scoped Product Runtime handle. AppHost never rebuilds a Capability graph,
Resource loader, Plugin manager, or Runtime Profile beside that owner.

### Existing Harness Host reuse

- Embedded and legacy Product profiles may reuse `ProductHostRuntime`,
  `ProductHostTaskTracker`, `ProductHostStreams`, and `CliApplicationRuntime`
  where their current contracts fit.
- AppHost does not parse the App protocol or build a second input loop.
- AppServer may reuse an admitted low-level stdio/line-reading mechanism, but
  owns its App Contract framing and connection semantics.
- AppServer does not reinterpret the legacy Product RPC command schema as the
  App Contract, and Harness Host does not acquire AppServer responsibilities.

## Product Contracts And Hosted Integration

The dependency inversion requires two distinct contracts:

1. AppHost core owns Product descriptor, catalog, factory, and scoped
   Runtime-handle contracts. They contain no AppServer types and may be
   implemented by every Product Package.
2. An optional `apphost.hosted` integration binder owns the AppHost-to-AppServer
   composition edge. A Product Package may contribute an outer hosted adapter
   factory that maps its public Product Runtime handle to AppServer's structural
   Product Session, Work, projection, and interaction ports. Product domain core
   does not import AppServer.

The AppHost catalog records only Product/OEM-admitted descriptors, factories,
profile contributions, and optional hosted integration factories. The hosted
binder selects from that immutable catalog; it does not discover by importing a
Product-internal module. AppHost core therefore need not import AppServer,
Harness never returns AppServer types, the embedded profile does not import
AppServer, and AppServer never imports a Product package.

Product Factory is an outer composition contract, not another Session or
Package runtime. Its implementation composes or delegates to the established
`ProductSessionRuntime`, `AgentTranscriptSessionFactory`, and
`PackageProductRuntimeFactoryPort` owners when those mechanisms are selected.
It must not duplicate their transcript, resume, Capability, Package, Plugin, or
disposal lifecycle.

The process-level AppHost catalog contains descriptors and factory
registrations, never one mutable Product Runtime singleton. Every new/open/
resume Session resolves an explicit `product_id` and creates an independent
scoped Product Runtime binding. A first delivery may allow only one Product ID
in an AppServer process, but that constrains allowed identities, not the number
or lifetime of Session Runtime handles. Multi-Product admission may remain
deferred without changing this per-Session cardinality.

### Multi-Aggregate Hosted Cardinality

One target-process AppHost constructs one AppService coordinator. That
coordinator may own zero or more application-level coordination aggregates,
including a future named mux, and each aggregate may reference several
independently scoped Session bindings. Aggregate count never creates another
AppHost, AppServer listener, application `RunLease`, or process-level
`RuntimeResourceOwner`.

AppHost does not import an aggregate type, index its selector names, arbitrate
membership, combine Session cursors, or acquire controller authority. Those
semantics stay inside AppService and its typed App Contract. AppHost retains
the scoped Product Runtime handles returned through that boundary and closes
AppService once during the process shutdown protocol; AppService then fences
all aggregate admission and attempts each distinct Session release exactly
once. Process readiness means that the AppServer/AppService admission boundary
is ready, not that any particular aggregate exists or is healthy.

## Pre-Routing Session Identity

Resume cannot select a Product by first invoking a Product-specific parser.
Every newly written durable Session therefore has a small, generic, versioned
**Session Identity Envelope** readable before Product selection. It contains:

- an envelope schema/version and stable Session or conversation identity;
- the required `product_id` and Product-owned locator/provider discriminator;
- an immutable continuity identity or reference sufficient to reject an
  incompatible authority; and
- no Product payload, credentials, mutable runtime state, or default Product.

A lightweight AppHost header reader validates only this envelope, resolves the
explicit Product descriptor/factory, and then transfers the opaque Product
locator to that Product's canonical transcript/continuity owner. The Session
catalog and resume summary project `product_id` from the same envelope. AppHost
owns the cross-Product envelope schema and read contract, not a second Session
store: the Product-selected canonical conversation/continuity owner persists
the envelope atomically with creation/publication of its durable Session.
`ConversationHeader` and Product runtime-profile metadata are Current evidence,
not yet a sufficient cross-Product routing contract: opaque metadata may omit
or rename Product identity. Legacy Coding Sessions therefore enter through an
explicit compatibility importer/migration that writes the new envelope, or
resume fails with typed `ProductIdentityRequired`. No missing or unknown
identity silently selects a default Product.

## Runtime And Launcher Split

Python objects and factories do not cross a process boundary. AppHost therefore
has two distinct roles, even if they eventually share a top-level package:

```text
controller process
  AppHost launcher
    -> immutable executable + argv/env/profile/state references
    -> Hosting Process Host or future Service Instance Controller

external supervisor
  -> complete foreground AppHost executable + signal/service-notification contract
  -/-> Hosting library

target process
  AppHost runtime/bootstrap
    -> resolve PlatformPaths once and load admitted descriptors/factories
    -> construct one AppService composition coordinator
    -> inject AppService into one AppServer connection runtime
    -> per Session: read identity envelope -> resolve product_id
                    -> create scoped Product Runtime + hosted binding
```

The launcher never sends an in-memory Product Factory, adapter, or AppService
through Hosting. A foreground invocation may enter AppHost runtime directly
without using Hosting at all. When a parent launches another foreground
process, it launches the complete AppHost executable rather than asking an
in-process AppHost to spawn its own AppServer object graph. AppHost is the
composition root: it constructs AppService, injects it into AppServer, and owns
whole-process shutdown ordering. AppServer neither constructs AppService nor
owns its semantic lifecycle.

## Deployment Profiles

| Profile | AppHost responsibility | AppServer | Hosting |
| --- | --- | --- | --- |
| embedded | select Product and compose its direct UI/runtime binding | absent | absent unless Product explicitly launches a child mechanism |
| hosted in-process | select Product and bind hosted adapter | in-process client/service/server runtime adapter | absent |
| foreground server | target-process bootstrap and orderly release | listener/stdio connection runtime | optional outer launcher only |
| externally supervised service | foreground entrypoint, readiness, graceful shutdown | listener/connection runtime | no library service controller; systemd/launchd/SCM/container is authority |
| library-managed daemon | daemon-control profile, process-level readiness/stop bridge, and target bootstrap | listener/connection runtime plus transport-state port | future Service Instance Controller |

Only the AppHost daemon-control profile may consume `hosting.service`:

```text
apphost daemon-control profile -> hosting.service -> complete AppHost process
AppServer -/-> Hosting
AppService -/-> hosting
```

Process liveness is not AppServer readiness, and neither is hosted Session
recovery. The target-process AppHost bootstrap exposes one process-level
readiness and stop boundary. It maps readiness to AppServer listener/admission
state and maps stop to the ordered AppServer drain plus AppService shutdown.
In a controller process, the AppHost daemon-control adapter converts the same
versioned serialized readiness/control specification into the injected Hosting
probe and stop behavior. An external supervisor invokes the same foreground
entrypoint and observes signals or platform service notifications. AppServer
supplies transport state but never imports Hosting; AppService owns its live
registry; Product/HarnessWork stores own durable truth.

## Cross-Scope Dependency And Responsibility

This parent decision, not the Hosting child scope, governs the sibling graph:

```text
HarnessGUI / HarnessWebUI -> AppClient + App Contract
AppServer -> AppService + App Contract + transport adapters
AppService -> injected structural Product ports
apphost.hosted -> AppHost Product contracts + AppServer Product ports
Product outer integration -> Product public API + Harness public contracts
AppHost launcher -> Hosting                              # optional

AppServer -X-> Hosting
AppService -X-> Hosting / concrete Product / UI frameworks
Hosting -X-> AppHost / AppServer / AppService / Product / UI frameworks
Harness -X-> AppHost / AppServer / concrete Product
```

| Scope | Owns | Explicitly does not own |
| --- | --- | --- |
| AppHost | Product catalog/routing, deployment composition, process-level assembly, Session-scoped Product binding ownership, ordered shutdown | Product semantics, App protocol, OS mechanism |
| AppServer | listeners, connections, authentication, framing, admission, correlation, bounded byte/frame buffers, connection status | AppService construction, Product routing, semantic detach, process supervision |
| AppService | hosted application coordination, logical attachment/mailbox/detach, snapshots, controller state, scoped Product-binding use | transport mechanics, Product discovery, OS process control |
| Product outer integration | adaptation from admitted Product Runtime handles to AppServer structural ports | global catalog, App protocol, Hosting |
| Hosting | local process, inherited endpoint, termination and optional generic service-instance mechanisms | AppServer/AppService/Product/UI semantics |
| presentation profile | rendering/input/client binding and bounded unsubmitted draft | Product identity, security replacement, durable Blob storage |

## Graceful Shutdown Protocol

AppHost owns one bounded, idempotent state machine for direct foreground,
externally supervised, and library-managed profiles:

1. mark the process `stopping`; reject new bootstrap, Product resolution, and
   profile activation;
2. tell AppServer to stop accepting connections and reject new request
   admission;
3. tell AppServer to stop reading new frames and freeze/report connection state;
   it does not drain writers yet and does not decide logical detach;
4. tell AppService to reject new Sessions, perform the sole logical detach,
   settle or interrupt admitted work by
   explicit Product policy, clean up interactions, close logical attachments,
   and request release through each Session-scoped Product binding's sole
   idempotent close port;
5. ensure AppHost releases all remaining Product Runtime handles and admitted
   presentation-profile leases;
6. drain-or-abort AppServer writers within the remaining deadline, then close
   transports, listener, and connection records;
7. close the process's one `RuntimeResourceOwner`; that owner alone revokes
   projections, drains admitted operations, and closes its ArtifactStore and
   `RunLease` as one transaction; and
8. publish `stopped` readiness and let the foreground process exit.

Repeated stop requests join the same operation. A phase failure is recorded but
does not skip later cleanup phases; shutdown returns an aggregate typed result
after all reachable owners have been attempted. One monotonic deadline bounds
the sequence. On expiry, a controller-side Hosting owner or external supervisor
may terminate, wait its configured grace period, kill the owned process tree,
and reap it. A direct foreground AppHost force-closes its remaining local
handles and exits nonzero; an external supervisor or operator remains the hard
termination owner if the process cannot exit. Forced termination reports only
raw process facts: it cannot claim semantic Session closure, delete persistent
data, or synthesize successful AppService cleanup.

## Machine-Resource Composition

Each process resolves or receives exactly one admitted, immutable
`PlatformPaths` at its outer composition root. A controller and its target are
separate processes: only normalized, serialized, policy-admitted overrides,
profile identifiers, and state references cross between them. The target
constructs and validates its own `PlatformPaths` once. OEM/deployment overrides
occur only at those roots. Narrow children are derived by lifecycle and
injected:

- service records and rotating observability use admitted subdirectories of
  `PlatformPaths.state`;
- listener/rendezvous paths use `PlatformPaths.runtime`;
- atomic intermediates use `PlatformPaths.temporary`;
- durable local Session transcripts use the canonical
  `$LOUSHANG_HOME/data/sessions` authority;
- durable Session Blob objects use
  `$LOUSHANG_HOME/data/session-assets/<session-id>`; and
- cwd `.loushang/sessions` and legacy `$LOUSHANG_HOME/sessions` remain
  compatibility discovery/import inputs, never peer writable authorities.

| Resource concern | Lifecycle owner | Placement/composition rule |
| --- | --- | --- |
| platform roots and run-lease primitive | Foundation | pure `PlatformPaths` plus Product-neutral `RuntimeScope`/`RunLease`; no Product or storage semantics |
| shared configuration and Resource discovery | Harness configuration/resources | project `.loushang` is reviewable declaration; private generated state is user-global; Product admits policy and content |
| application-run artifacts and machine inventory | Harness `RuntimeResourceOwner` | one effectful owner per application process; it alone owns the ArtifactStore/RunLease transaction and revocable projections |
| durable Session transcripts | Harness conversation/transcript owner selected by Product | canonical writable default is `$LOUSHANG_HOME/data/sessions`; compatibility roots are discovery/import inputs only |
| durable Session Blob objects | Harness Session Blob authority | canonical writable layout is `$LOUSHANG_HOME/data/session-assets/<session-id>` with immutable objects and manifest |
| clipboard/image capture or upload | active presentation-client adapter | Native TUI is Current; GUI/WebUI own browser/OS selection without transferring storage to AppHost/AppServer/Hosting |
| unsubmitted image/prompt draft | active client/input-router draft owner | bounded private client/run-local draft, removed on submit/cancel/disposal |
| submitted image bytes | Harness Session Blob authority | validate and promote before a pathless durable reference enters the transcript |
| logs, traces, diagnostics | producing observability service | bounded-retention state subdirectory; not Session content and not Hosting policy |
| AppServer listener and transport scratch | AppServer transport | listener under runtime root, atomic scratch under temporary root, one transport cleanup owner |
| AppService live registry and snapshots | AppService | live application state; durable recovery remains an explicit Product/store operation |
| service-instance record | future Hosting Service Instance Controller | narrow injected state subdirectory containing mechanism facts only; retire removes it only after the exact process tree is confirmed reaped, and cleanup failure leaves conservative residue |

Leaf AppHost, AppServer, AppService, Hosting, and Product adapters do not
reread path environment variables or infer cwd/home. Presentation Profile
Plugins own clipboard selection or upload and their bounded unsubmitted draft;
submitted durable images cross the Harness transcript-image boundary into the
Session Blob authority. AppHost, AppServer, and Hosting never become image
stores. The detailed lifecycle rules remain owned by
[Machine-Local Runtime Storage](../harness/machine-local-runtime-storage.md).

## Lifetime Model

Service-instance, application-run, and durable Session resources have different
owners:

- the optional Service Instance Controller owns only process identity,
  operation serialization, readiness attempts, and its service record;
- each AppHost target process is one application/presentation run and retains
  at most one `RuntimeResourceOwner` for that process lifetime; that owner alone
  acquires the `RunLease`, constructs the ArtifactStore, and exposes the
  immutable `RuntimeScope` and revocable projections;
- each hosted Session has its own transcript, Session Blob authority, and
  independently scoped Product Runtime binding; switching or adding Sessions
  does not imply another application `RunLease`;
- adding, attaching, or closing an AppService coordination aggregate does not
  imply another application `RunLease`, listener, service record, or
  `RuntimeResourceOwner`;
- a daemon target process likewise has one application-run scope for its
  process lifetime, separate from the controller's service record;
- Session transcript and Blob authorities outlive those process/run leases; and
- stopping the daemon joins AppService and Product Runtime disposal but never
  treats the service record or daemon RunLease as authority to delete Session
  data.

## Package-Placement Alternatives

### Place inside `loushang.harness`

Rejected. It would require Harness to import AppServer and deployment policy,
reverse the stable substrate direction, and confuse Platform Host ownership
with reusable single-Product mechanisms.

### Create `loushang.harnesshost`

Rejected. It would collide with the established `loushang.harness.host` term
while still suggesting that Product catalog and deployment topology belong to
Harness.

### Place inside one Product

Rejected. Coding, PPT, Design, Research, Cowork, and OEM Products must be peers
under one Platform Host contract.

### Top-level `loushang.apphost`

Proposed. It realizes the existing Platform Host role and may depend inward on
Harness, AppServer, and Hosting without making any of them depend outward on a
Product or UI.

## Acceptance And Implementation Gates

Before this placement becomes accepted:

1. AppHost component discovery must validate the contract/catalog/router,
   runtime/lifecycle, profile-composition, and launcher boundaries.
2. AppServer and Hosting dependencies must remain optional, profile-selected
   edges.
3. The Product integration contract must be proven with at least two
   semantically unrelated fake Product Packages.
4. Import gates must prohibit Harness, AppServer, AppService, and Hosting from
   importing AppHost or concrete Product packages, and must prohibit every
   AppServer subpackage from importing any Hosting package.
5. Product resume tests must prove persisted `product_id` routing and reject an
   unavailable or incompatible Product without default fallback.
6. Launcher tests must prove only serializable launch material crosses the
   process boundary and exercise readiness, graceful stop, and forced-timeout
   reporting.
7. Acceptance must update the parent Architecture Overview Diagram, subsystem
   map, governance scope tree, cross-scope decision catalog, and every affected
   scope document in the same architecture change; promote this draft into a
   parent-owned `decisions/ARD-*`, obtain common-parent and affected-sibling
   owner review, and add AppHost, Session Identity Envelope, and
   Host/Presentation Profile Plugin to the canonical glossary/alias governance.

Until implementation begins, `src/loushang/apphost` remains absent.
