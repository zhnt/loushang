# AppHost A0 Contract Model

## Status

- ID: `APPHOST-A0-CONTRACT`
- Scope: `apphost`
- Parent: `loushang`
- Authority: normative — accepted AppHost A0 contract specification
- Design status: accepted
- Implementation status: implemented — A0.1 values and ports only
- Activation status: none
- Owner: Loushang AppHost architecture

## Purpose

A0.1 creates the smallest dependency-safe seam for later Product routing. It
defines immutable values and structural ports, validates one immutable catalog
input generation, and performs no discovery, import, routing, attachment,
runtime construction, persistence, or process launch.

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
trusted-boundary-minted, high-entropy `operation_id`. Neither token is an
authorization claim. The injected canonical Session owner uses
`(product_id, creator_scope_id, operation_id)` as an idempotency identity and
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
