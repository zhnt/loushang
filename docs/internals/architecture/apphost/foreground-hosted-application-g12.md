# Foreground Hosted Application G12

[Architecture](../README.md) · [AppHost](README.md) ·
[G11 Hosted Application](../appserver/hosted-application-g11.md) ·
[ARD-003](../decisions/ARD-003-apphost-top-level-placement.md) ·
[Embedded And Hosted Boundary](../drafts/appservice-embedded-tui-hosted-boundary-plan.md)

## Status

- ID: `FOREGROUND-HOSTED-APPLICATION-G12`
- Kind: accepted delivery design
- Scope: optional AppHost composition / AppService / Coding hosted edge
- Parent: Loushang application architecture
- Authority: normative accepted design
- Design status: accepted
- Implementation status: implemented — G12.0--G12.4 complete
- Activation status: explicit process-local library only
- Owner: Loushang AppHost architecture with Product and AppService boundary review

## Outcome And First-Principles Boundary

G12 composes the G11 application semantics with AppHost for the first time. An
explicit caller constructs one foreground, process-local hosted application for
one admitted Product generation. The application owns one AppService and one
AppHost Runtime; every hosted Session is created or resumed through the
canonical AppHost routing and live-binding registry. The returned AppClient can
drive the existing Harnesstui Hosted Mux Profile without either side knowing the
other's implementation.

```text
explicit caller
  -> Coding hosted-application edge
       -> admitted foreground Coding Product factory
       -> AppHost catalog/runtime and canonical Session routing
       -> optional apphost.application lifecycle owner
            -> AppService
            -> InProcessAppClient

Harnesstui Hosted Mux Profile -> AppClient only
default Coding CLI / TUI / SDK -> unchanged Current path
```

The minimum useful G12 path is foreground and in process. It introduces no
socket, listener, authentication, framing, daemon, service-instance controller,
Hosting process, background owner, or installed hosted command. Those belong to
separately accepted successors. This separation proves semantic composition and
owner settlement before transport and process survival add new failure domains.

## Current, Target, And Delta

| Plane | Statement |
| --- | --- |
| Facts | G11 provides the App Contract, AppClient, AppService, one Coding Session adapter and an explicit Harnesstui Hosted Mux Profile. AppHost G8--G10 provides default-dark Product/runtime composition and one unrelated installed Hosting canary. G12 adds an optional foreground composition without changing either installed route. |
| Current | An explicit caller may construct one G12 library application that joins AppService to AppHost canonical routing and ordered shutdown. Normal Coding CLI/TUI/SDK remains Current. |
| Target | The accepted G12 target is realized: one explicit library composition owns one Product generation, AppHost Runtime, AppService and in-process client. Coding supplies the Product-specific foreground Session factory and projection edge; hosted create/resume traverses AppHost and supports canonical cwd and user-home identities. |
| Delta | G12 closes the foreground in-process composition delta. Transport, Hosting, installed activation, background continuity and a default-owner change remain outside this goal. |

## Requirements

| ID | Requirement |
| --- | --- |
| `G12-R1-EXPLICIT-FOREGROUND` | Construction requires an exact typed activation value. Import, omission, environment, platform, persisted state, AppClient creation and profile discovery cannot activate it. |
| `G12-R2-ONE-PRODUCT-GENERATION` | One hosted application admits exactly one `product_id` and one immutable catalog generation. Each live Session retains that generation through its AppHost binding; no request may retarget it. |
| `G12-R3-APPHOST-ROUTING` | AppService's Coding resolver maps create/resume to AppHost create/resume. The backward-compatible AppHost create request carries optional requested continuity and discovery scope into the canonical create-if-absent intent, and Router validates both before Product factory effect. The resolver receives a canonical path-free Session identity/catalog port, never derives cwd/home paths, never opens a locator, and rejects ambiguous or mismatched identities. |
| `G12-R4-FOREGROUND-PRODUCT` | Coding's G12 Product factory creates one independently owned foreground hosted Session binding from the finally opened AppHost candidate. It neither selects nor imports Hosting and does not reuse the G9/G10 Worker canary owner. |
| `G12-R5-LEASE-OWNERSHIP` | AppService owns a hosted Session wrapper; the wrapper owns exactly one AppHost profile lease and closes the exact AppHost Session binding. Borrowed Product ports never gain close authority over AppHost. |
| `G12-R6-ORDERED-SHUTDOWN` | Close first fences new application and AppService admissions, then closes AppService attachments/Sessions, then shuts down AppHost Runtime, then settles Product-factory construction debt. A later phase never runs while a prerequisite remains unresolved. |
| `G12-R7-RETRYABLE-CLEANUP` | Construction, request, cancellation and close failures retain exact owner-specific cleanup debt. Close is idempotent and retryable; cancellation joins adopted cleanup before propagation. |
| `G12-R8-CLIENT-ONLY-PRESENTATION` | Harnesstui consumes only `AppClientV1` and protocol values. AppHost and Coding do not import Harnesstui, and Harnesstui does not import AppHost, AppService, Product or Harness. |
| `G12-R9-REAL-VERTICAL-CANARY` | An explicit in-process test traverses AppHost routing, Coding foreground binding, AppService, AppClient and Harnesstui controller for mux create, member create/resume, snapshot, turn/event, detach and close. Parser-only or isolated fakes do not satisfy it. |
| `G12-R10-SCOPE-COMPATIBILITY` | Canonical cwd and user-home create/resume preserve Product, continuity, Session, scope and scope fingerprint. Legacy candidates remain migration-required and are rejected by G12 rather than opened by path. |
| `G12-R11-BOUNDED-EVIDENCE` | Inventory v5 records every new composition surface, package budgets remain reviewable, and deterministic lifecycle/error tests cover concurrency, cancellation, stale generation and cleanup retry. |
| `G12-R12-NO-AUTHORITY-EXPANSION` | Passing G12 grants no AppServer listener, local IPC, authentication, daemon continuity, Hosting service control, installed hosted route, default profile/owner change, Current deletion, multi-client takeover, or AppHost crash recovery. |

## Component And System Boundary

| Component | Owns | Must not own |
| --- | --- | --- |
| `loushang.apphost.application` | optional process-local service/runtime composition, application admission fence, close report and dependency order | App protocol behavior, Product construction policy, transport, listener, OS process or presentation |
| AppHost core | catalog, routing, canonical live Product binding, profile leases and runtime shutdown | AppService semantics, Product internals, Session storage roots or UI |
| `loushang.appservice` | named mux, logical attachment, hosted Session ownership and bounded delivery | AppHost routing, Product selection, transport or process lifetime |
| `loushang.coding.hosted_application` | explicit foreground Product registration/factory, AppHost-backed resolver, canonical scope mapping and Coding binding validation | mux policy, generic AppHost core, Harnesstui state, transport or Hosting |
| `loushang.coding.appservice_adapter` | Product-specific Session control/projection adapter | AppHost routing, mux registry or process lifetime |
| `loushang.harnesstui.mux` | client-side hosted presentation and attachment controller | service construction, Product/session ownership or AppHost shutdown |

`apphost.application` is an optional outer edge, not part of the dependency-free
AppHost core facade. It may import AppService and AppServer's client contract;
`apphost.__init__`, contracts, catalog, router and runtime remain independent.
Concrete Product registration remains in the Product package. This keeps the
common lifecycle policy reusable while keeping Product semantics out of
AppHost.

## Dependency Direction

```text
apphost core -> Python standard library
apphost.application -> apphost runtime/contracts + appservice + appserver.client
appservice -> appserver.protocol
coding.hosted_application -> apphost public modules + appservice ports + coding.appservice_adapter
coding.appservice_adapter -> appserver.protocol + appservice ports + public Harness Session controls
harnesstui.mux -> appserver.client + appserver.protocol

apphost core -/-> AppService / AppServer protocol / Coding / Harness / Hosting / UI
apphost.application -/-> Coding / Harness / Hosting / Harnesstui / TUI
appservice -/-> AppHost / Hosting / Product / Harness / Harnesstui / TUI
coding.hosted_application -/-> Hosting / Harnesstui / TUI / AppServer transport
harnesstui.mux -/-> AppHost / AppService / Coding / Harness / Hosting
```

## Identity And Routing

AppService supplies one `SessionOpenSpecV1`. The Coding resolver maps its scope
without deriving a filesystem path:

| App Contract scope | AppHost discovery scope |
| --- | --- |
| `cwd` | `CURRENT_DIRECTORY` |
| `user_home` | `USER_GLOBAL_CANONICAL` |

For resume, the resolver asks the injected canonical catalog for a bounded list
in exactly that scope. It selects exactly one canonical projection whose
envelope matches Product, continuity and Session identity, then passes the
opaque candidate reference to AppHost. Zero matches is not found; more than one
match or any same-Session mismatch is ambiguous and fails closed. A
`MIGRATION_REQUIRED` projection is never opened by G12.

For create, the resolver gives AppHost an explicit Product, creator-scope token,
fresh operation identity, requested continuity identity and requested discovery
scope. The latter two fields are optional additions to
`SessionCreateRequestV1`, so existing embedded callers retain their contract.
The canonical owner receives them inside the existing create-if-absent intent,
mints and establishes the identity, and AppHost Router validates the resulting
canonical projection before Product factory effect. After attachment, the
Coding edge also validates Product, continuity, Session, scope and scope
fingerprint before publication. A mismatch is closed, never rewritten or
silently accepted.

No protocol value contains a path, provider implementation, locator token,
candidate reference, admission lease or Product runtime handle.

## Ownership And Lifecycle

### Construction

1. Validate explicit activation and all injected ports without effect.
2. Admit one immutable Product/profile catalog generation.
3. Construct one AppHost Runtime over the same canonical Session owner.
4. Construct the AppHost-backed Coding resolver and one AppService.
5. Publish one `HostedApplicationRuntimeV1` and its non-owning AppClient.

Every effectful step is adopted before inspection. Failed construction closes
in reverse dependency order and retains unresolved debt inside its original
owner.

### Session open

1. Application and AppService admission are checked.
2. The resolver performs canonical create or bounded resume selection.
3. AppHost pins the exact Product generation, creates or joins the one live
   binding and attaches the hosted profile.
4. Coding validates the borrowed hosted binding and wraps the AppHost lease.
5. AppService adopts the wrapper before snapshot/subscription and publishes the
   member only after its existing atomic barrier.

Closing the wrapper first closes the profile lease, then asks AppHost to close
the exact binding key. If either phase fails, the wrapper retains the
corresponding debt and a later close retries from that phase.

### Application close

```text
fence application admission
  -> AppService.close()
       -> settle logical attachments
       -> close every hosted Session wrapper
            -> close AppHost profile lease
            -> close exact AppHost Session binding
  -> AppHostRuntime.shutdown(budget)
  -> foreground Coding Product factory.close()
```

If a prerequisite phase times out or fails, later phases do not claim success.
The close report names only stable phases and booleans. It contains no paths,
prompts, events, exceptions, candidate references or Product objects.

## Threat Model

| Threat | Control |
| --- | --- |
| G12 becomes an implicit replacement for Current | explicit activation type, inventory v5, installed-entrypoint omission guards |
| AppService bypasses AppHost and opens Product state directly | exact resolver dependency plus end-to-end routing evidence |
| cwd/home identity becomes a path capability | closed scope mapping; path-free candidate references stay inside AppHost |
| catalog replacement retargets a live hosted Session | AppHost live binding retains the exact admitted generation |
| AppService close leaks Product runtime owners | hosted wrapper owns lease plus exact close-session authority; ordered retryable close |
| a failed profile bind destroys borrowed Product state | profile lease owns only its attachment; Product runtime remains AppHost-owned |
| transport or daemon authority arrives through convenience code | AST denylist for sockets, subprocess, Hosting, listeners and installed routes |
| Harnesstui gains service/process authority | client-only import and construction guards |
| raw Product failure leaks to a client | existing G11 stable error mapping and bounded G12 close report |

## Delivery Slices

| Slice | Deliverable | Exit evidence |
| --- | --- | --- |
| G12.0 | accepted boundary, requirements, ownership model, lifecycle, threat model and design guards | three-view design review has no unresolved high/medium finding; no production source change |
| G12.1 | optional `apphost.application` owner and close report | admission fence, dependency-ordered idempotent/retryable close, cancellation and no-core-import tests |
| G12.2 | Coding foreground Product factory/profile and AppHost-backed create/resume resolver | exact generation, canonical cwd/user-home identity, ambiguous/legacy rejection and owner cleanup tests |
| G12.3 | explicit Harnesstui end-to-end in-process canary | mux/create/resume/snapshot/turn/event/detach/close crosses every accepted boundary without transport or installed activation |
| G12.4 | inventory v5, affected quality gates, implementation review and architecture reconciliation | immutable-head checks and three-view implementation review have no unresolved high/medium finding |

## Evidence Contract

| ID | Proof |
| --- | --- |
| `G12-OPTIONAL-EDGE` | only `apphost.application` imports AppService/AppClient; AppHost core and facade remain independent |
| `G12-EXPLICIT-ACTIVATION` | exact activation value is required and all installed omission routes remain Current |
| `G12-CANONICAL-ROUTING` | create/resume use AppHost and the injected catalog, never paths or direct Product lookup |
| `G12-GENERATION-PIN` | a catalog replacement cannot retarget an already live hosted Session |
| `G12-FOREGROUND-PRODUCT` | Coding binding creation and teardown use no Hosting or Worker owner |
| `G12-SCOPE-COMPAT` | cwd and user-home identities survive create/resume; legacy and ambiguous selections fail closed |
| `G12-LEASE-CLOSE` | detach and Session close settle profile lease then exact binding once, with retry debt |
| `G12-APPLICATION-CLOSE` | service, AppHost and Product factory settle in dependency order under a finite budget |
| `G12-CANCELLATION` | adopted construction/open/close owners settle despite caller cancellation |
| `G12-CLIENT-ONLY-TUI` | Harnesstui imports only client/protocol and its controller runs over the composed client |
| `G12-VERTICAL-CANARY` | one test crosses mux, member, Session, turn/event and complete close on the real composition |
| `G12-INVENTORY-V5` | every supported/installed/composition surface has a source-backed exact disposition |

## Three-View Review Contract

Both G12.0 design and G12.4 implementation are reviewed independently through:

1. **Architecture and authority:** optional-edge placement, Product neutrality,
   dependency direction, generation pinning, explicit activation and unchanged
   Current ownership.
2. **Lifecycle, concurrency and safety:** adopt-before-inspect, AppService and
   AppHost admission fences, Session lease ownership, cancellation,
   compensation, retry debt and shutdown order.
3. **Contract, compatibility and evidence:** identity/scope mapping, error and
   report bounds, AppClient-only presentation, vertical behavior, inventory,
   package budgets and affected cross-platform-safe gates.

High or medium findings block implementation or completion. Fixes are rerun
through the same view and recorded here.

## G12.0 Design Review

The first three-view pass found four medium risks and the design was revised:

- **Architecture and authority:** putting construction in the AppHost facade
  would make every embedded consumer import AppService. The composition is now
  isolated in optional `apphost.application`; concrete Product registration
  stays in Coding.
- **Lifecycle, concurrency and safety:** closing only an AppHost profile lease
  would leave the canonical live Product binding in the registry. The Coding
  hosted wrapper now owns both ordered profile detach and exact binding close,
  while application close fences AppService before AppHost shutdown.
- **Contract, compatibility and evidence:** resume-by-Session-ID could select a
  wrong cwd/user-home candidate or a legacy locator. The resolver now performs
  bounded exact envelope/scope matching, rejects ambiguity and never opens a
  migration-required candidate.
- **Contract, compatibility and evidence:** the pre-G12 AppHost create request
  could not carry G11's requested continuity and scope to the canonical owner.
  Two optional fields now travel in the existing create-if-absent intent and
  are verified by Router before any Product factory effect; old callers remain
  source compatible.

The same three views were rerun after these changes. No unresolved high or
medium finding remained, so implementation proceeded inside the requirements
and non-goals above.

## G12.4 Implementation Review

The final three-view pass found and closed the following issues:

- **Architecture and authority:** the optional application module and Coding
  edge were missing from the exact package/inventory gates, leaving their
  dependency direction vulnerable to later drift. Inventory v5, generated
  dependencies, package budgets and exact consumer/omission guards now cover
  both modules. A second Product identity test proves the application owner is
  Product-neutral, while the concrete factory remains Coding-owned.
- **Lifecycle, concurrency and safety:** failed or internally cancelled close
  tasks could make a later retry raise while inspecting the old task instead
  of restarting exact debt. Close-task predicates now treat cancellation and
  failure as retryable, and tests cover service debt, AppHost timeout, Product
  debt, caller cancellation and the profile-lease-to-binding retry chain.
- **Contract, compatibility and evidence:** placing the two optional hosted
  constraints before `contract_version` changed the meaning of an existing
  fourth positional argument. The existing version slot is restored and the
  new fields are keyword-only. The focused vertical canary, canonical
  cwd/user-home and legacy/ambiguity cases, create-before-factory rejection,
  inventory v5 and affected AppHost/AppService gates are all source-backed.

The same three views were rerun after these fixes. No unresolved high or medium
finding remains. The implementation remains an explicit, uninstalled,
foreground in-process library and grants none of the deferred authorities.

## Exit Gate

G12 is complete only when G12.0--G12.4 are implemented, all twelve evidence
cases pass, inventory v5 matches source and installed entrypoints, both
three-view reviews have no unresolved high/medium finding, and the same
immutable head passes:

- focused G12 AppHost/AppService/Coding/Harnesstui tests;
- `make check-appservice`;
- `make check-apphost`;
- `make check-harnesstui`;
- `make check-harness`;
- `make check-architecture-docs`; and
- `git diff --check`.

Passing this gate authorizes only the explicit foreground in-process library
composition. It does not authorize AppServer transport, a listener, IPC,
Hosting, a daemon, installed activation or a Current-owner decision.
