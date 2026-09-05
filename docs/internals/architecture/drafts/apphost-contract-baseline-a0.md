# AppHost A0 Contract Baseline

## Status

- ID: `APPHOST-A0`
- Scope: `AppHost`
- Parent: `Loushang`
- Authority: historical — refined by the canonical A0 Contract Model
- Design status: accepted and promoted
- Implementation status: partial — A0.2 implemented; A0.3+ not started
- Activation status: none; no AppHost runtime composition route
- Owner: Loushang architecture

## Purpose

A0 defines the smallest cross-Product AppHost contract boundary that can later
be proven without prematurely accepting a new top-level scope. It refines the
[AppHost placement proposal](apphost-top-level-placement.md) using the
[A0 component discovery](apphost-component-discovery-a0.md).

A0 is not AppServer, AppService, a hosted application implementation, a daemon,
or PLC9C5 Product activation. It reserves responsibility and proof obligations,
not final Python symbol names.

The accepted, implementation-aligned specification is
[AppHost A0 Contract Model](../apphost/contract-model-a0.md); the placement is
owned by [ARD-003](../decisions/ARD-003-apphost-top-level-placement.md).

## Contract Boundary

AppHost core owns five kinds of immutable value contract plus one required-port
contract:

1. **Product descriptor** — data-only stable `product_id`, compatibility
   identity, and supported profile identifiers. A separate catalog
   registration pairs it with an already admitted factory capability; the
   descriptor contains no import path and AppHost performs no discovery.
2. **Product factory and candidate validator** — the Product-owned validator
   borrows a finally claimed create-or-resume candidate and returns a separately
   owned opaque Product candidate; only then may the factory borrow it to create
   one scoped Product Runtime handle. Neither exposes a global runtime singleton
   or asks AppHost to parse Product state.
3. **Scoped Product Runtime handle** — stable Product/Session identity plus one
   idempotent close port and an opaque Product-owned binding consumed only by a
   separately registered profile adapter. It is not a generic capability bag,
   Harness registry, or Product-internal owner graph.
4. **Session Identity Envelope** — a versioned generic header containing the
   required `product_id`, continuity identity/reference, Session identity, and
   opaque Product-owned locator/provider discriminator.
5. **Profile descriptor/factory/lease** — one admitted delivery profile that
   binds a restricted non-owning Product view without changing Product identity
   or receiving the shared runtime's close authority, and exposes one
   idempotent release operation.

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
trusted composition. Each registration carries a concrete frozen
generation/kind/subject identity and a borrowed, owner-minted, subject-bound
Product/OEM admission source. A future accepted catalog acquires its own
independent idempotently closed pin from each source and, before publication,
matches the returned pin identity exactly against that snapshot. Rejection,
mismatch, retirement, or cancellation publishes nothing and closes any
returned pin. Resume derives its key from the envelope and linearizes
existing-versus-absent before an absent route pins the current generation.
Create first performs a read-only idempotency lookup. Only an absent record pins
the explicitly selected current Product and calls create-if-absent; the route
can reserve the newly known binding key only after the returned candidate and
envelope provide it.
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
  its locator is safe. After the routing lease's final verify and claim, the
  selected Product candidate validator borrows the claimed candidate,
  revalidates locator and continuity authority, and returns a separately owned
  opened Product candidate bound to the same revision before the factory is
  called. A changed or stale candidate never reaches the validator or factory.
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
- A create route carries an explicit `product_id` in a bounded request and
  performs a read-only lookup before Product admission. Only for an absent
  record, after Product admission is pinned, the canonical Session owner mints
  the Session/continuity/locator identity and atomically establishes its
  envelope. AppHost never invents those values or fabricates a resume
  candidate.
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

## Core Interactions

Create and resume cannot share their first linearization point: only a resume
envelope already contains the complete live-binding key.

### Create

```text
explicit product_id + admitted creator_scope_id + high-entropy operation_id
  -> canonical Session owner: read-only lookup of the idempotency record
  -> if absent: resolve current Product, acquire exact pin, create-if-absent with compatibility identity
  -> recover/create one exact candidate + envelope and derive its complete binding key
  -> live registry existing: close only the provisional current pin; final verify/claim the candidate, validate/open it through the retained generation, compare binding key/compatibility, close temporary candidate/claimed/opened leases, and attach without calling the current factory
  -> live registry fenced: close provisional acquisitions and return generation conflict
  -> live registry absent: require a current descriptor compatible with the envelope, acquire/retain its pin, reserve key
  -> absent only: final verify/claim, Product validation, factory construction, and one binding publication
  -> profile factory: borrow only the runtime's non-owning profile view
  -> publish profile/session lease
```

The canonical Session owner treats
`(product_id, creator_scope_id, operation_id)` as the collision domain and
retains that mapping for the durable Session lifetime. The operation ID is
minted by a trusted boundary with at least 128 bits of entropy and is never
reused within its creator scope; the same token in another authenticated scope
cannot alias the Session. If durable envelope commit succeeds but
cancellation, failure, or host crash occurs before the lease is returned,
retry recovers the same exact candidate/revision; it cannot mint a duplicate.
An established but not-yet-bound durable Session is retained as recoverable
state rather than silently deleted.

Recovery guarantees candidate identity, not Product availability. If no live
binding remains and the Product is absent, recovery returns typed unavailable
without minting a new Session. If a compatible current registration exists,
the absent branch may build under its newly acquired generation; an
incompatible compatibility identity fails before Product code. If an existing
binding remains, retry joins only that binding's retained generation and never
invokes a current-generation validator or factory.

### Resume

```text
exact envelope projection
  -> derive complete Product/continuity/Session binding key
  -> live registry: acquire existing retained-generation binding; otherwise reserve key
  -> absent key only: resolve Product and acquire the admitted generation pin
  -> Session identity/catalog port: open exact selected cwd/user-global candidate
  -> candidate lease: final verify and claim exact candidate
  -> Product candidate validator: borrow claimed candidate and return opened candidate
  -> Product factory: borrow opened candidate and return scoped runtime
  -> live registry: publish one binding; concurrent attach joins it
  -> profile factory: borrow only the runtime's non-owning profile view
  -> publish profile/session lease
```

Every call borrows its input and returns a separately owned output. Failure or
cancellation closes acquired handles once in reverse order and waits for owned
cleanup before propagating; no callee closes a borrowed input. Failure after
runtime creation but before profile publication closes the profile lease, then
the Product Runtime handle. No failed candidate is cached as a default. The
routing lease, claimed candidate, opened Product candidate, and
admission-generation pin are closed on every unpublished path; a published
Session binding retains only the exact pins needed to prevent premature
retirement.

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
5. close the catalog generation and each catalog-owned Product/OEM admission
   pin once; borrowed registration sources remain outer-composition-owned;
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
| A0.1 | standard-library-only public Contract Model facade with runtime default-dark | exact validation, frozen catalog input, no optional-profile imports, no composition |
| A0.2 | catalog/router, admission-generation pins, injected Session identity/catalog port, minimal prepared-route protocol, Router-owned cleanup debt, and explicit Product-owned importer over fakes | two unrelated fake Products; cwd/user-global listing; no-default resume/migration; bounded immutable 8 MiB legacy snapshot; duplicate, revision-swap, retirement, incompatibility, and cleanup-retry matrix pass |
| A0.3 | canonical live-binding registry, scoped runtime lifecycle, and embedded profile composition | single-flight multi-attach/multi-mux ownership, detach/cancel/stale-detach, partial-construction, deadline, and shutdown matrix pass |
| A0.4 | optional hosted binder against accepted structural AppServer ports | core stays AppServer-free; transport and semantic owners remain separate |
| A0.5 | optional serialized launcher adapter | no Python object crosses process; readiness/stop/timeout evidence remains typed |

A0.1 implementation began only after A0.0 accepted the package placement and
field-level Contract Model. Hosted and launcher adapters are
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
| `A0-ADMISSION-PIN` | returned pin identity must exactly match the frozen registration generation/kind/subject; mismatch, sync/non-callable close, retire-during-acquire, and cancel-after-return publish nothing and close the pin; existing-key attach uses only its retained generation |
| `A0-RESUME-PIN` | request-bound opened candidates reject list/open replacement and locator/provider revision changes before factory effect |
| `A0-CREATE-IDEMPOTENCY` | commit-before-return cancellation/crash recovers one exact candidate; same operation/different creator scope never aliases; existing binding joins retained generation; fenced, removed, or compatibility-changed Product never duplicates or invokes the wrong factory |
| `A0-MIGRATION` | explicit Product-owned copy-first import handles Coding and Codex/Claude fixtures without default selection or source mutation |
| `A0-MULTI-ATTACH` | concurrent named-mux/session attachments single-flight one canonical runtime and detach only their own leases |
| `A0-PROFILE-ORTHOGONAL` | one Product works with two profiles and two Products work with one profile |
| `A0-IMPORTS` | core excludes AppServer, Hosting, concrete Products, and UI frameworks; reverse edges are forbidden |
| `A0-ROLLBACK` | every acquisition/cancellation/shutdown boundary has deterministic cleanup evidence; dependency debt prevents out-of-order resource-owner close |
| `A0-SERIALIZED-LAUNCH` | launcher boundary contains values/references only, never factories or live handles |

## Acceptance Fence

ARD-003 accepts AppHost as a top-level scope. A0.2 adds only the admitted
catalog, prepared-candidate router, and uncomposed AppHost-owned optional
Harness integration;
Product-specific Current entrypoints remain authoritative until the later
catalog, lifecycle, and profile slices pass their own acceptance gates.
