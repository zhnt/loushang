# Hosting H3 Inherited Peer Endpoint

## Status

- ID: `HOST-H3`
- Scope: `hosting`
- Parent: `loushang`
- Authority: normative — accepted H3 endpoint specification
- Design status: accepted
- Implementation status: implemented
- Delivery status: platform-neutral and local POSIX evidence complete; native Windows evidence awaits the combined CI gate
- Owner: Loushang Hosting architecture
- Public contract version: `loushang.hosting/v1`

## Purpose And Boundary

H3 implements `HOST-CMP-ENDPOINT` as a private resource owner. It creates one
unnamed host/child byte pair, exposes only the bounded host endpoint, and hands
one backend-bound single-use inheritance capability to the process platform
adapter. H3 also implements the H2 private transfer seam in both process
backends.

H3 does not expose an endpoint factory publicly, publish a process-plus-endpoint
session, choose a protocol, perform a handshake, listen for later clients, add
an address to argv or environment, or activate a Harness Worker route. Atomic
composition and the public `ChildSessionHostingPort` were deliberately deferred
to H4.

## Ownership Model

The pair has exactly two ownership branches:

| Resource | Owner before spawn | Successful transfer | Failure or close |
| --- | --- | --- | --- |
| host read/write side | Endpoint Host lease | remains with the lease | closed by the lease |
| child stdin/stdout side | single-use inheritance capability | matching process backend closes the parent's copy after atomic spawn | capability closes every untransferred copy |
| blocking I/O operation | endpoint transport | remains tracked after caller cancellation | transport close unblocks and joins it |
| endpoint capacity | pending reservation or published lease | remains charged while the lease is live | released only after pair cleanup settles |

The inheritance capability has four private states:

```text
owned --matching claim--> claimed --spawn success + parent close--> transferred
  |                          |
  +-------- close ----------+-------------------------------> closed
```

A backend mismatch does not consume the capability. A second claim, a transfer
without a claim, or malformed native values fails as
`endpoint_transfer_failed`. If closing the parent's child-side copy fails, the
state remains retry-closeable; it is never falsely marked transferred.

## Transport And Process Stream Boundary

The inherited endpoint occupies child standard input and standard output. This
is a mechanism mapping, not semantic stdout discovery: the child receives a
duplex byte channel at its conventional stdio handles and Hosting interprets
none of its bytes. The process request used with inheritance must therefore
declare `stdin=CLOSED` and `stdout=DISCARD`; the aggregate session owns those
two directions through `HostByteEndpoint`, and the `ProcessLease` cannot expose
duplicate stream owners. Child stderr remains independently governed by the
process request.

No descriptor, handle, address, token, or endpoint name enters argv or the
complete effective environment. This preserves the H0 materialized-request
boundary and prevents a bootstrap variable from becoming ambient authority.

## POSIX Mechanism

The POSIX endpoint backend uses one unnamed `AF_UNIX` `SOCK_STREAM`
`socket.socketpair`. The host socket is nonblocking and non-inheritable. The
child socket is non-inheritable in the parent and is supplied explicitly as
both `stdin` and `stdout` to `asyncio.create_subprocess_exec` with
`close_fds=True` and `start_new_session=True`.

The spawn implementation duplicates that exact child socket onto descriptors
0 and 1 before exec and closes the source descriptor. No `pass_fds`, listener,
filesystem rendezvous, TCP fallback, or ambient descriptor inheritance is
used. After successful creation the parent's child-socket copy is closed by
the transfer capability. The host socket is proved absent from the child.

## Windows Mechanism

The Windows endpoint backend creates two unnamed anonymous pipes: host-write to
child-stdin and child-stdout to host-read. Only the child read/write handles
remain inheritable. They replace the process backend's ordinary stdin/stdout
handles in the exact `PROC_THREAD_ATTRIBUTE_HANDLE_LIST`; the Job Object stays
in `PROC_THREAD_ATTRIBUTE_JOB_LIST`. `CreateProcessW` therefore attaches both
tree ownership and the endpoint allowlist before the primary thread runs.

The raw spawner treats supplied endpoint handles as caller-owned throughout
acquisition. It neither closes them on failure nor returns parent process-stream
handles. After successful process creation, the process backend marks transfer
and closes the parent's child-handle copies. Child stderr remains separately
created and owned by the process transport.

Synchronous pipe I/O runs on a capacity-derived private executor. Caller
cancellation does not cancel the owned native operation. Endpoint close first
uses each executor thread identity with `CancelSynchronousIo`, joins each
tracked operation, closes both host handles, and only then lets host shutdown
close the executor. A fixed settlement interval fences kernel anomalies.
Windows 10 or later is
already required by the H2 atomic Job Object path; absence of required Win32
APIs fails closed rather than selecting another transport.

## Lifecycle, Bounds, And Failure Semantics

`_InheritedEndpointHost` reserves capacity before backend creation and counts
pending reservations together with live leases. The host fixes maximum live
endpoints, bytes per read, and bytes per write. Native kernel buffers provide
backpressure; Hosting adds no unbounded application queue.

Close is idempotent and cancellation-shielded. Host close fences new creation,
cancels pending creators, waits for their rollback, closes every published
lease, then closes the backend. A caller cancelled after native attachment does
not regain control until both sides of the pair have been reclaimed. Cleanup
failures are aggregated and do not skip later cleanup. A failed pair close is
retryable, keeps its capacity debt, and faults the host against new creation;
it is never counted as a successful release.

Ownership also survives failures before a pair object can be returned. The
Windows backend records any raw handles that fail to close during partial pipe
acquisition and retries them from backend close. A provider that attaches a
pair and then fails leaves that pair on the Endpoint Host reservation until a
close retry settles it. These debts use a typed private `cleanup_failed` cause,
allowing an aggregate Session Host to retain its own reservation even though it
received no endpoint lease.

The Endpoint Host emits bounded `HOST-CMP-ENDPOINT` lifecycle observations with
an opaque endpoint owner, optional aggregate-session correlation, and exact
backend identity. Observation callbacks are non-owning and cannot veto or
delay resource transitions.

Peer closure is represented as read EOF or `peer_closed` on write. Backend
creation failures map to `endpoint_unavailable`; target mismatch, invalid stream
topology, reuse, or parent-copy transfer failure maps to
`endpoint_transfer_failed`. Neither category asserts Worker health or protocol
meaning.

## Conformance Inventory

| ID | Platform | Evidence |
| --- | --- | --- |
| `H3-OWNER-CAPACITY` | platform-neutral | pending plus live capacity, close fencing, and release after cleanup |
| `H3-OWNER-BOUNDS` | platform-neutral | fixed read/write bounds and backend-result validation |
| `H3-OWNER-CANCEL` | platform-neutral | cancellation after attachment, cancelled close waiters, and host-close cancellation reclaim the pair exactly once |
| `H3-TRANSFER-ONCE` | platform-neutral | backend-bound claim, exactly-once transfer, retry-closeable failure path |
| `H3-POSIX-PAIR` | POSIX | real socketpair byte round trip through child stdin/stdout |
| `H3-POSIX-FD` | POSIX | host descriptor and unrelated ambient descriptors are absent in child |
| `H3-WIN-PAIR` | Windows | two anonymous pipes with exact direction and peer-close behavior |
| `H3-WIN-HANDLE` | Windows | endpoint handles appear only in the intended spawn allowlist and parent copies close after success |
| `H3-WIN-CANCEL` | Windows | cancelled blocking operation remains owned and is unblocked during pair close; partial-acquisition handle debt is retained and retried |
| `H3-SELECT` | all CI platforms | exact endpoint backend is selected; no weaker fallback exists |

The deterministic owner and fake-Windows cases run everywhere. Real POSIX
evidence runs on Linux and macOS. Real Windows endpoint/process round-trip and
the non-skipped backend sentinel run on Windows CI. A local checkout proves
only its current platform; the three-platform workflow is the authoritative
combined report.

## H4 Entry Boundary

H4 composes this private endpoint owner with the H2 Process Lifetime Host.
The orchestration order is process-capacity reservation, caller preparation,
endpoint acquisition, final preparation verification, atomic process spawn and
endpoint transfer, then aggregate publication. Failure or cancellation must
publish neither resource and unwind process, endpoint, and preparation owners
without skipping later cleanup. H4 adds no public raw endpoint factory or
inheritance material.
