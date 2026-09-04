# AppHost A0 Contract Baseline

## Status

- ID: `APPHOST-A0`
- Scope: `AppHost`
- Parent: `Loushang`
- Authority: normative target proposal
- Design status: proposed
- Implementation status: not-started
- Activation status: none; no AppHost source package or composition route
- Owner: Loushang architecture

## Purpose

A0 defines the smallest cross-Product AppHost contract boundary that can later
be proven without prematurely accepting a new top-level scope. It refines the
[AppHost placement proposal](apphost-top-level-placement.md) using the
[A0 component discovery](apphost-component-discovery-a0.md).

A0 is not AppServer, AppService, a hosted application implementation, a daemon,
or PLC9C5 Product activation. It reserves responsibility and proof obligations,
not final Python symbol names.

## Contract Boundary

AppHost core owns five kinds of immutable value contract plus one required-port
contract:

1. **Product descriptor** — data-only stable `product_id`, compatibility
   identity, and supported profile identifiers. A separate catalog
   registration pairs it with an already admitted factory capability; the
   descriptor contains no import path and AppHost performs no discovery.
2. **Product factory** — creates one scoped Product Runtime handle from an
   explicit Session context and opaque Product locator; it does not expose a
   global runtime singleton.
3. **Scoped Product Runtime handle** — stable Product/Session identity plus one
   idempotent close port and an opaque Product-owned binding consumed only by a
   separately registered profile adapter. It is not a generic capability bag,
   Harness registry, or Product-internal owner graph.
4. **Session Identity Envelope** — a versioned generic header containing the
   required `product_id`, continuity identity/reference, Session identity, and
   opaque Product-owned locator/provider discriminator.
5. **Profile descriptor/factory/lease** — one admitted delivery profile that
   binds a scoped Product Runtime without changing Product identity and exposes
   one idempotent release operation.

The **Session identity/catalog required port** lists bounded identity
projections and opens one envelope from explicitly selected discovery scopes.
Its implementation owns root selection, filesystem/store access,
compatibility-root discovery, deduplication, and stable reopen. AppHost neither
derives paths nor reads Session files.

The first adapter should project the existing Harness `SessionDiscoverySource`,
`SessionLocator`, `SessionDiscoveryMetadata`, bounded catalog, and
alias/conflict behavior into this path-free AppHost contract. A0 adds only the
missing generic Product envelope fields. It does not create a peer session
index, rescan roots independently, or make the standard-library-only AppHost
Contract Model import Harness implementation modules.

Descriptors and registrations are process-local immutable values assembled by
trusted composition. They contain no credentials, Store handles, raw
descriptors, Python objects intended for another process, or open-ended
metadata used to bypass versioning.

## Required Behavioral Invariants

- Every new/open/resume route states a `product_id`; omission is a typed
  `ProductIdentityRequired` failure, not a default selection.
- Unknown, disabled, incompatible, or ambiguous Product identity fails before
  a Product-specific transcript parser or runtime factory is invoked.
- An envelope selects only among already admitted Product registrations. It is
  bounded routing input, not Product trust, continuity authority, or proof that
  its locator is safe; the selected canonical Product/continuity owner must
  revalidate the opaque locator and authority identity before opening state.
- The catalog is an immutable generation frozen before serving work. Duplicate
  Product/profile identities and late mutation are rejected; replacement
  creates a new generation, and existing Session leases never retarget.
- Each Session receives an independent scoped Product Runtime handle. Catalog
  membership never creates a global mutable Product runtime.
- The canonical Session persistence owner writes the Session Identity Envelope
  atomically with Session creation/publication and exposes it through the
  injected identity/catalog port. AppHost consumes the projection but does not
  own a filesystem reader or second Session store.
- Trusted composition explicitly selects current-directory
  `.loushang/sessions`, legacy user-global `$LOUSHANG_HOME/sessions`, and/or
  canonical global `$LOUSHANG_HOME/data/sessions` discovery. The port preserves
  source identity; an incompatible duplicate fails as ambiguous rather than
  winning by search order.
- Listing and envelope reads have fixed candidate, byte, and schema bounds.
  Invalid, truncated, conflicting, or changed projections cannot reach a
  Product factory as a resumable Session.
- Product identity and presentation/deployment profile are orthogonal. A
  CodingTUI profile and CodingApp profile may share one Coding Product.
- AppHost core imports neither AppServer nor Hosting. Optional hosted and
  launcher adapters own those outward edges.
- Python factories and runtime handles never cross a process boundary. Only a
  complete executable, normalized argv/environment, profile identity, admitted
  platform-root references, and versioned readiness/stop material may cross.
- AppHost owns process-level shutdown ordering but does not reinterpret
  AppService detach, Product cleanup, AppServer drain, or Hosting termination
  evidence as one another.
- AppService aggregate or named-mux count creates no additional AppHost,
  catalog generation, Product Runtime for an already bound Session,
  application `RunLease`, or process resource owner.

## Core Interaction: Create Or Resume

```text
trusted process composition
  -> inject admitted Product/profile registrations + Session identity/catalog port
  -> freeze one immutable catalog generation
client/profile request
  -> state explicit product_id for create; or request an exact envelope projection
  -> Session identity/catalog port: list/open selected cwd/user-global scope
  -> Product Catalog And Router: resolve explicit product_id
  -> selected Product Factory: create scoped Product Runtime handle
  -> Deployment Profile Composer: bind the elected profile
  -> publish profile/session lease only after both owners are usable
```

Failure after runtime creation but before profile publication closes the
profile candidate, then the Product Runtime handle. Cancellation waits for
owned cleanup before propagating. No failed candidate is cached as a default.

## Hosted And Launched Edges

An optional `apphost.hosted` binder may depend on AppHost contracts and
AppServer structural Product ports. It maps a scoped Product Runtime handle to
the ports consumed by AppService/AppServer; it does not teach AppHost core the
App protocol or let AppServer discover Products.

An optional controller-side launcher consumes only a serialized foreground
launch specification and an injected Hosting process/service port. The target
process constructs its own AppHost runtime and AppServer/AppService graph.
Hosting never receives Product factories, Session locators, AppService
objects, or Product activation receipts.

## Shutdown Ownership

The future process-level runtime joins repeated stop requests on one bounded,
idempotent operation:

1. reject new Product/profile/runtime admission;
2. ask the elected server/profile adapter to stop accepting new work;
3. ask AppService, when present, to perform the sole logical detach and settle
   admitted work;
4. close every distinct profile lease and scoped Product Runtime handle exactly
   once;
5. close the one process `RuntimeResourceOwner`; and
6. report bounded independent phase failures after all reachable cleanup.

An external supervisor or Hosting launcher may force-terminate after its own
deadline, but that proves only process facts. It cannot synthesize successful
Session detach, durable persistence, or Product retirement.

## A0 Delivery Slices

| Slice | Delivery | Exit gate |
| --- | --- | --- |
| A0.0 | placement refinement, component discovery, contract baseline, Current inventory, and absence guard | common-parent and neighboring-owner design review; no source package |
| A0.1 | standard-library-only private Contract Model package | exact validation, frozen catalog input, no optional-profile imports, no composition |
| A0.2 | catalog/router plus injected Session identity/catalog port over fakes | two unrelated fake Products; cwd/user-global listing, no-default resume, duplicate, and incompatibility matrix pass |
| A0.3 | scoped runtime lifecycle and embedded profile composition | multi-Session ownership, cancellation, partial-construction, and shutdown matrix pass |
| A0.4 | optional hosted binder against accepted structural AppServer ports | core stays AppServer-free; transport and semantic owners remain separate |
| A0.5 | optional serialized launcher adapter | no Python object crosses process; readiness/stop/timeout evidence remains typed |

A0.1 implementation begins only after A0.0 review accepts the package
placement and field-level Contract Model. Hosted and launcher adapters are
independent optional slices; neither is an entry criterion for embedded use.

## Planned Conformance Inventory

| ID | Evidence |
| --- | --- |
| `A0-CATALOG` | immutable unique admission snapshot and no import-time discovery |
| `A0-TWO-PRODUCTS` | two semantically unrelated fake Product Packages use the same contracts |
| `A0-NO-DEFAULT` | missing/unknown/incompatible Product identity fails before Product parsing |
| `A0-IDENTITY-NO-AUTHORITY` | envelope routing never bypasses Product admission or locator/continuity revalidation |
| `A0-SESSION-DISCOVERY` | explicit cwd/user-global scopes preserve source identity; exact duplicates dedupe and conflicts fail ambiguous |
| `A0-SESSION-SCOPE` | each Session owns one independently closed Product Runtime handle |
| `A0-CATALOG-GENERATION` | immutable catalog replacement never retargets an existing Session lease |
| `A0-PROFILE-ORTHOGONAL` | one Product works with two profiles and two Products work with one profile |
| `A0-IMPORTS` | core excludes AppServer, Hosting, concrete Products, and UI frameworks; reverse edges are forbidden |
| `A0-ROLLBACK` | every acquisition/cancellation/shutdown boundary has deterministic cleanup evidence |
| `A0-SERIALIZED-LAUNCH` | launcher boundary contains values/references only, never factories or live handles |

## Acceptance Fence

This A0 proposal does not accept AppHost as a top-level scope. Before source is
added, the parent acceptance gates in the placement proposal still require a
cross-scope ARD, parent catalog/scope/diagram updates, sibling-owner review,
canonical glossary updates, and field-level contract acceptance. Until then,
`src/loushang/apphost` remains absent and Product-specific Current entrypoints
remain authoritative.
