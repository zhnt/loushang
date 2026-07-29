# Tool Execution Binding Boundary

Status: implemented (2026-07-29)

## 1. Decision

Every model-visible tool call enters one Harness-owned execution host.
`ToolDefinition` describes the tool and selects exactly one Harness-owned
execution binding:

```text
ToolDefinition
  -> DirectExecution
  -> AuthorizedExecution
```

`DirectExecution` invokes a handler that does not use the common protected
resource plane. `AuthorizedExecution` prepares an authorization request and
can invoke its handler only through the session's authorization gateway.

This combines two useful implementation properties without copying either
implementation wholesale:

- one common pre-execution path for every tool call;
- a typed, mandatory authorization path for filesystem, process, network,
  secret, publication, privilege, and other common protected-resource
  effects.

The change is a structural refactor of the existing Harness authorization
stack. It does not add a Policy rule, Approval option, sandbox backend, UI
surface, MCP capability, or durable workflow.

## 2. Problem

Before this refactor, `ToolDefinition` stored a freely callable `execute`
function. Registries and session command surfaces could call it directly:

```text
ToolRegistry
  -> ToolDefinition.execute(...)
```

The seven core Workspace tools also closed over Policy and Approval
dependencies and called the Workspace authorization function themselves:

```text
read/write/edit/bash/grep/find/ls
  -> resolve live/fallback Policy and Approval
  -> build a Policy subject
  -> call the Workspace authorization gateway
  -> execute the effect
```

That behavior was correct for the then-migrated tools, but it left three
recurring costs:

1. a tool author must understand Policy, Approval, execution profiles, and the
   Gateway call shape;
2. Policy and Approval dependencies are threaded through Workspace tool
   options and Product bootstrap even though they are session-owned;
3. the architecture test protects a known list of tool files rather than the
   execution contract of every registered definition.

Adding another protected-resource tool can therefore accidentally recreate a
direct execution path.

## 3. Goals

The refactor must:

1. give every model-visible tool call one Harness-owned dispatch boundary;
2. make the execution binding explicit and mandatory;
3. make a protected-resource handler unreachable through normal dispatch
   until Policy, Approval, execution-profile resolution, and pre-execution
   revalidation succeed;
4. remove Policy and Approval knowledge from individual Product tool
   definitions;
5. preserve the current user-visible permission behavior;
6. retain domain-specific authority for session-local operations such as
   multi-agent control;
7. replace the hard-coded seven-tool architecture assertion with Registry
   contract tests.

## 4. Non-goals

This design does not:

- add or change Policy rules, Approval choices, permission modes, audit fields,
  or TUI behavior;
- make OS sandboxing mandatory or add a platform backend;
- classify MCP tools or define an MCP trust model;
- add durable approvals, Work checkpoints, or daemon recovery;
- move multi-agent tree authority into general Policy;
- claim that Python types contain malicious in-process extension code;
- generalize the current Workspace path validator before a second Product
  presents a concrete incompatible requirement.

## 5. Terminology

### 5.1 Direct execution

Direct execution means that the tool does not consume the common protected
resource plane. It does not mean that the operation is mathematically pure.

Examples include:

- in-memory calculation;
- a session-state projection;
- `list_agents`, whose visibility is enforced by `MultiAgentControl`;
- `spawn_agent`, whose type, tree, quota, and delegation rules are enforced by
  the multi-agent authority runtime.

A direct handler must not receive common filesystem, process, network, secret,
or publication services through its execution context.

### 5.2 Authorized execution

Authorized execution is required when an operation consumes a common protected
resource:

- filesystem reads or mutations;
- local process execution;
- network access;
- secret access or transmission;
- privilege changes;
- repository publication or remote mutation;
- external-system mutation.

Read-only is not equivalent to direct. Reading a secret or a path outside the
admitted roots remains an authorized operation.

### 5.3 Execution binding

An execution binding is a closed Harness-owned value stored by a
`ToolDefinition`. It selects the dispatch route; it is not a Product-provided
Policy verdict.

## 6. Target API

The common metadata stays in one definition:

```python
@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    label: str
    description: str
    parameters: dict[str, object]
    execution: DirectExecution | AuthorizedExecution
    # existing prompt, rendering, and concurrency metadata
```

There is no default execution binding. A definition without one is invalid.

The two bindings are deliberately small:

```python
from loushang.ai.types import ToolCall


class DirectToolHandler(Protocol):
    async def __call__(
        self,
        call: ToolCall,
        context: DirectToolContext,
    ) -> AgentToolResult[object]: ...


@dataclass(frozen=True, slots=True)
class DirectExecution:
    handler: DirectToolHandler


class ToolActionAdapter(Protocol):
    def prepare(
        self,
        call: ToolCall,
        context: ToolCallContext,
    ) -> PreparedToolAction: ...


@dataclass(frozen=True, slots=True)
class PreparedToolAction:
    tool_name: str
    authorization_arguments: Mapping[str, object]
    execution_arguments: Mapping[str, object]
    cwd: str | None
    policy_subject: ToolPolicySubject | None = None


@dataclass(frozen=True, slots=True)
class AuthorizedToolAction:
    tool_name: str
    authorization_arguments: Mapping[str, object]
    execution_arguments: Mapping[str, object]
    cwd: str | None
    fingerprint: str
    actor_id: str = "root"
    execution_profile: EffectiveExecutionProfile | None = None
    policy_code: str | None = None
    approval_action_id: str | None = None


class AuthorizedToolHandler(Protocol):
    async def __call__(
        self,
        action: AuthorizedToolAction,
        context: AuthorizedToolContext,
    ) -> AgentToolResult[object]: ...


@dataclass(frozen=True, slots=True)
class AuthorizedExecution:
    action_adapter: ToolActionAdapter
    handler: AuthorizedToolHandler


class ToolExecutionHost:
    async def dispatch(
        self,
        definition: ToolDefinition,
        call: ToolCall,
        context: ToolCallContext,
    ) -> AgentToolResult[object]: ...
```

`ToolCall` is the existing `loushang.ai.types.ToolCall`; Harness does not
introduce a second call record.

`ToolCallContext` is a separate, non-model invocation record. It carries call
identity, cancellation, update delivery, and Product-approved typed operation
ports. Runtime services are never encoded in `ToolCall.arguments` or either
frozen argument mapping. The host projects this record into
`DirectToolContext` or `AuthorizedToolContext` according to the binding.

This separation also replaces the current session-command convention that
passes Bash operations through a private `__operations` parameter. A command
bridge binds its selected `BashOperations` in the call context; the authorized
Bash handler receives it through `AuthorizedToolContext`. The service object is
neither model-visible, fingerprinted, nor deep-frozen.

The adapter separates two immutable snapshots:

- `authorization_arguments` contains every input that affects the protected
  resource, Policy decision, Approval grant, audit shape, or pre-execution
  revalidation. Its canonical form retains the current fingerprint behavior.
- `execution_arguments` contains the complete normalized input needed by the
  handler, including non-authority fields such as read offsets and output
  limits.

Both mappings are deeply frozen before Policy evaluation. An adapter must put
every effect-changing value in `authorization_arguments`; Registry contract
tests enforce this for built-in tools. This avoids both unsafe post-approval
mutation and unnecessary changes to existing fingerprints. For example, a
read action authorizes its resolved path while its immutable execution
arguments also carry `offset` and `limit`.

`AuthorizedToolAction` is Product-neutral. The existing
`AuthorizedWorkspaceAction` is folded into this contract during migration;
Workspace path resolution and revalidation remain Workspace implementation
details rather than dependencies of `harness.tools.execution`.

The names above express responsibilities. Implementations may use generic
result types, but must not add another public compatibility protocol.

Decorated tools use the explicit convenience binders:

```python
@tool(name="calculate", description="Calculate in process")
async def calculate(expression: str) -> str:
    ...

definition = direct_tool(calculate)

@tool(name="read", description="Read a protected path")
async def read(path: str, context: ToolContext) -> str:
    ...

definition = authorized_tool(
    read,
    action=prepare_read_action,
)
```

For hand-written definitions, authors construct `ToolDefinition` with
`DirectExecution(handler)` or
`AuthorizedExecution(action_adapter, handler)`. Both forms create the same
`ToolDefinition`; they do not create Product-specific subclasses.

## 7. Runtime Flow

### 7.1 Common host

The session owns one `ToolExecutionHost`:

```text
AgentLoop or admitted session command
  -> existing argument preparation, schema validation, and pre-tool hooks
  -> ToolExecutionHost.dispatch(
       definition,
       final prepared ToolCall,
       non-model ToolCallContext,
     )
  -> select definition.execution
```

The host is intentionally narrow. It does not own schema validation,
`prepare_arguments`, `before_tool_call`, streaming updates, timing, common
start/finish/cancel lifecycle, or result rendering. `AgentLoop` already owns
those concerns. The host receives the final admitted call only after any input
rewrite has been prepared and revalidated.

An input transformation therefore precedes authorization. The updated input
produces a new prepared action and fingerprint; approval for the original
input cannot authorize the updated input. Policy audit remains owned by the
authorization gateway.

### 7.2 Direct path

```text
ToolExecutionHost
  -> DirectExecution
  -> DirectToolHandler
```

`DirectToolContext` contains call identity, cancellation, presentation update,
and explicitly admitted domain ports. It does not contain Policy, Approval,
the authorization gateway, raw `ExecService`, or generic filesystem/network
clients. A call-scoped protected-resource operation port is projected only into
`AuthorizedToolContext`.

Domain ports retain their own authority. This design does not reinterpret
multi-agent tree authority as Policy.

### 7.3 Authorized path

```text
ToolExecutionHost
  -> AuthorizedExecution.action_adapter.prepare(...)
  -> session AuthorizationGateway
     -> freeze authorization and execution arguments
     -> fingerprint canonical authorization arguments
     -> evaluate Policy
     -> resolve Approval when required
     -> intersect the effective execution profile
     -> revalidate the frozen action
     -> emit execution_started
     -> AuthorizedToolHandler
     -> emit execution_completed / execution_failed
```

The handler receives the already-authorized immutable action plus an
`AuthorizedToolContext`. The context exposes only the live services needed to
enforce that action, such as the session `ExecService` carrying the effective
profile.

The handler does not receive `PolicyEngine` or `ApprovalResolver`.

The implementation preserves the proven Workspace authorization sequence
behind `WorkspaceToolAuthorizationGateway`. Its execution helper is private;
the Gateway is the only production entry point. Workspace path validation
remains a concrete revalidator rather than becoming a speculative universal
resource validator.

## 8. Ownership

```text
harness.tools.core
  ToolDefinition and presentation/schema metadata

harness.tools.execution
  ToolExecutionHost
  DirectExecution
  AuthorizedExecution
  PreparedToolAction
  AuthorizedToolAction
  ToolAuthorizationGateway

harness.tools.authoring
  @tool schema metadata
  ToolContext
  direct_tool / authorized_tool
  typed filesystem, process, network, and publication action adapters

harness.effects
  immutable protected-resource effect records
  capability and redacted-audit projections

harness.tools.workspace.authorization
  session-owned Workspace Gateway and path revalidation

harness.tools.workspace
  authorized handlers for the seven core workspace tools
  Workspace-specific Gateway revalidation

Product
  selects and contributes ToolDefinitions
  selects the standard Policy evaluator or supplies a specialized one
  supplies Product-specific action facts when required
  does not own Policy, Approval, or Gateway dispatch
```

`ToolRegistry` stores definitions and may be bound to a host supplied by its
execution scope. It does not select Policy, retain Approval, construct a
Gateway, or execute effects.

`SessionToolController` owns the live `ToolExecutionHost` for a composed
session. Its `WorkspaceToolAuthorizationGateway` receives the typed Policy
evaluator and the live Approval resolver once; the per-call context supplies
the audit sink, execution service, execution environment, and profile ceiling.
`ToolDefinition` and individual tool factories receive none of those session
services. A standalone caller that materializes an authorized definition must
construct an explicit host with
`create_workspace_tool_execution_host(...)`; there is no Registry fallback
that silently selects a Policy or Approval resolver. A new Product therefore
defines and contributes tools without implementing Policy, Approval, or
Gateway dispatch; the Product's session composition selects the standard
Policy evaluator.

## 9. Registration Invariants

At registration:

1. `ToolDefinition.execution` is mandatory;
2. only Harness-owned binding types are admitted;
3. `AuthorizedExecution` requires both an action adapter and a handler;
4. the Registry rejects a raw callable as an execution binding;
5. implicit conversion from an arbitrary `AgentTool.execute` is removed at the
   migration exit gate;
6. a dynamic or externally contributed definition must also select an explicit
   binding; there is no implicit direct fallback;
7. a standard Harness session requires a Registry and materializes every
   model-visible tool through its `ToolExecutionHost`;
8. preinstalled raw `AgentTool` instances are rejected instead of retained as
   an alternate execution route.

These rules prevent accidental bypass. They do not claim to sandbox malicious
Python loaded into the host process.

## 10. Context And Dependency Simplification

After migration:

- Workspace tool definitions no longer accept `policy_engine` or
  `approval_resolver`;
- `ToolsOptions` no longer threads those values into every tool factory;
- `SessionCompositionPorts` receives a typed Product-selected Policy evaluator
  and the existing Approval, audit, environment, and execution-ceiling inputs;
- the session constructs one authorization gateway from those live inputs
  before materializing tools;
- child sessions bind the same Root-owned Approval coordinator through their
  actor-scoped session gateway;
- action adapters receive actor and environment facts from `ToolCallContext`,
  not from Product-global state.

Headless and interactive sessions continue to differ only in the Approval
resolver bound to the session gateway. There is no `None` Policy fallback for
an authorized binding: Products that admit authorized tools must supply a
Policy evaluator. This prerequisite is established in Batch A before
per-tool dependencies are removed.

### 10.1 Extension authoring

Extension lifecycle hooks may continue to receive the standard
`ExtensionContext`. A model-visible extension tool does not receive that full
context implicitly, because it currently exposes `exec_command` and would make
`DirectExecution` capable of starting processes.

The authoring migration is explicit:

```python
api.register_tool(direct_tool(decorated_tool))

api.register_tool(
    authorized_tool(
        decorated_tool,
        action=prepare_extension_action,
    )
)
```

The existing `@tool` decorator may continue to describe schema and rendering
metadata, but `register_tool` accepts only a completed `ToolDefinition`.
Registration of `DecoratedTool` or raw `AgentTool` is removed at the exit
gate; neither is silently classified as direct.

Direct extension handlers receive a restricted tool-time context without
`exec_command` or generic resource services. Authorized extension handlers
receive the prepared action and the scoped authorized context. Current
extension examples and API documentation migrate in the same branch. This is
an execution-safety migration, not a new extension permission-contribution
feature.

### 10.2 Typed common effects

An authorized action describes common protected resources with immutable
Harness records:

```python
FilesystemEffect("write", (resolved_path,))
ProcessEffect(("git", "status"))
NetworkEffect("https://service.example/api", mutation=False)
PublicationEffect("refs/heads/main", repository=repo, remote="origin")
```

The action adapter freezes these records together with the authorization
arguments. The Gateway includes them in the action fingerprint, feeds them to
Policy effect detection, and uses filesystem effects for execution-profile
revalidation. Common audit events receive only a redacted capability summary;
raw commands, paths, URLs, repository names, and remotes do not enter that
event stream through an effect record.

`FilesystemActionAdapter`, `ProcessActionAdapter`, `NetworkActionAdapter`, and
`PublicationActionAdapter` are authoring conveniences, not a closed tool list.
`ToolActionAdapter` remains the extension point for a custom protected
resource.

## 11. Migration Plan

The migration was intentionally limited to four bounded batches. All four are
complete.

### Batch A: contracts and hosted dispatch

- add `harness.tools.execution`;
- add mandatory execution bindings to `ToolDefinition`;
- add the narrow `ToolExecutionHost`;
- generalize the existing authorization action record into
  `PreparedToolAction` and `AuthorizedToolAction`, keeping Workspace
  revalidation concrete;
- add the typed Policy evaluator to `SessionCompositionPorts` and construct the
  session Gateway and host there;
- merge the core and Workspace materialization wrappers into one hosted
  wrapper;
- require `SessionToolRuntime` to have a Registry and reject preinstalled raw
  tools;
- make materialized tools and admitted session command execution call the host;
- move the session Bash command's `__operations` service override from tool
  arguments into `ToolCallContext`;
- adapt existing definitions on the implementation branch without changing
  behavior.

No public compatibility executor remains.

### Batch B: core Workspace tools

- convert Bash, read, write, edit, grep, find, and ls to
  `AuthorizedExecution`;
- use the common filesystem adapter for file tools and a typed process effect
  for Bash;
- retain the current operation implementations and output shapes;
- remove per-tool calls to `execute_workspace_tool_action`;
- remove Policy and Approval parameters from their options and factories.

### Batch C: direct and domain-authorized tools

- convert pure/in-process tools to `DirectExecution`;
- keep multi-agent authority calls inside the multi-agent runtime;
- verify that direct contexts do not expose common protected-resource ports;
- require explicit binding when registering extension tools;
- replace full `ExtensionContext` injection into model-visible tools with the
  restricted direct or authorized tool-time context;
- update current extension examples and API documentation.

This batch does not add extension permission contributions.

### Batch D: delete the old route

- remove `ToolDefinition.execute`;
- remove implicit raw `AgentTool` execution normalization;
- reject missing or unknown execution bindings;
- replace the seven-file static check with Registry-wide contract tests;
- update public examples and current architecture documentation.

The branch exit gate requires all four batches. The implemented state exposes
only hosted dispatch; a raw `AgentTool` cannot be registered or preinstalled as
an alternate model-tool route.

## 12. Tests And Acceptance Criteria

### Contract tests

- every registered definition has exactly one admitted binding;
- missing bindings and raw callables fail registration;
- standard session composition fails if model-visible tools cannot be
  Registry-materialized through the host;
- a preinstalled raw `AgentTool` cannot survive session composition;
- a direct binding never receives the authorization gateway or common effect
  services;
- an authorized handler is not invoked after deny, abort, stale approval, or
  execution-profile rejection;
- authorization and execution arguments are immutable before Policy runs;
- call-scoped operation services travel through `ToolCallContext`, never
  through tool arguments or fingerprints;
- effect-changing built-in arguments are present in
  `authorization_arguments`, while execution-only fields do not alter the
  existing fingerprint;
- the Registry never retains Policy or Approval state and never constructs a
  Gateway implicitly;
- common action adapters freeze typed effects into the action fingerprint;
- an input transformation changes the frozen fingerprint and is evaluated
  again;
- only the host invokes execution bindings.

### Behavioral regression

- the existing permission behavior matrix remains unchanged;
- routine Coding work still produces no unnecessary prompts;
- deletion, publication, privilege, secret, and remote mutation still ask;
- managed deny and execution ceilings still win;
- Root and child approval routing remains actor-scoped;
- Gateway audit ordering and redaction remain unchanged;
- common effect audit projection never copies raw commands, paths, URLs,
  repository names, or remotes;
- all seven Workspace tool outputs, streaming, cancellation, and rendering
  remain compatible at the user-visible boundary.

### Architecture checks

- Product packages do not import or construct `PolicyEngine`,
  `ApprovalBroker`, or Workspace authorization internals for tool execution;
- Workspace tool modules do not evaluate Policy or resolve Approval;
- no production call site invokes a stored tool handler outside
  `ToolExecutionHost`;
- `SessionToolRuntime` has no Registry-less raw-tool fallback;
- extension tool registration cannot infer an execution binding;
- no Product implements another execution binding class.

## 13. Rejected Alternatives

### Add only `effectful: bool`

A Boolean documents intent but leaves the raw `execute` callable available and
does not enforce a route.

### Copy per-tool `checkPermissions`

This distributes Policy semantics back into Product tools and recreates the
ownership problem that the Policy/Approval migration removed.

### Make every tool enter Policy

This conflates protected-resource authorization with domain authority and adds
Policy vocabulary to harmless session operations.

### Add an opaque approval token now

The Gateway already owns the executor callback and invokes it only after
authorization. A new public permit type adds ceremony without closing the
in-process malicious-code boundary. It can be reconsidered only if a concrete
out-of-process executor requires it.

### Generalize every action and path validator now

The generic authorization sequence and immutable action record must move
because the execution host is Product-neutral. The existing Workspace path
validator already has real behavior and extensive tests; replacing it with a
speculative universal resource validator would add ports without evidence.

### Keep raw tools for compatibility

A compatibility fallback would preserve the exact bypass this refactor is
meant to close. Extension and Product authoring migrate to explicit bindings in
the same branch; there is no permanent legacy route.

## 14. Exit State

The completed architecture is:

```text
one ToolDefinition
one Product-neutral authoring surface
one ToolExecutionHost
two execution bindings
one session authorization gateway
four common typed effect records
zero Product-owned Policy/Approval execution paths
zero raw definition.execute call sites
zero Registry-less model-tool execution paths
```

For a new Product, the permission model is reduced to one question at tool
definition time:

```text
Does the tool consume a common protected resource?
  yes -> AuthorizedExecution(action_adapter=..., handler=...)
         or authorized_tool(decorated_tool, action=...)
  no  -> DirectExecution(handler=...)
         or direct_tool(decorated_tool)
```

The Product describes the action and implements the operation. Harness owns the
authorization decision and execution boundary.
