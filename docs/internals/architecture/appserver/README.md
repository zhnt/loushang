# Loushang AppServer Structural Ports

[Architecture](../README.md) ·
[AppHost](../apphost/README.md) ·
[G11 In-Process Hosted Application](hosted-application-g11.md) ·
[AppService Hosted Boundary](../drafts/appservice-embedded-tui-hosted-boundary-plan.md)

## Status

- Scope: `appserver`
- Parent: `loushang`
- Authority: normative for the A0.4 structural wiring boundary only
- Design status: accepted contract slice
- Implementation status: implemented — contract-only structural Product port bundle
- Activation status: none; no protocol, service, listener, connection, or transport
- Owner: Loushang AppServer architecture

The accepted
[G11 In-Process Hosted Application](hosted-application-g11.md) design is the
next delivery boundary.  It permits a strict protocol kernel and client
contract here, plus a separate Product-neutral `loushang.appservice` semantic
package.  Until its implementation lands, the Current package remains the
contract-only A0.4 structural bundle described below.

## Purpose

A0.4 needs a stable sibling-owned type at the AppHost hosted composition edge
without prematurely implementing AppService or a server. The package therefore
owns only `AppServerSessionIdentityV1` and generic
`AppServerProductPortsV1[Session, Work, Projection, Interaction]` values.

The bundle is immutable and lifecycle-free. Generic parameters preserve the
exact structural ports selected by the future AppService slice; AppHost neither
defines nor invokes their semantic methods. The bundle contains no generic
command dictionary, `Any` payload, Product Runtime handle, close authority,
path, credential, listener, or transport object.

## Boundary

```text
future AppService -> loushang.appserver.ports
apphost.hosted -> loushang.appserver.ports + AppHost attachment contracts
Product hosted profile -> Product public API + loushang.appserver.ports

loushang.appserver.ports -/-> AppHost / Harness / Hosting / Product / UI
AppHost core -/-> loushang.appserver
```

Only `apphost.hosted` imports this package in A0.4. No production composition
imports either side. A later AppServer protocol/service slice must separately
accept concrete port method contracts, lifecycle, bounded queues, and transport
semantics; it cannot infer those authorities from this wiring bundle.

## Invariants

1. Session identity is copied as bounded Product, continuity, and Session
   identifiers and is not an admission or authorization claim.
2. Session and projection ports are required; Work and interaction ports are
   explicitly optional.
3. The bundle owns no close method. Its AppHost profile attachment owns the
   adapter lifetime.
4. AppServer never imports AppHost. The optional AppHost binder is the outward
   composition edge.
5. There is no protocol, request dispatch, listener, authentication, framing,
   transport, AppService, daemon, or Hosting behavior in this slice.

## Evidence

- `tests/apphost/test_runtime.py` validates frozen values, exact identity
  mapping, rejection cleanup, and hosted attachment ownership.
- `tests/architecture/test_apphost_a03_a04_architecture.py` enforces the
  one-way optional dependency and contract-only package shape.
- `make check-apphost` includes this package in lint, typecheck, and tests.
