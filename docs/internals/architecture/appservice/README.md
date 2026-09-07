# Loushang AppService Architecture

[Architecture](../README.md) · [AppServer](../appserver/README.md) ·
[G11 In-Process Hosted Application](../appserver/hosted-application-g11.md)

## Status

- Scope: `appservice`
- Parent: `loushang`
- Authority: normative — G11 in-process application semantics
- Design status: accepted
- Implementation status: implemented — G11.2 Product-neutral core
- Activation status: explicit in-process construction only
- Owner: Loushang AppService architecture

## Purpose

AppService is the transport-neutral hosted application boundary over injected
Product Session ports.  It owns named MuxSpace membership, per-aggregate
revision coordination, hosted Session ownership, attach initialization, and
bounded logical delivery.  It does not own an AppServer listener, byte/frame
buffers, authentication, AppHost composition, Hosting process mechanics,
Product policy, or UI state.

The G11 implementation contains:

- `ports.py`: the independently owned hosted Session and resolver protocols;
- `runtime.py`: MuxSpace, member, Session and attachment lifecycle;
- `client.py`: the in-process implementation of AppServer's transport-neutral
  AppClient contract; and
- `__init__.py`: the deliberately small public facade.

## Dependency And Ownership

```text
AppService -> AppServer protocol
Product outer adapter -> AppService ports + Product/Harness/AppHost public contracts
Harnesstui Hosted Profile -> AppClient + AppServer protocol

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

## Non-Goals

G11 has no connection, listener, wire dispatcher, authentication, IPC,
WebSocket, daemon, process controller, persistent MuxSpace store, multi-client
controller takeover, or AppHost restart recovery.  The default Embedded
Profile and installed Coding CLI/TUI/SDK routes remain unchanged.

## Evidence

- `tests/appservice/test_runtime.py` covers identity, attach barriers, mailbox
  bounds, aggregate concurrency, stale-generation fencing and close order.
- `tests/coding/test_appservice_adapter.py` covers the Coding Product edge and
  cwd/user-home create/resume facts.
- `tests/harnesstui/test_hosted_mux_profile.py` covers explicit presentation,
  local state, reducer ordering and snapshot recovery.
- `tests/architecture/test_hosted_application_g11.py` enforces inventory and
  dependency direction.
- `make check-appservice` runs the focused lint, typecheck and behavioral suite.
