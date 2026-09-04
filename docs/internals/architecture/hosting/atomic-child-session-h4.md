# Loushang Hosting H4 Atomic Child Session

## Status

- ID: `HOST-H4`
- Scope: `hosting`
- Parent: `loushang`
- Authority: normative — accepted H4 child-session specification
- Design status: accepted
- Implementation status: implemented
- Delivery status: platform-neutral and native Linux/macOS/Windows evidence complete
- Owner: Loushang Hosting architecture
- Public contract version: `loushang.hosting/v1`

## Purpose And Boundary

H4 implements `HOST-CMP-SESSION` as the sole aggregate lifetime owner for one
process and one inherited peer endpoint. The public
`create_child_session_host` composition entrypoint selects one compatible
platform adapter set and returns only `ChildSessionHostingPort`. A successful
`start` publishes one `ChildSessionLease`; every unsuccessful transaction
publishes neither constituent lease.

The Child Session Host owns no protocol framing, handshake, heartbeat, Worker
health, restart, durable identity, Sandbox decision, or domain publication.
It adds no raw endpoint factory, descriptor, handle, address, or bootstrap
environment variable to the public surface. `stdin=CLOSED` and
`stdout=DISCARD` reserve the child standard streams exclusively for the
inherited duplex endpoint; stderr remains governed by the process request.

## Composition And Platform Set

The composition root constructs a process backend and endpoint backend as one
exact set:

| Platform | Process backend | Endpoint backend | Shared invariant |
| --- | --- | --- | --- |
| POSIX | `posix-process-group-v1` | `posix-socketpair-v1` | the socket child side is accepted only by the POSIX spawn seam |
| Windows | `windows-job-v1` | `windows-anonymous-pipes-v1` | one Win32 API owner supplies the atomic Job/handle-list spawn and pipe handles |

Construction fails closed if either member is unavailable. There is no
cross-platform mix, stdio fallback, TCP fallback, filesystem rendezvous, or
partially returned host. The existing public `create_process_host` remains an
independent process-only composition entrypoint.

## Atomic Start Transaction

The exact successful order is:

1. have the Session Host validate the immutable request's reserved-stream
   topology before capacity or resource acquisition;
2. reserve aggregate session capacity;
3. reserve process capacity;
4. acquire the caller's `LaunchPreparationLease`;
5. create and attach the inherited endpoint pair;
6. bind its single-use child inheritance to the matching process backend;
7. run `verify_current` at the final pre-spawn point;
8. atomically spawn/contain the process and transfer the child endpoint;
9. attach both internal leases to the aggregate reservation;
10. publish one `ChildSessionLease` and start natural-exit convergence.

The endpoint is deliberately created inside the Process Host preparation
transaction. This preserves the process-capacity-before-preparation rule while
letting the Process Host retain its single final verification and spawn owner.
A private deferred-inheritance capability carries no raw value until the
endpoint has been attached and rejects a backend mismatch before spawn.
The prepared request is validated again before endpoint acquisition, because
preparation may return a different materialized request. This host-level check
preserves H0 `loushang.hosting/v1` construction compatibility: creating a
`ChildSessionRequest` does not itself reject a process-only stream topology.

## Ownership And Rollback Matrix

| Failure or cancellation point | Owned material | Required settlement before propagation |
| --- | --- | --- |
| aggregate/process capacity | no caller preparation or OS resource | release the aggregate reservation |
| caller preparation | only material attached by the caller itself | caller port reports failure; Hosting releases its reservations |
| endpoint acquisition or binding | preparation plus any attached pair | settle Endpoint Host rollback, close preparation, and close any returned endpoint lease without skipping either owner |
| final verification | preparation and endpoint | Process Host closes preparation; Session Host closes endpoint |
| spawn before process attachment | preparation and endpoint | close transfer material, preparation, and endpoint |
| spawn after process attachment or early exit | process tree, preparation, endpoint | reclaim process/tree/handles and preparation, then close endpoint |
| aggregate publication fence | both internal leases | close process lease first, then endpoint lease; publish neither |

Primary failure or cancellation remains primary. Cleanup failures are attached
as causes/notes or aggregates, and later reachable cleanup is still attempted.
Cancellation is delayed until the owned rollback task settles. Failed cleanup
retains capacity debt, faults the relevant owner against new work, and is never
reported as successful release.

This rule crosses nested owners. If an Endpoint Host acquisition or Process
Host unpublished-spawn rollback reports typed cleanup debt, the Session Host
also retains its aggregate reservation and faults even when no constituent
lease was returned to it. Host close then drives the nested owner's retry path;
the earlier cleanup failure remains visible rather than being erased by a later
successful retry.

## Joint Lifetime And Close

The aggregate lease is the only public joint owner. Explicit close and natural
process exit converge on one cancellation-shielded close operation. The
process lease closes first so the child tree can no longer use the channel;
the endpoint closes second. Concurrent callers share that operation. A
cancelled waiter does not discard a successfully completed owner task, so a
later close cannot repeat cleanup or lifecycle observations. A transient
endpoint or unpublished-process cleanup failure may be retried, but the
aggregate host stays faulted and accepts no new sessions after observing
incomplete cleanup.

Host close fences new starts, cancels pending start transactions, waits for
their transaction-settlement events rather than arbitrary later caller work,
closes published aggregate leases, and finally closes both internal hosts.
Cleanup failure never reopens the host or erases its prior capacity debt.

## Observability

Process, Endpoint, and Session observations use the same opaque `session_id`.
Each component retains its own `owner_id` and exact backend identity. The
Session component emits capacity, preparing, published, cleaning, closed, and
failed transitions. Observation callbacks remain synchronous, bounded,
non-owning, and unable to veto lifecycle work.

These facts prove only Hosting mechanism state. They do not assert handshake
success, protocol health, Sandbox containment, Plugin admission, or domain
publication.

## Public Surface

H4 adds only `create_child_session_host(...)`. Its owner-selected bounds cover
pending/live sessions, process reads/writes, stderr tail, termination grace,
stderr drain, and Windows endpoint-I/O settlement. The factory returns the
existing H0 protocol and exposes no concrete host, backend, native handle, or
inheritance capability.

## Conformance Inventory

| ID | Platform | Evidence |
| --- | --- | --- |
| `H4-TXN-ORDER` | platform-neutral | aggregate/process capacity, preparation, endpoint, verify, spawn, transfer, and publication order |
| `H4-TXN-ROLLBACK` | platform-neutral | exact failure categories plus preparation, topology-swap, endpoint, backend-mismatch, verification, spawn, early-exit, post-attachment, nested-cleanup-debt, and aggregate-publication-fence cases publish neither |
| `H4-TXN-CANCEL` | platform-neutral | cancellation after attachment and host close settle the owned transaction before propagation |
| `H4-LIFE-JOINT` | platform-neutral | explicit close, natural exit, concurrent close, and cancelled waiters close process then endpoint exactly once |
| `H4-LIFE-DEBT` | platform-neutral | cleanup failure faults the host, retains debt, rejects new sessions, and permits safe retry where possible |
| `H4-OBS-CORRELATE` | platform-neutral | process, endpoint, and session facts share one opaque session correlation |
| `H4-SELECT-SET` | all CI platforms | exact compatible backend set and unsupported-platform refusal |
| `H4-NATIVE-ROUNDTRIP` | Linux, macOS, Windows | public factory transfers bytes through the inherited endpoint and settles the child process |

Deterministic fake-backed cases run on every platform. The native round trip
and non-skipped backend sentinel run in the Linux, macOS, and Windows Hosting
workflow. A local checkout proves only its current platform; the workflow is
the authoritative combined report.

## Activation Boundary

H4 completes the five-component Hosting v1 mechanism baseline. It does not
switch the Current Harness Worker owner. A later, separately reviewed Harness
activation slice may adapt an admitted Worker request and preparation port to
`ChildSessionHostingPort`, then retain framing, handshake, restart, journal,
and domain-generation authority above Hosting. Default-dark behavior remains
unchanged until that activation is explicitly accepted.
