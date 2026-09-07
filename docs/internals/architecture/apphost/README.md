# Loushang AppHost Architecture

[Architecture](../README.md) ·
[ARD-003](../decisions/ARD-003-apphost-top-level-placement.md) ·
[A0 Contract Model](contract-model-a0.md) ·
[G8 Product/Worker Join](product-worker-join-g8.md) ·
[G9 V1 Closure](hosted-product-v1-closure-g9.md) ·
[G9.3 Current Owner Decision](current-worker-owner-decision-g9.md) ·
[G9 Promotion Record](hosted-product-g9-promotion-record.md) ·
[G10 Installed Explicit Canary](installed-explicit-canary-g10.md) ·
[G11 Hosted Application](../appserver/hosted-application-g11.md) ·
[Hosted Product Runtime V1 Plan](../drafts/hosted-product-runtime-v1-plan.md)

## Status

- Scope: `apphost`
- Parent: `loushang`
- Authority: normative — accepted AppHost scope boundary
- Design status: accepted
- Implementation status: partial — Hosted Product Runtime G0--G10 is
  implemented; A0.5 remains not-started
- Activation status: default-dark; only the exact installed G10 canary selects
  Hosting, while ordinary CLI, TUI, SDK, AppService, and AppServer routes do not
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
caller cannot bypass routing.

A0.3 adds:

- `AppHostRuntimeV1`, the sole process-local owner of a canonical live Product
  Runtime per `(product_id, continuity_id, session_id)`;
- private pre-runtime Router seams that derive or recover the complete binding
  key before current-generation admission when the identity already exists;
- a full-generation runtime bundle pin retaining the selected Product
  validator/factory and every supported profile factory for the binding's
  lifetime;
- single-flight construction, independent profile attachment leases, exact
  Session fencing, stale-detach safety, cancellation compensation, retryable
  dependency-ordered cleanup, and bounded monotonic shutdown phases; and
- callback-domain re-entry rejection before an owner wait can deadlock.

A0.4 adds one optional `apphost.hosted` binder. A hosted profile factory maps
the runtime's non-owning Product view into the contract-only
`AppServerProductPortsV1` bundle owned by `loushang.appserver.ports`. The binder
checks exact Session identity and returns an owned hosted attachment, but never
invokes Session/Work/projection/interaction ports or constructs AppService,
protocol, listener, connection, or transport state.

Existing Product-specific bootstrap/CLI/TUI paths remain authoritative and do
not import the G9 composition. The one installed explicit factory may
instantiate the catalog, runtime, selected profiles, and G8 Product
registration only after an exact typed Hosting activation request.

The implemented [G8 Product/Worker Join](product-worker-join-g8.md) is the first
concrete Product composition without changing AppHost core. The Coding-owned
outer adapter implements the existing Product factory/runtime ports and retains
all Worker authority inside Coding/Harness. Its explicit registration helper is
uncomposed and grants no activation authority by itself.

The accepted [G9 V1 Closure](hosted-product-v1-closure-g9.md) separates installed
composition, explicit activation, omitted-owner policy, Current deletion
decision, and main promotion. G9.1--G9.2 implement the explicit composition and
rollback/crash drill; the accepted G9.3 decision retains Current after a
source-backed entrypoint and eight-condition deletion audit. No Current source
or route changes, and omission remains Current. The
[G9 promotion record](hosted-product-g9-promotion-record.md) closes G9.4 on the
exact reviewed lane head and records capability availability on `main` without
activation.

The implemented [G10 Installed Explicit Canary](installed-explicit-canary-g10.md)
provides the first installed, exact-command path through the G9 composition and
a real short-lived Hosting child. It remains a canary rather than a normal
Coding session route. Its Product-owned durable enable/rollback control,
bounded report, lazy CLI edge, source-backed inventory, and separate
Linux/Windows evidence are retained by the AppHost quality gate.

The implemented sibling
[G11 Hosted Application](../appserver/hosted-application-g11.md) adds an
explicit in-process AppService and Harnesstui Hosted Mux Profile. It does not
compose through AppHost, select Hosting, or change this scope's runtime. The
A0.4 binder still consumes only AppServer's structural `ports.py`; AppServer's
new protocol/client contract and AppService remain sibling-owned.

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

Coding G8 integration -> AppHost public facade + Coding/Harness Worker values

AppHost catalog/router -> AppHost contracts + injected Product ports
A0.3 embedded profile -> AppHost contracts + injected Product/profile ports
A0.4 hosted binder -> AppHost contracts + AppServer structural port bundle
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
7. Exactly one live binding owns a Product Runtime for one
   `(product_id, continuity_id, session_id)` key; profile/mux attachments are
   leases over a non-owning profile view, not runtime owners.
8. Python factories and live handles never cross a process boundary.
9. Cleanup evidence is owner-specific: Product detach, AppServer drain,
   Hosting process exit, and durable Session persistence cannot synthesize one
   another.
10. A0.1 performs validation only. A0.2 may invoke only admission, Session
    candidate, Product validator, importer, and cleanup ports; it never invokes
    a Product factory or profile factory. Only A0.3's private runtime path may
    invoke them.
11. The optional Harness integration receives exact source bindings from outer
    composition.
    It never derives a path from cwd/home scope, treats a candidate token as a
    path, or creates a second Session index.
12. The Coding-owned G8 adapter joins PLC9C5 Product/native Worker activation
    to AppHost without moving Worker policy into AppHost; the route remains
    default-dark.
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
18. An existing live key validates and attaches only through its retained
    generation bundle. Catalog replacement cannot redirect it to a new
    validator, runtime factory, or profile factory.
19. Runtime close precedes release of its Product/profile generation bundle.
    An unresolved dependent closer fences every prerequisite owner; retry
    resumes at the exact debt rather than synthesizing release.
20. A0.4 carries AppServer-owned typed structural ports but does not call them.
    Port behavior, logical detach, protocol, listener, and transport ownership
    remain outside AppHost.
21. Main promotion, explicit route activation, omitted-owner change, and
    Current-owner deletion are separate decisions. None is inferred from
    another, and a valid G9 retention decision may keep Current.
22. G10 may activate only through the exact installed canary command. Its
    ephemeral identity cannot read or write user Sessions, and a successful
    canary cannot authorize normal-session migration or Current deletion.

## Delivery Sequence

| Slice | Delivery | State |
| --- | --- | --- |
| A0.0 | accepted placement, scope, component boundary, glossary, and parent architecture gates | accepted |
| A0.1 | standard-library Contract Model and immutable catalog-input validation | implemented, uncomposed |
| A0.2 | catalog/router, exact admission-pin verification, idempotent Session create/candidate adapter, and explicit importer over fakes | implemented, uncomposed |
| A0.3 | canonical live-binding registry, scoped runtime lifecycle, and embedded profile | implemented, uncomposed |
| A0.4 | optional hosted binder over the contract-only AppServer structural port bundle | implemented, uncomposed |
| A0.5 | optional serialized launcher | deferred pending its own boundary review |
| G8.0 | cross-scope Product/Worker join boundary and executable guards | accepted |
| G8.1 | Coding Product registration/factory, exact receipt join, and frozen profile projection | implemented, uncomposed |
| G8.2 | concrete Coding canary normal-close lifecycle and Product compatibility | implemented, uncomposed |
| G8.3 | multi-profile/Session, cancellation, retry, shutdown, and retained evidence gates | implemented, uncomposed |
| G9.0 | production-composition, operational-drill, Current-deletion, and main-promotion closure contract | accepted; no source or activation change |
| G9.1 | sole Product-owned installed composition with explicit opt-in | implemented, default-dark |
| G9.2 | rollback/crash drill and retained Linux/Windows evidence | implemented; Windows retained by CI |
| G9.3 | entrypoint inventory and Current-owner RETAIN/DELETE decision | implemented; `RETAIN` accepted |
| G9.4 | architecture reconciliation and lane-to-main promotion | implemented; promoted default-dark |
| G10.0 | installed explicit canary boundary, durable control, evidence, and threat model | accepted |
| G10.1--G10.4 | Product control journal, native canary, lazy CLI route, retained cross-platform evidence, and promotion | implemented, explicit and default-dark |

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
- `tests/apphost/test_runtime.py` proves single-flight multi-attach, retained
  generation validation/profile binding, cancellation, construction rollback,
  stale detach, dependency-ordered close, shutdown deadline/retry, re-entry,
  and hosted identity mapping;
- `tests/architecture/test_apphost_a03_a04_architecture.py` proves that the
  runtime stays in the standard-library-only core, the hosted edge remains the
  sole AppHost-to-AppServer consumer, and the A0.4 structural ports remain
  contract-only after G11;
- `tests/coding/test_apphost_product.py` and
  `tests/architecture/test_hosted_product_runtime_g8_join.py` prove the exact
  G8 receipt, recovery, ownership, multi-profile/Session, fault, cleanup, and
  dependency matrix;
- `hosted-product-g8-evidence-manifest.json` pins the zero-skip G8 case set;
  PLC9C5 separately retains Linux and Windows native/Product evidence;
- `tests/coding/test_apphost_composition.py`,
  `tests/architecture/test_hosted_product_runtime_g9_closure.py`, the
  source-backed `hosted-product-g9-entrypoint-inventory.json`, and
  `hosted-product-g9-evidence-manifest.json` prove the G9.1--G9.2 explicit
  composition, default-dark source facts, rollback/crash matrix, exact
  dependency edge, and separate Linux/Windows report identities;
- `current-worker-owner-decision-g9.md` and
  `hosted-product-g9-promotion-record.md` prove the G9.3 `RETAIN` decision and
  G9.4 exact-head default-dark promotion independently;
- `tests/coding/test_apphost_canary*.py`, `tests/coding/test_cli_apphost.py`,
  `tests/architecture/test_hosted_product_g10_explicit_canary.py`, and
  `hosted-product-g10-evidence-manifest.json` prove exact lazy dispatch,
  durable selection, ephemeral Session identity, native Hosting ownership,
  bounded reporting, rollback, cancellation cleanup, and inventory v3 on
  Linux and Windows;
- `make check-apphost` runs the focused lint, typecheck, and contract suite;
- `make check-architecture-docs` validates parent documentation integrity.

Passing these gates proves A0.4 mechanics, the default-dark G8--G9 concrete
Product composition, and the explicitly selected short-lived G10 canary. G10
itself grants no default Product, normal-session Hosting route,
AppService/AppServer runtime, launcher, omitted-owner change, or Current
deletion. G11's separate in-process application semantics do not change those
AppHost conclusions.
