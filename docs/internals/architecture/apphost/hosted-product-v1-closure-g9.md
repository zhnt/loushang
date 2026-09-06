# Hosted Product Runtime G9 V1 Closure

## Status

- ID: `HOSTED-PRODUCT-G9`
- Scope: common-parent closure across AppHost, Product composition, Harness, and
  Hosting
- Parent: `HOSTED-PRODUCT-RUNTIME-V1`
- Authority: normative accepted design
- Design status: accepted
- Implementation status: partial — G9.0--G9.3 implemented; G9.4 remains
- Activation status: default-dark; omitted Worker owner remains Current
- Owner: Loushang architecture with AppHost, Product, Harness, and Hosting
  boundary review

## Goal

G9 closes Hosted Product Runtime V1 as an operable, promotable capability. It
freezes one installed but explicit Product composition boundary, a repeatable
rollback and crash-recovery drill, the admission conditions for any Current
Worker owner deletion, and the evidence required to promote `lane/harness` to
`main`.

G9 deliberately separates four decisions:

1. making a production composition available;
2. selecting that composition for an explicit invocation;
3. changing an omitted invocation's owner; and
4. deleting the compatibility owner.

None implies another. In particular, code availability on `main` is not
activation, activation is not a default change, and a default change is not
authority to delete Current.

G9 does not implement AppServer, AppService, a daemon, named mux, remote
transport, serialized launcher, live process adoption, or a second Product.

## Current, Target, And Delta

| Plane | State |
| --- | --- |
| Facts | AppHost A0.1--A0.4, G8, and G9.0--G9.3 are implemented. `src/loushang/coding/apphost_product.py` remains the sole concrete Product/Worker join; `src/loushang/coding/apphost_composition.py` is its sole explicit installed AppHost composition owner; the accepted G9.3 decision retains Current. |
| Current | Existing Coding CLI/TUI composition remains authoritative. `WorkerHostingActivationV1()` and omitted activation select `owner="current"`; a selected launch never falls back to the other owner within the attempt. |
| Target | Reconcile the architecture and promote the default-dark capability. The accepted G9.3 `RETAIN` decision remains authoritative unless a separate successor deletion decision proves every admission condition. |
| G9.1--G9.2 delta | Add the one Product-owned explicit composition facade, source-backed entrypoint inventory, retryable rollback settlement, exact offline drill, and separate Linux/Windows evidence identities. Existing bootstrap/CLI/TUI omission paths, owner selection, native profiles, and Current remain unchanged. |
| G9.3 delta | Expand the source-backed inventory across every installed/supported CLI, TUI, SDK, AppServer, hosted, and mux disposition; record `RETAIN`; retain every unmet deletion condition as an explicit gap. |

## Closure Requirements

| Requirement | Required outcome |
| --- | --- |
| `G9-R1-EXPLICIT-COMPOSITION` | One concrete Product owns the only installed module allowed to compose AppHost and its Product/Worker adapter. |
| `G9-R2-NO-IMPLICIT-ACTIVATION` | Missing configuration, environment, platform detection, backend availability, Session contents, or import side effects never selects Hosting. |
| `G9-R3-OPERABLE-ROLLBACK` | The rollback selection change affects future attempts only; the same operation drains exact in-flight owners without retargeting them, never retries Current in the same attempt, and retains cleanup debt until settlement. |
| `G9-R4-EVIDENCE-BASED-DELETION` | Current may be deleted only by a separate decision and change after exact source, entrypoint, rollback, persistence, and cross-platform evidence all pass. |
| `G9-R5-INDEPENDENT-PROMOTION` | `lane/harness -> main`, route activation, omitted-owner change, and Current deletion are independently reviewable and reversible changes. |
| `G9-R6-TRACEABLE-CLOSURE` | Every closure claim names its source inventory, deterministic case ID, retained report, and owning scope; a green unit suite alone cannot close an operational row. |

## Ownership And Non-Ownership

| Concern | Primary owner | Collaborators | Explicit non-owners |
| --- | --- | --- | --- |
| installed Product composition and explicit selection | concrete Product package | installed entrypoints, AppHost public facade | AppHost core, Harness, Hosting, UI framework |
| Product/runtime binding and phased shutdown | AppHost | injected Product/profile/Session ports | Product entrypoint, AppServer, Hosting |
| Worker policy, activation receipt, rollback latch, publication, recovery | Product/Harness composition | Harness Worker components | AppHost, Hosting, profile/mux attachment |
| process, endpoint, containment, native cleanup | Hosting | Harness preparation adapter | Product, AppHost, AppServer |
| Current-retention decision and lane promotion | common-parent architecture owner | all affected scope owners | an individual package or CI job acting alone |

The common parent owns this closure because it changes a sibling dependency and
release policy. AppHost remains a black box to Product composition, and each
child retains its existing internal authority.

## Frozen Production Composition Boundary

G9.1 adds exactly one Product-owned composition module at
`src/loushang/coding/apphost_composition.py`. It is the only production module
allowed to know both the AppHost public facade and the concrete Coding G8
adapter. AppHost, Harness, Hosting, AppServer, AppService, and shared UI code
must not import it.

The module owns one process-scoped composition object, not a global singleton.
Its construction receives explicit typed inputs from trusted Product
composition and performs, in dependency order:

1. bind exact Session, Product, profile, admission-generation, and Worker
   attempt ports;
2. construct and retain `CodingAppHostProductFactoryV1`;
3. build the Coding Product and selected profile registrations;
4. admit one immutable `AppHostCatalogV1` generation; and
5. retain one `AppHostRuntimeV1` privately and return only the Product-owned
   admission, attachment, rollback, and cleanup facade.

The registration helper remains data assembly, not the composition root. A
future CLI, TUI, hosted adapter, or named-mux profile may borrow an attachment
lease from the returned facade, but cannot access the raw AppHost runtime or
construct another Worker owner for the same canonical Session binding. Existing
Coding bootstrap/CLI/TUI entrypoints remain Current-only.

The composition privately retains one Product Rollback Control responsibility
cluster. It serializes an outer admission barrier, the durable Product kill
switch/selection authority, the AppHost runtime shutdown owner, and bounded
evidence readers. It does not expose a rollback capability through AppHost,
profile bindings, AppServer ports, or UI state. After the global latch, normal
AppHost Session/runtime close drains each already selected exact attempt; the
control does not replay per-attempt activation or invent a second Worker
registry.

### Selection contract

- Only an explicit versioned Product configuration or command choice may enter
  the G9 composition.
- Absence continues on the existing Current path and does not import or probe
  the composition module.
- Environment variables, operating-system detection, installed extras,
  discoverable plugins, backend availability, cwd, home, or Session data are
  not activation authority.
- An explicit Hosting selection without the exact Product, Session, profile,
  admission, and Worker receipt facts fails closed before effect.
- A failed Hosting attempt never falls back to Current in that attempt. A new
  invocation may use Current only through a new explicit/default selection.

### Shutdown contract

The outer composition first fences its entrypoints and refuses new Product
operations. `AppHostRuntimeV1.shutdown` then remains authoritative for its
existing monotonic phases: drain admission operations, close profile/live
bindings and Product runtimes, close Router state, then retire Catalog
generations and pins. The outer owner retains the Coding Product factory until
AppHost shutdown can no longer create Product cleanup debt, settles that debt,
and reports completion only when both reports are complete.

A timed-out or failed phase remains fenced and retryable. Process exit,
profile detach, AppHost close, Product cleanup, catalog retirement, and durable
Session persistence are distinct evidence; none may synthesize another.
Normal close does not latch rollback by itself. If an explicit emergency
rollback races with or follows normal close on the same composition, rollback
dominates: it latches future attempts and then joins/retries the already-owned
AppHost and Product cleanup rather than rejecting the operator request.

## Rollback And Crash-Recovery Drill

G9.2 adds an executable, offline composition-level drill. Unit tests remain
necessary but do not substitute for the drill. The drill runs from installed
entrypoint composition through the real AppHost/G8/Harness ownership chain,
uses controlled process doubles where live native execution is unsafe, and
retains Linux and Windows reports separately. Existing C5.4 and C5.5b/c native
reports remain mandatory and are linked rather than copied.

### Rollback sequence

```text
operator/Product rollback request
  -> acquire outer rollback barrier; fence new AppHost/Product admissions
  -> first Worker-side mutation: latch future attempts to Current
  -> snapshot exact Hosting attempt/generation owners
  -> drain or explicitly close existing profile attachments
  -> close exact AppHost Session/Product Runtime owners
  -> settle Worker, native process, catalog pin, and Product-factory debt
  -> publish one bounded rollback report

later invocation
  -> new selection generation
  -> Current owner while latch remains active
```

The outer barrier removes the race between new AppHost construction and the
durable latch; within the Worker lifecycle, latching remains the first
mutation. The in-flight owner selected before the latch is sticky. It either completes
under Hosting and is then drained, or fails under Hosting and is settled. It is
never replayed against Current. Re-enabling Hosting requires a new explicit
selection generation and a fresh exact activation receipt; clearing a boolean
in the existing attempt is insufficient.

### Required drill cases

| Case | Required proof |
| --- | --- |
| `G9-COMPOSE-EXPLICIT` | only explicit typed selection constructs the sole Product composition root |
| `G9-OMISSION-CURRENT` | omission reaches Current without importing, probing, or partially constructing Hosting/AppHost composition |
| `G9-ROLLBACK-BEFORE-EFFECT` | a pre-effect rollback creates no Worker, runtime, publication, or cleanup debt |
| `G9-ROLLBACK-INFLIGHT-STICKY` | a concurrently selected Hosting attempt is never retargeted and is drained by exact identity |
| `G9-ROLLBACK-NO-FALLBACK` | every Hosting start/recovery failure remains on Hosting for that attempt |
| `G9-ROLLBACK-DRAIN-ORDER` | admission fence precedes attachment/runtime close, which precedes generation retirement and final Product debt settlement |
| `G9-CRASH-RECOVERY` | restart fences/reaps or refuses uncertain prior ownership before a fresh attempt and never adopts a surviving process |
| `G9-CLEANUP-DEBT-RETRY` | failed close retains the exact fenced owner and a later settlement resumes at that debt |
| `G9-MULTIPROFILE-SINGLE-FLIGHT` | embedded, hosted, or mux attachments share one Product Runtime/Worker attempt and detach independently |
| `G9-MULTISESSION-ISOLATION` | one Session rollback/close cannot retire another Session's owner or generation |
| `G9-RESTART-GENERATION` | process restart and Hosting re-enable require new generation/receipt identity; stale owners cannot publish or retire successors |
| `G9-ENTRYPOINT-INVENTORY` | every supported explicit Product entrypoint either maps to the one composition or is recorded as Current-only |
| `G9-DEPENDENCY-GRAPH` | generated and AST-backed scans contain only the accepted Product-to-AppHost composition edge |

`hosted-product-g9-evidence-manifest.json` pins the exact case set and two
zero-skip JUnit report identities. The Linux report is produced by
`test-hosted-product-g9-linux-evidence`; the AppHost Windows job independently
produces the Windows identity from the same deterministic suite. The reports
are build artifacts rather than committed generated output.

### Implemented evidence

- [entrypoint inventory](hosted-product-g9-entrypoint-inventory.json) records
  the one explicit Hosting composition and the retained Current-only roots;
- [G9 evidence manifest](hosted-product-g9-evidence-manifest.json) fixes both
  platform report identities and all 13 case IDs;
- [G8 evidence manifest](hosted-product-g8-evidence-manifest.json) remains the
  exact Product/Worker join proof; and
- [PLC9C5 evidence manifest](../harness/plugin/plugin-lifecycle-plc9c5-evidence-manifest.json)
  remains the native lifecycle and containment proof rather than being copied
  into G9.

## Current Owner Retention Or Deletion Gate

G9.3 produces the separate accepted
[Current Worker Owner Decision](current-worker-owner-decision-g9.md). The
record has exactly one conclusion: `RETAIN` or `DELETE`; the accepted record
chooses `RETAIN`. `RETAIN` is a successful G9 decision and does not block V1
promotion. Silence, a passing G9 suite, or a successful Hosting canary is never
interpreted as `DELETE`.

`DELETE` is admissible only when all conditions are true:

1. an AST/import/composition inventory proves zero production Current-owner
   consumers outside the deletion change's explicit test/history allowlist;
2. every installed and supported CLI, TUI, SDK, AppServer, hosted, and mux
   entrypoint has an explicit source-backed disposition and no omission
   semantics depend on Current;
3. Linux C5.4, Windows C5.5b/c, G8, and G9 reports are retained, zero-skip, and
   match the exact promoted commit;
4. the G9 rollback/crash matrix passes repeatedly without an orphan, stale
   publication, leaked pin, or unresolved cleanup owner;
5. a separately accepted replacement rollback strategy exists, because
   `rollback_to_current` cannot survive deletion of Current;
6. persisted Session/envelope compatibility, downgrade/export behavior, and
   rollback across the promoted version are explicitly decided and tested;
7. the deletion is a dedicated PR that removes the Current implementation,
   selection branch, default, exports, and dead dependencies together; and
8. parent and affected scope documents, generated dependency facts, public
   surface facts, and reverse-dependency guards are reconciled in that PR.

If any condition is false or unknown, the required result is `RETAIN` with the
remaining condition recorded in the gap ledger. The G9.3 audit records all
eight as unmet at its decision head, including live Current consumers, the
absence of a replacement rollback strategy, and uncomposed persisted Session
identity compatibility. The existing default therefore remains Current.

## Main Promotion Plan

Promotion uses four independently reviewable control points:

| Control point | Required state | Explicitly does not grant |
| --- | --- | --- |
| G9 baseline on `lane/harness` | G9.0 accepted, architecture guards green | production composition, activation, deletion |
| closure implementation on `lane/harness` | G9.1 composition and G9.2 evidence complete; G9.3 decision accepted | omitted-owner change or Current deletion |
| `lane/harness -> main` PR | clean source/dependency inventories; AppHost, Harness, Hosting, architecture, Linux, and Windows required gates green on the exact head | route activation merely because code is on `main` |
| later activation/deletion PRs | explicit typed rollout or all deletion conditions, with independent rollback plan | unrelated AppServer/AppService/mux authority |

The promotion PR carries no opportunistic feature work. It must identify the
exact lane head, link the retained G8/G9 and C5 reports, show a clean dependency
graph, state the G9.3 `RETAIN`/`DELETE` decision, and preserve default-dark
semantics. Local `main` is refreshed only after the remote merge is complete
and the control worktree is clean or its unrelated user changes are preserved.

The exact affected-scope gate set is:

| Gate | Required proof |
| --- | --- |
| `make check-apphost` | AppHost/G8/G9 contracts, type safety, and retained Product join evidence |
| `make check-harness` | Worker ownership, activation, recovery, publication, and compatibility contracts |
| `make check-hosting` | Product-neutral process/native preparation boundaries and deterministic platform mechanics |
| `make check-architecture-docs` | links, status, parent adoption, generated package facts, and gap reconciliation |
| `make test-plc9c5-c54-linux-product` | retained zero-skip Linux Product/native path |
| AppHost Linux and Windows workflow jobs | exact G9 composition/drill reports on both platform families |
| Hosting Windows C5.5b/c workflow jobs | retained zero-skip LPAC native and Product containment reports |

All gates run against the same immutable PR head. A platform report from a
different commit, a skipped required case, or a rerun that merely hides a
deterministic failure is not promotion evidence. No live or network test is
implied by this list.

## Delivery Slices

| Slice | Delivery | Exit condition |
| --- | --- | --- |
| G9.0 | this accepted closure contract, inventory/parent updates, threat model, and executable architecture guards | no production source or activation change; omission is still Current; no unresolved high/medium design finding |
| G9.1 | implemented sole Product-owned installed composition root and explicit opt-in entrypoint mapping | exact dependency allowlist, one process owner, uncomposed omission path, cross-entrypoint deterministic tests |
| G9.2 | implemented offline rollback/crash-recovery drill, evidence manifest, Linux/Windows report identities, and retained C5/G8 links | every exact case passes without required skip; cleanup and stale-owner inventories are empty |
| G9.3 | implemented source-backed entrypoint inventory and accepted Current-owner `RETAIN` record | every condition has evidence or is an explicit retained gap; deletion remains a dedicated successor decision and change |
| G9.4 | architecture reconciliation and `lane/harness -> main` promotion | exact-head remote gates pass; main contains capability without implicit activation |

## Traceability

| Requirement | Owning slice | Source/evidence anchor |
| --- | --- | --- |
| `G9-R1-EXPLICIT-COMPOSITION` | G9.1 | target composition module plus `G9-COMPOSE-EXPLICIT`, entrypoint inventory, and dependency graph cases |
| `G9-R2-NO-IMPLICIT-ACTIVATION` | G9.1--G9.2 | H5 owner selection plus omission and no-fallback cases |
| `G9-R3-OPERABLE-ROLLBACK` | G9.2 | AppHost phased shutdown, Product activation aggregate, rollback/crash/debt cases, and platform reports |
| `G9-R4-EVIDENCE-BASED-DELETION` | G9.3 | source inventory, entrypoint disposition, retained reports, and the accepted Current-owner decision |
| `G9-R5-INDEPENDENT-PROMOTION` | G9.4 | exact-head PR gate set, default-dark diff, and separate activation/deletion records |
| `G9-R6-TRACEABLE-CLOSURE` | G9.0--G9.4 | architecture guard, G9 manifest, linked C5/G8 reports, generated facts, and reconciled gap ledger |

## Threat Model

| Threat | Required control |
| --- | --- |
| import, environment, or platform availability silently activates Hosting | explicit typed selection; omission/import-safety tests |
| Current and Hosting both own one Session attempt | one immutable receipt and sticky per-attempt selection; no same-attempt fallback |
| rollback closes a successor or reopens a stale Worker | exact attempt/generation fencing and stale-publication tests |
| multi-mux/profile composition creates duplicate Workers | AppHost canonical binding single-flight and non-owning attachment leases |
| AppHost shutdown loses Product or native cleanup debt | monotonic phased close plus retained outer factory and owner-specific reports |
| only one entrypoint migrates and creates split operational semantics | source-generated entrypoint disposition inventory and conformance cases |
| a green unit test is treated as native or operational proof | separate zero-skip retained Linux, Windows, and composition reports |
| merging to `main` is mistaken for activation or deletion approval | separate PR/control points and default-dark architecture guards |

Live adoption of a surviving process remains forbidden. A crash may recover by
confirming the prior tree reaped or by fencing/terminating it; uncertain
ownership fails closed.

## G9.3 Architecture Guards

Executable tests must prove that:

- this accepted design and its G9.3 status are indexed by the AppHost scope and
  common-parent delivery plan;
- the exact target production composition module exists with only the accepted
  AppHost-public and Coding Product adapter dependencies;
- existing installed Coding bootstrap/CLI/TUI paths do not import the target
  composition module;
- `WorkerHostingActivationV1` still defaults to `"current"`, has no environment
  lookup, and `WorkerSessionOwnerRouter.start` contains no alternate-owner
  retry;
- AppHost core retains no Coding, Harness Worker, Hosting, environment,
  platform-detection, or dynamic-import dependency;
- the source-backed entrypoint inventory is checked against every installed
  console script and explicitly disposes the Coding SDK, AppServer package,
  hosted binder, supported module CLI, and named-mux proposal;
- the G9 evidence manifest fixes exactly 13 cases and separate Linux/Windows
  report identities; and
- the accepted decision contains exactly one `RETAIN` conclusion, evaluates all
  eight deletion conditions, and preserves the default-Current and no-fallback
  fences.

G9.4 replaces only its own promotion guards after exact-head evidence exists.
G9.3 does not relax AppHost core, Harness-to-AppHost,
Hosting-to-Product, default-Current, or same-attempt fallback fences.

## G9.3 Exit Gate

G9.3 is complete when the expanded entrypoint inventory, accepted `RETAIN`
record, eight-condition audit, parent status updates, and architecture guards
pass; and a three-view review has no unresolved high or medium finding.

Passing G9.3 permits the separate G9.4 promotion. It grants no production
activation, omitted-owner change, Current deletion, live/native test waiver,
or implicit main promotion.
