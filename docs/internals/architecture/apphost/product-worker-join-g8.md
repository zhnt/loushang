# Hosted Product Runtime G8 Product/Worker Join

## Status

- ID: `HOSTED-PRODUCT-G8`
- Scope: cross-scope AppHost plus Product-owned Harness Worker composition
- Parent: `HOSTED-PRODUCT-RUNTIME-V1`
- Authority: normative accepted design
- Design status: accepted
- Implementation status: not-started — G8.0 design accepted; G8.1 not started
- Activation status: default-dark; no installed entrypoint or default Product route
- Owner: Loushang architecture with AppHost, Coding Product, Harness, and Hosting
  boundary review

## Goal

G8 is the first end-to-end join between the already implemented AppHost rail
and the already implemented Product/Harness Worker rail. An explicitly admitted
Coding Product Session may construct one exact Product-owned Worker attempt from
its immutable C5.1 activation receipt. A semantically unrelated Product remains
fully usable without importing, constructing, probing, or closing a Worker.

The join is complete only when AppHost continues to see ordinary Product and
profile ports, the Coding Product owns all Worker policy and lifecycle meaning,
and retained Linux and Windows evidence proves that the same exact receipt can
reach the already accepted native profiles without fallback.

G8 does not activate a production default, delete the Current Worker owner, add
an AppServer runtime, implement AppService, or introduce a daemon, listener,
remote protocol, serialized launcher, or surviving-process adoption.

## Current, Target, And Delta

### Current

- AppHost A0.1--A0.4 owns explicit Product routing, canonical per-Session live
  bindings, independently leased profiles, bounded shutdown, and an optional
  AppServer structural-port binder. It is default-dark and has no concrete
  Product registration.
- PLC9C5 C5.1--C5.5c owns the pathless Product Worker activation receipt,
  sticky owner selection, lifecycle coordinator, Linux static containment,
  Windows LPAC containment, and explicit Coding canaries. G7 is closed.
- Coding is the only installed Product, but its current CLI/TUI composition does
  not construct AppHost.

### Target

One outer Coding-owned integration implements AppHost's existing Product
factory/runtime contracts. For every new AppHost live binding it obtains one
fresh Worker attempt from an injected Product-owned factory, verifies that the
attempt carries the exact Session/Product receipt, completes durable recovery,
starts it, and returns an AppHost-owned scoped Product Runtime. AppHost profile
attachments borrow a frozen status projection and receive no Worker control
capability.

### Permitted source delta

- add one Coding-owned AppHost Product integration module;
- add Product-scoped normal-close support to the existing Coding Worker canary;
- add G8 contract, lifecycle, fault, and architecture tests;
- add a retained G8 report and CI gate; and
- update Current architecture facts and indexes.

No AppHost core, Hosting, Harness Worker, AppServer, AppService, UI, or installed
entrypoint may import the concrete integration.

## First-Principles Decisions

1. **The concrete Product owns the join.** AppHost owns routing and scoped
   lifetime, not Worker policy. Harness owns Worker mechanisms, not Product
   selection. The only layer allowed to know both is the explicit Coding
   Product integration.
2. **The activation receipt is the join authority.** A Coding Worker attempt is
   accepted only when its typed receipt names the exact AppHost `product_id` and
   `session_id`. A profile name, platform fact, available backend, environment
   variable, or opaque Session payload cannot synthesize that authority.
3. **One AppHost live binding owns one Worker attempt.** AppHost's existing
   single-flight key `(product_id, continuity_id, session_id)` is reused. Multiple
   embedded, hosted, or named-mux profile attachments share the Product Runtime;
   they never create duplicate Workers. Different Session keys remain
   independent.
4. **Recovery precedes effect.** The Product factory completes the canary's
   durable recovery drill before calling `start`. Recovery failure creates no
   AppHost runtime and never falls back to Current within the attempt.
5. **Profiles borrow facts, not authority.** The Product Runtime exposes a
   frozen pathless binding containing only the exact binding key, receipt
   fingerprint, attempt identity, generation, requiredness, owner, readiness,
   and stable status code. It exposes no canary, supervisor, process, native
   profile, receipt object, rollback method, or close capability.
6. **A Worker-free Product is genuinely Worker-free.** An unrelated Product
   registers its own ordinary AppHost factory. AppHost does not import the
   Coding integration and never constructs the Coding attempt factory on that
   Product's route.
7. **Normal close is not rollback.** AppHost Session close fences and drains the
   exact domain publication, retires the exact attempt, gracefully shuts down
   or fences its process, settles cleanup, and clears readiness. It does not
   latch the Product-wide kill switch or issue a replacement Current receipt.
   Explicit rollback retains the existing C5.1/C5.4 semantics.
8. **Ownership is adopted before inspection.** Once the Product attempt factory
   returns, the Coding integration binds its close operation before reading its
   receipt or status. Malformed returns, cancellation, recovery failure, and
   start failure are compensated before the AppHost factory returns.
9. **Failure stays typed and redacted.** Product detail does not escape through
   AppHost. AppHost continues to project `runtime_unavailable` or
   `cleanup_incomplete`; paths, native identities, payloads, exceptions, and
   receipts remain below their owners.
10. **The route remains explicit and dark.** No existing CLI, TUI, SDK,
    AppServer, or hosted entrypoint imports or constructs the G8 registration.
    Production activation requires a later independently reviewed composition.

## System Boundary

```text
trusted outer composition
  -> AppHost catalog generation
       -> Coding ProductRegistrationV1
            -> Product-owned candidate validator
            -> CodingAppHostProductFactoryV1
                 -> injected CodingAppHostWorkerAttemptFactoryV1
                      -> exact CodingProductWorkerCanary
                           -> ProductWorkerActivationReceiptV1
                           -> Harness Worker -> Hosting native child session
                 -> scoped Coding Product Runtime
                      -> frozen non-owning Product/profile binding

unrelated ProductRegistrationV1
  -> unrelated Product factory/runtime/profile
  -/-> Coding integration / Worker attempt factory
```

AppHost calls only its existing Product and profile protocols. The physical
dependency is one-way:

```text
loushang.coding.apphost_product -> loushang.apphost public facade
loushang.coding.apphost_product -> Coding Worker canary / public Harness values

loushang.apphost -/-> loushang.coding
loushang.apphost core -/-> loushang.harness / loushang.hosting / Product code
loushang.harness / loushang.hosting / loushang.appserver -/-> loushang.apphost
```

The pre-existing optional `apphost.integrations.harness_session` adapter remains
the sole AppHost-to-Harness integration and owns Session discovery only. It does
not gain Worker imports or activation authority.

## Contract Model

### `CodingAppHostWorkerAttemptV1`

The Product-owned structural attempt port supplies:

- `receipt_for_entrypoint("product")`;
- `recover()`;
- `start(correlation_id=...)`;
- immutable `status`; and
- retryable idempotent `close()`.

The concrete `CodingProductWorkerCanary` implements this port. G8 does not make
the port part of AppHost or Harness.

### `CodingAppHostWorkerAttemptFactoryV1`

The injected factory receives the exact `SessionBindingKeyV1` and the
Product-opened opaque Session binding. It returns a fresh, unpublished attempt.
It does not receive AppHost runtime ownership or a profile attachment.

### `CodingAppHostProductFactoryV1`

This Product-owned implementation of `ProductFactoryV1`:

1. validates the already-opened candidate's exact binding key;
2. obtains and immediately adopts one fresh Worker attempt;
3. reads the `product` entrypoint receipt and matches Product/Session identity;
4. runs recovery;
5. starts the attempt and validates the returned immutable status against the
   receipt; and
6. returns the scoped Product Runtime only after required readiness succeeds or
   an explicitly optional contribution reaches a typed degraded state.

Every exceptional or cancelled path closes the unpublished attempt. Failed
construction is not cached by AppHost, so a later attach obtains a fresh
attempt rather than replaying a failed one.

### `CodingAppHostProductBindingV1`

This frozen projection is the only G8 object supplied through
`ProductProfileBindingV1.opaque_binding`. It carries bounded scalar identity and
status facts. Profile code cannot close, restart, recover, query, or roll back a
Worker through it.

### Registration

The Coding helper constructs one ordinary `ProductRegistrationV1` from an
explicit generation id, admission source, Product candidate validator, exact
supported profile ids, compatibility id, and Worker-attempt factory. It performs
no discovery, admission, native selection, or activation by itself.

## Lifecycle And Linearization

```text
AppHost attach/create
  -> route and claim exact Session candidate
  -> Product validator opens exact candidate
  -> AppHost single-flight selects or builds live binding
     -> Coding factory adopts fresh attempt
     -> validate exact receipt to binding key
     -> recover prior attempt evidence
     -> start / handshake / domain publication
     -> publish scoped Product Runtime
  -> bind independently owned profile attachment

profile detach
  -> close only that profile lease
  -> Product Runtime and Worker remain live

last detach
  -> no implicit Product Runtime close

AppHost close_session / shutdown
  -> fence new profile reservations
  -> drain and close profile leases
  -> Product Runtime closes exact Worker attempt
  -> release Product/profile generation pins
```

The Worker effect remains linearized by C5.1 admission and Hosting capture, not
by AppHost route preparation. AppHost publication does not replace Worker
handshake/domain publication evidence.

## Failure And Recovery Rules

- Candidate or receipt mismatch fails before recovery or Worker effect.
- Recovery failure closes the unpublished attempt and returns no Product
  Runtime.
- Required Worker start failure fails Product Runtime construction.
- Optional Worker start failure may return only the canary's explicit degraded
  status; it never retries Current in the same attempt.
- Cancellation waits for the shielded construction result and closes any
  unpublished or cancelled attachment through existing AppHost ownership.
- Product Runtime close is retryable. Partial Worker settlement keeps the
  AppHost live slot fenced and retains its catalog pins until the same closer
  succeeds.
- A stale profile detach can close only its own attachment token and cannot
  close a successor Product Runtime or Worker attempt.
- Process/native cleanup evidence remains owned by Harness/Hosting. AppHost
  cleanup success cannot manufacture Worker tree or LPAC settlement.

## Delivery Slices

| Slice | Delivery | Exit condition |
| --- | --- | --- |
| G8.0 | this accepted boundary, Current inventory delta, threat model, evidence matrix, and executable architecture guards | no production source or activation change; no unresolved high/medium design issue |
| G8.1 | Coding-owned registration, attempt factory port, frozen profile projection, and scoped Product Runtime over deterministic fakes | exact receipt binding, recovery-before-start, adoption-before-inspection, Worker-free unrelated Product, single-flight and multi-Session tests pass |
| G8.2 | concrete `CodingProductWorkerCanary` normal-close lifecycle and Product-factory compatibility | real canary object joins through AppHost; required/optional, no-fallback, Linux and Windows retained evidence remain green |
| G8.3 | cancellation, construction failure, multi-profile/mux, stale detach, shutdown, cleanup-debt retry, recovery, and cross-entrypoint report | retained zero-skip G8 report and architecture/CI gates pass; route remains default-dark |

## Retained Evidence Matrix

| Case | Required proof |
| --- | --- |
| `G8-EXACT-RECEIPT` | Product and Session in the typed receipt exactly equal the AppHost binding key |
| `G8-RECEIPT-MISMATCH` | foreign/missing/current receipts fail before recovery or effect and are closed |
| `G8-RECOVERY-FIRST` | recovery completes before start and failure creates no cached runtime |
| `G8-REQUIRED-READY` | required canary returns only after ready publication |
| `G8-OPTIONAL-DEGRADED` | optional failure returns the explicit degraded state without fallback |
| `G8-UNRELATED-WORKER-FREE` | unrelated Product attaches while the Coding attempt factory remains untouched |
| `G8-MULTIPROFILE-SINGLE-FLIGHT` | two profile/mux attachments share one Product Runtime and one Worker attempt |
| `G8-MULTISESSION-ISOLATION` | distinct Session keys own distinct attempts and can close independently |
| `G8-DETACH-NONOWNING` | profile detach does not close the Worker; Session close does |
| `G8-STALE-DETACH` | stale attachment cannot close a successor Worker attempt |
| `G8-CANCEL-COMPENSATION` | cancellation closes the exact unpublished/attached owner without leak |
| `G8-START-FAIL-NO-FALLBACK` | failed Worker construction is not cached and no Current retry occurs |
| `G8-CLOSE-DEBT-RETRY` | failed Worker close retains a fenced live slot and pins until retry succeeds |
| `G8-SHUTDOWN-ORDER` | profiles close before Worker/Product Runtime and generation pins |
| `G8-CROSS-ENTRYPOINT` | Product entrypoint receives the exact C5.4/C5.5c receipt identity |
| `G8-LINUX-RETAINED` | the C5.4 Linux Product report remains mandatory |
| `G8-WINDOWS-RETAINED` | the C5.5b native and C5.5c Windows Product reports remain mandatory |

## Architecture Guards

Executable tests must prove:

- the only concrete G8 source consumer is the Coding-owned integration module;
- AppHost core has no Coding, Worker, Hosting, concrete Product, environment,
  platform detection, or dynamic-import dependency;
- the Coding integration uses the public AppHost facade and does not import
  AppHost private modules, Hosting, AppServer, AppService, UI, or entrypoints;
- the frozen profile projection exposes no control/lifecycle object;
- no installed entrypoint or current Coding bootstrap imports the G8 module;
- the unrelated fake Product test reaches no Worker factory;
- native C5.4/C5.5b/C5.5c reports remain separate mandatory evidence; and
- Current owner deletion and G9 remain forbidden.

## G8 Exit Gate

G8 closes only when G8.1--G8.3 are implemented, the complete retained matrix
passes, Linux and Windows Worker evidence remains green, the dependency graph
shows only the intended Coding-to-AppHost edge, and a review finds no unresolved
high or medium issue. Passing G8 permits G9 planning; it grants no production
default and no authority to delete Current.
