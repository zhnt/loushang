# Loushang AppService Architecture

[Architecture](../README.md) · [AppServer](../appserver/README.md) ·
[G11 In-Process Hosted Application](../appserver/hosted-application-g11.md) ·
[G12 Foreground Hosted Application](../apphost/foreground-hosted-application-g12.md) ·
[G13 Durable Hosted Continuity](../apphost/durable-hosted-application-continuity-g13.md)

## Status

- Scope: `appservice`
- Parent: `loushang`
- Authority: normative — G11 in-process application semantics
- Design status: accepted
- Implementation status: implemented — G11.2 Product-neutral core and the
  AppService-owned G13.1--G13.2 continuity slices are complete
- Activation status: explicit in-process construction only
- Owner: Loushang AppService architecture

## Purpose

AppService is the transport-neutral hosted application boundary over injected
Product Session ports.  It owns named MuxSpace membership, per-aggregate
revision coordination, hosted Session ownership, attach initialization, and
bounded logical delivery.  It does not own an AppServer listener, byte/frame
buffers, authentication, AppHost composition, Hosting process mechanics,
Product policy, or UI state.

The [accepted G16 design](../appserver/detachable-local-workspace-g16.md)
adds a future optional semantic client scope: connection-bound controller
authority, application-owned admitted execution and control-loss interaction
settlement. These remain implementation gaps; the G11/G14 in-process adapter
and attachment behavior are not silently changed by the design.

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
