# Loushang Hosting H5 Default-Dark Harness Worker Adapter

## Status

- ID: `HOST-H5`
- Scope: `hosting` consumer migration
- Parent: `loushang`
- Authority: normative — accepted H5 dark-adapter specification
- Design status: accepted
- Implementation status: implemented
- Activation status: default-dark; no production Product composition
- Owner: Harness Worker composition
- Public Hosting contract version: `loushang.hosting/v1`

## Purpose And Boundary

H5 lets the Harness Worker supervisor consume an atomic
`ChildSessionHostingPort` without moving Worker meaning into Hosting. It is an
additive migration seam, not PLC9C5 Product activation. H5 has three slices:

| Slice | Delivery | Excluded change |
| --- | --- | --- |
| H5a | aggregate `ManagedWorkerSessionLaunchPort`, Current compatibility aggregate, Hosting request/session adapter, and Supervisor `start_session` entrypoint | no production composition, Sandbox authority move, or old entrypoint removal |
| H5b | executable Current-owner versus Hosting-owner compatibility matrix | no claim that missing sealed-descriptor transfer is solved |
| H5c | explicit typed owner selection, pathless diagnostics, no-fallback routing, and sticky future-attempt rollback | no environment-variable activation, mid-start fallback, or default change |

The existing `WorkerSupervisor.start(launch_port, transport, ...)` remains the
Current entrypoint and default behavior. It adapts its separately supplied
process and transport into the aggregate interface internally. No Product,
Sandbox runtime, host RPC, or capability-publication composition imports the
H5 adapter in this slice.

## H5a Aggregate Worker Session

`ManagedWorkerSessionLaunchPort.start` returns one
`ManagedWorkerSession` containing all three views needed above the mechanism
boundary:

- immutable `WorkerLaunchEvidenceV1` for the exact admitted attempt;
- `ManagedWorkerProcessControl` for wait, termination, and bounded diagnostics;
- `WorkerFramedTransport` for the existing Worker protocol owner; and
- aggregate `terminate` and `close` operations.

The Current compatibility aggregate retains its existing ownership order. A
launch failure closes its caller-supplied transport before returning. A
terminal Supervisor failure closes the transport, then terminates the Current
process with the existing close fallback. The narrow
`bind_current_worker_session_port` function combines only the launch and
transport capabilities already held by trusted composition; it mints no spawn
or endpoint authority and is single-use.

The Hosting adapter maps only an already-bound `ManagedWorkerLaunchRequestV1`:

| Worker fact | Hosting material |
| --- | --- |
| exact runtime executable | one-element absolute `argv` |
| exact package revision root | absolute `cwd` |
| Worker environment | complete empty environment |
| Worker protocol channel | inherited endpoint with `stdin=CLOSED`, `stdout=DISCARD` |
| diagnostics | explicit `stderr=PIPE` |

The injected `LaunchPreparationPort` remains the caller's capability. The
adapter checks admitted Worker runtime evidence before the transaction and
again at Hosting's final `verify_current` fence. It neither creates approval,
containment, or sealed-executable evidence nor infers a native descriptor from
`argv`. On success the endpoint byte adapter delegates close to the complete
`ChildSessionLease`; it never closes the endpoint ahead of the process.

The Supervisor validates returned aggregate evidence before entering
handshake. Framing, protocol direction, handshake identity, heartbeat,
correlation, journal transitions, restart budget, fencing, and domain
publication remain Harness responsibilities.

## H5b Current Versus Hosting Compatibility Matrix

| Concern | Current owner | H5 Hosting owner | H5 conclusion |
| --- | --- | --- | --- |
| admitted Worker identity and evidence | `ManagedWorkerLaunchPort` | Harness adapter around the session port | equivalent and rechecked |
| mandatory Approval | Process authorization gateway | must be supplied by the injected preparation capability | retained boundary; no Product binder yet |
| required Sandbox containment | owner-minted plan verified by Sandbox | preparation must materialize an equivalent Hosting-consumable launch | **gap remains** |
| sealed executable and bound cwd | private retained POSIX descriptors | Hosting v1 request/backend cannot inherit those Harness descriptors | **not representable; production Hosting owner unavailable** |
| process and protocol transport publication | separately supplied to Supervisor | one atomic `ChildSessionLease` | Hosting is stronger after successful start |
| process-tree cleanup | Current Process Host | H4 platform process owner | equivalent contract, separately proven platform mechanics |
| endpoint cleanup | caller-owned transport | H4 aggregate closes process before endpoint | Hosting is stronger and atomic |
| Worker framing and handshake | Worker Supervisor | same Worker Supervisor | unchanged |
| failure vocabulary | Worker/Process errors | Hosting start errors mapped to stable Worker binding codes | compatible, raw platform text remains hidden |
| default route | Current | only through explicit typed selection | Current remains default |
| rollback | composition replacement | sticky selector affects future attempts only | no double-owner fallback |
| Product/native evidence | Current PLC9C baseline only | absent | remains PLC9C5 work |

The bold gap is intentional and executable. H5 does not pass a mutable path as
a substitute for a sealed executable, use `close_fds=False`, expose a raw
handle, or treat a generic preparation port as Sandbox proof. A later contract
must introduce a separately reviewed opaque preparation capability that both
Hosting's exact platform backend and Sandbox can consume before any Product
may supply a Hosting session owner.

## H5c Selection, Diagnostics, And Rollback

`WorkerHostingActivationV1()` selects `current`. Selecting `hosting` requires
an explicit typed value at trusted composition and an injected Hosting session
port; absence raises `worker_hosting_owner_unavailable`. No environment
variable, config-file lookup, Product-name heuristic, platform heuristic, or
implicit availability probe changes the default.

`WorkerSessionOwnerRouter` snapshots the selected port synchronously before
awaiting start. It never retries the other port after any failure or
cancellation. This prevents one logical attempt from acquiring two processes,
two endpoints, or two cleanup owners.

`rollback_to_current` is idempotent and permanently latches that router to the
Current owner. An attempt that already captured Hosting continues with its
original owner; only later starts observe the incremented selection
generation. Re-enabling Hosting requires construction of a new explicitly
configured router after a new readiness decision.

`WorkerHostingSelectionV1` exposes only version, requested/effective owner,
Hosting availability, rollback state, generation, and one closed diagnostic
code. It contains no executable, cwd, environment, Plugin identity, session
nonce, native handle, exception text, or protocol payload.

## Conformance Inventory

| ID | Evidence |
| --- | --- |
| `H5-ADAPT-MAP` | exact executable/cwd/empty-environment/stream mapping plus pre-transaction and final evidence fences |
| `H5-AGGREGATE` | process, framed endpoint, evidence, and process-before-endpoint cleanup are published together |
| `H5-SUPERVISOR` | the existing journal and handshake owner runs through `start_session` without moving protocol meaning |
| `H5-CURRENT-COMPAT` | the legacy `start` signature and terminal termination timing remain covered by the prior Worker suite |
| `H5-SELECT` | omission stays Current; Hosting requires typed opt-in and an available port |
| `H5-NO-FALLBACK` | a selected-owner failure never starts the other owner |
| `H5-ROLLBACK` | an in-flight attempt remains sticky while future starts switch idempotently to Current |
| `H5-DIAGNOSTIC` | selection snapshots use a closed pathless schema |
| `H5-NO-PRODUCT` | architecture inspection proves no non-Worker production module composes the adapter or selects Hosting |

## Exit And Next Gate

H5 is complete when the dark adapter, compatibility matrix, selector,
rollback, Supervisor integration, and architecture absence gate are green.
This does **not** complete PLC9C5.

The next gate is an opaque, native preparation contract plus Product-owned
rollout and recovery. That work must prove required containment and exact
Linux/Windows resource transfer, then add an explicit canary composition. The
Current owner must remain available until those Product-native tests and
rollback drills pass independently.
