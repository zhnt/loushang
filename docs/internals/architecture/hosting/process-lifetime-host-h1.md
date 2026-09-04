# Hosting H1 Process Lifetime Host

## Status

- ID: `HOST-H1`
- Scope: `hosting`
- Parent: `loushang`
- Authority: normative — implemented H1 internal runtime specification
- Design status: accepted
- Implementation status: implemented
- Owner: Loushang Hosting architecture
- Public contract version: unchanged at `loushang.hosting/v1`

## Purpose And Delivery Boundary

H1 implements `HOST-CMP-PROCESS` as a private and fake-backed process-lifetime
owner. It proves ownership and concurrency independently of operating-system
creation details. The implementation is `_process_host.py`; its required
platform seam is `_process_backend.py`. Neither is exported from
`loushang.hosting`, so H1 adds no unproven backend SPI or construction promise
to the H0 public surface.

H1 does not migrate the Current Harness process owner, add a Harness adapter,
or select a real platform backend. It does not implement H3 inherited
endpoints or H4 child sessions. PID values, native handles, spawners,
reservation objects, and backend registration remain absent from the public
contract.

## Ownership Transaction

One start has exactly one task-owned reservation and follows:

```text
capacity -> preparation -> verify -> spawn/attach -> publication
```

Capacity covers both pending reservations and published leases. It is reserved
before invoking caller preparation. The returned preparation lease becomes
Hosting-owned, supplies the exact request, is verified at the final safe point,
and is closed exactly once after the process has settled or start rolls back.

The private spawn contract must synchronously attach a newly created process to
the reservation before another cancellation point. A successful start publishes
one opaque process lease only after the host remains open and the child has not
already exited. Failure, early exit, host-close fencing, or cancellation
publishes nothing and executes the owned rollback before propagating.

## Process Lease State And Convergence

Natural exit has one backend wait owner. It stores one immutable raw
`ProcessExit`, wakes all `wait` and termination observers from that same result,
drains the bounded stderr tail when requested, closes backend-owned process
handles, closes the preparation lease, and only then returns host capacity.

Explicit close and terminate share one task per operation. Repeated or
concurrent callers observe that task; a cancelled caller is delayed by shielding
until the owner task settles. Cleanup follows:

```text
terminate -> bounded grace -> kill -> reap -> close handles
```

Closing stdin precedes termination. Failure in stdin close, terminate, kill,
reap, stderr drain, handle close, or preparation close is recorded in a typed
private aggregate and does not skip a later reachable step. A failure
observation contains only the stable public category, never an exception
message or backend payload.

## Fixed Bounds

The immutable host limits bound:

- pending plus live processes;
- each stdout/stderr read and stdin write;
- the retained stderr suffix;
- the graceful termination wait; and
- post-exit stderr drain time.

The clock/timeout operation is a private seam, allowing deterministic timeout
tests without a real process or wall-clock delay. Backend process-tree and
post-kill reap guarantees are platform obligations that H2 must prove; H1 does
not disguise an unproven real implementation behind the fake.

## Observations

Observations use the H0 closed schema with component `process`, deterministic
opaque owner IDs, the selected bounded backend ID, lifecycle transition, and
an optional stable failure category. Sink exceptions are isolated from the
state machine. H1 records no argv, cwd, environment, byte content, PID, handle,
security claim, Worker health, or Product meaning.

## Executable Evidence

- `tests/hosting/test_process_host.py` supplies fake preparation, process,
  backend, timeout, and observation seams. It covers natural exit, capacity,
  early exit, preparation/spawn failure, termination escalation, fault
  aggregation, start/close cancellation, concurrent close, stream bounds,
  stderr-tail truncation, adversarial backend reads, and sink isolation.
- `tests/architecture/test_hosting_h1_process_lifetime.py` proves the backend
  and owner remain private, no real spawn primitive or upward dependency is
  introduced, Current Harness ownership is unchanged, and this delivery
  boundary stays explicit.
- `make check-hosting` and the Hosting Quality workflow run H0 and H1 lint,
  type, contract, runtime, and architecture evidence independently of Harness
  migration.

## H2 entry criteria

H2 may start only when this fake lifecycle matrix remains green and its design
names separate POSIX and Windows evidence. H2 should be sliced in this order:

1. specify exact process-group/job-object creation, handle inheritance,
   terminate/kill/reap, stream closure, and unsupported-platform behavior;
2. implement private POSIX and Windows adapters with real conformance tests;
3. compare the Hosting lifecycle against the Current Harness matrix; and
4. add a narrow Harness compatibility adapter only after behavioral parity,
   leaving activation and old-owner removal to a later reviewed change.

H3 endpoint feasibility may be investigated alongside H2 documentation, but
must not share a platform capability claim until allowlist and peer-closure
tests exist. H4 must wait for H3 and then prove atomic rollback at every
process/endpoint/preparation acquisition and publication boundary.
