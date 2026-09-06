# Hosted Product Runtime V1 Delivery Plan

## Status

- ID: `HOSTED-PRODUCT-RUNTIME-V1`
- Scope: `Loushang` cross-scope delivery
- Parent: none
- Authority: normative target proposal
- Design status: proposed
- Implementation status: partial — implemented through G9.2; G9.3--G9.4 remain
- Production activation: closed
- Owner: Loushang architecture

## Goal

Deliver one Product-neutral path that can select an explicit Product, create an
independently scoped runtime, and—when that Product elects a local Worker—start
it through Hosting with exact native preparation, required containment,
recovery, and rollback evidence on Linux and Windows.

The goal is complete only when two semantically unrelated fake Products prove
AppHost neutrality and one narrow PLC9C5 canary proves the real Product/native
Worker path without fallback. It does not require AppServer, WebUI, a daemon,
remote execution, or live process adoption.

## Source, Target, And Delta

- **Current source:** Hosting H0--H6.5b remains default-dark; PLC9C5
  C5.1--C5.5c provide the receipt/lifecycle aggregate, retained Linux and
  Windows native evidence, and the sole explicit Linux/Windows Coding Product
  canary. G7 is closed. AppHost A0.3 live binding, the optional A0.4 hosted
  binder, and the Coding-owned G8 Product/Worker join are implemented but
  remain uncomposed; AppServer contains contracts only, and AppService remains
  absent.
- **Proposed Target:** H6 supplies opaque native preparation; AppHost supplies
  explicit Product routing and scoped runtime lifetime; Product/Harness
  composition alone activates one reviewed Worker canary.
- **Delta authority:** the source-backed
  [Current inventory](../hosting/validation/hosted-product-runtime-v1-inventory.md)
  lists exact owners and absences. This plan sequences changes but does not
  override accepted scope contracts or source facts.

## Cross-Scope Responsibility Chain

```text
AppHost rail
  AppHost catalog/router
    -> explicit product_id -> Product Factory -> scoped Product Runtime

Worker rail
  Product/Harness domain adapter and authority receipts
    -> Harness Sandbox preparation requirements
       -> Hosting opaque native preparation + atomic Child Session
          -> Harness Worker supervisor -> exact domain generation owner

end-to-end join
  AppHost-scoped Product Runtime -> Product-owned Worker integration -> Worker rail
```

Each arrow is an injected contract. PLC9C5 can prove the Worker rail through an
existing Product composition without waiting for AppHost. AppHost A0 can prove
catalog/routing/lifecycle without Hosting. AppHost never owns Sandbox or Worker
protocol; Harness never owns the cross-Product catalog; Hosting never owns
Product selection, authority, protocol health, or generation publication.

## Workstreams And Dependency Gates

| Gate | Owning scope | Delivery | Depends on | Exit condition |
| --- | --- | --- | --- | --- |
| G0H | common parent / Hosting | H6.0 design, inventory, feasibility questions, and guards | H5 and PLC9C1--C4 Current facts | Hosting plus neighboring-owner design review; zero runtime activation |
| G0A | common parent / AppHost | AppHost A0.0 placement, contracts, inventory, and guards | current Product and Session-discovery facts | AppHost plus sibling-owner design review; zero source-package/runtime activation |
| G1 | Hosting | H6.1 non-committing POSIX/Windows probes plus fake opaque preparation ownership protocol | G0H | both platform families support the core; one-use/request-bound/concurrency/fault/cancellation matrix; no public raw handles |
| G2L | Hosting | H6.2 Linux native backend | G1 | retained native executable/cwd/containment/inheritance/tree oracle |
| G2W | Hosting | H6.3 Windows native backend | G1 | retained native identity/AppContainer-or-token/handle-list/Job oracle |
| G3 | Harness consumer | implemented H6.4 dark managed preparation adapter over fakes and the real private Child Session seam | G1 | Current/public/managed semantic and rollback matrix; default still Current; no native Worker compatibility claim |
| G4 | AppHost | implemented A0.1 Contract Model | accepted A0.0 / ARD-003 | standard-library-only contract/import/validation gates; no runtime composition |
| G5 | AppHost | implemented A0.2 catalog/router, admission pins, optional AppHost-owned Harness Session integration, and explicit Product importer | G4 | two unrelated fake Products; minimal public prepared-route surface; Router-owned cleanup debt; cwd/user-global discovery; 8 MiB immutable snapshot bound; Windows fail-closed gate; no production consumer |
| G6 | AppHost | implemented A0.3 canonical live-binding lifecycle and embedded profile plus A0.4 optional contract-only hosted binder | G5 | multi-Session and multi-profile single-flight attach/detach/cancellation/deadline/shutdown matrix; exact AppServer port identity; no listener, transport, protocol, service runtime, or production consumer |
| G7 | Product/Harness | implemented PLC9C5 C5.0--C5.5c receipt/lifecycle, Linux native/Product, retained Windows restricted-mechanics rejection, and Windows LPAC native/Product containment | G2L + G2W + G3 | closed by the retained Linux reports plus separate zero-skip C5.5 native and Product reports proving Windows required containment, cross-entrypoint, recovery, rollback, and no-fallback behavior |
| G8 | AppHost + Product/Harness | implemented G8.0--G8.3 default-dark Product-neutral end-to-end join | G6 + G7 | exact Worker receipt/recovery/normal-close join, unrelated Worker-free Product, multi-profile/Session, fault and retained cross-platform evidence |
| G9 | common parent | implemented through G9.2; G9.3--G9.4 remain | G8 | explicit Product composition and rollback/crash drill are implemented default-dark; source-backed Current-owner decision and lane-to-main promotion remain |

G0H and G0A are independently accepted gates even when reviewed or delivered
in one documentation change. A failed AppHost placement review cannot block
H6, and an H6 platform question cannot block AppHost core. G2L, G2W, and G3
should proceed in parallel after G1; each native parity claim
still depends on its matching G2 evidence. G4--G6 may proceed in parallel with
G1--G3 because AppHost core has no Hosting dependency. G7 is the first
Hosting/Harness activation join and the only gate in this plan allowed to
revise the PLC9C5 activation absence. G8 now implements the first join between
the AppHost and Worker rails without activating an installed route. The
accepted [G9 closure](../apphost/hosted-product-v1-closure-g9.md) makes
production composition, route activation, omitted-owner policy, Current
deletion, and main promotion independent control points.
G9.1--G9.2 now provide the sole explicit Coding composition facade and its
cross-platform deterministic drill; existing bootstrap/CLI/TUI omission paths
remain Current-only.

The optional A0.4 hosted binder is now accepted with only AppServer-owned
structural Product-port contracts. A0.5 still requires its own serialized-launch
contract. Neither slice activates a production route or changes the G7/G8
critical path.

## Merge And Activation Discipline

1. Land each workstream default-dark with an exact inventory and architecture
   guard update.
2. Require deterministic fake lifecycle tests before native platform or
   Product composition.
3. Retain Linux and Windows evidence separately; neither substitutes for the
   other and a rerun cannot erase a deterministic defect. H6.3's Windows
   restricted mechanics are not Product required-containment evidence.
4. Keep Current and Hosting owners independently runnable through G8 rollback
   drills, but never retry the other owner within one launch attempt.
5. Activate only an explicit Product/contribution allowlist with a versioned
   receipt; no environment variable, platform auto-detection, or missing
   configuration chooses Hosting.
6. Expand only after health, restart, required/optional contribution,
   cancellation, crash, cleanup-debt, and forced rollback cases pass.
7. Record `RETAIN` or `DELETE` for Current in G9.3. Delete only in a dedicated
   change after every exact condition in the accepted G9 closure passes; a
   valid `RETAIN` decision does not block V1 promotion.
8. Treat `lane/harness -> main` as capability availability only. Activation,
   omitted-owner change, and compatibility deletion require independent
   review and rollback authority.

## G7 Canary Acceptance Matrix

The first PLC9C5 canary must cover at least:

| Dimension | Required cases |
| --- | --- |
| Product route | explicit selected Product, missing Product, wrong Product, disabled contribution |
| Session route | canonical and cwd/home compatibility projections, tampered/unknown Product envelope, alias, conflict, and changed locator |
| contribution policy | required success/failure and optional success/degraded failure |
| native platform | Linux required containment and Windows required containment; unsupported hosts fail closed |
| preparation | executable/cwd replacement, stale authority, handle/fd substitution, unsupported profile |
| lifecycle | cancellation at each acquisition, early exit, handshake failure, heartbeat loss, clean stop, forced kill |
| recovery | prior attempt absent, confirmed reaped, uncertain tree, restart-budget exhaustion, host restart |
| publication | no generation before handshake/domain admission; stale attempt cannot publish or retire successor |
| rollback | future attempts return to Current owner; in-flight owner is sticky; no same-attempt fallback |
| entrypoint | every Current canary-capable CLI/TUI/Product composition path shares the exact activation receipt; hosted paths join only after A0.4 is separately accepted |

The accepted
[PLC9C5 C5.0 baseline](../harness/plugin/plugin-lifecycle-plc9c5-c50-baseline.md)
and [Current inventory](../harness/plugin/plugin-lifecycle-plc9c5-c50-inventory.md)
assign every row through C5.5c and freeze the Linux/Windows shape deltas. The
[C5.5 Windows baseline](../harness/plugin/plugin-lifecycle-plc9c5-c55-windows-containment.md)
records the accepted C5.5a containment design and retains separate C5.5b native
and C5.5c Product reports; those zero-skip reports close G7 without activating
a default route. The implemented
[G8 join](../apphost/product-worker-join-g8.md) and its exact
[evidence manifest](../apphost/hosted-product-g8-evidence-manifest.json) govern
the first AppHost/Worker composition.

The first production route fences and terminates a surviving old Worker before
restart. Live adoption remains a later separately reviewed threat model.

## Architecture And Test Guards

Through G9.2, executable architecture tests must continue to prove:

- AppHost core contains only the accepted A0.1--A0.3 contracts, catalog/router,
  and live-binding owner; optional A0.4 hosted wiring remains outside its facade;
- AppHost core has no AppServer, Hosting, concrete Product, or UI imports;
- `apphost.hosted` is the sole AppServer importer and AppServer remains
  contract-only with no reverse AppHost dependency;
- Harness, AppServer, AppService, and Hosting never import AppHost;
- Hosting has no Harness/Product security vocabulary or dependency;
- H5 owner selection defaults to `"current"`, performs no environment lookup,
  and never falls back within an attempt;
- no non-Worker production module composes the H5 adapter; and
- the PLC9C5 production-composition guard is revised only by C5.4 after the
  C5.1 receipt, C5.2 Linux, and C5.3 Windows mechanics/rejection evidence
  exists; C5.4 revises only the Linux canary absence and cannot close G7;
  C5.0 removes no runtime guard; and
- inventory source paths equal the executable expected set; the G9 composition
  is the sole Product-owned edge to AppHost and is absent from Current-only
  entrypoints; the 13-case manifest has separate Linux/Windows identities; and
  any later G9 deletion change includes the exact reverse import/composition and
  entrypoint evidence required by the accepted G9 closure.

## Non-Goals

- implementing an AppServer runtime, AppService package, or hosted protocol;
- daemon/service-instance management, discovery, or surviving-process adoption;
- remote Worker/service topology;
- Product UI implementation, clipboard/image storage, logs, traces, Session
  transcripts, or machine-root ownership;
- publishing raw OS resources or a general process/plugin SDK; and
- moving Product, Sandbox, Worker, or generation authority into Hosting.

## Completion Evidence

V1 closure requires one linked evidence bundle containing:

- accepted H6 and AppHost decisions plus updated parent/sibling catalogs;
- generated dependency and public-surface reports;
- deterministic contract/lifecycle/fault suites;
- retained native Linux and Windows reports with no required skips;
- two-unrelated-fake-Product routing/lifecycle evidence;
- explicit legacy Coding and external Codex/Claude-format migration evidence
  through Product-owned adapters, with source immutability and atomic envelope
  publication;
- catalog retirement pins plus concurrent multi-mux Session attach/detach
  evidence;
- the PLC9C5 canary and cross-entrypoint conformance report;
- rollback and crash-recovery drill results; and
- a final Current-to-Target inventory proving which compatibility owner remains
  and why.

The accepted
[G9 V1 closure](../apphost/hosted-product-v1-closure-g9.md) defines the exact
slice order, evidence case IDs, Current-owner admission conditions, and
lane-to-main promotion controls for these final rows.
