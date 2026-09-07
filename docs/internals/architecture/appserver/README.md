# Loushang AppServer Architecture

[Architecture](../README.md) ·
[AppHost](../apphost/README.md) ·
[G11 In-Process Hosted Application](hosted-application-g11.md) ·
[G14 Foreground Stdio](foreground-stdio-hosted-app-g14.md) ·
[G12 Foreground Hosted Application](../apphost/foreground-hosted-application-g12.md) ·
[AppService Hosted Boundary](../drafts/appservice-embedded-tui-hosted-boundary-plan.md)

## Status

- Scope: `appserver`
- Parent: `loushang`
- Authority: normative — A0.4 ports, G11 client contract and G14 connection edge
- Design status: accepted
- Implementation status: partial — G14 connection, stdio client and Product executable implemented; native-platform delivery validation pending
- Activation status: explicit library or `loushang-hosted` foreground command; no listener or default-route change
- Owner: Loushang AppServer architecture

The implemented
[G11 In-Process Hosted Application](hosted-application-g11.md) adds a strict
protocol kernel and transport-neutral AppClient contract here, plus a separate
Product-neutral `loushang.appservice` semantic package.  It adds no AppServer
runtime or external entrypoint.

G14 adds a separately imported connection runtime, bounded framing and stdio
AppClient. It accepts an injected semantic client and already-owned IO, never
constructs an AppService, and has no process launch or listener authority.
The Product-owned `loushang-hosted` entrypoint composes this explicit route;
it remains separate from the existing default CLI/TUI entrypoints.

G12's optional AppHost application edge consumes the client contract for its
in-process view. AppServer neither constructs nor imports that composition.

## Purpose

The contract-only structural Product port bundle remains the A0.4 stable
sibling-owned type at the AppHost hosted composition edge. Its `ports.py`
module owns only `AppServerSessionIdentityV1` and generic
`AppServerProductPortsV1[Session, Work, Projection, Interaction]` values.
G11's sibling `protocol` package and `client.py` add client-safe vocabulary,
without making AppServer an application service or server runtime.

The bundle is immutable and lifecycle-free. Generic parameters preserve the
exact structural ports selected by optional outer AppHost composition; AppHost
neither defines nor invokes their semantic methods. The bundle contains no generic
command dictionary, `Any` payload, Product Runtime handle, close authority,
path, credential, listener, or transport object.

## Boundary

```text
AppService -> loushang.appserver.protocol
apphost.application -> loushang.appserver.client
apphost.hosted -> loushang.appserver.ports + AppHost attachment contracts
Product hosted profile -> Product public API + loushang.appserver.ports
Harnesstui Hosted Profile -> loushang.appserver.client + protocol
appserver.connection -> appserver.client + protocol + byte ports
appserver.remote_client -> protocol + byte ports

loushang.appserver -/-> AppService / AppHost / Harness / Hosting / Product / UI
AppHost core -/-> loushang.appserver
```

Only `apphost.hosted` imports `ports.py` from AppHost. G11's exact hosted
Session input port is AppService-owned because it expresses service semantics,
not AppHost wiring. G11 adds the sibling
protocol and client abstractions without changing that binder. AppService owns
concrete semantic coordination and its in-process client implementation. The
G14 connection edge now accepts foreground stdio lifecycle and framing.
Listener authentication and reconnect semantics remain separate future work.

## Invariants

1. Session identity is copied as bounded Product, continuity, and Session
   identifiers and is not an admission or authorization claim.
2. Session and projection ports are required; Work and interaction ports are
   explicitly optional.
3. The bundle owns no close method. Its AppHost profile attachment owns the
   adapter lifetime.
4. AppServer never imports AppHost. The optional AppHost binder is the outward
   composition edge.
5. G11 protocol values and strict codecs contain no request dispatch, listener,
   authentication, framing, transport, AppService, daemon, or Hosting behavior.

## Evidence

- `tests/apphost/test_runtime.py` validates frozen values, exact identity
  mapping, rejection cleanup, and hosted attachment ownership.
- `tests/architecture/test_apphost_a03_a04_architecture.py` enforces the
  one-way optional dependency and contract-only A0.4 port shape.
- `tests/appserver/test_protocol.py` validates strict G11 codecs and values.
- `app-protocol-v1.schema.json` freezes the public version and operation
  vocabulary; the reference codec owns operation-specific closed payloads.
- `tests/architecture/test_hosted_application_g11.py` rejects reverse service,
  Product, UI, process, and transport dependencies.
- `tests/architecture/test_foreground_hosted_application_g12.py` retains the
  optional outward consumer and unchanged installed-entrypoint boundary.
- `make check-apphost` retains A0.4/G12 coverage; `make check-appservice` owns
  the G11 semantics and G12 composition evidence.
- G14 connection tests cover bounded dispatch, reserved interrupt capacity,
  caller cancellation, EOF and invalid frames. A native subprocess fixture
  covers byte IO. Native real Product/Harnesstui tests now cover the installed
  command and G13 restart recovery; complete three-platform results and review
  remain required before G14 delivery is complete.
