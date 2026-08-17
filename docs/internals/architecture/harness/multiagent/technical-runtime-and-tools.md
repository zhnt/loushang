# Technical Multi-Agent Runtime, Scheduling, And Tools

> Status: **implemented**. This document records the accepted and
> implemented boundary for multi-agent execution. Phases 1A-1C and 2A-2B
> are complete; the technical runtime, tools, workspace, and TUI surface
> are shipping.
>
> For implementation shape, execution ownership, and the model tool surface,
> this document supersedes older candidate-component wording when they differ.
> The established ownership and async-notification decisions in ARD-001 and
> ARD-002 remain authoritative unless explicitly revised.

## Decision Summary

Multi-agent has two deliberately separate layers:

```text
technical multi-agent runtime     scheduling multi-agent
how agents cooperate             why, when, and until what outcome they run
```

The technical runtime is implemented first. It owns agent identity, context
isolation, messaging, authority, execution attachment, and real-time facts.
It does not know a Method plan, a Work run, an acceptance rule, or a Product
artifact.

The scheduling layer is owned by `loushang.work` and, eventually,
`loushang.method`. It selects agent types, dependencies, retry policy,
checkpoints, durable execution, workspace policy, and acceptance rules.

```text
Coding / PPT / Design / Research
        | product types, tools, and presentation
        v
Method (optional) -> Work scheduler
                         | durable operations and event log
                         v
                 harness.multiagent
                         | cooperation control plane
                         v
       runner / HostRuntime / queue / approval / transcript / workspace
```

Dependencies point down. In particular, `harness.multiagent` must not import
`work`, `method`, a Product package, or `harnesstui`.

## Technical Runtime

### Physical Modules

The first implementation deliberately has four architectural responsibility
modules, not one module per candidate responsibility.  Task ownership is kept
in one control-owned support module so the pure synchronous control plane does
not absorb asyncio lifecycle code:

```text
loushang.harness.multiagent/
  types.py
  registry.py
  context.py
  control.py
  run_handle.py  # control-owned async task lifecycle helper

loushang.harness.session/
  multiagent.py   # live Product-session adapter
```

| Module | Owns | Reuses rather than recreates |
|---|---|---|
| `types.py` | `AgentPath`, `AgentTypeSpec`, `SpawnRequest`, `AgentFact`, authority, usage, and workspace protocols | — |
| `registry.py` | tree addressing, reservation/commit/rollback, open/closed entries, descendant lookup | in-memory data structures |
| `context.py` | fresh/fork context plans, transcript watermark, deterministic history rebuild, admitted tool names, approval-provenance bubbling | transcript repository and `ApprovalRequest` |
| `control.py` | spawn, message routing, lifecycle transitions, close, authority checks, fact publication | registry and immutable facts |
| `run_handle.py` | one owned task per round, wake-up, interrupt/await, dispose-before-close | `HostRuntime` and `run_agent()` through a narrow round driver |
| `session/multiagent.py` | live handle ownership, `AgentInputFacade`, explicit `SessionSubagentBinding`, session tree operations, completion-notice policy, lifecycle-hook composition | `HostRuntime`, `HostInputQueue`, and session lifecycle hooks |

`LifecycleProjection` and `Limits` remain responsibility names rather than
mandatory files. `AgentInputFacade` lives in the thin session adapter because
it wraps an already-existing Product queue; it is not a second queue.
`SubagentRunHandle` is the one intentional async support file because task
ownership and cancellation races require an independent test boundary.

Delivery is incremental: `types.py`, `registry.py`, and the pure lifecycle
portion of `control.py` land first.  `context.py` and live run ownership are
connected only after incarnation- and round-safe transitions are covered by
tests.  This staging does not add another architectural layer.

### Execution And Workspace

Phase one has one actual execution environment: the current session. The pure
`control.py` remains synchronous; `session/multiagent.py` composes existing
`HostRuntime` and `HostInputQueue`, while the Product child factory adapts its
prepared `run_agent(AgentRunSpec)`/session round through
`SubagentRoundDriver`. It does **not** introduce an `AgentExecutionPort`
merely to hide that one implementation.

`SessionSubagentFactory.create()` returns a typed `SessionSubagentBinding`:
the round driver, an optional input-activity port, and an optional initial
workspace reference. Driver disposal returns `SubagentDisposeResult`, including
an optional released-workspace snapshot and cleanup error. These explicit
values replace attribute probing while preserving the current session-owned
execution structure. They are in-process composition contracts, not remote
protocol objects.

Remote placement does not automatically add a second multiagent runtime. The
remote seam follows the weakest interaction contract that satisfies the use
case:

```text
one-shot capability
  invoke(request) -> result

asynchronous job
  submit(request) -> RunRef
  await_result(run_ref)
  cancel(run_ref)

continuous collaboration
  spawn / send / wait / list / interrupt / close

```

The first two are ordinary Harness capabilities and do not enter
`harness.multiagent` merely because the implementation uses an Agent remotely.
For continuous collaboration, `MultiAgentToolPack` remains the model-visible
façade and its injected live collaboration seam binds either the current local
`SessionMultiAgentRuntime` or one remote collaboration client for the Session /
capability profile. Tool schema and remote wire protocol remain distinct.

An `AgentExecutionPort` remains a deferred, optional extraction rather than a
phase-one public interface. A remote client alone does not justify it. Harness
extracts the smallest proven internal port only when at least two physical
backends must participate transparently in the same logical tree or share
attach, lease, fencing, checkpoint, orphan and recovery semantics. Host
infrastructure supplies those physical backends. `loushang.work` does not
implement the port: Work owns accepted business lifecycle and durable facts;
a Product `WorkDomainExecutor` maps business steps to Harness execution and
maps execution facts back to `WorkEvent` values.

See [Remote Agent Capability Boundary](remote-agent-capability-boundary.md) for
the client/server dependency direction and state model.

Workspace isolation is independently useful, so its internal protocol is
defined now but optional on every spawn:

```text
WorkspaceLeasePort
  acquire(request) -> WorkspaceLease
  snapshot(lease) -> WorkspaceLeaseSnapshot
  release(lease) -> WorkspaceLeaseSnapshot
```

When a spawn has no workspace request, the child inherits the parent workspace
with the agent type's default read-only semantics; no lease is acquired.
`GitWorktreeLease` is Coding's first concrete implementation, not a
prerequisite for exploration, review, or aggregation agents.

`WorkspaceLease` is intentionally broader than a Git worktree:

```text
Coding  -> shared directory, Git worktree
PPT     -> deck revision or deck branch
Design  -> canvas branch
Research-> document revision or draft sandbox
```

Its `execution_ref` is opaque to Harness: Coding interprets it as a managed
filesystem path, while another Product may interpret it as a deck, canvas, or
revision handle.

The multi-agent runtime carries opaque workspace and artifact references; it
does not parse a Git diff, slide document, or canvas model.

### Session Adapter

`loushang.harness.session.multiagent` is a thin session adapter. It creates
one control instance for a root session/tree and translates live session
objects into the core ports:

```text
session transcript       -> TranscriptSource
session approval exit    -> ApprovalExitPort
session runner/queue     -> direct HostRuntime/HostInputQueue composition
session event consumers  -> AgentFact listeners
session before_release   -> close session-owned executions
```

It must not implement fork filtering, approval policy, or tool shaping; those
rules remain in `harness.multiagent.context`.

Harness defines the `SessionSubagentFactory` contract but intentionally does
not provide a factory that creates an arbitrary Product child. Coding, PPT,
Design, and OEM-defined Products must explicitly bind their own factory because
only the Product knows how to construct its transcript/session, select its model
and tools, route approvals, and interpret its workspace. A disabled or absent
binding therefore fails closed. A shared callback-driven factory may be
extracted only after at least two Product implementations demonstrate the same
stable construction seam.

Completion notices default to `queue_only`: the immutable notice enters the
parent Agent's system mailbox, but an idle parent is not unexpectedly started.
The Agent loop drains that mailbox before sampling at the next safe boundary,
including immediately after a tool result. The notice never enters the
editable steering/follow-up queues or their TUI preview. `wake_if_idle` is an
explicit policy. Any async notice delivery task is owned and drained by the
session runtime.

When a session is replaced or disposed, its `before_release` hook closes only
session-owned executions. A durable Work operation is detached, not cancelled;
the Work runtime remains its authority and a later session may attach to it.

### Authority And Lifecycle

`AgentAuthorityPolicy` is evaluated after target resolution and before every
control operation. Communication authority is deliberately narrower and is
evaluated separately: a child may always report to its direct parent, while
cross-branch communication is opt-in.

```text
AgentCaller(path): default authority over self and descendants only
HostCaller:        may manage the complete tree, through the same policy/audit path
Cross-branch:      denied by default; explicitly granted by product policy

CommunicationPolicy
  child -> direct parent: always allowed
  parent -> descendant:   allowed under the parent's control authority
  sibling/cross-branch:   denied by default; explicitly granted by product policy
```

Terminal facts are written before notification, cleanup, or summarisation.
The registry is the live control-plane authority. Phase-one fact consumers are
best-effort and ordered per agent; they are not a durable event log.

### Communication Model

There are two non-interchangeable paths:

```text
agent message       -> target AgentInputMessage -> target HostInputQueue
completion notice   -> target system mailbox -> next model sampling boundary
agent fact/progress -> AgentFact event stream -> TUI / Work / audit consumers
```

`AgentInputMessage` carries a message id, sender path, recipient path,
delivery mode, text, and structured references. It is injected as a normal
user-role input at the target's next permitted queue boundary; it is not a
hidden transcript read by a sibling.

```text
parent -> child:  send_message(child, text)
child  -> parent: send_message("parent", text)
child terminal:   control publishes terminal fact + completion notice
host   -> agent:  host sends through the same delivery path with HostCaller identity
```

`"parent"` is a stable relative target; the system also tells a child its
canonical and parent paths. `send_message` defaults to follow-up delivery.
Steering a running target is a distinct policy-controlled delivery mode, not a
way for arbitrary siblings to interrupt each other. Delivery to an open idle
or terminal target automatically starts its next run; delivery to a running
target queues the message for the relevant boundary.

The completion notice is not a model-authored message. Control generates its
immutable payload from the terminal fact and publishes it through a dedicated
notice sink; it does **not** implement the notice by recursively calling
`send_message`. `AgentInputFacade` later submits the notice to the system
mailbox and decides whether an idle parent should start a turn. A recipe executor may instead
await terminal facts directly. These two consumers must not both trigger a
parent model turn.

## Model-Callable Tools

The following are **Harness-owned collaboration tool definitions**: their
schema, authority checks, and calls into `MultiAgentControl` are common across
Products.  A Product registers the admitted subset through its normal live
tool registry with the current `MultiAgentControl` closed over; it does not
reimplement their semantics or register them through a static
capability/profile binding.

```text
spawn_agent
send_message
wait_agent
list_agents
interrupt_agent
close_agent
```

| Tool | Semantics |
|---|---|
| `spawn_agent` | Asynchronously create an admitted child task, inject its first prompt, and return its canonical path. A failed call creates no child. Results arrive later as a completion notice. |
| `send_message` | Deliver a message. A running target receives it at the appropriate queue boundary; an open idle or terminal target is automatically awakened for its next turn. |
| `wait_agent` | Wait for the caller's input activity (completion notice, agent message, or user steering); it does not poll a target or return hidden partial output. |
| `list_agents` | List the current live session tree visible to the caller's authority scope, with status, progress, and summary. |
| `interrupt_agent` | Abort the target's current turn while retaining an open execution when policy allows. |
| `close_agent` | Recursively close a target and its descendants; this releases session-owned resources and open-agent capacity. Terminal children remain open and reusable until this explicit close. |

The stable core input to `spawn_agent` is deliberately small:

```json
{
  "name": "security_review",
  "prompt": "Review the authentication change. Read only; report risks.",
  "agent_type": "security_reviewer"
}
```

`AgentTypeSpec`, not an arbitrary model request, decides the normal model,
reasoning level, tools, permission policy, spawn permission, and workspace
defaults. This prevents a coordinator from accidentally creating an
unbounded, full-authority, expensive worker.

Products may add constrained workspace fields. The target Coding contract has
two Claude-Code-style cases:

```text
workspace.mode = "isolated"  -> request a managed Git worktree lease
cwd = absolute existing path  -> attach to an existing permitted directory
```

`cwd` and managed isolation are mutually exclusive. A managed worktree's real
path is allocated by the system and returned as a `workspace_ref`; it is not
chosen by the model. A supplied `cwd` must be an existing directory under the
Product's allowed roots. The same general request is represented by deck,
canvas, or artifact references in non-Coding products.

Workspace sharing and Git checkout identity are independent. The target model
uses named profiles over the valid combinations:

```text
parent + current   -> children share the parent worktree
agent + detached  -> one child owns an isolated artifact worktree
agent + branch    -> one durable worker owns a branch-backed worktree
group + branch    -> one child group shares a branch-backed worktree
```

A branch without a separate worktree is not isolation. Phase two implements
only `parent + current` and `agent + detached`; the branch-backed profiles are
reserved for later Work/group ownership and do not imply current merge, commit,
push, PR, or group-lifecycle support. The detailed ownership, artifact, apply,
and cleanup design is in
[Workspace Collaboration And Git Handoff](workspace-collaboration-and-git-handoff.md).

The implemented phase-two model tool does not yet accept either field
directly. `AgentTypeSpec.workspace_mode` selects inherited or isolated policy;
Coding's `implementation_worker` and `test_runner` force isolated managed
worktrees. Coding's explicitly admitted `shared_implementation_worker` instead
uses the parent session's already-authorized, resolved `cwd`, so it edits the
same worktree and branch and can see existing uncommitted changes. It is
bounded by the Product's normal child concurrency limit rather than a
single-writer limit. The parent must assign explicit, disjoint file or
responsibility ownership; workers must not revert peer changes, and the parent
must not edit a worker-owned file while that worker is running. Same-file or
tightly coupled changes stay serial or use isolated worktrees. This is a
Codex-style orchestration contract, not a generic filesystem lock or automatic
merge protocol. It is also not arbitrary `cwd` attachment: model-supplied paths
remain deferred until their allowed-root policy and user-facing authority are
implemented.

Tool exposure is per agent type. An explorer may have no spawn or close tool;
a coordinator can manage its descendants; a worker can be required to use an
isolated workspace. Available type lists are injected as product context, not
baked into a changing tool schema.

### Progress, Usage, And Notification Discipline

`AgentFact` separates volatile progress from terminal facts. Its minimum
shape includes:

```text
AgentProgress
  latest_input_tokens       # provider input usage is cumulative; replace, do not sum
  cumulative_output_tokens  # output usage is per turn; sum
  tool_uses
  recent_activity
  summary                   # maintained independently from activity updates

AgentFact
  kind: spawned | started | activity | progress | terminal | closed
  agent_path, parent_path, agent_type, status
  progress: AgentProgress | None
  workspace_ref, artifact_refs
  change_set_ref              # transitional compatibility; Coding leaves null
  terminal: {final_message, usage, duration_ms} | None
```

The control/registry owns an atomic terminal-notification marker keyed by
agent incarnation and run round. Completion, failure, explicit stop, cleanup,
or a racing observer may all discover a terminal state, but exactly one
structured completion notice is published for that round. The session input
facade inserts that notice into the parent's system mailbox. The notice
includes the retained `workspace_ref` and opaque artifact references,
so a parent can locate a worker's output without reading its raw sidechain
transcript. The transitional `change_set_ref` remains a nullable,
provider-interpreted compatibility field, but Coding's target Git path leaves
it empty and uses immutable `artifact_refs`; there is no additional
Product-specific public type at this boundary.

The phase-one cancellation policy is `link_parent_cancel = false`: an
asynchronous background child survives cancellation of its parent turn. The
field is an internal execution policy, never a model-supplied spawn parameter.
It is reserved for a future foreground/in-process execution mode that
explicitly links a child abort scope to its parent.

Workspace lifecycle and version operations remain internal ports:

```text
WorkspaceLeasePort.acquire/release
ArtifactRevisionPort.read
ChangeSetPort.compare
ChangeApplyPort.apply
```

A Product may later expose safe wrappers such as `compare_artifact_revisions`
or `apply_change_set`; the latter always uses product-specific conflict and
approval semantics. Git merge is not a generic multi-agent tool.

## Scheduling Layer

`loushang.work` owns durable multi-agent scheduling. It records the authority
for long-running work rather than making a TUI task table or a live control
tree pretend to be durable.

```text
agent_requested
workspace_acquired
agent_started
agent_progressed
agent_checkpointed
agent_waiting_for_approval
agent_completed | agent_failed
agent_retry_scheduled | agent_orphaned
workspace_retained | workspace_released
```

The scheduler can drive fan-out/fan-in, pipelines, independent review,
adversarial review, specialist routing, hierarchical aggregation, and durable
monitoring. `MethodPlan` may eventually compile into these operations, but is
not required for a Product or a user-directed coordinator to use the technical
runtime today.

## Presentation

`loushang.harnesstui.multiagent` owns the Product-neutral `/agents` command
surface and is a fact consumer only:

```text
AgentFact -> AgentTreeViewModel -> AgentTreeSurface
```

It reuses `ScreenSurfaceView`, `ScreenSurfaceCoordinator`,
`ScreenSurfaceWorkflow`, the status line, Markdown rendering, scrolling, and
the approval surface. The multi-agent core never imports it.

The first implemented `/agents` surface is deliberately read-only. It
initializes from the Host-authorized live registry snapshot, then updates only
through `AgentFact` subscription. Coding is the first Product adapter and only
binds its current session runtime; PPT, Design, and other Products reuse the
same command and surface with their own bindings. Interrupt and close remain
normal authority-checked collaboration tools rather than TUI-specific control
paths.

## Claude Code Qualities To Preserve

The design intentionally preserves these proven qualities from Claude Code:

1. Agent types select model, tools, permissions, and prompts.
2. Background agents survive parent-turn cancellation and report by structured
   notification.
3. An isolated Coding worker receives a managed worktree; unchanged worktrees
   may be cleaned up and changed ones retained with a reference.
4. Progress includes activity, tool count, token usage, and a concise summary.
5. Sidechain history and workspace/artifact references make a completed worker
   inspectable without forcing raw output into the parent context.

Loushang improves the authority boundary: live collaboration state belongs to
the control plane, durable long-running state belongs to Work, and TUI state is
only a projection.

## Delivery Sequence

1. Define and test the pure control core: incarnation-safe identity, tree
   reservation, authority, limits, lifecycle rounds, usage, facts, and notice
   idempotency.
2. Add task-owning run handles, then the context/session adapter and completion
   notice input policy.
3. Register Coding's initial collaboration tools only after real child
   interrupt/close/follow-up tests pass.
4. Implement Coding's managed Git worktree lease and fact-driven TUI surface.
5. Implement the durable Work execution adapter, checkpoints, orphan recovery,
   and attach/cancel controls.
6. Let Method compile task/product plans into durable schedules and acceptance
   rules.
