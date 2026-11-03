# Loushang AppService Architecture

[Architecture](../README.md) · [AppServer](../appserver/README.md) ·
[G11 In-Process Hosted Application](../appserver/hosted-application-g11.md) ·
[G12 Foreground Hosted Application](../apphost/foreground-hosted-application-g12.md) ·
[G13 Durable Hosted Continuity](../apphost/durable-hosted-application-continuity-g13.md)

## Status

- Scope: `appservice`
- Parent: `loushang`
- Authority: normative — G11 application semantics, G13 continuity and optional G16 client scopes
- Design status: accepted
- Implementation status: implemented — G11.2 Product-neutral core and the
  AppService-owned G13.1--G13.2 continuity and G16 client-scope slices are complete
- Activation status: explicit construction; the installed Product `loushang-mux`
  route opts into G16 client scopes, without changing default or G14 behavior
- Owner: Loushang AppService architecture

Accepted amendment: [ARD-020](../decisions/accepted/ARD-020-hosted-goal-budget-and-observation.md)
and the [Coding budget/observation design](../coding/key-designs/hosted-goal-budget-observation.md)
add an optional scoped progress view while retaining full query/wait semantics.
R1 was accepted on 2026-11-02; original scope, owner and revocation checks remain
authoritative. Local implementation evidence is linked from the Coding design.

## Accepted Resume Contract

AppService retains attachment, controller, and execution ownership and consumes a narrow Product readiness and durable-input lookup port. It does not own a second preparation queue.

The project owner accepted the cross-scope #696 boundaries on 2026-10-12:
[ARD-004](../decisions/accepted/ARD-004-resume-history-and-current-authority.md),
[ARD-005](../decisions/accepted/ARD-005-resume-continuation-commit.md), and
[ARD-006](../decisions/accepted/ARD-006-hosted-resume-readiness-and-admission.md).
The [Delta ledger](../current-target-gap-ledger.md) records remaining work;
acceptance does not establish writable release or performance readiness.

The original scoped client can observe a Resume subject with
`resume_subject_digest` and revalidate it synchronously with
`require_current_resume_subject`. These entries check the owning client scope,
live attachment/controller generation, canonical member and Session, and the
original Session's accepting state. The bounded fingerprint includes the native
execution application's service instance and exact target scope. An absent
execution instance is unavailable. Observation does not select an execution
port, bind an execution, invoke Product code or reserve accepted work.

This dependency observation is not a Product permission, Approval fact or
effect-settlement receipt. A Product borrower must supply its exact target
Session and recheck the same native owner at mutation boundaries. Coding can
bind this owner selection into its original exact Approval request; controller
takeover or dropping the selected owner cannot reuse that fact. Default Hosted
Resume activation and the remaining admission/effect producers still require
integration under ARD-006.

The selected scoped execution submit and registry-backed legacy turn routes
carry the original scope, control request and observed fingerprint into the
task created by the existing execution registry. Stable submit also carries
its original submission ID; legacy Ack has no stable ID. The caller resets
this task-local borrow after admission or settlement. Product access rechecks
the original live owner, so takeover invalidates Resume borrowing while the
registry continues to own and settle previously accepted ordinary work.
The optional functions bind to the same scope instance; they keep no separate
controller table, execution ledger or permission state. Coding consumes the
borrow at its existing optional Hosted execution bridge.

`SessionSnapshotV1.submission_mode` selects the client delivery contract for
that exact binding. Ordinary Sessions default to `legacy` and serialize with
the original snapshot fields. Resume bindings under the explicit execution
profile serialize the optional `submissionMode: execution` field, allowing
reattached clients to use the stable submission ledger without probing the
wait-until-complete legacy operation.

## Purpose

AppService is the transport-neutral hosted application boundary over injected
Product Session ports.  It owns named MuxSpace membership, per-aggregate
revision coordination, hosted Session ownership, attach initialization, and
bounded logical delivery.  It does not own an AppServer listener, byte/frame
buffers, authentication, AppHost composition, Hosting process mechanics,
Product policy, or UI state.

The [implemented G16 profile](../appserver/detachable-local-workspace-g16.md)
adds an optional semantic client scope: connection-bound controller
authority, application-owned admitted execution and control-loss interaction
settlement. `client_scope.ScopedAppServiceV1` explicitly installs this policy on
one service and creates bounded `AppClientScopeV1` capabilities. Its private
operation owner retains admitted work independently of delivery cancellation;
its private interaction policy denies questions on control loss. AppHost's
optional local deployment now binds its public ready-scope factory into the
local transport. A synchronous scope fence stops new client actions before
asynchronous stop settlement, without itself cancelling accepted work. The
edge is absent from the default facade; ordinary G11/G14 behavior is unchanged.
The separate installed Coding `loushang-mux` command explicitly composes this
policy with real Product Sessions; it does not add transport or Product
dependencies here. The
[G16 final delivery record](../appserver/detachable-local-workspace-g16.md#final-delivery-acceptance)
records native/isolated-wheel acceptance and main promotion, separately from
the post-merge Hosting regression tracked by G17.0.
The application must install it before exposing clients or starting execution,
and must never expose a legacy unscoped client to the same untrusted peers.

The current implementation contains:

- `ports.py`: the independently owned hosted Session and resolver protocols;
- `runtime.py`: MuxSpace, member, Session and attachment lifecycle;
- `client.py`: the in-process implementation of AppServer's transport-neutral
  AppClient contract;
- `continuity.py`: the G13 strict desired-state record and lease/store ports;
- `continuity_file.py`: the exact-root private atomic JSON adapter with one
  OS-released lock per application key;
- `continuity_runtime.py`: the published recovery-attempt owner and
  all-or-nothing Session/MuxSpace reconstruction; and
- `__init__.py`: the deliberately small public facade.

The separate [optional Product execution contract](execution-contract.md) adds
invocation identity, full-call settlement and composite snapshot validation.
Its helpers and explicitly constructed real Coding adapter are implemented.
The [execution service delivery](execution-service-delivery.md) adds the
instance-local submission ledger, independent settlement ownership, scoped
recovery and an optional versioned local protocol. Mechanism, real Product and
transport tests verify these separately. Default Product activation and native
GUI platform acceptance remain separate integration work.

## Dependency And Ownership

```text
AppService -> AppServer protocol
Product outer adapter -> AppService ports + Product/Harness/AppHost public contracts
Harnesstui Hosted Profile -> AppClient + AppServer protocol
apphost.application -> AppService
apphost.continuity -> apphost.application + AppService

AppService -/-> AppHost / Hosting / Harness / Product / Harnesstui / TUI
AppServer -/-> AppService / AppHost / Hosting / Harness / Product / UI
```

AppService calls a Product only through `HostedSessionResolverV1` and the
owned `HostedSessionPortV1` returned by it.  Product callbacks run outside
service and aggregate locks.  A Session belongs to at most one MuxSpace in
G11, while each MuxSpace serializes its own membership independently.
The exact hosted Session input port belongs here because it describes
AppService's semantic requirement. A0.4's generic `appserver.ports` bundle
remains an AppHost composition structure and is not a runtime Session API.

## Lifecycle

An attachment is reserved before Session snapshots are captured.  AppService
then verifies the same membership revision and activates delivery strictly
after each snapshot cursor.  A concurrent membership change or cursor gap
requires a new snapshot.  Each attachment has a bounded nonblocking logical
mailbox; overflow isolates that attachment and still permits explicit detach.

Detaching does not close a MuxSpace or Session.  Member removal and Session
close remain separate flags.  Mux close removes admission, settles its
attachments, then closes owned Sessions.  Service close is idempotent and
settles every remaining Session, including explicitly unplaced Sessions.

G12 does not move lifecycle authority into AppService. The optional outer
`apphost.application` owner fences and closes this service before AppHost, while
AppService continues to know only its injected Product-neutral resolver.

G13.1--G13.2 implement the accepted strict record/store, optional durable
AppService mutations and all-or-nothing recovery. The AppService never
discovers a path or acquires/releases its lease. The implemented optional
`apphost.continuity` owner holds that lease through G12 settlement;
Product/Harness remains authoritative for canonical Session recovery.

## Non-Goals

Current G11--G13 has no connection, listener, wire dispatcher, authentication,
IPC, WebSocket, daemon, process controller or multi-client controller takeover.
G13 covers only explicit durable coordination reconstruction; the default
Embedded Profile and installed Coding CLI/TUI/SDK routes remain unchanged.

## Evidence

- `tests/appservice/test_runtime.py` covers identity, attach barriers, mailbox
  bounds, aggregate concurrency, stale-generation fencing and close order.
- `tests/appservice/test_continuity.py` and
  `tests/appservice/test_continuity_runtime.py` cover the strict store,
  one-writer lease, atomic mutation/recovery and retryable cleanup debt.
- `tests/coding/test_appservice_adapter.py` covers the Coding Product edge and
  cwd/user-home create/resume facts.
- `tests/harnesstui/test_hosted_mux_profile.py` covers explicit presentation,
  local state, reducer ordering and snapshot recovery.
- `tests/architecture/test_hosted_application_g11.py` enforces inventory and
  dependency direction.
- `tests/architecture/test_foreground_hosted_application_g12.py` proves G12 is
  an outward optional consumer and does not create a reverse dependency.
- `tests/apphost/test_continuity.py`,
  `tests/coding/test_hosted_application.py`, and the G13 architecture tests
  prove lease-last settlement, current-generation cwd/user-home recovery,
  fresh Harnesstui authority and default-dark inventory v6.
- `make check-appservice` runs the focused lint, typecheck and behavioral suite.
