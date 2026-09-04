# Loushang Hosting Requirements

## Status

- Scope: `hosting`
- Parent: `loushang`
- Authority: normative — proposed requirements
- Design status: proposed
- Implementation status: not-started
- Owner: Loushang Hosting architecture

## Functional Requirements

### HOST-FR-001 — Materialized local launch

Hosting shall accept one immutable, shell-free, fully materialized local launch
request and shall not perform Product command resolution, executable discovery,
or environment inheritance by default.

Acceptance: a request states exact argv, absolute cwd, complete effective
environment, and explicit stream/endpoint intent; shell strings and implicit
ambient environment are rejected.

### HOST-FR-002 — One-owner process lifetime

Hosting shall reserve capacity before spawn, attach every created process to
exactly one lease, converge natural exit and explicit cleanup on one exit
result, and reclaim the whole owned process tree.

Acceptance: success, spawn failure, early exit, cancellation, terminate, kill,
and host close have executable leak-free lifecycle cases.

Termination targets the whole owned process tree: request graceful tree
termination, wait one bounded OS-termination grace interval, kill the remaining
owned tree, reap it, close every process handle, and settle all waiters on the
same raw exit result. Cancellation or failure of an earlier step never skips a
reachable reclamation step.

### HOST-FR-003 — Inherited peer-endpoint ownership

Hosting shall create a local host/child byte-endpoint pair and transfer only the
child side through an explicit handle allowlist during spawn. This contract is
not a named/listening endpoint for later clients.

Acceptance: the host side is never inherited, unrelated ambient handles are
not inherited, each side closes its unused peer, and peer closure is observable
without interpreting an application protocol.

### HOST-FR-004 — Atomic child session

Hosting shall compose preparation, inherited peer-endpoint creation, process spawn,
handle transfer, and publication as one child-session transaction.

Acceptance: callers receive one process lease plus one host byte endpoint only
after both are usable; every failure path closes all created resources and the
preparation lease before propagating failure or cancellation.

### HOST-FR-005 — Neutral lifecycle observations

Hosting shall expose bounded, redacted observations for Hosting-owned facts:
backend identity, opaque host/session identity, lifecycle transition, exit
classification, and cleanup outcome.

Acceptance: observations contain no environment values and make no Policy,
Approval, containment, Plugin admission, protocol health, or domain publication
claim.

### HOST-FR-006 — Explicit platform support

Hosting shall select an exact platform backend and reject unavailable or
unproven required mechanics.

Acceptance: there is no silent substitution of TCP, semantic stdout, filesystem
address discovery, inherited ambient handles, or a weaker spawn/cleanup path.

## Quality Requirements

### HOST-QR-001 — Cancellation-safe cleanup

Cleanup of acquired resources shall settle before caller cancellation is
re-raised. Concurrent close calls shall share one idempotent owner operation.

### HOST-QR-002 — Bounded resource use

Hosts shall impose fixed owner-selected bounds on live/pending processes,
writes, diagnostic tails, endpoint buffers, shutdown time, and cleanup work.
Application frame and message limits remain outside Hosting.

### HOST-QR-003 — Least ambient authority

No child receives inherited credentials, descriptors/handles, cwd choice,
environment, endpoint, or network capability merely because Hosting can create
a process. Exact authority remains caller-owned and explicitly materialized.

### HOST-QR-004 — Product-neutral dependency direction

`loushang.hosting` shall have no import dependency on Harness, Coding, Plugin,
Agent, AI, Method, Work, Channel, TUI, or Product packages. An initial
implementation should use the standard library only; adding a Loushang
dependency requires a reviewed boundary change.

### HOST-QR-005 — Deterministic testability

Process, endpoint, clock/timeout, and failure seams shall support fake-backed
contract tests. Real-platform conformance tests supplement rather than replace
deterministic lifecycle tests.

### HOST-QR-006 — Exact portability evidence

POSIX and Windows backends shall each prove their own creation, inheritance,
closure, cancellation, and process-tree semantics. A platform name or common
interface alone is not conformance evidence.

## Constraints

- Python 3.11+ and the current asyncio execution model.
- Initial packaging remains one `loushang` distribution with a new top-level
  import package only after implementation begins.
- Current Harness public contracts and default-dark Worker behavior remain
  compatible during migration.
- Hosting is an in-process library, not a privileged daemon or security
  boundary against untrusted co-resident Python code importing it.

## Non-Goals

- general plugin/RPC framework or author SDK;
- process scheduler, service manager, remote executor, or cluster agent;
- Worker protocol, restart/adoption journal, Capability publication, or domain
  adapter;
- Policy, Approval, Sandbox policy, credential broker, or trust evaluator;
- durable process registry, PID reattachment, or live adoption in v1;
- AppServer listener/accept loops, connection authentication, or transport
  framing;
- global log, trace, session, cache, image, clipboard, or temporary-root owner;
- separate `loushang-hosting` distribution before independent demand exists.

## Design Acceptance Criteria

The design can enter implementation planning only when:

1. the top-level placement and dependency direction receive cross-scope review;
2. every requirement maps to one primary component and a planned gate;
3. process, endpoint, and joint-session ownership are distinct and complete;
4. security meanings retained by Harness are explicit;
5. POSIX and Windows uncertainties have narrow validation plans;
6. the compatibility and rollback boundary preserves Current Harness behavior;
7. the implementation-absence guard is replaced by slice-specific gates rather
   than simply deleted.
