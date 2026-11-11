# Loushang Hosting H5 Default-Dark Harness Worker Adapter

## Status

- ID: `HOST-H5`
- Scope: `hosting` consumer migration
- Parent: `loushang`
- Authority: normative — accepted H5 boundary with the bounded A63 adoption below
- Design status: accepted
- Implementation status: implemented
- Activation status: H5c defaults to Current; the explicit A63 operator path is separately adopted
- Owner: Harness Worker composition
- Public Hosting contract version: `loushang.hosting/v1`

## Purpose And Boundary

H5 lets the Harness Worker supervisor consume an atomic
`ChildSessionHostingPort` without moving Worker meaning into Hosting. It is an
additive migration seam, not PLC9C5 Product activation. The following table records
the original H5 delivery, rather than an absence claim about all later callers.
H5 has three slices:

| Slice | Delivery | Excluded change |
| --- | --- | --- |
| H5a | aggregate `ManagedWorkerSessionLaunchPort`, Current compatibility aggregate, Hosting request/session adapter, and Supervisor `start_session` entrypoint | no production composition, Sandbox authority move, or old entrypoint removal |
| H5b | executable Current-owner versus Hosting-owner compatibility matrix | no claim that missing sealed-descriptor transfer is solved |
| H5c | explicit typed owner selection, pathless diagnostics, no-fallback routing, and sticky future-attempt rollback | no environment-variable activation, mid-start fallback, or default change |

The existing `WorkerSupervisor.start(launch_port, transport, ...)` remains the
Current entrypoint and default behavior. It adapts its separately supplied
process and transport into the aggregate interface internally. At the original
H5 delivery there was no production Product composition: Product, Sandbox, host
RPC and capability-publication callers were outside that slice.

## Current Bounded Adoption: Explicit Operator Query

The earlier explicit Product query already used the Hosting adapter before
[A63](../harness/key-designs/worker-product-runtime-convergence.md#26-a63完整单次查询接通原session)
moved its complete lifetime into the existing Session owner. The one accepted
non-Worker Harness consumer is
`loushang.harness.session._worker_operator_query::_query_selected_worker_once`,
using `HostingManagedWorkerSessionAdapter`. Coding's explicit native CLI query
supplies a selected Product receipt, admitted source, native preparation and
start gate. Session retains the original Supervisor, C5 and Graph coordination
and reverse cleanup; Worker and Hosting remain the mechanism owners.

This path does not instantiate `WorkerHostingActivationV1` or
`WorkerSessionOwnerRouter`. Ordinary startup and the generic H5c default remain
Current. The operator uses its separately reviewed native preparation path;
it does not make H5's general sealed-descriptor transfer representable, replace
required Sandbox evidence, or demonstrate H5c rollout/rollback. A failed operator
attempt follows its original selected-owner cleanup and error handling; it never
switches to another launch owner.

Architecture inspection therefore permits only that existing module's adapter
reference. Other non-Worker consumers, including Activation/Router references in
that same module, remain forbidden. Hosting still cannot import Harness.

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
| mandatory Approval | Process authorization gateway | must be supplied by the injected preparation capability | retained boundary; H5 supplies no generic Product binder |
| required Sandbox containment | owner-minted plan verified by Sandbox | preparation must materialize an equivalent Hosting-consumable launch | **gap remains** |
| sealed executable and bound cwd | private retained POSIX descriptors | Hosting v1 request/backend cannot inherit those Harness descriptors | **not representable; production Hosting owner unavailable** for the Current descriptor route |
| process and protocol transport publication | separately supplied to Supervisor | one atomic `ChildSessionLease` | Hosting is stronger after successful start |
| process-tree cleanup | Current Process Host | H4 platform process owner | equivalent contract, separately proven platform mechanics |
| endpoint cleanup | caller-owned transport | H4 aggregate closes process before endpoint | Hosting is stronger and atomic |
| Worker framing and handshake | Worker Supervisor | same Worker Supervisor | unchanged |
| failure vocabulary | Worker/Process errors | Hosting start errors mapped to stable Worker binding codes | compatible, raw platform text remains hidden |
| default route | Current | only through explicit typed selection | Current remains default |
| rollback | composition replacement | sticky selector affects future attempts only | no double-owner fallback |
| Product/native evidence | separately admitted Product facts | H5 itself supplies none; the explicit operator uses its own native preparation | general migration remains separate work |

The bold gap is intentional and executable. H5 does not pass a mutable path as
a substitute for a sealed executable, use `close_fds=False`, expose a raw
handle, or treat a generic preparation port as Sandbox proof. A later contract
must introduce a separately reviewed opaque preparation capability that both
Hosting's exact platform backend and Sandbox can consume before general
migration of the Current sealed-descriptor route. The separately reviewed
native operator above does not erase this representability gap.

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
| `H5-NO-PRODUCT` | historical ID: architecture inspection rejects unaccepted non-Worker consumers; only the A63 operator adapter reference is adopted, with no selector/router exception |

## Exit And Next Gate

H5 is complete when the dark adapter, compatibility matrix, selector,
rollback, Supervisor integration, and the precise consumer boundary check are green.
This does **not** complete PLC9C5.

The original next delivery was opaque native preparation plus Product-owned
rollout and recovery, refined by the later H6/PLC9C5 work and the bounded query
adoption above. General migration must still prove required containment, exact
Linux/Windows resource transfer and its own explicit canary composition. The
Current owner must remain available until those Product-native tests and
rollback drills pass independently.

## A94 Reconciliation Evidence

A94 reconciles the already accepted A63 Session operator with H5/H6 Current;
it does not authorize a new activation. Independent responsibility/reuse,
runtime/failure and compatibility reviews accepted the actual test/doc change.
The review narrowed an overstatement of failed-owner settlement to the original
cleanup and error handling, which can fail and retain debt.

The inspection exception is exactly one file and one adapter symbol. All original
assertions and the forbidden-name set retain their AST; the rest of the test module
also retains its AST after reversing the exception. Static absence/allowed/other
file/selector/router experiments confirm scope reduction, including no requirement
that the accepted consumer be present. This adds no gate, trigger, platform or
new failure condition. All 1,968 production sources and 13 resources match A93
by SHA; Coding remains 113,579 lines and the system 647,772, with zero production
change or simplification credit in A94.

The final affected existing checks passed 25 cases; pure documentation invariants
passed 9. Existing Hosting lint passed and mypy checked 35 sources successfully.
The broader Hosting execution produced 505 passes, 8 failures, 53 skips and 4
marker deselections. Three text-contract failures introduced during drafting were
corrected and included in the final 25 passes. The other five failures reproduce
at frozen HEAD `175d68a90f4c400083c4fcc711cded7418891a24`, alongside the original H5
consumer failure that this change closes. The broader suite is not declared green.

The five remaining issues are the H0 standard-library-only constraint versus
Foundation owned tasks, the AppHost canonical-catalog source inventory, the
original explicit-query/launch consumer inventory, the C50 Windows backend reader
inventory and the C52 preparation consumer inventory. Their actual owner and
accepted scope must be reconciled separately; baseline failure alone authorizes
no exception. Public/native platform, cancellation and complete Goal acceptance
are not inferred from these architecture checks.

Detailed source snapshots, three independent reports, unchanged-source proof and
logs/XML are retained outside Git in the local A94 reconciliation evidence bundle.
The first Make attempt stopped before tests because offline uv lacked build-system
packages; the same check then used the installed virtual environment without sync.
No Product guard or runtime code was changed to accommodate the environment.
