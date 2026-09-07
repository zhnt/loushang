# AppHost A0 Contract Model

## Status

- ID: `APPHOST-A0-CONTRACT`
- Scope: `apphost`
- Parent: `loushang`
- Authority: normative — accepted AppHost A0 contract specification
- Design status: accepted
- Implementation status: implemented through A0.4 hosted binding
- Activation status: default-dark; no concrete Product or server composition
- Owner: Loushang AppHost architecture

## Purpose

A0.1 creates the smallest dependency-safe seam for later Product routing. A0.2
admits immutable generations and routes exact Session candidates. A0.3 owns
canonical live runtime bindings and embedded profile attachments. A0.4 maps an
explicit hosted profile to AppServer-owned structural ports. None performs
Product discovery, persistence, process launch, server protocol, or production
composition.

## Contract Groups

### Identity and discovery values

`SessionIdentityEnvelopeV1` carries a schema version, explicit Product,
Product compatibility identity, continuity and Session identity, plus bounded
opaque provider and locator tokens. It carries no path, credentials, payload,
mutable runtime state, or trust decision.

`SessionCandidateRefV1` identifies an already projected source/candidate and
its exact revision. `SessionIdentityProjectionV1` combines the reference,
discovery scope, candidate mode, and optional envelope. Compatibility entries
without an envelope are `migration_required`; canonical resumable entries must
have one. AppHost never derives a root from a scope enum.

`SessionCreateRequestV1` carries the explicit Product identity for a new
Session plus an already authenticated/admitted `creator_scope_id` and a
trusted-boundary-minted, high-entropy `operation_id`. G12 adds optional
`requested_continuity_id` and `requested_scope` constraints for hosted
creation; they travel inside the same create-if-absent intent and Router checks
the resulting canonical projection before Product factory effect. Neither
token nor constraint is an authorization claim. The injected canonical Session
owner uses the complete request, rooted at
`(product_id, creator_scope_id, operation_id)`, as an idempotency identity and
retains the mapping. After Product selection, AppHost combines the request
with the descriptor's compatibility identity as `SessionCreateIntentV1`; the
canonical owner atomically establishes that identity in the envelope. A
different intent for the same key conflicts. The owner returns the same exact
candidate/revision on recovery or retry. AppHost does not mint a path, Session
ID, continuity ID, provider locator, or persistence authority.
Commit-before-return cancellation or crash therefore leaves one recoverable
durable identity rather than an orphaning retry ambiguity.
The owner retains the mapping for the durable Session lifetime; an operation
ID is never reused within its creator scope, and the same operation token in a
different creator scope cannot alias the Session.

### Product and profile values

`ProductDescriptorV1` identifies one Product compatibility boundary and the
profile IDs it supports. `ProfileDescriptorV1` identifies an orthogonal
delivery profile. Both are data-only and contain no import path or callable.

`ProductRegistrationV1` pairs a descriptor with already admitted process-local
factory/validator/importer ports and a subject-bound admission-generation
source plus its concrete frozen `AdmissionIdentityV1` snapshot.
`ProfileRegistrationV1` does the same for a profile factory. Trusted outer
composition creates registrations; AppHost performs no package discovery.

### Required and provided ports

- `SessionIdentityCatalogPortV1` lists bounded projections and opens an exact
  candidate reference, or asks the canonical owner to mint a new candidate
  from an explicit `SessionCreateRequestV1`.
- `SessionCandidateLeaseV1` supports final `verify_current`, one claim, and
  idempotent close without revealing a path or Store.
- `ProductCandidateValidatorV1` borrows a claimed create-or-resume candidate
  and returns a separately owned Product-opened candidate only after
  Product/continuity validation.
- `ProductFactoryV1` returns one scoped Product Runtime handle.
- `ProductCompatibilityImporterV1` performs a future explicit copy-first
  import through a canonical destination owner.
- `ProfileFactoryV1` receives only `ProductProfileBindingV1`, a restricted
  non-owning view with no runtime-close capability, and returns an independently
  releasable profile lease.
- `AdmissionGenerationSourceV1` is a borrowed subject-bound source. A later
  catalog acceptance obtains its own independent `AdmissionGenerationLeaseV1`
  pin; failed acquisition transfers no ownership. Before publication, it must
  read the returned lease identity once and match generation, subject kind,
  and subject ID exactly against the registration snapshot. A mismatch is
  closed and rejected.
- admission, candidate, runtime, and profile leases have owner-specific,
  idempotent close semantics; no lease is interchangeable with another.

A0.1 defines these shapes but invokes no effect-bearing operation on them.
Catalog-input validation reads only the concrete frozen admission identity
snapshot; trusted composition is responsible for supplying the corresponding
already-admitted source. Validation never reads a source property and does not
acquire or close a pin.

AppHost core imports neither AppServer nor Hosting. It also imports no Harness,
AppService, UI, Plugin implementation, or concrete Product package; optional
edges belong to later adapter slices.

## A0.2 Catalog And Router

`AppHostCatalogV1` owns one active immutable admitted generation. Admission
acquires one independent pin for every Product and profile, reads each returned
identity exactly once, and compares generation, subject kind, and subject ID
with the frozen registration. Publication occurs only after all pins pass.
Mismatch, source retirement, cancellation, or invalid cleanup capability
publishes nothing; rollback attempts every acquired pin in reverse order. A
cleanup failure is retained as closed `cleanup_incomplete` evidence with only a
safe primary category and debt count, never an external exception chain.

Replacement admits its new generation before an exact generation-ID CAS. A
successful CAS routes new work only to the new immutable snapshot and retires
the old catalog-owned pins. A private route lease owns a separate subject pin,
so retirement cannot close, mutate, or retarget a prepared route. A
catalog-owned base pin proves generation retention only; it never impersonates
route drain.

`AppHostRouterV1` requires an explicit Product for every operation. Resume
pins the explicit selected Product, opens one exact path-free candidate, checks
its envelope, executes final verify and claim, then invokes only the Product
candidate validator. Create first performs the read-only idempotency
lookup without acquiring a current pin. Only an absent record pins the Product
and calls create-if-absent with the descriptor compatibility identity. Recovery
pins the current Product only after the durable candidate is found. Explicit
migration requires a migration-only candidate and an admitted Product-owned
importer. No branch derives a Product, imports a Product module, or invokes a
Product/profile factory.

Success returns one independently owned implementation of the public minimal
`PreparedProductRouteV1` protocol. It retains the opened candidate, claimed
candidate, request lease, and exact route pin, but exposes only frozen
descriptor/generation/binding identity plus close. A0.2
hands out no factory or Product execution capability. Close settles those
owners in reverse acquisition order. Failure and cancellation register every
actually acquired unpublished owner in a Router-owned pending-cleanup registry
before settlement; failed items remain retryable through
`settle_pending_cleanup` and Router close, while successful items never repeat.

The AppHost-owned optional `HarnessAppHostSessionAdapterV1` integration is
outside AppHost core. Outer
composition explicitly binds existing `SessionDiscoverySource` identities to
AppHost scopes; the adapter asks the existing directory owner for its bounded,
deduplicated projection, retains the exact no-follow revision under a private
lease, and exposes current JSONL candidates only as `migration_required`. It
does not derive cwd/home roots, rescan a directory, create an index, or interpret
candidate tokens as paths. A migration candidate is accepted only after a full
pre/post stat-stable read from the same no-follow descriptor, bounded by the
AppHost-owned `HARNESS_SESSION_SNAPSHOT_MAX_BYTES_V1` constant (8 MiB). Claim
hands the Product sealed bytes, never a mutable descriptor or path; oversize or
read-time mutation fails closed. Canonical create/recovery is an optional
injected owner and remains absent by default. Every returned canonical owner is
bound to a static close descriptor and registered in the adapter's private
pending-cleanup registry before its projection or remaining callbacks are
validated. A rejected return therefore remains retryable even when its first
close fails or is cancelled, without requiring the Router to receive it. The
adapter's close fences new calls, joins in-flight validation, and settles that
registry; concurrent settlement joins the same attempt and retries only
unsettled owners. Canonical delegation is absent unless explicitly injected and
is capped by `HARNESS_SESSION_MAX_ACTIVE_CANONICAL_OPS_V1` at eight concurrent
provider calls. Every later provider call first drains existing unpublished
cleanup debt; if debt remains, the call fails before entering the provider.
Since every returned raw is still adopted before validation, the concurrent
permit bound also bounds registry strong references. The adapter itself has no
production consumer.

On POSIX, descriptor close has an inherently ambiguous error boundary: the
kernel may have released the descriptor even when `close(2)` reports failure.
The private descriptor owner atomically relinquishes its integer before the
syscall. It records the failed attempt but never retries that integer, avoiding
accidental close of a subsequently reused descriptor number.

## A0.3 Live Binding And Embedded Profile

`AppHostRuntimeV1` owns one `AppHostRouterV1`, one canonical live-binding
registry, and the supplied catalog. Public create/resume attachment calls first
enter a runtime admission fence. Resume opens the exact request-bound candidate
and derives the complete key before current catalog acquisition. Create keeps
its A0.2 lookup-first rule: a recovered durable candidate derives its key
without current admission, while an absent idempotency record acquires a
provisional current runtime bundle before create-if-absent.

The registry linearizes each binding key once. The first caller installs an
owner task and constructs one scoped Product Runtime; concurrent callers shield
and join that task. A waiter then validates its own final candidate through the
binding's retained validator. A recovered create caller releases any
provisional current bundle before using the existing binding. Failed
construction is removed rather than cached, and cancellation cannot abandon a
published attachment: the owner operation finishes, closes that exact
attachment, and re-raises cancellation.

An absent-key build retains a full-generation runtime bundle containing a
separate exact Product pin and a separate exact pin for every supported profile
factory. This is distinct from the catalog's base pins. Catalog replacement may
retire those base pins, but an existing binding can still validate and attach
only through its immutable retained Product/profile callbacks. It never consults
or falls forward to the new generation.

The Product factory borrows a frozen opened-candidate view. Its returned runtime
must expose the exact binding key, one non-owning `ProductProfileBindingV1`, and
an idempotent native-async close descriptor. A selected profile factory borrows
only that frozen view. Its returned lease must state the exact profile ID,
provide a non-owning `profile_binding`, and close idempotently. The public
`AppHostSessionLeaseV1` exposes only descriptor/generation/key/profile identity,
the borrowed profile binding, and close; it cannot close the Product Runtime.

Every attachment has a monotonic private token. Close and stale repeat-close
release only that exact attachment. Profile detach never closes a live Runtime;
only explicit Session close or process shutdown fences attachment admission,
waits already admitted validation/profile work, closes all profile leases, then
closes the scoped Product Runtime. The full-generation bundle is released only
after runtime close succeeds. An unresolved dependent close fences prerequisite
release and remains retryable.

`AppHostShutdownBudgetV1` supplies finite overall and per-phase monotonic
deadlines. Concurrent shutdown callers join one operation. The phases fence and
drain runtime admission, close bindings, close Router cleanup, then close the
catalog only when every dependency has settled. A timed-out phase remains
owned by its task; a later shutdown retries or rejoins it. The bounded
`AppHostShutdownReportV1` records closed phase identifiers only. It never treats
process, transport, Session persistence, or Product evidence as interchangeable.

Product, profile, Session, and cleanup callbacks execute without AppHost owner
locks held. A context-propagated runtime callback-domain fence rejects recursive
attach, Session close, pending-cleanup, or process-close calls on the same
runtime before they can wait on themselves.

## A0.4 Hosted Binder

`loushang.appserver.ports` owns the immutable generic
`AppServerProductPortsV1` wiring bundle and its authority-free Session identity.
This is a contract-only AppServer slice: it contains no protocol, AppService,
listener, connection, authentication, framing, transport, or daemon runtime.
The generic Session, Work, projection, and optional interaction type parameters
preserve the concrete structural types selected by a later AppService contract;
the bundle is not a `dict`, `Any`, generic command, or lifecycle owner.

The optional `loushang.apphost.hosted` module is the sole AppServer consumer.
`AppHostHostedBinderV1` borrows an `AppHostRuntimeV1` and selects one explicit
hosted profile ID. That profile's outer integration factory maps the Product
runtime view into `AppServerProductPortsV1`. The binder checks exact
Product/continuity/Session identity, returns an owned hosted attachment, and
otherwise closes the attachment before returning a closed
`profile_unavailable` failure. It never invokes the structural ports, parses an
App protocol, constructs AppService, or owns transport state. Neither AppHost's
core facade nor AppServer imports this optional edge.

## Immutable Catalog Input

`AppHostCatalogInputV1` accepts one bounded tuple of Product registrations and
one bounded tuple of profile registrations for exactly one generation. It
rejects:

- empty or malformed generation and contract identities;
- non-tuple or oversized registration inputs;
- duplicate Product or profile IDs;
- registration admission identity snapshots declared for another generation;
- registration admission identity snapshots whose subject does not match the
  descriptor kind and identity;
- Product references to profiles absent from the same snapshot; and
- incompatible contract versions.

The validated object remains an input value, not a registry. It has no lookup,
replacement, mutation, retirement, default, or factory invocation behavior.
Its admission sources are borrowed. A0.2 must acquire a distinct owned pin for
each accepted registration before publication and compare the returned
lease's concrete identity exactly with the frozen registration snapshot.
Mismatch, retirement during acquire, failure, or cancellation publishes
nothing and closes any returned pin; rejection leaves every source with
trusted outer composition.

## Borrow And Ownership Semantics

Every effectful step is non-consuming. `claim` returns a separately owned
claimed candidate while the request lease stays caller-owned. The Product
validator borrows that claimed candidate and returns a separately owned opened
candidate. The Product factory borrows the opened candidate and returns a
separately owned scoped runtime. The profile factory receives only the
runtime's non-owning profile binding and returns an independently owned profile
lease.

On success, failure, or cancellation the caller closes acquired values once in
reverse order. A callee never closes a borrowed input; a failed or cancelled
callee settles its unpublished partial resources and returns no owned output.
The live registry alone closes the scoped runtime. A profile lease cannot close
or otherwise impersonate that owner.

## Validation Rules

- stable identifiers use lowercase ASCII letters/digits plus `._-`, start with
  a letter or digit, and are bounded to 128 characters;
- opaque lookup tokens are bounded ASCII token-alphabet values; Session,
  continuity, operation, generation, locator, candidate, and revision tokens
  are never interpreted directly as filesystem operands;
- operation IDs contain at least 22 token characters; trusted boundaries mint
  at least 128 bits of entropy and never reuse one within a creator scope;
- collections are exact immutable tuples, bounded, duplicate-free, and retain
  their caller-declared order;
- registration effect ports expose class-defined native-async methods;
  validation inspects descriptors statically and never executes a property or
  dynamic attribute hook;
- validation reads no environment, cwd, home, filesystem, registry, network,
  clock, random source, or Product module.

## Failure And Observation Boundary

`AppHostFailureCategory` is a closed cross-Product routing/lifecycle taxonomy.
`InvalidAppHostContractError` retains only a bounded stable field name and a
closed `InvalidAppHostContractReason`; base error text is derived only from its
closed category. No public constructor accepts a free-form message, and no
exception preserves a rejected value or arbitrary reason payload.
`AppHostObservationV1` contains only bounded component, transition, identity,
generation, and closed failure fields. It contains no message, details, path,
environment, Product payload, or authorization claim.

## A0.1 Exit Gate

A0.1 is complete when:

1. the package imports only Python standard-library modules;
2. public values are frozen and exact validation tests pass;
3. catalog input uniqueness, generation, profile-reference, and bound checks
   pass without invoking a supplied effect-bearing port operation;
4. no catalog/router/live registry/profile composer/launcher implementation or
   Product import exists;
5. Harness, Hosting, AppServer, AppService, and concrete Products do not import
   AppHost; and
6. no production composition path imports or instantiates AppHost.

These gates keep every existing runtime path unchanged and default-dark.

## A0.2 Exit Gate

A0.2 is complete when:

1. AppHost core remains standard-library-only and imports no Harness, Hosting,
   AppServer, AppService, UI, Plugin implementation, or concrete Product;
2. two unrelated fake Products pass explicit resume, idempotent create, and
   copy-first migration without a default branch or factory invocation;
3. catalog admission, exact pin identity, reverse rollback, CAS replacement,
   revision swap, retirement, and compatibility failure matrices pass;
4. the optional Harness integration projects explicitly injected cwd, legacy
   user-global, and canonical user-global sources through the existing owner,
   sealing at most 8 MiB after full pre/post descriptor-stat equality; claimed
   reads remain immutable and Windows stays fail-closed until a reviewed
   native retained-handle backend exists; rejected canonical returns remain in
   the adapter-owned cleanup registry across failure and cancellation, and
   adapter close fences and joins in-flight calls; canonical provider calls are
   capped at eight and cannot continue while earlier cleanup debt remains;
5. no live registry, profile composer, launcher, Product activation, native
   profile, or production composition consumer exists; and
6. A0.1 and neighboring Hosting architecture gates remain green.

## A0.3 Exit Gate

A0.3 is complete when:

1. concurrent create/resume callers for one key construct exactly one Runtime,
   while unrelated keys and Products remain independent;
2. existing-key validation and profile binding use only the retained generation
   across catalog replacement;
3. multi-profile and multi-mux attachments close independently, and stale or
   cancelled detach cannot close a successor or the underlying Runtime;
4. failed validation, partial construction, malformed returns, cancellation,
   explicit Session close, and shutdown retain and retry every owned cleanup in
   dependency order;
5. finite shutdown deadlines report typed phase facts, leave timed-out tasks
   owned, continue every dependency-safe phase, and converge on retry; and
6. AppHost core remains standard-library-only and has no production consumer,
   concrete Product, AppServer, Hosting, UI, or implicit default route.

## A0.4 Exit Gate

A0.4 is complete when:

1. AppServer owns only the contract-only typed structural Product port bundle;
2. `apphost.hosted` is the sole AppServer consumer and the core facade stays
   AppServer-free;
3. exact identity maps through the hosted profile while foreign or malformed
   bindings are closed and rejected;
4. hosted detach owns only its AppHost attachment and cannot synthesize Product
   Runtime, AppService, listener, transport, or process closure; and
5. no AppServer runtime, concrete Product adapter, launcher, Product/native
   Worker activation, or production composition route is introduced.
