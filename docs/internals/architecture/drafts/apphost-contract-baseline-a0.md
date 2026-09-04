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
2. **Product factory and resume validator** — the Product-owned validator
   consumes a revision-pinned routing candidate and returns an opaque opened
   Product candidate; only then may the factory create one scoped Product
   Runtime handle. Neither exposes a global runtime singleton or asks AppHost
   to parse Product state.
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
projections and opens one request-bound, revision-pinned candidate lease from
explicitly selected discovery scopes. The lease retains the exact opened
source/provider reference without exposing a path or Store handle, supports one
final `verify/claim`, and closes idempotently. Its implementation owns root
selection, filesystem/store access, compatibility-root discovery,
deduplication, and stable reopen. AppHost neither derives paths nor reads
Session files.

The first adapter should project the existing Harness `SessionDiscoverySource`,
`SessionLocator`, `SessionDiscoveryMetadata`, bounded catalog, and
alias/conflict behavior into this path-free AppHost contract. A0 adds only the
missing generic Product envelope fields. It does not create a peer session
index, rescan roots independently, or make the standard-library-only AppHost
Contract Model import Harness implementation modules.

Descriptors and registrations are process-local immutable values assembled by
trusted composition. Each registration carries an owner-minted, immutable
Product/OEM admission-generation lease. The live-binding registry linearizes
route selection before any generation is pinned: an existing binding is
validated and acquired only through its retained generation, while an absent
binding pins the current catalog generation before single-flight construction.
Catalog replacement atomically stops new pins on the old generation and drains
existing Session pins before Plugin retirement or final content deletion.
Registrations contain no credentials, Store handles, raw descriptors, Python
objects intended for another process, or open-ended metadata used to bypass
versioning.

## Required Behavioral Invariants

- Every new/open/resume route states a `product_id`; omission is a typed
  `ProductIdentityRequired` failure, not a default selection.
- Unknown, disabled, incompatible, or ambiguous Product identity fails before
  a Product-specific transcript parser or runtime factory is invoked.
- An envelope selects only among already admitted Product registrations. It is
  bounded routing input, not Product trust, continuity authority, or proof that
  its locator is safe. The selected Product resume validator consumes the
  pinned candidate, revalidates locator and continuity authority, and returns
  an opened Product candidate bound to the same revision before the factory is
  called. A changed or stale candidate is closed and never reaches the factory.
- The catalog is an immutable generation frozen before serving work. Duplicate
  Product/profile identities and late mutation are rejected; replacement
  creates a new generation, closes old-generation admission to new routes, and
  existing Session leases retain their exact admission/content pin without
  retargeting until final release.
- A canonical live-binding registry owns exactly one scoped Product Runtime per
  `(product_id, continuity identity, Session identity)` key. First acquisition
  is single-flight; concurrent attach joins the same result. For an existing
  key, validation and attachment use only the binding's retained Product
  validator and admission/content-generation pin. For an absent key, the
  registry reserves construction and pins the current generation atomically.
  If an old binding is fenced against new attachment, a new generation cannot
  reuse or replace it under the same key; the route returns a typed generation
  transition conflict until the old binding drains or an explicit Product
  migration succeeds. The registry, not an AppService aggregate, is the sole
  runtime owner and closes it only after explicit Session close/process
  shutdown fences admission and all binding leases drain. Catalog membership
  never creates a global Product runtime.
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
  application `RunLease`, or process resource owner. AppService owns only
  membership, subscription, presenter, and attachment leases; detach or stale
  detach cannot directly close the underlying AppHost runtime binding.
- Legacy Coding and external Codex/Claude-style Session formats have no implied
  Product. Migration requires an explicit selected `product_id` and a
  Product-owned importer admitted by the same generation. The importer reads a
  pinned compatibility candidate, copies first into the canonical Session
  owner, atomically publishes the new envelope, and leaves the source read-only.
  Failure or cancellation removes no source and publishes no partial envelope.

## Core Interaction: Create Or Resume

```text
trusted process composition
  -> inject admitted Product/profile registrations + Session identity/catalog port
  -> freeze one immutable catalog generation
client/profile request
  -> state explicit product_id for create; or request an exact envelope projection
  -> Session identity/catalog port: list/open pinned selected cwd/user-global candidate
  -> canonical live-binding registry: linearize existing-key or absent-key route
  -> existing key: retain its generation and validator, or reject its retirement fence
  -> absent key: reserve construction and pin the current admitted catalog generation
  -> branch-selected Product resume validator: validate and open exact Product candidate
  -> candidate lease: final verify/claim immediately before factory effect
  -> canonical live-binding registry: publish one created binding or acquire the existing binding
  -> Deployment Profile Composer: bind the elected profile
  -> publish profile/session lease only after both owners are usable
```

Failure after runtime creation but before profile publication closes the
profile candidate, then the Product Runtime handle. Cancellation waits for
owned cleanup before propagating. No failed candidate is cached as a default.
The routing candidate, Product candidate, and admission-generation pin are
closed on every path; a published Session binding retains only the exact pins
needed to prevent premature retirement.

### Explicit Legacy Import

A compatibility candidate without a generic envelope is listable only as
`migration_required`, never resumable. The caller selects `product_id`; AppHost
routes to that Product's admitted importer without inspecting the legacy
payload. The importer validates its own format and continuity identity against
the pinned read-only candidate, asks the canonical Session persistence owner to
copy content and atomically commit the new envelope, then returns the new
canonical candidate. Coding JSONL and Codex/Claude-shaped fixtures exercise the
same AppHost contract through Product-specific adapters. AppHost contains no
format switch, filename heuristic, or default Coding branch.

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
idempotent operation. Trusted composition supplies a finite deadline for each
phase and an overall deadline; timeout records a typed phase failure and
continues with every reachable later cleanup action:

1. atomically fence the active catalog generation, new routes, and new
   live-binding/attachment pins;
2. ask the elected server/profile adapter to stop accepting new work;
3. ask AppService, when present, to perform the sole logical detach and settle
   admitted work;
4. close every distinct profile lease and scoped Product Runtime handle exactly
   once, then wait for dependent attachment/runtime pins to drain;
5. close the catalog generation and each base Product/OEM admission lease once;
6. close the one process `RuntimeResourceOwner` only after all dependent
   runtime, profile, catalog, and admission leases settled; and
7. report bounded independent phase failures after all reachable cleanup.

A timeout or cleanup failure makes a dependent later owner unreachable: it is
recorded as typed cleanup debt and retained rather than closed out of order.
In particular, AppHost never closes `RuntimeResourceOwner` beneath a live
Product runtime or catalog lease. An external supervisor may then terminate the
process, but AppHost does not synthesize successful retirement or release.

An external supervisor or Hosting launcher may force-terminate after its own
deadline, but that proves only process facts. It cannot synthesize successful
Session detach, durable persistence, or Product retirement.

## A0 Delivery Slices

| Slice | Delivery | Exit gate |
| --- | --- | --- |
| A0.0 | placement refinement, component discovery, contract baseline, Current inventory, and absence guard | common-parent and neighboring-owner design review; no source package |
| A0.1 | standard-library-only private Contract Model package | exact validation, frozen catalog input, no optional-profile imports, no composition |
| A0.2 | catalog/router, admission-generation pins, injected Session identity/catalog port, and explicit Product-owned importer over fakes | two unrelated fake Products; cwd/user-global listing; no-default resume/migration; legacy Coding and Codex/Claude fixture; duplicate, revision-swap, retirement, and incompatibility matrix pass |
| A0.3 | canonical live-binding registry, scoped runtime lifecycle, and embedded profile composition | single-flight multi-attach/multi-mux ownership, detach/cancel/stale-detach, partial-construction, deadline, and shutdown matrix pass |
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
| `A0-ADMISSION-PIN` | replace/disable/retire/shutdown races stop new routes; existing-key attach uses only its retained generation; base leases close once after all pins drain |
| `A0-RESUME-PIN` | request-bound opened candidates reject list/open replacement and locator/provider revision changes before factory effect |
| `A0-MIGRATION` | explicit Product-owned copy-first import handles Coding and Codex/Claude fixtures without default selection or source mutation |
| `A0-MULTI-ATTACH` | concurrent named-mux/session attachments single-flight one canonical runtime and detach only their own leases |
| `A0-PROFILE-ORTHOGONAL` | one Product works with two profiles and two Products work with one profile |
| `A0-IMPORTS` | core excludes AppServer, Hosting, concrete Products, and UI frameworks; reverse edges are forbidden |
| `A0-ROLLBACK` | every acquisition/cancellation/shutdown boundary has deterministic cleanup evidence; dependency debt prevents out-of-order resource-owner close |
| `A0-SERIALIZED-LAUNCH` | launcher boundary contains values/references only, never factories or live handles |

## Acceptance Fence

This A0 proposal does not accept AppHost as a top-level scope. Before source is
added, the parent acceptance gates in the placement proposal still require a
cross-scope ARD, parent catalog/scope/diagram updates, sibling-owner review,
canonical glossary updates, and field-level contract acceptance. Until then,
`src/loushang/apphost` remains absent and Product-specific Current entrypoints
remain authoritative.
