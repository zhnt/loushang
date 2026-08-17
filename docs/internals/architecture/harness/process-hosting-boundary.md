# Harness Process Hosting Boundary

## Status

Status: H1 and H2 accepted for `lane/harness`.

This document defines the Product-neutral substrate for session-owned,
long-lived child processes. It does not make LSP a Harness concern.

## Decision

Harness owns the mechanics required to keep a bounded child process alive:

- a frozen, shell-free launch request;
- a raw byte stdin/stdout handle and a bounded stderr tail;
- fixed Host-owned process, read, write, stderr, and termination limits;
- pending-start reservations and atomic handle publication;
- process-group termination with kill fallback;
- natural-exit, failed-start, cancellation, and Session-fallback cleanup.

Products own executable admission, selection, protocol behavior, document
state, semantic tools, restart policy, and user-facing diagnostics. Coding LSP
therefore remains under `loushang.coding`; it consumes this substrate through a
narrow launcher binding.

This binding follows the
[Capability Variation And Replacement Boundary](capability-variation-and-replacement-boundary.md):
Coding may replace a Product-owned language-service provider and aggregate
server definitions, while Harness injects the authorized process capability.
Authorization, required containment, fixed Host limits, and cleanup remain an
invariant enforcement layer that a Coding provider or Plugin cannot replace or
bypass.

## Public Surface

`loushang.harness.workspace.process` exports only:

- `AuthorizedProcessLauncher`;
- `ProcessLaunchRequest`;
- `ProcessHandle`;
- `ProcessExit`;
- `ProcessStderrTail`.

`ProcessHost`, the local transport, the spawner seam, reservations, process
identifiers, and OS signaling remain Harness internals. There is no public
`ProcessBackend`, transport API, process event family, Host snapshot, daemon,
or RPC service. H1 publishes `AuthorizedProcessLauncher` only as the consumer
port. H2 provides its execution-scope binding without publishing the concrete
launcher or Host.

The launch request contains only the complete executable argv, an absolute
cwd, and a frozen effective environment. It cannot carry caller-selected
resource limits, shell text, LSP methods, restart settings, or approval policy.
Environment values are execution state and must not be projected into normal
status, audit, transcript, or approval text.

## Lifecycle Invariants

`ProcessHost` has `open -> closing -> closed` lifecycle semantics.

- A start reserves capacity before any asynchronous spawn work. Pending and
  published children consume the same fixed quota.
- `close()` rejects new reservations, cancels in-flight starts, reclaims any
  attached but unpublished child, and closes every published handle.
- A child that exits before publication cannot leave a phantom registration.
- Natural exit, `wait()`, `terminate()`, `close()`, and the internal finalizer
  share one exit result and one registration release.
- Host cleanup continues through terminate, kill, stream draining, and child
  settlement before caller cancellation is propagated.
- Close failures do not skip other children and leave the Host in `closed`
  state before an aggregate Host error is reported.

These are correctness requirements, not optional Product policy.

## Authorization And Sandbox Boundary

Process Hosting itself does not display or request approval. Interactive
approval is not an intrinsic cost of a Coding LSP launch. H2 binds one immutable
`ProcessExecutionScope` containing Policy, Approval, audit, and the effective
execution-profile ceiling. Every `start()` becomes a `process.host.start`
protected action with a `ProcessEffect`; automatic authorization for a
catalog-admitted built-in server is a Product/Host policy choice within that
ceiling, not a bypass around the gateway.

The concrete launcher freezes executable argv, cwd, and the complete effective
environment before Policy. Approval and audit receive argv plus a private
complete-launch fingerprint, never environment values. After authorization it
revalidates actor, launch fingerprint, abort state, and cwd admission before
asking Sandbox for a containment plan and delegating to `ProcessHost`. A Product
receives only `AuthorizedProcessLauncher`; it cannot call the Host directly.
Harness does not validate Coding catalog admission and does not import Coding.

Long-lived Sandbox ownership is intentionally not claimed by the H1 core. H2
implements the private seam as wrapped spawn material plus an owned idempotent
cleanup. A Sandbox backend may support hosted processes through a private
capability; this does not widen the public `SandboxBackend` Protocol. Required
containment fails before spawn. Best-effort containment falls back locally,
marks runtime status degraded, and emits one diagnostic.

The Process Host owns normal per-child cleanup. `SandboxExecutionRuntime` is the
Session fallback owner and closes in this order: Host, remaining containment
plans, then the one-shot Sandbox binding/backend. Cleanup continues after an
earlier failure, concurrent close calls share one task, and caller cancellation
is delayed until owned cleanup settles. Coding first disposes Product-owned
protocol capabilities, then invokes this fallback; a Product disposal error
remains primary if fallback cleanup also fails.

## Relationship To One-Shot Exec

`ExecService` remains a one-shot request/result service. Hosted processes do
not add `keep_alive` to `ExecRequest` and do not expose an `ExecService` handle.

The two paths share only local OS mechanics: shell-free spawn, a new process
session, and process-group termination. Their ownership and cancellation
contracts remain separate.

## Delivery State

H1 provides the neutral records, internal `ProcessHost`, local spawner, shared
OS helpers, private containment lifecycle seam, Fake Spawner tests, and a real
raw-stdio smoke test.

H2 provides:

- the execution-scope-bound authorized launcher;
- long-lived Sandbox containment planning and scope ownership;
- shared one-shot/hosted Bubblewrap command planning;
- Host-before-Sandbox runtime disposal with delayed cancellation;
- audit correlation and a private complete-launch fingerprint;
- Coding adapter cleanup that preserves the primary Product disposal error.

Deferred to Coding H3:

- binding the production launcher into the H3 LSP capability;
- LSP framing and protocol handlers;
- server definitions, admission, selection, and instance supervision;
- document synchronization and semantic tools;
- any restart, idle eviction, diagnostics inbox, or cross-Session pooling.
