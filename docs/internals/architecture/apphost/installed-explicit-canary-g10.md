# Hosted Product Runtime G10 Installed Explicit Canary

[AppHost Architecture](README.md) ·
[G9 V1 Closure](hosted-product-v1-closure-g9.md) ·
[G9.3 Current Owner Decision](current-worker-owner-decision-g9.md) ·
[G9 Promotion Record](hosted-product-g9-promotion-record.md)

## Status

- ID: `HOSTED-PRODUCT-G10-EXPLICIT-CANARY`
- Scope: `coding / apphost / hosting / harness`
- Parent: `loushang`
- Authority: normative accepted design
- Design status: accepted
- Implementation status: not-started — G10.0 design baseline only
- Activation status: default-dark; no installed entrypoint selects Hosting yet
- Owner: Loushang Coding Product architecture with AppHost common-parent governance

## Purpose

G10 adds the first installed, explicitly invoked path through the G9 Coding
composition. It is a bounded operational canary, not a replacement Coding
session runtime. A user must name the `apphost canary run` operation; only that
operation may compose AppHost and launch one short-lived Hosting child. Normal
CLI, TUI, SDK, resume, AppServer, hosted, and mux paths remain Current.

The slice answers one narrow question that G9 intentionally left open: can the
installed Coding distribution exercise its Product-owned composition, AppHost
catalog/runtime, Product/Worker attempt seam, and native Hosting process owner
as one observable, cleanly reversible operation on Linux and Windows?

G10 does not claim that a normal Coding turn runs in a Worker. It does not
satisfy the G9.3 Current-deletion gate, introduce a long-lived Platform Host,
or pre-approve a later default-owner decision.

## First-Principles Boundary

The smallest useful canary must prove the ownership boundaries that packaging
and unit-only composition cannot prove, while acquiring no user Session or
application authority it does not need.

1. **Selection precedes effect.** An exact installed subcommand is the only
   activation input. Import, environment, platform, backend availability,
   persisted Session contents, or missing control state cannot activate it.
2. **One owner per lifetime.** Coding owns the canary operation and G9
   composition; AppHost owns Product/runtime/profile leases; Hosting owns the
   child process; Harness owns the durable journal mechanism. No owner closes
   another owner's raw handle.
3. **The proof is smaller than the product.** The canary uses an ephemeral,
   path-free Session identity and a one-shot child protocol. It never opens,
   creates, migrates, or mutates a user conversation.
4. **Rollback changes selection, not history.** The durable latch fences future
   canary attempts. An already admitted attempt keeps Hosting ownership and is
   never replayed through Current.
5. **Observations are evidence, not authority.** Output contains bounded
   lifecycle categories and opaque fingerprints, never argv, environment,
   filesystem paths, prompt/session payload, credentials, or raw exceptions.

## Current / Target / Delta

| Plane | Statement |
| --- | --- |
| Facts | G9.1 provides `loushang.coding.apphost_composition`; G9.2 proves its lifecycle with deterministic doubles; G9.3 retains Current; G9.4 promotes the default-dark capability. No installed route imports or invokes the composition, and no production AppHost-to-Hosting canary process exists. |
| Current | `loushang` and `loushang-tui` enter the Current Coding bootstrap. `loushang.coding.__init__` exposes the Current SDK. AppServer remains contract-only; the hosted binder and named mux have no installed runtime. |
| Target | One `loushang apphost canary` command family can inspect Product-owned control state, explicitly run one ephemeral Hosting canary through the G9 composition, durably latch future attempts off, and explicitly re-enable them. All omitted and non-canary routes remain byte-for-byte Current in owner semantics. |
| Delta | Add a lazy CLI adapter, Product-owned canary composition adapter, private one-shot child, durable Product control journal, bounded report, source-backed inventory v3, and retained Linux/Windows evidence. Do not change AppHost core, normal Coding bootstrap, AppServer/AppService, named mux, or the G9.3 `RETAIN` decision. |

## Requirements

| ID | Requirement |
| --- | --- |
| `G10-R1-EXACT-OPT-IN` | Only the exact installed `loushang apphost canary run` operation may request the canary. Missing action, ordinary CLI/TUI/SDK use, imports, environment, platform, backend discovery, and Session contents never activate Hosting. |
| `G10-R2-REAL-OWNERSHIP-CHAIN` | A successful run traverses the installed CLI adapter, Coding-owned G9 composition, AppHost catalog/runtime, exact Product attempt, and public Hosting process port; a parser-only or in-process fake does not satisfy the run case. |
| `G10-R3-EPHEMERAL-IDENTITY` | The canary uses one fresh path-free in-memory Product/continuity/Session identity and never reads or writes the canonical or compatibility Session stores. |
| `G10-R4-DURABLE-SELECTION-CONTROL` | A Product-owned append-only control journal under canonical machine state serializes `run`, `rollback`, and `enable`, treats missing/corrupt/unsafe storage as disabled, and monotonically advances selection generation. |
| `G10-R5-NO-FALLBACK` | Once a run is admitted to Hosting, every start, protocol, timeout, cancellation, or cleanup failure remains that Hosting attempt. Current is never invoked in the same attempt. |
| `G10-R6-BOUNDED-OBSERVABILITY` | Text and JSON reports expose only versioned status, selection generation, stable code, opaque attempt/receipt fingerprints, backend ID, and bounded lifecycle transitions. Paths, argv, environment, payloads, credentials, and raw exception strings are forbidden. |
| `G10-R7-SETTLED-LIFECYCLE` | Success requires child protocol completion, profile detach, Session close, AppHost shutdown, Product cleanup, Hosting process close, and control-lock release. Failure and cancellation retain cleanup authority until settlement or return a stable incomplete-cleanup code. |
| `G10-R8-CROSS-PLATFORM-EVIDENCE` | Linux and Windows execute the exact installed command route with a real native Hosting backend, zero required skips, fixed evidence case IDs, and separate retained reports. |
| `G10-R9-INDEPENDENT-ROLLBACK` | `rollback` durably disables future canary attempts without deleting code or changing normal Current routes; only an explicit `enable` operation with a new generation may admit later runs. |
| `G10-R10-NO-AUTHORITY-EXPANSION` | Passing G10 grants no default owner change, Current deletion, general Worker security claim, normal Coding-session migration, AppServer/AppService runtime, hosted profile listener, A0.5 launcher, or named-mux activation. |

## Command Contract

The installed surface is intentionally a pre-session operation:

```text
loushang apphost canary status   [--format text|json] [--cwd PATH]
loushang apphost canary run      [--format text|json] [--cwd PATH]
loushang apphost canary rollback [--format text|json] [--cwd PATH]
loushang apphost canary enable   [--format text|json] [--cwd PATH]
```

`--cwd` selects only the child working directory after exact directory
validation. It does not relocate durable control, derive a Session root, or
change Product identity. Control always lives below the canonical
`resolve_platform_paths().state` root.

`status` is read-only and starts no AppHost or Hosting owner. `rollback` and
`enable` mutate only the canary selection journal. `run` is the sole effectful
canary path. The standalone `loushang-tui` entrypoint, public SDK, bootstrap,
AppServer, hosted binder, and named mux are explicitly out of the G10 route.

Exit codes are stable at the CLI boundary:

| Code | Meaning |
| --- | --- |
| `0` | requested status/control operation completed, or the canary completed and every owner settled |
| `1` | admitted operation failed with a stable runtime/control/cleanup result |
| `2` | command grammar or caller input is invalid; no canary effect began |

## Component Model

| Component | Owner | Responsibility | Forbidden responsibility |
| --- | --- | --- | --- |
| `coding.cli.apphost` | Coding CLI | recognize exact command grammar, lazy-dispatch the operation, render the bounded report | construct AppHost/Hosting owners, read control files directly, expose raw failures |
| `coding.apphost_canary` | Coding Product | bind explicit request, Product control snapshot, ephemeral Session/profile/admission ports, G9 composition, exact attempt, cleanup, and report | normal Coding bootstrap/session, AppServer/AppService, named mux, implicit selection |
| `coding._apphost_canary_control` | Coding Product | validate and append monotonic enable/rollback records under one Harness journal lock | generic settings, Session persistence, global Hosting policy |
| `coding._apphost_canary_child` | Coding Product | execute the bounded nonce challenge over stdout and exit | import AppHost, access Session/config/resources, accept commands, become a daemon |
| `apphost_composition` | Coding Product/AppHost edge | retain the sole G9 catalog/runtime/composition lifetime and phased settlement | parse CLI or discover Hosting/configuration |
| AppHost public runtime | AppHost | exact catalog, Product/runtime, profile and Session-lease ownership | process launch, CLI, Product policy, persistence |
| Hosting public process port | Hosting | shell-free native process launch, bounded stdio, wait/terminate/close, backend observations | interpret canary protocol or Product success |
| Harness JSONL journal | Harness | cross-platform private lock, strict durable append/read mechanics | decide enabled state or selection generation |

## Dependency Boundary

```text
loushang.coding.cli.__main__
  -> loushang.coding.cli.apphost                 # grammar only

loushang.coding.cli.apphost
  -(exact run/control action; lazy import)-> loushang.coding.apphost_canary

loushang.coding.apphost_canary
  -> loushang.coding.apphost_composition
  -> loushang.apphost                            # public values only
  -> loushang.hosting                            # public process port only
  -> loushang.coding._apphost_canary_control

loushang.coding._apphost_canary_control
  -> loushang.harness.journal
  -> loushang.foundation.platform_paths

AppHost core -/-> Coding / Harness / Hosting / AppServer / AppService
Hosting -/-> Coding / AppHost / Harness / AppServer / AppService
Harness journal -/-> Coding / AppHost / Hosting
```

The accepted G9 composition remains the only module that constructs
`AppHostCatalogV1` and `AppHostRuntimeV1`. G10 adds one installed Product-owned
consumer; it does not create a second composition implementation.

## Selection And Durable Control

The canonical journal leaf is
`state/products/coding/apphost-explicit-canary-control.jsonl`. Its location is
resolved from `PlatformPaths.state`; it is not configurable through cwd and is
added to the machine-resource inventory as Product-owned durable machine
state.

Each strict record contains only:

- schema version;
- monotonic record revision;
- monotonic selection generation;
- state `enabled` or `disabled`;
- operation `enable` or `rollback`; and
- a bounded opaque operation ID.

Absence means `unconfigured` at virtual generation zero and rejects `run`.
The first explicit `enable` appends enabled generation one. A corrupt,
partial-invalid, missing-after-prior-use, aliased, non-private, or non-monotonic
journal fails closed. Deleting a disabled journal therefore cannot re-enable
the canary. History is never rewritten in place. The Product may distinguish
`unconfigured` from a corrupt state for diagnostics, but both deny activation.

`run`, `rollback`, and `enable` share one exclusive cross-platform journal
lock. `run` holds the lock from its final enabled-state read until every
canary owner settles. Therefore a concurrent rollback linearizes either before
the run (which is rejected without effect) or after the exact Hosting attempt
has settled. No rollback can race between final selection and spawn.

Rollback affects future attempts only. It never retargets an admitted attempt,
never calls Current, and never claims to drain another process without an IPC
authority. That limitation is intentional for this short-lived installed
canary; a later long-lived AppServer/mux owner requires a different control
plane.

## Canary Protocol And Lifecycle

The Product adapter creates a fresh in-memory canonical candidate with exact
`coding` Product and compatibility identities. The candidate, Product validator,
admission pins, and `canary` profile expose only the public AppHost protocols.
They own no filesystem path and cannot enumerate user Sessions.

The Product attempt constructs one `ProductWorkerActivationReceiptV1` bound to
that ephemeral Session and one fresh attempt ID. Its `recover` step confirms
that no prior owner is adoptable; it never discovers or adopts a process. Its
`start` step asks the public Hosting process port to launch:

```text
<current Python executable> -m loushang.coding._apphost_canary_child <nonce>
```

The launch is shell-free, uses the validated cwd, a complete explicit effective
environment built from a fixed minimum OS-bootstrap allowlist rather than the
ambient environment, closed stdin, bounded stdout, and bounded stderr tail.
Credential-like variables are never forwarded. The child emits exactly one
versioned nonce response and exits. Coding validates the response and zero exit
status; Hosting observations independently prove the native backend and
process lifecycle. Semantic success is decided by Coding, not Hosting.

The owner sequence is:

```text
exact CLI action
  -> acquire Product control lock
  -> re-read enabled generation
  -> construct G9 composition
  -> attach ephemeral Session/profile
  -> recover exact attempt
  -> launch and validate one-shot Hosting child
  -> detach profile
  -> close exact Session/Product Runtime
       -> Product attempt closes its Process lease and Hosting host
  -> close G9 composition and retire admission pins
  -> release Product control lock
  -> render bounded report
```

All awaits use a finite monotonic budget. Cancellation joins owner cleanup
before propagating. A start or protocol failure cannot replay Current. If a
cleanup phase remains unsettled, the result is failure even if the child
returned the expected response.

## Bounded Report

The version-one report has a fixed schema:

- `reportVersion`;
- `operation` (`status`, `run`, `rollback`, or `enable`);
- `state` (`unconfigured`, `enabled`, `disabled`, `ready`, or `failed`);
- `code` (stable bounded identifier);
- `selectionGeneration`;
- optional receipt and attempt fingerprints;
- optional Hosting backend ID; and
- an ordered bounded tuple of Hosting lifecycle transition identifiers.

The report never contains cwd, state path, executable path, argv, environment,
nonce, stdout/stderr bytes, exception text, traceback, prompt, Session payload,
or credentials. Diagnostics may correlate by the opaque fingerprints only.

## Evidence Contract

Implementation must add a versioned G10 evidence manifest and these exact
case IDs:

| Case | Proof |
| --- | --- |
| `G10-OMISSION-CURRENT` | ordinary CLI/TUI/SDK routes do not import or construct G10/G9/Hosting owners |
| `G10-EXACT-COMMAND` | only exact `apphost canary` grammar dispatches before Session bootstrap |
| `G10-STATUS-NO-EFFECT` | status performs no AppHost construction or process launch |
| `G10-REAL-NATIVE-RUN` | installed command path reaches G9, AppHost, Product attempt, and the expected real Hosting backend |
| `G10-EPHEMERAL-NO-SESSION-IO` | run does not read/write canonical or compatibility Session roots |
| `G10-ROLLBACK-BEFORE-RUN` | disabled state rejects run before composition/process effect |
| `G10-RUN-ROLLBACK-LINEARIZATION` | concurrent rollback orders wholly before admission or after exact run settlement |
| `G10-ENABLE-NEW-GENERATION` | only explicit enable advances generation and permits a later run |
| `G10-NO-FALLBACK` | selected Hosting failure never invokes Current |
| `G10-CANCEL-CLEANUP` | cancellation joins child, AppHost, Product, profile, pin, and lock settlement |
| `G10-REPORT-REDACTION` | every outcome conforms to the bounded schema and forbidden-field scan |
| `G10-INVENTORY-V3` | source-backed entrypoint inventory records the one installed canary and unchanged Current routes |
| `G10-DEPENDENCY-GRAPH` | AST/fact graph contains only the accepted lazy CLI and Product-to-AppHost/Hosting/journal edges |

Unit/deterministic tests may use controlled ports for fault timing. The retained
Linux and Windows `G10-REAL-NATIVE-RUN` jobs must use the installed console
script and native backend sentinel with zero required skips. Reports are
retained separately; one platform cannot synthesize the other's evidence.

## Delivery Slices

| Slice | Delivery | Exit condition |
| --- | --- | --- |
| G10.0 | accepted boundary, requirements, command/control protocol, threat model, parent adoption, and executable architecture guards | three-view design review has no unresolved high/medium finding; no production source changes |
| G10.1 | strict Product-owned control journal and bounded report values | corruption/storage/concurrency/generation tests pass; no AppHost or process effect |
| G10.2 | ephemeral AppHost ports, exact Product attempt, one-shot child, and native Hosting runner | real POSIX/Windows-capable path settles every owner; no user Session I/O |
| G10.3 | lazy installed CLI command, output rendering, inventory v3, and omission guards | exact command runs before bootstrap; all other entrypoints remain Current |
| G10.4 | fault/cancellation/rollback matrix, retained cross-platform evidence, architecture reconciliation, lane/main promotion | three-view implementation review is closed; same immutable head passes AppHost/Harness/Hosting/architecture/Linux/Windows gates |

## Threat Model

| Threat | Required control |
| --- | --- |
| import or backend discovery accidentally activates Hosting | lazy exact-action dispatch plus omission tests that instrument composition and process factories |
| cwd is used to relocate state or discover Sessions | control root always derives from canonical PlatformPaths; ephemeral Session port has no filesystem inputs |
| rollback races after enabled check but before spawn | one exclusive control lock spans final read through complete owner settlement |
| a failed Hosting attempt silently replays Current | no Current port exists in the canary composition; exact no-fallback case instruments all effects |
| forged child output claims another attempt | unpredictable per-attempt nonce, exact versioned response, bounded one-line read, zero-exit requirement |
| child hangs or floods output | finite total budget, bounded stdout read, bounded stderr tail, terminate/close on timeout |
| observation leaks machine or user data | closed report schema and forbidden-field/value tests; raw observations/exceptions remain private |
| missing, deleted, corrupt, or aliased control state re-enables canary | absent state denies run; private regular-file/owner/link checks, strict JSONL codec, monotonic full-history validation, fail closed |
| inherited environment leaks a credential to the child | fixed minimum OS-bootstrap allowlist, explicit generated locale/encoding values, and credential-key rejection tests |
| cancellation abandons a child or AppHost lease | cancellation-shielded, dependency-ordered settlement retained by exact owner |
| green canary is mistaken for normal Coding migration | explicit non-goals, inventory dispositions, unchanged G9.3 `RETAIN`, and parent gap ledger |

## Three-View Review Contract

Design and implementation are reviewed independently from these views:

1. **Architecture and authority:** dependency direction, Product/AppHost/Hosting/
   Harness ownership, Current omission, no hidden AppServer/AppService/mux or
   default-owner expansion.
2. **Lifecycle and safety:** selection linearization, journal corruption,
   cancellation, timeout, no-fallback, exact close order, cleanup debt, and
   stale-generation behavior.
3. **Entrypoint and evidence:** installed grammar, pre-bootstrap dispatch,
   cross-platform native execution, bounded/redacted reports, inventory truth,
   reproducible immutable-head gates, and rollback usability.

High or medium findings block the next phase. Findings are fixed in the design
or source of truth; a review note is not an implementation substitute.

## Exit Gate

G10 is complete only when all G10.0--G10.4 slices are implemented, the
source-backed inventory names the exact installed canary path and every
unchanged Current surface, all thirteen evidence cases pass, Linux and Windows
retain real native zero-skip reports, and the same immutable head passes:

- `make check-apphost`;
- `make check-harness`;
- `make check-hosting`;
- `make check-architecture-docs`;
- the installed CLI canary smoke on Linux and Windows; and
- the repository's affected dependency and install gates.

Passing the gate grants only an explicit short-lived installed canary. Normal
Coding sessions, TUI, SDK, AppServer, AppService, hosted profiles, A0.5, and
named mux remain unchanged. Current remains retained until a separate successor
decision proves every G9.3 deletion condition.
