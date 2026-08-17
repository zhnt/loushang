# Sandbox Runtime Boundary

Status: Phases A-C implemented; additional native backends remain proposed

Owner: `loushang.harness`

Related:

- [Harness Workspace Execution Boundary](workspace-execution-boundary.md)
- [Policy And Approval Redesign](policy-approval-redesign.md)
- [Product Runtime Injection Architecture](product-runtime-injection/README.md)

## 1. Decision

Harness owns a product-neutral, protocol-based sandbox runtime for process
execution. Session/runtime composition owns `SandboxService` and injects its
execution backend into `ExecService`. Products, tools, and child Agents
continue to consume `ExecService`; they do not select operating-system
implementations or contain platform branches.

The first implementation is an in-process runtime service, not a daemon. Its
runtime call path is:

```text
Product / tool / child Agent
          |
          v
authorization runtime
          |
          v
ExecService
          |
          v injected ExecBackend
SandboxExecBackend
          |
          v
SandboxService -> selected SandboxBackend
          |
          v
restricted child process
```

The module dependency direction is different from the runtime arrows:

```text
loushang.harness.sandbox
  -> loushang.harness.workspace.exec

loushang.harness.session composition
  -> both packages
```

`workspace.exec` must not import `sandbox`. Sandbox implements an
`ExecBackend`, and session/runtime composition injects that implementation into
`ExecService`.

The word "service" describes an object with status, scope ownership, and
cleanup. It does not require an independently installed background process.
A future daemon client may implement the same protocol without changing
callers.

Sandboxing is optional and disabled by default. An absent sandbox
configuration behaves like Claude Code's default: normal execution continues
through the existing local `ExecService` and semantic Policy remains active.
Enabling a sandbox must not by itself cause routine sandboxed commands to ask
for approval. It also does not imply network isolation: a scope retains the
host network namespace unless an authorized scope profile explicitly requests
`restricted` or `denied` network access. Consequently ordinary `git`, `gh`,
`curl`, dependency lookup, and similar development commands are not disabled
merely because sandboxing was enabled.

Coding exposes the common settings through the standard layered settings file:

```json
{
  "sandbox": {
    "enabled": true,
    "requirement": "best_effort"
  }
}
```

Omitting `sandbox`, or leaving `enabled` false, preserves the exact injected
`ExecService` object and does not probe the host or construct a backend.

## 2. Scope

The runtime covers processes launched through the common Harness execution
path, initially:

- shell commands;
- Python and other interpreters launched as subprocesses;
- formatters, test runners, compilers, and local Git commands;
- process-based tools used by root and child Agents.

Later consumers may include long-lived language kernels and locally launched
MCP servers. They must enter the sandbox when their process is created.

The runtime does not:

- classify command intent;
- decide whether an action requires approval;
- create Git worktrees or branches;
- authorize secrets, publication, deployment, or privilege escalation;
- make in-process Python file APIs safe;
- provide durable or remote execution in phase one.

Strict containment of an in-process tool requires moving that tool into a
child process. Monkey-patching Python APIs is not a sandbox.

## 3. Default And Failure Semantics

The common settings shape is deliberately small:

```python
SandboxRequirement = Literal["best_effort", "required"]

@dataclass(frozen=True)
class SandboxSettings:
    enabled: bool = False
    requirement: SandboxRequirement = "best_effort"
```

`enabled=false` with `requirement="required"` is invalid configuration.
Requirement is resolved once by managed/Product/user configuration before the
service is constructed. A scope caller cannot weaken it.

The state table is:

| Configuration | Backend state | Result |
|---|---|---|
| omitted or `enabled=false` | any | sandbox disabled; execute normally |
| `enabled=true`, `best_effort` | available | sandbox enabled |
| `enabled=true`, `best_effort` | unavailable | warn once and execute without sandbox |
| `enabled=true`, `required` | available | sandbox enabled |
| `enabled=true`, `required` | unavailable | fail activation or execution before spawn |

The same rule applies if initial probing succeeds but backend initialization,
scope creation, or enforcement of a requested capability fails:

- `best_effort` creates a scope explicitly described as `degraded`, records one
  diagnostic, and delegates to the local execution backend;
- `required` fails before the requested process is spawned;
- no failure path reports partial enforcement as a successful sandbox.

The fallback is explicit in runtime status and diagnostics. Policy must never
mistake a disabled or degraded sandbox for enforced containment.

Managed configuration may require sandboxing. Product and session layers may
narrow managed settings but cannot turn `required` into `best_effort` or
disable a managed-required sandbox.

## 4. Separation From Policy And Approval

The three layers answer different questions:

| Layer | Question |
|---|---|
| Policy | May this actor attempt this action? |
| Approval | May a reviewer grant this bounded exception? |
| Sandbox | What can the resulting process actually access? |

The execution order is:

```text
materialize ExecRequest
  -> canonicalize ActionRequest
  -> evaluate Policy and resolve Approval when required
  -> produce one validated effective permission profile
  -> derive and open a bounded SandboxScopeRequest
  -> verify the same action snapshot against actual scope enforcement
  -> execute through the scope
  -> publish result and audit facts
```

Approval may authorize a wider requested scope only within the managed and
Product ceilings. It does not switch off a required sandbox. Conversely, a
sandbox does not make destructive, publishing, secret-bearing, or privileged
intent safe; those gates remain Policy concerns.

The post-open verification is not a second policy engine. It confirms that the
action snapshot has not changed and that the scope actually enforces the
already-authorized permission profile. Sandbox code performs structural path,
scope, and backend-capability validation; it does not classify semantic intent.

## 5. Public Protocols

The following examples define the intended contract, not final source syntax.

### 5.1 Service

```python
class SandboxService(Protocol):
    def status(self) -> SandboxStatus: ...

    async def open_scope(
        self,
        request: SandboxScopeRequest,
    ) -> SandboxScope: ...

    async def close(self) -> None: ...
```

One enabled service is bound to a session composition. It owns backend
initialization and all scopes created through it. Disabled composition records
disabled status without constructing a platform backend.

### 5.2 Scope

```python
class SandboxScope(Protocol):
    @property
    def descriptor(self) -> SandboxScopeDescriptor: ...

    def __call__(
        self,
        request: ExecRequest,
        *,
        signal: object | None = None,
        on_update: ExecUpdateCallback | None = None,
    ) -> Awaitable[ExecResult] | ExecResult: ...

    async def close(self) -> None: ...
```

`SandboxScope.__call__` intentionally matches the existing callable
`ExecBackend` shape. It is not a second execution API.

The current inline local subprocess path should be extracted as a reusable
local execution backend before sandbox integration. A degraded scope delegates
to that backend; an enforcing scope wraps or replaces its process launch.
Tools must not gain a second subprocess path.

Composition injects one session-owned `SandboxExecBackend` into `ExecService`.
For each call it derives a scope request from the immutable, already-authorized
execution profile plus the materialized request, opens one scope, calls it, and
closes it in `finally`:

```text
ExecService.execute(materialized request)
  -> SandboxExecBackend.__call__
  -> SandboxService.open_scope
  -> SandboxScope.__call__
  -> SandboxScope.close
```

With omitted or disabled configuration, composition uses the extracted local
execution backend directly and does not initialize `SandboxService`.

### 5.3 Backend

```python
class SandboxBackend(Protocol):
    backend_id: str

    def probe(
        self,
        environment: HostEnvironment,
    ) -> SandboxBackendStatus: ...

    async def open_scope(
        self,
        request: SandboxScopeRequest,
    ) -> SandboxScope: ...

    async def close(self) -> None: ...
```

Backends are created per session by the registry and are exclusively owned by
their `SandboxService`. External callers do not close a backend directly.
`SandboxService.close()` closes remaining scopes and then its backend.

Platform implementations may use different native mechanisms while preserving
the common scope contract:

```text
LinuxBubblewrapBackend
MacOSSeatbeltBackend
WindowsRestrictedTokenBackend
```

Phase one does not require every backend to implement the same optional
features. `probe()` reports capabilities; scope construction rejects a
required capability that the selected backend cannot enforce.

### 5.4 Requests And Status

```python
NetworkAccess = Literal["denied", "restricted", "allowed"]

@dataclass(frozen=True)
class SandboxScopeRequest:
    cwd: Path
    readable_roots: tuple[Path, ...]
    writable_roots: tuple[Path, ...]
    denied_roots: tuple[Path, ...]
    network: NetworkAccess

@dataclass(frozen=True)
class SandboxStatus:
    state: Literal["disabled", "enabled", "degraded", "unavailable"]
    backend_id: str | None
    enforced_capabilities: frozenset[str]
    reason: str | None = None

@dataclass(frozen=True)
class SandboxScopeDescriptor:
    state: Literal["enforcing", "degraded"]
    backend_id: str | None
    enforced_capabilities: frozenset[str]
    reason: str | None = None
```

Environment values and secrets are not duplicated into scope descriptors,
diagnostics, approval records, or transcripts. Environment materialization
continues to use the existing `ExecRequest.effective_environment` boundary.

The initial request deliberately avoids a general capability language. Add a
new field only when a real backend and consumer require a portable semantic.

## 6. Host Environment Detection

### 6.1 One shared fact model

OS detection is a Harness fact source, separate from backend selection:

```python
OperatingSystemFamily = Literal["linux", "macos", "windows", "other"]

@dataclass(frozen=True)
class HostEnvironment:
    os_family: OperatingSystemFamily
    platform_name: str
    architecture: str
    is_wsl: bool

class HostEnvironmentProbe(Protocol):
    def detect(self) -> HostEnvironment: ...
```

`LocalHostEnvironmentProbe` reads injected values when supplied and otherwise
uses `sys.platform`, `platform.machine()`, and a small set of environment or
host markers. Detection is pure and side-effect free.

### 6.2 Reuse of existing code

Harness does not currently have one general host-environment detector.
Existing code provides useful patterns:

- `harness.tools.workspace.external_tools` already accepts an injected
  `platform_name` and architecture for deterministic binary selection;
- several filesystem modules isolate their Windows checks behind small
  helpers;
- Native TUI has richer terminal-environment detection, including WSL, but
  that model also contains terminal-specific facts.

The sandbox design reuses the injected-value pattern and the existing
`sys.platform` vocabulary. It does not import Native TUI into Harness, and it
does not make sandbox code depend on the workspace external-tool downloader.
The new minimal `HostEnvironmentProbe` may later replace duplicated Harness
OS checks where doing so is an independently justified cleanup.

Terminal capability detection remains TUI-owned. Host environment detection
must not absorb terminal protocols, clipboard behavior, or rendering facts.

### 6.3 Static facts versus backend health

The host probe reports where the process is running. Each backend reports
whether its mechanism actually works there:

```text
HostEnvironmentProbe
  -> Linux, x86_64, WSL

LinuxBubblewrapBackend.probe()
  -> bwrap present
  -> user namespaces available
  -> seccomp available or unavailable
  -> backend supported or unavailable with reason
```

This distinction is required because the same OS may differ by installed
dependencies, kernel settings, WSL version, nesting restrictions, or managed
policy.

## 7. Backend Selection Without Scattered OS Branches

Callers never select a platform backend. A registry performs selection once
during runtime composition:

```python
class SandboxBackendRegistry:
    def resolve(
        self,
        environment: HostEnvironment,
    ) -> SandboxBackendResolution: ...
```

The default registry contains lazy backend factories. Each factory is safe to
inspect on every platform and its backend `probe()` returns
`not_applicable`, `available`, or `unavailable`. Applicability is explicit:

| Host | Applicable backend |
|---|---|
| Linux, including WSL | Linux bubblewrap |
| macOS / Darwin | macOS Seatbelt |
| native Windows | Windows restricted token |
| other | no default backend |

The implemented default registry currently contains only the lazy Linux
bubblewrap registration. Its scope starts from a minimal runtime filesystem
view, adds explicit readable directory roots, overlays explicit writable
directory roots, and applies denied-root masks last. `/dev` and `/proc` are
fresh mounts; `/tmp` is private unless an explicit root intersects it.

Phase B deliberately accepts directory roots only. It rejects missing roots,
missing denied paths below an admitted root, or contradictory cwd/root/deny
requests rather than reporting partial enforcement. A `restricted` network
request is narrowed to an isolated network namespace until a managed proxy
backend exists; `allowed` retains the host network namespace. These are
explicit first-backend limits, not portable decisions embedded in callers.
`SandboxScopeRequest.network` defaults to `allowed`; network restriction is an
explicit policy decision, not a side effect of constructing a sandbox.

The registry probes health only for applicable candidates. This keeps
"unsupported platform" distinct from "supported platform with missing
dependencies or kernel capabilities".

```text
runtime composition
  -> HostEnvironmentProbe.detect()
  -> SandboxBackendRegistry.resolve(environment)
  -> LocalSandboxService(selected backend)
  -> SandboxExecBackend(service, authorized scope profile)
  -> ExecService(backend=SandboxExecBackend)
```

There is one selection boundary. Bash, Python, Coding, child Agents, TUI, and
Product packages contain no `if linux / if darwin / if windows` sandbox
branches. Backend modules may contain their own native implementation details.

This registry is not a plugin marketplace or dynamic package loader in phase
one.

## 8. Process And Session Lifecycle

`SandboxService` is session-owned for interactive Agent work. The registry
creates one backend for that service; the service is its sole lifecycle owner:

```text
session create
  -> resolve settings
  -> detect host
  -> initialize service if enabled

each tool or child process execution
  -> open bounded scope
  -> execute the admitted process and its descendants
  -> close scope in finally

session replace / resume / exit
  -> close remaining scopes
  -> terminate owned helper processes
  -> close service
```

The initial implementation uses exactly one scope per `ExecService.execute()`
call. A reusable
child Agent reuses its session and service across rounds, but each process
execution receives a fresh scope. Long-lived language-kernel scope reuse is
deferred until it has a concrete consumer and lifecycle tests.

Cleanup is idempotent. Closing a scope terminates sandbox-owned helpers and
processes according to the existing execution cancellation contract. Session
disposal closes leaked scopes and then the backend as a final safety net; TUI
presentation does not own cleanup.

## 9. Multi-Agent And Workspace Binding

The Product resolves the child workspace lease before requesting a sandbox
scope:

```text
shared workspace or isolated worktree/branch lease
  -> execution_ref
  -> SandboxScopeRequest roots
  -> child execution scope
```

Workspace provisioning and Git handoff remain separate Harness workspace
capabilities. The sandbox consumes canonical roots; it does not create,
commit, merge, apply, or clean worktrees.

A child scope is derived from the parent's authorized ceiling plus the child
role:

```text
parent ceiling
  intersect Product child policy
  intersect AgentTypeSpec execution policy
  intersect workspace lease roots
  -> child SandboxScopeRequest
```

Children cannot receive a broader effective scope than their delegation
permits. Whether child sessions are persistent remains a Product/session
decision, not a sandbox decision.

The first Coding binding derives scopes as follows:

| Session/role | Read root | Write root |
|---|---|---|
| root Coding session | current workspace | current workspace |
| explorer/reviewer/debate roles | resolved child workspace | none |
| shared implementation worker | current shared workspace | current shared workspace |
| isolated implementation worker/test runner | acquired worktree | acquired worktree |

Coding resolves a workspace lease before constructing a child session. Each
child then owns its own `SandboxExecutionRuntime`; it does not reuse the
parent's live scope. Coding also discovers the current repository through the
existing Harness Git metadata helper. For linked worktrees it exposes the
specific worktree/common Git metadata directories with the same read-only or
writable role boundary as the session, without mounting the user's whole home
directory.

Phase C retains the host network namespace for enabled Coding scopes. This
keeps normal `git`, public or already-authenticated `gh`, `curl`, and package
metadata access available. The sandbox does not invent credentials or mount a
whole credential directory: authenticated commands continue to use credentials
already admitted through the process environment or a future Policy grant.
When sandboxing is disabled, the exact pre-sandbox Coding execution service and
network behavior remain unchanged.

## 10. Runtime Capability Binding

The service fits the existing Product runtime composition model as one
exclusive runtime capability:

```text
slot: execution.sandbox
shape: exclusive
scope: session
refresh_boundary: sealed
required: false
```

The default selection preserves the existing local `ExecBackend` and does not
construct a sandbox service. An enabled Product/user configuration selects the
automatic local sandbox implementation; a managed layer may require an
enforcing implementation.

An enabled binding carries a live `SandboxService`; a disabled binding carries
only disabled status and the existing local execution backend. Profiles and
transcripts retain only JSON configuration and stable backend/status
identifiers, never live objects, helper PIDs, native handles, or credentials.

The concrete Phase C binding is `SandboxExecutionRuntime`. It is created by
Coding's session factory after configuration/model/resource activation has
succeeded far enough to construct a session, and is closed by that session's
runtime-profile disposal hook. This provides the session-owned exclusive
capability semantics without putting an async live service into a persisted
capability profile.

Workspace Bash definitions remain shareable and static. At materialization,
the common session tool context injects the current session's `ExecService`;
the same service is injected into the session Bash command runtime and
extension command context. Consequently root, shared child, and isolated child
sessions cannot accidentally execute through a registry-time or parent
execution service.

## 11. Proposed Module Layout

```text
src/loushang/harness/environment/
  __init__.py
  types.py
  probe.py

src/loushang/harness/sandbox/
  __init__.py
  types.py
  protocols.py
  registry.py
  service.py
  exec_backend.py
  binding.py
  runtime.py
  backends/
    linux.py
    macos.py
    windows.py

src/loushang/coding/
  sandbox.py
```

If implementation shows that the environment model has no consumer outside
sandboxing, it may initially remain under `harness.sandbox.environment`.
It must still be a separate fact/probe contract and must not be copied into
each backend.

## 12. Security And Correctness Invariants

1. A process tool cannot bypass the execution path selected by composition.
2. A materialized `ExecRequest` is not rebuilt after authorization.
3. Disabled, degraded, and enforcing states are distinguishable.
4. Policy never assumes containment that `SandboxStatus` does not report.
5. `required` never degrades to unsandboxed execution.
6. Approval cannot remove a managed-required sandbox.
7. A scope cannot widen its roots or network access after creation.
8. Child scopes cannot exceed their delegated authority or workspace roots.
9. Helper processes and scopes are session-owned and cleanup is idempotent.
10. Diagnostics do not expose inherited environments, credentials, or secret
    values.

## 13. Delivery Plan

### Phase A: contracts and composition

- [x] add the environment facts/probe and deterministic tests;
- [x] add sandbox types and Protocols;
- [x] add registry, settings, status, and diagnostics;
- [x] extract the current local subprocess implementation as a reusable
  `ExecBackend`;
- [x] add the per-execution `SandboxExecBackend` integration seam;
- [x] prove that omitted configuration preserves current execution behavior.

### Phase B: first enforcing backend

- [x] implement and probe the Linux bubblewrap backend;
- [x] bind it behind `ExecService`;
- [x] verify filesystem roots, temporary paths, environment handling, streaming,
  timeout, cancellation, subprocess inheritance, and cleanup;
- [x] verify `best_effort` and `required` failure behavior.

### Phase C: Product integration

- [x] add Coding settings and runtime-capability binding;
- [x] route Bash, Python subprocesses, tests, and child-Agent process tools through
  the same bound execution service;
- [x] preserve routine network tools by default and expose only the repository
  metadata required by local Git commands;
- [x] expose one status/diagnostic projection without adding sandbox decisions to
  TUI.

### Phase D: authorization profile binding

- [x] add the Product-neutral, immutable `EffectiveExecutionProfile`;
- [x] intersect Policy-requested authority with the managed/Product ceiling so
  Approval cannot widen roots or network access;
- [x] adapt the current Policy/Approval decisions into an effective profile;
- [x] project the effective profile into `SandboxScopeRequest`;
- [x] let Coding consume a narrower authorized profile while preserving its
  experience-first default profile.

This phase establishes the enforcement contract. Migrating every effectful tool
to the new mandatory authorization gateway remains part of the Policy/Approval
delivery batches. The first core-tool slice is now bound for sessions with an
execution ceiling: Bash, read, write, and edit receive per-action profiles,
file tools validate profile roots, and Bash passes the profile through
`ExecRequest` for Sandbox enforcement. Their executor callbacks are Gateway-
owned and the action fingerprint and path authority are revalidated immediately
before invocation. This removes the application-layer time-of-check/time-of-use
gap; it does not claim descriptor-level protection against filesystem changes
after an asynchronous operation begins.

macOS and Windows backends follow the same Protocol when implemented. No
placeholder backend may report itself as enabled.

## 14. Acceptance Criteria

- omitted sandbox configuration starts no sandbox and preserves current
  execution behavior;
- enabled sandboxing selects a backend without platform branches in tools or
  Products;
- `not_applicable` and `unavailable` backend results remain distinguishable;
- fake environment and backend probes cover Linux, macOS, Windows, WSL,
  unavailable dependencies, degraded fallback, and required failure;
- Python and its subprocesses inherit the same enforced scope;
- an enabled default Coding scope retains host networking and supports local Git
  metadata without exposing the user's entire home directory;
- `ExecService` streaming, cancellation, timeout, and output capture remain
  unchanged;
- session and child-runtime disposal leave no owned sandbox helpers running;
- Policy/Approval tests demonstrate that sandbox state changes enforcement,
  not the semantic approval boundary;
- architecture dependency checks prevent Harness from importing Coding,
  Native TUI, Work, Method, or AI.
