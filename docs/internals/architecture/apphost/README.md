# Loushang AppHost Architecture

[Architecture](../README.md) ·
[ARD-003](../decisions/ARD-003-apphost-top-level-placement.md) ·
[A0 Contract Model](contract-model-a0.md) ·
[Hosted Product Runtime V1 Plan](../drafts/hosted-product-runtime-v1-plan.md)

## Status

- Scope: `apphost`
- Parent: `loushang`
- Authority: normative — accepted AppHost scope boundary
- Design status: accepted
- Implementation status: partial — A0.2 catalog/router and optional dark
  Harness Session integration
- Activation status: none; no live registry, profile composer, launcher, or
  Product composition route
- Owner: Loushang AppHost architecture

## Scope

AppHost is the Product-neutral process-local composition root for admitted
Products. It gives the logical Platform Host one physical owner without making
Harness, Hosting, AppServer, AppService, or a concrete Product own the others.

AppHost is a sibling Architecture Scope and initially remains in the main
`loushang` distribution. A separate distribution requires independent demand
and a later packaging decision.

## Current

A0.1 supplies immutable standard-library contracts and exact validation for:

- Product and profile descriptors;
- path-free Session identity envelopes and candidate references;
- Product factory, candidate validator, importer, runtime/profile binding, and
  subject-bound admission source/lease contracts;
- the injected Session identity/catalog port;
- immutable catalog input generations; and
- bounded failures and observations.

A0.2 adds:

- an atomic owner over immutable admitted generations, with one exact
  catalog-owned pin per Product/profile and an independent exact pin per route;
- compare-and-swap generation replacement and retirement fencing that never
  retargets an already returned route;
- explicit create, resume, and Product-owned migration routing through the
  injected Session identity owner; and
- one AppHost-owned optional Harness integration that projects only explicitly
  bound existing discovery sources and delegates canonical creation to an
  injected owner.

The router returns the public minimal `PreparedProductRouteV1` surface,
containing only immutable descriptor/generation/binding facts and close
ownership. It exposes neither a factory nor an opened Product capability. The
Catalog's Product-pin acquisition remains a private Router friend seam, so a
caller cannot bypass routing. There is no runtime owner or
composition entrypoint. Existing Product-specific CLI/TUI paths remain
authoritative. No production module imports or instantiates the catalog,
router, or Harness adapter.

## Target

The accepted target adds, by separately reviewed slices:

1. an immutable admitted Product/profile catalog and explicit router;
2. request-bound, revision-pinned Session candidate routing and explicit
   Product-owned compatibility import;
3. one canonical live Product Runtime binding per Session identity;
4. orthogonal embedded delivery-profile composition; and
5. optional hosted and serialized-launch adapters.

## Owns

- AppHost Product/profile contract vocabulary;
- immutable admitted catalog projection and explicit Product routing;
- canonical process-local Product Runtime binding identity and lifetime;
- deployment-profile selection and binding;
- process-level admission fencing and ordered Product Runtime release; and
- optional outward hosted/launcher adapters when separately accepted.

## Does Not Own

- Product kernels, Product policy, prompts, tools, resources, or presentation;
- Harness Runtime Profile, Capability, Plugin, Session, Transcript, Blob, Work,
  Policy, Approval, or Sandbox implementations;
- cwd, home, `$LOUSHANG_HOME`, Session store, or filesystem discovery;
- AppServer listener, transport, connection, authentication, or framing;
- AppService membership, subscription, presenter, or aggregate semantics;
- Hosting process, endpoint, containment, or service-instance mechanisms;
- UI rendering, clipboard/image capture, logs, traces, or artifact storage; or
- implicit Product selection or same-attempt owner fallback.

## Dependency Boundary

```text
Product package integration -> AppHost contracts
AppHost core -> Python standard library

AppHost catalog/router -> AppHost contracts + injected Product ports
future embedded profile -> AppHost contracts + public Harness/Product contracts
future hosted binder -> AppHost contracts + AppServer structural ports
future launcher -> AppHost serialized values + Hosting contracts

AppHost optional Harness integration -> public Harness owner + AppHost contracts
Hosting / AppServer / AppService -/-> AppHost
AppHost core -/-> Harness / Hosting / AppServer / AppService / concrete Product
```

Optional edges may not be introduced through the core facade merely for
convenience. Concrete Product imports occur only in trusted outer composition,
after Product/OEM admission, never through a derived module name.

## Core Invariants

1. Every route carries an explicit `product_id`; AppHost never guesses or
   silently falls back.
2. A Session Identity Envelope is routing input, not authority. The selected
   Product validates the finally claimed candidate and continuity before
   factory effect. New Sessions begin from an explicit Product request and the
   canonical Session owner mints and atomically establishes their identity.
3. AppHost receives path-free candidate references. Discovery owners choose
   cwd/user-global scopes and retain exact source revisions.
4. Create and resume have different first linearization points. Resume derives
   its complete binding key from the envelope before registry lookup. Create
   first looks up an existing idempotency record. If absent, it pins the
   explicit current Product and performs create-if-absent; then it branches on
   the newly known key. An existing compatible binding closes any provisional
   current pin and joins only its retained generation; a fenced binding fails;
   only an absent binding may validate/build using the current compatible pin.
5. Catalog generations are immutable. Replacement fences new pins while old
   Session bindings retain their exact admission/content generation.
6. Product identity and delivery profile are orthogonal.
7. Exactly one future live binding owns a Product Runtime for one
   `(product_id, continuity_id, session_id)` key; profile/mux attachments are
   leases over a non-owning profile view, not runtime owners.
8. Python factories and live handles never cross a process boundary.
9. Cleanup evidence is owner-specific: Product detach, AppServer drain,
   Hosting process exit, and durable Session persistence cannot synthesize one
   another.
10. A0.1 performs validation only. A0.2 may invoke only admission, Session
    candidate, Product validator, importer, and cleanup ports; it never invokes
    a Product factory or profile factory.
11. The optional Harness integration receives exact source bindings from outer
    composition.
    It never derives a path from cwd/home scope, treats a candidate token as a
    path, or creates a second Session index.
12. PLC9C5 Product/native Worker activation remains default-dark and outside
    AppHost A0.
13. The optional Harness integration seals at most 8 MiB from one no-follow
    descriptor. It accepts only an unchanged pre/post full stat snapshot and
    claimed reads use immutable bytes rather than the descriptor or path.
14. Failed unpublished Router cleanup remains Router-owned and retryable;
    `settle_pending_cleanup` and Router close join it without exposing owners.
15. The optional Harness integration independently fences its own calls and
    adopts every raw canonical candidate before projection validation. Rejected
    returns remain adapter-owned until `settle_pending_cleanup` or adapter close
    joins their successful settlement; the Router need never observe the raw
    return.
16. A POSIX descriptor owner relinquishes its descriptor number before calling
    `close(2)`. A post-effect or otherwise ambiguous close error is recorded as
    cleanup evidence, but that integer is never retried because the kernel may
    already have released and reused it.
17. Canonical delegation is default-dark and bounded to eight concurrent
    provider calls. Before starting another call, the adapter drains prior
    unpublished cleanup debt; unresolved debt rejects the call before the
    provider runs. Together, the fence and limit bound retained malformed raw
    owners without weakening adopt-before-validation.

## Delivery Sequence

| Slice | Delivery | State |
| --- | --- | --- |
| A0.0 | accepted placement, scope, component boundary, glossary, and parent architecture gates | accepted |
| A0.1 | standard-library Contract Model and immutable catalog-input validation | implemented, uncomposed |
| A0.2 | catalog/router, exact admission-pin verification, idempotent Session create/candidate adapter, and explicit importer over fakes | implemented, uncomposed |
| A0.3 | canonical live-binding registry, scoped runtime lifecycle, and embedded profile | not started |
| A0.4 | optional hosted binder | deferred pending AppServer contracts |
| A0.5 | optional serialized launcher | deferred pending its own boundary review |

## Evidence

- `tests/apphost/test_contracts.py` proves exact value and catalog validation;
- `tests/architecture/test_apphost_a0_contract.py` proves package shape,
  standard-library-only imports, parent adoption, and absence of runtime or
  optional dependency edges;
- `tests/architecture/test_apphost_a02_architecture.py` proves lookup-first
  create, no factory effect, the one-way optional Harness integration, and absence of
  production consumers;
- `tests/apphost/test_catalog.py`, `tests/apphost/test_router.py`, and
  `tests/apphost/test_harness_session_integration.py` prove the A0.2
  admission, replacement, candidate, scope, migration, race, and rollback
  matrix;
- `make check-apphost` runs the focused lint, typecheck, and contract suite;
- `make check-architecture-docs` validates parent documentation integrity.

Passing these gates proves A0.2 preparation only. It grants no live binding,
runtime/profile composition, default Product, hosted route, or Product/native
Worker activation.
