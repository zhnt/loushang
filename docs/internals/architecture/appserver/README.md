# Loushang AppServer Architecture

[Architecture](../README.md) ·
[AppHost](../apphost/README.md) ·
[G11 In-Process Hosted Application](hosted-application-g11.md) ·
[G14 Foreground Stdio](foreground-stdio-hosted-app-g14.md) ·
[G16 Detachable Local Workspace Design](detachable-local-workspace-g16.md) ·
[G12 Foreground Hosted Application](../apphost/foreground-hosted-application-g12.md) ·
[AppService Hosted Boundary](../drafts/appservice-embedded-tui-hosted-boundary-plan.md)

## Status

- Scope: `appserver`
- Parent: `loushang`
- Authority: normative — A0.4 ports, G11 client contract and explicit G14/G16 connection edges
- Design status: accepted
- Implementation status: implemented — G14 and G16 are delivered on Linux/macOS/Windows, including G16 native connections, real Coding composition and isolated-wheel interactive attach; see the delivery record and subsequent G17.0 baseline regression below
- Activation status: explicit library, `loushang-hosted` foreground command or `loushang-mux` local route; no default-route change
- Owner: Loushang AppServer architecture

Accepted amendment: [ARD-020](../decisions/accepted/ARD-020-hosted-goal-budget-and-observation.md)
and the [Coding budget/observation design](../coding/key-designs/hosted-goal-budget-observation.md)
define an optional application-local progress capability using existing Goal
value types. R1 was accepted on 2026-11-02; the local implementation is recorded
with the Coding design. This does not activate a remote wire contract.

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

G16 adds an explicit local connection library with native private records,
mutual authentication and injected scope ownership. Its sole native-IO adapter
can bind literal loopback or read an explicitly selected endpoint; no automatic
startup, discovery, Product construction or process signaling is granted.
The [G16 final delivery record](detachable-local-workspace-g16.md#final-delivery-acceptance)
records native fault and isolated-wheel terminal acceptance on all three platforms
and promotion to main. G17.0 separately tracks the subsequent Hosting test
regression; historical G16 checkpoints are not rewritten as current status.

G12's optional AppHost application edge consumes the client contract for its
in-process view. AppServer neither constructs nor imports that composition.

The [optional execution delivery](../appservice/execution-service-delivery.md)
adds a separate `execution` package for closed values, codecs and client
recovery, plus explicitly selected local execution profiles. The hello binds
the AppService instance and states its retention guarantee. AppService owns
submission registration and cleanup; this transport still owns only request
delivery and borrowed scoped capabilities. Existing v1 frames and default
profiles are unchanged. Native GUI acceptance follows the documented handoff.

## Optional Session Reasoning

Internal acceptance by the implementation agent (Codex), 2026-11-09.
Reviewed the `feature/gui-settings-reasoning` change based on `58a937909`
across HarnessGUI, AppServer, AppService and Coding. Coding projects the
current and available levels from its existing Session control. AppService
retains the attached-member and current-model checks. The GUI requests one
of the returned levels and displays the confirmed value.

The execution hello remains byte-compatible by default. An authenticated
execution client can echo the canonical hello with `sessionThinking: true`
and wait for an identical acknowledgement before attaching. Only that
connection can receive the optional `thinking` model metadata and send
`thinkingLevel` on model selection. An older Host closes the augmented
exchange. HarnessGUI retries the original exchange within the same startup
budget before acquiring attachment authority. The original exchange keeps
the two-field model result and model-only selection behavior.

The reviewed decision keeps level resolution in Coding and uses the
existing model selection authority, with an explicit opt-in to protect
strict legacy decoders. Evidence includes the
[connection](../../../../tests/appserver/test_execution_connection.py),
[protocol](../../../../tests/appserver/test_protocol.py) and
[hosted session](../../../../tests/coding/test_hosted_session.py) regressions
and a Linux native build against an isolated managed AppHost with a
deterministic model transport.

Reviewability budget reconciliation by the implementation agent (Codex),
2026-11-09, against the integrated GUI revision `39efc0910`. The G11 check
accounts for 63 net lines in AppServer protocol values, exports and codecs,
five in AppService's existing model selection authority, and 28 in the Coding
adapter. The counted files and remaining headroom stay the same. The
[G11 architecture test](../../../../tests/architecture/test_hosted_application_g11.py)
continues to check those boundaries.

## Automatic GUI Session Titles

Internal acceptance by the implementation agent (Codex), 2026-11-09.
Reviewed `feature/gui-session-title` based on `6ec51010b` across Coding's
Hosted Session and the existing Model Input boundary. GUI-created sessions
use the `gui-new-` and `gui-default-` continuity prefixes. After a successful
execution settles, an unnamed session can schedule a background title request
using a bounded excerpt of the original first user message. The request uses
the selected model and the existing prepared-request barrier, with an
eight-second budget and no tools.

Both requests write Model Input evidence to the same transcript. The
implementation starts title preparation after the primary execution settles
and lets the primary execution publish its outcome immediately. Follow-up
execution and model selection wait for any in-flight title request so their
transcript writes remain ordered. The Hosted Session cancels and joins the
title task on close. The existing metadata writer persists the title and
signals snapshot readers through a status event without adding a transcript row.

An empty session displays `New Session`. Once the first user message is
recorded, live and restored snapshots display a single-line preview of up to
48 characters until the generated title is stored. If title generation fails,
the preview remains visible and the next successful execution can try again
with the original first message. The
[hosted-session regression](../../../../tests/coding/test_hosted_session.py)
exercises the prepared-request barrier with a deterministic transport and
covers the primary outcome, background title publication and history restoration.

## Accepted Resume Contract

AppServer retains client framing and transport. Product readiness projections preserve old Ack completion timing and negotiate supported continuation behavior.

The project owner accepted the cross-scope #696 boundaries on 2026-10-12:
[ARD-004](../decisions/accepted/ARD-004-resume-history-and-current-authority.md),
[ARD-005](../decisions/accepted/ARD-005-resume-continuation-commit.md), and
[ARD-006](../decisions/accepted/ARD-006-hosted-resume-readiness-and-admission.md).
The [Delta ledger](../current-target-gap-ledger.md) records remaining work;
acceptance does not establish writable release or performance readiness.

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
appserver.connection -> appserver.client + protocol + message ports
appserver.remote_client -> protocol + message ports
appserver.local -> native IO + record/auth + injected scope/stop ports

loushang.appserver -/-> AppService / AppHost / Harness / Hosting / Product / UI
AppHost core -/-> loushang.appserver
```

Only `apphost.hosted` imports `ports.py` from AppHost. G11's exact hosted
Session input port is AppService-owned because it expresses service semantics,
not AppHost wiring. G11 adds the sibling
protocol and client abstractions without changing that binder. AppService owns
concrete semantic coordination and its in-process client implementation. The
G14 connection edge now accepts foreground stdio lifecycle and framing.
G16's optional local edge now composes authentication and connection-scoped
authority. Product constructs the real Coding deployment without reverse imports;
the installed interactive terminal borrows only AppClient. The delivery record
links the accepted platform evidence. The G14 foreground contract is unchanged.

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
  Product, UI and process dependencies; only the exact G16 local adapter may
  construct native connections.
- `tests/architecture/test_foreground_hosted_application_g12.py` retains the
  optional outward consumer and unchanged installed-entrypoint boundary.
- `make check-apphost` retains A0.4/G12 coverage; `make check-appservice` owns
  the G11 semantics and G12 composition evidence.
- G14 connection tests cover bounded dispatch, reserved interrupt capacity,
  caller cancellation, EOF and invalid frames. A native subprocess fixture
  covers byte IO. Native real Product/Harnesstui tests now cover the installed
  command and G13 restart recovery. The [G14 final evidence](foreground-stdio-hosted-app-g14.md#final-acceptance-evidence)
  records 211 passing cases on each native platform and the full-delta
  three-view review; the linked PR records integration status.
- G16 native loopback tests combine the real AppService with synthetic Product
  ports to exercise accepted work, fresh attachments and approval invalidation.
  These do not count as installed Product/TUI or restart-recovery evidence.
- The separate [G16 evidence manifest](detachable-local-workspace-g16-evidence-manifest.json)
  requires exact zero-skip native fault and isolated-wheel terminal reports for
  Linux, macOS and Windows. Platform, installation and terminal backend are
  verified properties, not conclusions inferred from report names. Gate
  implementation is distinct from the observed platform results recorded in
  the [final delivery record](detachable-local-workspace-g16.md#final-delivery-acceptance).
