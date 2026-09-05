# AppHost A0 Component Discovery And Refinement

## Status

- ID: `APPHOST-A0-DISCOVERY`
- Scope: `AppHost`
- Parent: `Loushang`
- Authority: descriptive — completed design validation evidence
- Design status: not-applicable
- Implementation status: not-applicable
- Owner: Loushang architecture

## Purpose

This record applied the Loushang component-identification method before an
AppHost package or public API existed. It validated the proposed top-level
placement with candidate functions, candidate components, an explicit
function mapping, and `split / merge / keep` decisions. It is evidence for the
[AppHost placement proposal](apphost-top-level-placement.md). ARD-003 now owns
the accepted placement and the canonical AppHost scope owns current status.

## Discovery Inputs

### Required scenarios

- start an embedded Product with no AppServer or Hosting dependency;
- run two semantically unrelated admitted Product Packages in one process
  catalog without importing either concrete package from AppHost;
- create, resume, and close several independently scoped Product Runtime
  bindings;
- concurrently attach two named-mux/profile consumers to one canonical Session
  without creating or closing the Product Runtime twice;
- reject a missing, unknown, or incompatible persisted `product_id` without a
  default Product;
- explicitly import legacy Coding or external Codex/Claude-shaped Sessions
  through a Product-owned copy-first adapter without mutating the source;
- select one admitted presentation/deployment profile independently from
  Product identity;
- bind an optional hosted profile to AppServer structural Product ports;
- launch a complete foreground AppHost executable from a controller without
  transferring Python factories across the process boundary; and
- stop admission, drain AppServer/AppService, release Product runtimes, and
  close the process resource owner exactly once.

### Facts at A0.0 discovery

- Product-specific entrypoints currently compose their own runtime and
  presentation concerns.
- `loushang.harness.host` owns reusable single-Product CLI/stdio lifecycle
  mechanics but no Product catalog, router, or deployment topology.
- `loushang.hosting` owns Product-neutral process, endpoint, child-session, and
  managed-preparation mechanics through H6.4; its Harness Worker consumer
  remains default-dark.
- At discovery time AppHost, AppServer, and the proposed AppService boundary
  had architecture drafts but no corresponding source packages. The canonical
  scopes now record AppHost A0.1--A0.4 and an AppServer contract-only slice as
  implemented; AppService remains absent.
- Existing conversation/runtime metadata is useful migration evidence, but is
  not yet the generic Session Identity Envelope required before Product
  routing.
- Current-directory `.loushang/sessions`, legacy user-global
  `$LOUSHANG_HOME/sessions`, and canonical
  `$LOUSHANG_HOME/data/sessions` have different discovery/write authority.
  AppHost must not infer, merge, or write those roots directly.
- Harness already exposes `SessionDiscoverySource`, `SessionLocator`,
  `SessionDiscoveryMetadata`, bounded multi-source catalog reads, alias/conflict
  projection, and canonical-versus-compatibility modes. Coding composition
  currently supplies the global, cwd-compatibility, and home-compatibility
  sources. A0 should adapt this owner and add the missing pre-routing Product
  envelope projection, not build a second discovery engine.

### Neighboring owners

- Product Packages own Product kernels, public Product APIs, descriptors and
  factories supplied through an admission boundary.
- Harness owns Product-neutral runtime/profile/session/tool/resource
  mechanisms, not the cross-Product catalog.
- AppServer owns listeners, connections, authentication, framing, admission,
  correlation, and transport status.
- AppService owns hosted semantic coordination and Session attachment/detach.
- Hosting owns local OS process/endpoint lifetime, not Product routing or App
  protocol.

## Candidate Function Inventory

| ID | Candidate function | Important non-owner |
| --- | --- | --- |
| `AH-F01` | define immutable Product descriptor/factory/runtime-handle contracts | concrete Product kernel |
| `AH-F02` | validate unique admitted Product and profile registrations | Plugin discovery implementation |
| `AH-F03` | freeze a process-local catalog snapshot | global mutable singleton |
| `AH-F04` | route an explicit `product_id` to one descriptor/factory | default Product heuristic |
| `AH-F05` | consume a bounded generic Session Identity Envelope projection before routing | AppHost filesystem reader |
| `AH-F06` | transfer the opaque Product locator to the selected Product owner | second Session store |
| `AH-F07` | create one independently scoped Product Runtime binding per Session | AppServer connection owner |
| `AH-F08` | own idempotent release and process-level shutdown ordering | Product-internal disposal policy |
| `AH-F09` | select an admitted deployment/presentation profile orthogonally to Product | UI renderer |
| `AH-F10` | compose embedded, hosted, foreground, and supervised target-process roots | OS process backend |
| `AH-F11` | bind a hosted Product Runtime to AppServer structural ports | AppService coordinator |
| `AH-F12` | produce serialized foreground-launch material in a controller process | Hosting platform adapter |
| `AH-F13` | map target readiness/stop to an optional outer launcher/controller | listener implementation |
| `AH-F14` | expose bounded Product/profile/runtime lifecycle observations | log/trace retention owner |
| `AH-F15` | prove Product neutrality with unrelated fake Product Packages | production Product registry |
| `AH-F16` | pin one admitted Product/OEM content generation across routing and Session lifetime | mutable catalog entry |
| `AH-F17` | validate and claim a revision-pinned resume candidate before the Product factory effect | AppHost Product parser |
| `AH-F18` | coordinate an explicit Product-owned copy-first compatibility import | default Product or in-place migration |
| `AH-F19` | single-flight and lease one canonical live Product Runtime binding across profile/mux attachments | aggregate-owned runtime |

## Candidate Components

| Candidate | Classification | Reason to consider |
| --- | --- | --- |
| AppHost Contract Model | logical supporting component | one stable vocabulary for Product descriptors, factories, scoped handles, identity envelopes, profiles, failures, and observations |
| Product Catalog And Router | logical functional component | admission projection plus explicit identity routing form one coherent decision center |
| Scoped Runtime Lifecycle | logical functional component | per-Session runtime creation/release and whole-process shutdown share one ownership invariant |
| Deployment Profile Composer | logical functional component | selects and assembles embedded/hosted/foreground profiles without changing Product identity |
| Outer Launcher Adapters | boundary adapter group | converts serializable launch material to optional Hosting or external-supervisor interactions |
| AppServer Runtime | candidate responsibility cluster | excluded because listener/connection/framing is a sibling scope |
| AppService Coordinator | candidate responsibility cluster | excluded because hosted semantic coordination is a sibling scope |
| Session Store | candidate responsibility cluster | excluded because the canonical Session owner persists the envelope and a neutral catalog port projects it |
| Session Discovery/Catalog | neighboring required port | adapts the existing Harness bounded multi-source projection across explicitly selected cwd/user-global scopes; AppHost neither chooses roots nor reads stores |
| Plugin Manager | candidate responsibility cluster | excluded because AppHost consumes admitted registrations and owns no Package lifecycle |
| Product Runtime Builder | candidate responsibility cluster | excluded because Product factories compose existing Harness/Product mechanisms |
| Runtime Resource Owner | candidate responsibility cluster | reused through its public contract; AppHost owns ordering, not a duplicate artifact/run-lease implementation |

## Function-To-Component Mapping

| Function | Primary owner | Collaborators | Explicit non-owners |
| --- | --- | --- | --- |
| `AH-F01`, `AH-F05`, `AH-F14` | AppHost Contract Model | injected Session identity/catalog port, Product integration | filesystem/store implementation, Product kernel, log store |
| `AH-F02`--`AH-F04`, `AH-F06`, `AH-F16`--`AH-F18` | Product Catalog And Router | Contract Model, Product admission, Product resume/import adapters | AppServer, default resolver, transcript store |
| `AH-F07`, `AH-F08`, `AH-F19` | Scoped Runtime Lifecycle | Product Factory, profile and attachment leases | AppService aggregate, Hosting, Product internals |
| `AH-F09`--`AH-F11` | Deployment Profile Composer | Runtime Lifecycle, optional hosted binder | UI renderer, AppServer internals |
| `AH-F12`, `AH-F13` | Outer Launcher Adapters | Profile Composer, optional Hosting | AppHost core catalog, AppServer, AppService |
| `AH-F15` | component conformance tests | fake Product and profile packages | production registry |

The mapping keeps catalog/routing, runtime ownership, and profile composition
separate. The Contract Model is intentionally shared, while launcher adapters
depend inward on serializable contracts and remain absent from embedded
composition.

## Refinement: Split / Merge / Keep

| Candidate | Decision | Rationale |
| --- | --- | --- |
| AppHost Contract Model | keep | stable cross-Product vocabulary should not depend on any deployment adapter |
| Product Catalog And Router | keep | catalog snapshot and explicit routing change together and share admission invariants |
| Scoped Runtime Lifecycle | keep | sole ownership of per-Session handles and ordered process release is stronger than a utility factory |
| Deployment Profile Composer | keep | Product identity and delivery topology remain orthogonal while one composition owner selects both |
| Outer Launcher Adapters | keep as optional edge group | process-boundary translation is real but must not force Hosting/AppServer into core imports |
| AppServer/AppService | split to sibling scopes | transport and hosted semantic coordination have independent actors, lifetimes, and failure semantics |
| Session Store | exclude | AppHost consumes a generic identity projection but never becomes a filesystem or persistence authority |
| Session Discovery/Catalog | keep outside via required port | reuse the established Harness source/locator/alias/conflict owner; add only the Product-envelope projection needed before routing |
| Plugin Manager/Product builder | exclude | importing their responsibilities would duplicate established owners |
| Runtime Resource Owner | reuse, do not wrap as peer component | AppHost orders its close through a narrow handle rather than re-owning artifact/run-lease state |

The resulting five peers remain within the method's `3-7` review range and use
one level of decomposition: stable contracts, routing, runtime lifetime,
profile composition, and optional outer launching.

## Proposed Dependency View

```text
outer launcher adapters -> profile composer -> runtime lifecycle
outer launcher adapters -> AppHost contracts -> optional Hosting contracts
profile composer -> catalog/router -> AppHost contracts
catalog/router -> injected Session identity/catalog port
hosted profile binder -> AppHost contracts + AppServer structural Product ports
runtime lifecycle -> Product Factory + scoped Product Runtime handle

AppHost core -/-> AppServer / Hosting / concrete Product / UI framework
AppServer/AppService/Harness/Hosting -/-> AppHost
```

Physical packaging may place the optional hosted binder and launcher adapters
under the future `loushang.apphost` package, but import gates must preserve the
logical split. A convenience facade does not permit core modules to import all
profile dependencies.

## Open Validation Questions

1. Which minimum Session Identity Envelope can be committed atomically by the
   canonical Session persistence owner and projected across explicit
   current-directory/user-global discovery scopes without creating a second
   store or ambiguous duplicate?
2. Which existing Product runtime contracts are sufficient for two unrelated
   fake Products, and which require a narrow AppHost-owned protocol?
3. Can profile admission consume the existing Plugin/OEM projection without
   introducing a second mutable registry or import-time discovery?
4. Which AppServer structural ports are genuinely profile-neutral before an
   `apphost.hosted` binder is implemented?
5. Which serialized readiness/stop contract is shared by a Hosting launcher
   and an external supervisor without moving service semantics into Hosting?
6. Which subject-bound Product/OEM admission source can mint independent
   catalog-owned pins while replacement stops new routes and retirement waits
   for existing Sessions?
7. Which request-bound Session candidate and Product validator contracts close
   the list/open/factory race without exposing paths or Store handles?

These questions gated field-level API and implementation acceptance. A0.1
answers the core contract questions; hosted and launcher adapter questions
remain deferred to their separately accepted slices.
