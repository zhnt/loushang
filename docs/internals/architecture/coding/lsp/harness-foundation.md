# Harness Process Hosting Foundation For Coding LSP

[Coding LSP Architecture](README.md) | [Component Boundaries](component-boundaries.md)

## Status

Supporting design record. H1-H2 are implemented and accepted in the canonical
Harness [Process Hosting Boundary](../../harness/process-hosting-boundary.md).

This document preserves the rationale connecting that Product-neutral Harness
foundation to `coding.lsp`. Current Harness source, the Harness current owner
map, and accepted Harness boundary documents are authoritative. Coding consumes
the resulting narrow public port and must not copy the infrastructure into
`loushang.coding.lsp`.

Acceptance remains independent across lanes: this Coding design does not widen
or supersede the accepted Harness Process Hosting boundary.

## Decision

Harness needs a small, session-owned Process Hosting capability before active
Coding LSP becomes production-ready:

```text
Coding LSP
  -> AuthorizedProcessLauncher.start(request)
  -> ProcessHandle
  -> raw stdio while the process is alive
  -> Coding graceful LSP shutdown
  -> Harness terminate/kill fallback
```

The only Process Hosting port exposed to Coding is
`AuthorizedProcessLauncher`. `ProcessHost`, its registry, the authorized frozen
launch record, local spawn mechanics, sandbox process scope, and OS transport
remain Harness implementation details.

`ExecService` remains the one-shot API for shell commands, tests, formatters,
and other operations whose result is available only after process exit. It is
not widened with `keep_alive` or a union of `ExecResult` and live handles.

The ownership split is:

| Concern | Owner |
| --- | --- |
| OS process creation, raw stdio, fixed limits, process-group cleanup | Harness |
| One-time launch Policy decision and effective sandbox profile | Harness mechanism with Product policy |
| Session ownership and close-all fallback | Harness |
| Server catalog admission, pooling, readiness and restart decisions | Coding |
| LSP framing, JSON-RPC, documents, semantic results and code diagnostics | Coding |

Harness must not contain LSP methods, language-server definitions, document
versions, semantic query types, restart policy, or `CodeDiagnostic`.

## Functional Restraint

Active LSP P0 needs only:

- one authorized local process launch;
- raw byte stdin/stdout;
- continuously drained, bounded stderr;
- exit waiting and process-group termination;
- a fixed per-session process ceiling;
- current Sandbox enforcement without a bypass;
- cancellation-safe session cleanup.

It does not need:

- a public `ProcessBackend` or `ProcessTransport` abstraction;
- process ids used to recover handles across tool calls or RPC;
- Host-wide public snapshots;
- a generic process-event family;
- remote execution, daemon, Unix socket, or cross-session pooling;
- authority leases, authority generations, asynchronous revocation, or a new
  general authorization framework;
- workspace mutation events for active semantic queries.

Workspace mutation facts are a separate prerequisite for the later passive
edit-to-diagnostic feedback loop, not for the first active LSP vertical slice.

## Why Existing Harness Is Not Sufficient

Most substrate already exists:

| Existing capability | Reusable | Missing piece |
| --- | --- | --- |
| `workspace.exec.ExecService` | environment materialization, pipes, process groups, cancellation | returns only after exit and closes stdin |
| Policy/Approval | allow/deny/ask decisions, frozen actions, `ProcessEffect`, effective execution profile | narrow adapter; admitted P0 LSP launches default to non-interactive allow |
| Sandbox | execution-profile projection and backend selection | process scope held until the hosted child exits |
| Session lifecycle | replacement and disposal ordering | guaranteed async Product-close then ProcessHost fallback |
| Workspace mutation queue and `OrderedEventBus` | per-path serialization and typed ordered delivery | later typed post-commit mutation fact/source/sink |

The missing abstraction is an in-process owner for external OS child processes,
not an LSP daemon or a second RPC layer.

## Minimal Runtime Shape

```text
CodingLspBinding
  |
  +-- LspServerSupervisor              Coding pooling/readiness
  |      `-- LspClient                 Coding LSP/JSON-RPC
  |
  `-- AuthorizedProcessLauncher        only Product-visible Harness port
           |
           v
       ProcessHost                     session-owned internal owner
           |
           v
    sandbox-aware local spawn          Harness internal implementation
           |
           v
     OS child process + stdio
```

The Coding supervisor maps `(server_definition_id, canonical_root)` to its own
runtime. Harness does not interpret that key and does not provide lookup by a
public process id.

## Public Contract

### Placement

The proposed owner is a sibling of the existing one-shot execution package:

```text
src/loushang/harness/workspace/process/
  __init__.py
  types.py
  local.py
  host.py
```

The physical split is provisional. H1 should begin with the smallest files
that preserve the public boundary rather than pre-creating one module per
possible backend.

### Launch request

```python
@dataclass(frozen=True, slots=True)
class ProcessLaunchRequest:
    command: tuple[str, ...]
    cwd: str
    effective_environment: tuple[tuple[str, str], ...] = field(repr=False)
```

The environment rule is exact:

1. Coding decides the Product-approved baseline and explicit Server overrides.
2. Coding supplies the resulting complete effective environment.
3. Harness freezes that supplied snapshot once and does not read or merge
   `os.environ` again after the request crosses the boundary.
4. The complete environment is excluded from approval text, audit projection,
   diagnostics, status and model context.

Harness also freezes the argv and canonical absolute cwd. No shell expansion
is applied. The request carries no per-launch values that can enlarge Host
limits: stderr capacity, maximum write size, process count and termination
grace are fixed by session-owned Harness configuration.

`ExecRequest` and `ProcessLaunchRequest` are separate public contracts because
one returns an `ExecResult` while the other returns a live handle. Their local
materialization, process-group and termination mechanics must use the same
internal helpers; H1 must not add another general workspace-process lifecycle
implementation. Specialized bounded probes such as package materialization's
`git ls-remote` remain explicit one-shot exceptions and are not Process Hosting
reuse targets.

### Authorized launcher

```python
class AuthorizedProcessLauncher(Protocol):
    async def start(
        self,
        request: ProcessLaunchRequest,
        *,
        correlation_id: str,
        signal: object | None = None,
    ) -> ProcessHandle: ...
```

This is the sole Process Hosting port injected into Coding. The launcher is
bound at construction to one immutable execution scope containing the actor,
Policy evaluator, Approval resolver, audit sink, execution environment and
`EffectiveExecutionProfile` ceiling. Those values are not supplied by the
model or repeated in every launch request. `correlation_id` associates the
launch with the initiating Coding operation/tool call without changing the
authorized effect.

One `coding.lsp` binding receives one scope-bound launcher. All Server runtimes
owned by that binding use the same scope, and runtime-profile replacement must
dispose the complete binding before a launcher with a different scope is
installed. Therefore `LspServerKey` does not need a profile identity in P0. If
future pooling crosses an execution-scope boundary, the pool key must include
that immutable scope identity.

The launcher owns this operation:

```text
freeze the neutral process effect and private launch fingerprint
  -> current Product-selected Policy decision
  -> resolve current EffectiveExecutionProfile
  -> reserve one pending OS start in ProcessHost
  -> prepare Sandbox containment when enabled
  -> spawn and register with ProcessHost
  -> return ProcessHandle
```

Coding has already admitted the Server definition before calling this port.
Harness neither validates nor claims knowledge of Product admission; it
authorizes only the exact Product-neutral process effect presented to it.

For P0, Coding selects a policy profile that silently returns `allow` for its
explicitly configured or Product-default, admitted Server definitions. The
launch still passes Policy, profile-ceiling, Sandbox, fingerprint and audit
checks, but does not open an interactive approval prompt. `ask` remains
available to user policy and future project/extension-contributed definitions;
`deny` still fails closed. A replacement process is evaluated again, but an
unchanged admitted launch normally remains non-interactive.

If spawn succeeds but registration or cancellation wins before publication,
the launcher terminates the child and closes the sandbox scope before returning.
There is no raw spawner in `ToolCallContext` and Coding cannot construct an
authorized launch token.

### Process handle

```python
class ProcessHandle(Protocol):
    async def read_stdout(self, max_bytes: int = 64 * 1024) -> bytes: ...
    async def write_stdin(self, data: bytes) -> None: ...
    async def close_stdin(self) -> None: ...
    async def wait(self) -> ProcessExit: ...
    async def terminate(self) -> ProcessExit: ...
    async def close(self) -> None: ...
    def stderr_tail(self) -> ProcessStderrTail: ...
```

Required semantics:

- stdout remains raw bytes; Harness never calls `readline()`, decodes it, or
  assumes one read equals one protocol message;
- the handle is a single-consumer byte transport. Coding owns the only stdout
  reader task and the only protocol writer task;
- Harness resolves write/close/exit races but does not add a second LSP frame
  lock or request dispatcher;
- stderr is drained for the entire process lifetime into a fixed bounded tail;
- stdout is neither broadcast nor retained by Harness; OS pipe backpressure
  applies if Coding stops reading;
- `terminate` addresses the process group, waits for the Host-fixed grace
  period, then escalates to kill internally;
- `close` is idempotent and cannot leave an owned child or stderr task alive;
- cancelling one LSP request does not close the shared handle. Coding maps that
  cancellation to `$/cancelRequest`.

P0 does not expose `process_id`, `kill`, `snapshot`, output subscriptions, or
generic process events. A later real consumer may justify those additions.

## Internal ProcessHost

`ProcessHost` is a session-composition owner, not a Product dependency. It
maintains bounded private pending reservations and live registrations and
provides the final close-all safety net. Its state machine is:

```text
open -> closing -> closed
```

A start reserves capacity while the Host is `open`, after the Policy decision
and immediately before Sandbox containment planning can acquire OS resources.
Reservations count against the fixed process ceiling. Host close atomically
changes the state to `closing`, rejects new reservations, cancels and awaits
every pending contained start, then closes every live registration.
It reaches `closed` only after all reservation rollback and registration
cleanup has settled.

Policy evaluation or an exceptional interactive approval wait is owned by the
existing authorization/session lifecycle, not `ProcessHost`, and does not
consume process quota. After Policy returns, the launcher must acquire a live
Host reservation before containment or spawn; a closed Host therefore prevents
a late authorization result from creating a process.

As a pending start acquires a Sandbox containment scope or OS child, it attaches
that resource to its reservation before continuing. Close can therefore clean
an unpublished child/scope at every race point. The start path rechecks its
live reservation immediately before OS spawn and before publishing the handle.

Each registration atomically owns:

```text
OS transport
stderr drain task and bounded tail
optional Sandbox process scope
exit state
```

Normal close order is child process, stderr task, then Sandbox scope. The
Sandbox service remains an outer fallback, but normal Session disposal must
close `ProcessHost` before closing the Sandbox service.

Every registration also owns one exit finalizer. Natural exit, crash,
`wait()`, `terminate()`, `close()`, and Host shutdown converge on one
single-assignment `ProcessExit`. The finalizer drains/settles stderr, closes the
Sandbox scope, removes the registration and releases quota exactly once.

The local implementation must extract and reuse an internal
`LocalProcessSpawner`/process-group helper with `ExecService`. Public one-shot
and live-process contracts remain separate; only the OS mechanics are shared.
An internal spawn callable may be injected for deterministic tests. This does
not establish a public multi-backend platform.

## Authorization Boundary

Catalog admission and launch authorization remain separate:

- Coding selects a previously admitted Server definition and supplies its
  immutable launch request;
- the scope-bound Harness launcher declares the existing neutral
  `ProcessEffect`, evaluates current Policy, resolves the effective
  profile and starts exactly that process;
- the model never supplies command, cwd, environment or execution profile.

Authorization permits one spawn. The fingerprint is retained only for audit
correlation. It is not a continuing authority lease and P0 has no authority
generation or asynchronous revocation model.

The existing `ProcessEffect(command)` remains the neutral capability/policy
classification; P0 does not widen every Tool effect merely for Process Hosting.
The process-launch adapter additionally computes a private immutable launch
fingerprint over the exact executable/argv, canonical cwd and complete effective
environment, and revalidates it immediately before OS spawn. Environment values
are excluded from approval text and audit projection, but remain part of this
consistency check; only the opaque fingerprint may be recorded. Actor,
correlation id, effective profile and approval outcome are included in the
normal scoped audit context, not in the model-visible request.

The resulting OS process continues under the filesystem/network restrictions
actually enforced by its Sandbox/host environment. Replacing or restarting the
process consumes a new launch authorization under current policy. Authorization
does not imply an interactive approval: an `allow` decision is silent.

The current gateway requires a tool-shaped action name and emits tool-prefixed
audit event types. H2 uses the neutral compatibility action name
`process.host.start`; it is not a model-visible tool. This is an internal adapter
over the existing gateway, not a reason to generalize the approval framework or
rename the audit event family in P0.

H2 should implement a narrow process-launch adapter over the existing action
gateway. It must not make a broad generic protected-action refactor a launch
prerequisite. Such extraction is reconsidered only after another non-tool
protected action requires it.

## Sandbox Integration

There is one hosted-process spawn implementation, not parallel
`ProcessBackend.spawn` and `SandboxProcessScope.spawn` APIs. The existing
one-shot `SandboxExecBackend` remains a separate consumer path because it
returns an `ExecResult`; both paths reuse the same internal spawn/process-group
mechanics rather than duplicating OS process code.

The current public `SandboxScope` and `SandboxExecBackend` are one-shot
`ExecRequest -> ExecResult` contracts and cannot host a live transport. H2 must
not pretend otherwise or widen them into a public live-process API. Harness
session composition instead binds the launcher to this private, testable seam:

```text
frozen authorized request
  -> internal Sandbox containment planner
  -> containment plan (wrapped spawn material + owned cleanup)
  -> shared LocalProcessSpawner
  -> live transport attached to the Host reservation
```

The planner reuses existing Sandbox profile projection and backend-specific
command/root/network builders. Its containment plan supplies the exact spawn
material and an idempotent close operation; it is not a public
`SandboxProcessScope` or `ProcessBackend`. When Sandbox is required, planning
must establish enforceable containment or fail before any OS spawn. When a
scope/plan has been acquired, the Host reservation owns it through spawn
failure, cancellation, natural exit, explicit close and Session fallback.

If sandboxing is required and the selected backend cannot host a live process,
launch fails before spawn. Best-effort degradation follows the existing
truthful Sandbox status and diagnostics; it never claims enforcement.

H2 extracts the existing module-private Linux bubblewrap command/root/network
builder into a shared internal helper used by both one-shot and hosted-process
containment. It does not make that helper public. The new implementation work
is lifetime ownership, not a second Sandbox registry.

## Session Lifecycle

The current lifecycle does not automatically satisfy the required ordering:
`before_release` can fail before the session disposer runs. Runtime-profile
capability disposal already supports async disposers; the later capability-
composition disposal is the separate synchronous mechanism. H2 must attach to
the existing async Product session/runtime-profile disposal chain rather than
`before_release`, the synchronous composition disposer, or a new lifecycle
coordinator.

Required shape:

```python
async def dispose_product_session() -> None:
    product_error = await capture_error(
        coding_lsp_binding.dispose(),  # shutdown, exit, bounded wait
    )
    host_error = await close_process_host_delaying_cancellation()
    sandbox_error = await close_sandbox_runtime()
    raise_preserving_primary(product_error, host_error, sandbox_error)
```

The required order is `CodingLspBinding.dispose -> ProcessHost.close ->
SandboxExecutionRuntime.close`. Caller cancellation is recorded but not
propagated until Host close has cancelled/settled pending starts, terminated or
killed children, joined stderr/finalizer tasks and closed their scopes. A bare
`asyncio.shield()` is insufficient because its caller can observe cancellation
while the cleanup task still runs. Repeated cancellation must not skip a later
cleanup phase.

The original Product disposal exception remains the primary failure. Host or
Sandbox cleanup failures are attached/aggregated and emitted as operational
diagnostics rather than replacing it. The same rule preserves cancellation
after cleanup completes.

This path must cover normal quit, replacement, failed activation and host
shutdown. There is one `ProcessHost` per live Harness session composition and
no module-global registry or cross-session pool.

Session construction must register the Host cleanup fallback before any Product
activation can launch a process. If capability/session activation fails after
partial composition, rollback still executes `ProcessHost.close()` before
Sandbox runtime close.

## Concurrency Invariants

Harness guarantees:

1. Host state advances only `open -> closing -> closed`;
2. pending reservations and live registrations share one fixed process quota;
3. close rejects new reservations and awaits rollback of every pending start;
4. containment planning, spawn and registration publish resources through the
   reservation so close can clean every intermediate state;
5. natural exit, wait, terminate, close and finalization settle one exit result;
6. natural exit releases the registration, Sandbox scope and quota;
7. launch cancellation leaks neither a child, task nor Sandbox scope;
8. stderr memory and individual byte writes have Host-fixed bounds;
9. session cleanup cannot be skipped by Product disposal failure/cancellation.

Coding guarantees:

1. startup for one `(definition_id, root)` is single-flight;
2. exactly one LSP reader consumes stdout;
3. exactly one LSP writer preserves complete JSON-RPC frames;
4. the reader parses partial/coalesced frames and routes responses by id;
5. request count is bounded and document changes are ordered per document;
6. restart and readiness remain Product decisions.

## Status And Diagnostics

P0 adds no generic process event family or Host-wide snapshot API.

`ProcessHandle.wait()` supplies exit facts and `stderr_tail()` supplies bounded
debug context. Coding combines those with its own Server id, root, readiness,
request metrics and restart state for `lsp status`/`doctor`. Harness records
spawn, Sandbox and cleanup failures through existing operational diagnostics
without publishing stdio payloads, source content, inherited environment or
complete command arguments.

## Follow-On Passive Feedback Contract

Active semantic queries always resynchronize their target from disk before a
request. They do not depend on workspace mutation delivery.

The later passive edit-to-diagnostic loop needs only these neutral contracts:

```python
@dataclass(frozen=True, slots=True)
class WorkspaceMutationFact:
    mutation_id: str
    path: str
    kind: Literal["created", "updated"]
    path_sequence: int
    occurred_at: datetime


class WorkspaceMutationSink(Protocol):
    def publish(self, fact: WorkspaceMutationFact) -> None: ...


class WorkspaceMutationSource(Protocol):
    def subscribe(
        self,
        listener: Callable[[WorkspaceMutationFact], object],
    ) -> Callable[[], None]: ...
```

Session composition may implement sink/source with the existing
`OrderedEventBus`; no new `WorkspaceMutationHub` or mandatory runtime-event
projection is introduced.

Initial producers are the single-path Harness write/edit operations. A fact is
enqueued only after a successful commit and before releasing same-path ordering.
Denied, failed or aborted operations publish nothing. Publication failure after
a committed write is recorded as an operational diagnostic and does not turn
the write into a retryable failure. Delete, move, multiple paths, actor, content
hash, shell detection and file watching wait for real producers/consumers.

This contract is H4 and does not block H1-H3.

## P0 And Deferred Capabilities

Active LSP P0 uses lazy start. A process remains alive until crash, explicit
stop, or Session close. A crash fails current pending requests; a later demand
may start a replacement through a new authorization.

Deferred until after the active feedback loop is measured:

- workspace warm-up;
- idle eviction;
- automatic restart/backoff;
- live catalog generation migration;
- generic process events and Host snapshots;
- remote Process Hosting, daemon/RPC transport and cross-session sharing;
- passive mutation feedback, watcher coverage and Server-initiated actions.

A live `ProcessHandle` is runtime state and never an App/Channel wire value.

## Testing Contract

Harness tests require no real language server. H1 provides an internal fake
spawn callable plus a tiny local helper process.

Required H1-H2 tests:

- argv/cwd/effective environment are frozen once and shell strings rejected;
- the private launch fingerprint changes with executable, argv, cwd or any
  effective-environment entry while audit projection reveals no environment;
- a scope-bound launcher preserves actor, correlation, audit and execution-
  profile ceiling, and profile replacement cannot reuse an old runtime;
- raw stdout preserves partial and coalesced byte boundaries;
- bounded stderr is drained while the process lives;
- exit/terminate/close races settle once;
- spawn failure, cancellation and failed registration leak no child/scope;
- close racing with containment planning, spawn and registration rolls every
  reservation back;
- concurrent pending/live starts never exceed the fixed Host ceiling;
- natural exit releases its registration, containment scope and quota;
- a Policy result arriving after Host close cannot reserve or spawn;
- fixed process/write/stderr ceilings cannot be enlarged by a Product request;
- required and best-effort Sandbox behavior for whole process lifetime;
- restart consumes a new authorization;
- Product shutdown failure/cancellation still reaches Host close;
- partially composed activation failure still reaches Host close before
  Sandbox close;
- Session disposal leaves no child, stderr task or Sandbox scope.

Coding tests use the fake launcher to prove LSP framing, single-reader routing,
initialization, request cancellation, document synchronization and clean
degradation. Initialization failure must close the returned handle and leave no
Coding runtime entry.

H4 separately tests successful-only, same-path ordered mutation delivery and
post-commit publisher failure.

## Delivery Slices

### H1. Process Hosting core

- add `ProcessLaunchRequest`, `ProcessHandle`, `ProcessExit` and bounded stderr
  tail values;
- implement internal `ProcessHost`, fixed limits and local asyncio transport;
- implement `open -> closing -> closed`, pending reservations, natural-exit
  finalization and exactly-once quota release;
- extract shared local spawn/process-group helpers used by `ExecService` and
  Process Hosting;
- provide internal fake spawn tests; expose no public backend platform.

### H2. Authorized and contained launch

- implement `AuthorizedProcessLauncher` over the existing action gateway and
  `ProcessEffect` without a broad authorization refactor; bind it to one
  immutable execution scope and privately fingerprint complete launch material;
- bind the private containment-plan seam, single Sandbox-aware spawn path and
  atomic process/scope ownership;
- extract the existing bubblewrap plan builder into a shared internal helper;
- integrate ordered Product/Host/Sandbox cleanup into the existing async
  runtime-profile disposal path;
- delay cancellation through Host convergence and preserve the primary Product
  disposal error;
- add only operational failure diagnostics required to explain launch/cleanup.

Only H1-H2 are Harness prerequisites for active production LSP.

### H3. Active Coding LSP

- implement lazy catalog selection, supervisor, client and pre-query full-text
  document synchronization;
- ship bounded active semantic tools and read-only status/doctor;
- on crash, fail current requests and allow the next demand to reauthorize and
  start a replacement;
- do not add warm-up, idle eviction, automatic backoff or model-visible passive
  diagnostic delivery.

### H4. Passive diagnostic feedback

H4.1 is Coding-only bounded reception and lifecycle cleanup; it needs no new
Harness contract. H4.2 completes the feedback loop:

- add the minimal mutation fact/source/sink over `OrderedEventBus`;
- integrate successful Harness write/edit commits;
- connect ordered document synchronization and bounded diagnostic delivery;
- retain pre-query disk reconciliation for uncovered mutation sources.

## Acceptance Gates

H1-H2 are sufficient when:

- production Coding has only `AuthorizedProcessLauncher`, never a raw spawner;
- no LSP module calls `asyncio.create_subprocess_exec` directly;
- `ExecService` remains one-shot and shares internal OS mechanics;
- every start passes current Policy and effective Sandbox enforcement; admitted
  P0 LSP definitions default to a silent `allow`, not interactive approval;
- actor/correlation/audit/profile ceiling are bound by the launcher's immutable
  execution scope;
- authorization, containment, spawn, register, exit, cancel and close races are
  quota-safe and leak-free;
- Product cleanup failure or caller cancellation cannot skip bounded Host
  cleanup, and cleanup errors do not replace the primary failure;
- partial activation rollback closes the Host before Sandbox teardown;
- Session disposal leaves no process or task behind;
- Harness imports no Coding or LSP module;
- no public backend, remote, process-event, snapshot or authority-lease API is
  introduced in P0;
- focused Harness, Sandbox, lifecycle, architecture and Coding tests pass.

H4 has an independent acceptance gate: passive diagnostics consume only typed,
successful mutation facts and remain bounded. Active LSP correctness cannot
depend on that gate.

## Rejected Alternatives

### Reuse `ExecService` with a `keep_alive` flag

Rejected because one-shot results and live stream ownership have incompatible
stdin, capture, cancellation and cleanup semantics.

### Put process spawning in `coding.lsp`

Rejected because it duplicates authorization, Sandbox and lifecycle cleanup.

### Put LSP protocol code in Harness

Rejected because LSP methods, documents and code diagnostics are Coding
semantics.

### Add public backend/remote/process-event APIs in P0

Rejected until a second real consumer proves the contract. Test fakes are
internal injection points, not production backend evidence.

### Add a daemon or share a Server across Sessions in P0

Rejected because Session ownership already supplies the required lifetime and
cross-session sharing would couple overlays, authority and cleanup.
