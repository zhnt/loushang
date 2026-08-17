# Multi-Agent Temporary Implementation Plan

> Status: **executed**（Phases 1A-1C, 2A-2B 全部完成）。本文是
> [Technical Runtime, Scheduling, And Tools](technical-runtime-and-tools.md)
> 的执行检查表，保留为已完成阶段的开发记录。Phase 3 (Durable Work Execution)
> 与 Phase 4 (Method Orchestration) 移至各自的子系统设计文档。

## Goal

Deliver multi-agent capability in layers without mixing session collaboration,
workspace isolation, durable Work scheduling, and Method business orchestration
into one implementation step.

```text
technical collaboration
  -> Coding product experience
  -> durable Work execution
  -> Method-declared orchestration
```

## Phase 0 — Design Baseline

### Deliverables

- Accept the technical/runtime/tools boundary document.
- Reconcile older candidate-component wording with the implementation baseline.
- Turn the following semantics into scenario-level test cases before code is
  written.

### Required Scenarios

```text
send_message:
  running target -> queued at the appropriate boundary
  open idle/terminal target -> automatically starts the next turn

authority:
  child -> parent communication allowed
  parent -> descendant communication allowed
  cross-branch communication denied unless policy grants it
  control operations limited to self/descendants, except HostCaller

lifecycle:
  parent turn cancellation does not stop a background child
  /new, /resume, and quit close session-owned children
  durable Work execution detaches rather than being cancelled

workspace:
  no request -> inherited default read-only workspace
  isolated request -> managed lease
  cwd -> existing permitted directory and mutually exclusive with isolation

notification:
  exactly one completion notification per agent incarnation and run round
  across completion/stop/cleanup races
  notification includes workspace_ref, artifact_refs, and the nullable
  transitional change_set_ref; Coding's target Git path leaves change_set_ref
  empty
  terminal facts and completion notices do not travel through send_message

stale callbacks:
  closing an agent makes an in-flight run callback harmless
  reusing a closed path creates a new incarnation
  a callback from an older incarnation cannot mutate the replacement

usage/progress:
  input usage replaces latest cumulative value
  output usage accumulates per turn
  progress activity does not overwrite summary
```

### Command-Line Manual Validation

Provide a command-line **collaboration recipe runner** while the technical
layer is being built.  It must construct a declared agent tree itself; it
must not depend on a root model deciding to call `spawn_agent`.  This makes a
terminal run reproducible and suitable for diagnosing queueing, authority,
lifecycle, and notification races.

#### Command Boundary

Use `multiagent` as the technical, short-lived collaboration namespace:

```console
loushang multiagent recipes
loushang multiagent run <recipe> --prompt <prompt> [options]
loushang ma run <recipe> --prompt <prompt> [options]
```

It intentionally has no `status`, `resume`, `retry`, `attach`, or `schedule`
commands in phase one: a session-owned run ends with its process.  Giving it
durable-looking verbs before Work exists would promise a capability that the
runtime cannot provide.  Once an operation needs durability, recovery,
dependencies, or later attachment, it belongs under `loushang work`; when its
topology is declared by a work-product method, it belongs under
`loushang method`.

```text
loushang multiagent run ...    immediate, session-owned collaboration
loushang work ...              durable operations and scheduling
loushang method ...            product/method-declared orchestration
```

Inside an already-running product session, the model uses the collaboration
tools (`spawn_agent`, `send_message`, `wait_agent`, `list_agents`,
`interrupt_agent`, `close_agent`) and the human uses the Agent Tree surface.
Those are live-session controls, not a second shell command surface.

The implemented phase-one command shape is:

```console
# Deterministic checks with no provider credentials. These still exercise the
# real Coding child session, Agent loop, queue, RunHandle, and cleanup path.
uv run loushang ma run parallel-review \
  --provider scripted --prompt "Review this design" --count 3
uv run loushang ma run debate \
  --provider scripted --prompt "Should we adopt this proposal?"

# Manual real-model smoke tests.  These are short-lived session collaboration,
# not durable Work schedules.
uv run loushang ma run parallel-review \
  --prompt "Review this design and report risks" \
  --replicas reviewer=3 --model provider/model
uv run loushang ma run debate \
  --prompt "Should we adopt this proposal?" \
  --agent proposer=provider/model-a \
  --agent critic=provider/model-b \
  --agent judge=provider/model-c

# Include one or more UTF-8 source documents in the recipe prompt.
uv run loushang ma run parallel-review \
  --prompt "Review the attached design" @docs/design.md
```

The ready recipes are deliberately small and static:

| Recipe | Declared topology | What it verifies |
| --- | --- | --- |
| `parallel-review` | parallel reviewers -> synthesizer | parallel runs, full terminal fan-in, bounded replica counts |
| `debate` | proposer -> critic -> judge | opposed evidence, role model overrides, explicit decision |

`messaging`, `lifecycle`, and workspace isolation remain focused technical
tests rather than user-visible recipes. `workspace` becomes a recipe only
after the lease policy is implemented.

Built-in recipes use short command names: `debate` and `parallel-review`.
A Product contributes a similarly readable unique name such as
`coding-review` or `design-usability-review`; the active Product catalog
rejects collisions at registration time.  `--agent ROLE=MODEL` is repeatable
and overrides the model chosen for a declared role without creating a separate
flag for every recipe.
Common execution options remain generic: `--model` supplies the default,
`--cwd` supplies a permitted existing directory, `--format plain|json`
chooses observation, and policy caps such as `--max-parallel` only lower the
recipe's admitted limit.  A CLI caller cannot name a managed worktree path or
raise a recipe's tool/approval authority.

`--replicas ROLE=COUNT` is repeatable and only applies to a role that the
recipe marks as scalable.  For example, `parallel-review --replicas
reviewer=3` creates `reviewer-1` through `reviewer-3`, runs them subject to the
parallelism cap, and fans their terminal summaries into the declared
synthesizer.  The recipe owns the default and maximum count; the caller may
only request a value within that bound.  A convenience `--count 3` may be
accepted only when the selected recipe has exactly one scalable role; it is an
alias for `--replicas <that-role>=3`, never a global "make three arbitrary
agents" switch.

The runner prints terminal notices, usage, final output, and retained
workspace or artifact references in plain text or JSON; it may later be given
a TUI view, but a TUI is not required to validate the runtime. The
`scripted` provider is a deterministic Coding stream fixture, not a parallel
state machine: it exercises the same child factory and lifecycle as a real
provider. Real-model scenarios remain opt-in because their content, latency,
and cost are inherently non-deterministic.

`multiagent run` is an experimental, short-lived recipe entry point rather
than a durable workflow language.  Debate, review, and similar recipes make
manual collaboration useful immediately, while Work and then Method later own
durable, declarative orchestration.  Normal Coding sessions also receive the
model-callable collaboration tools, where the model can compose a topology
appropriate to the task.

## Phase 1 — Session-Owned Technical Runtime

Phase 1 is deliberately delivered through three internal checkpoints.  A
checkpoint may be merged only when its own contracts are true; later
checkpoints must not be represented by placeholder implementations.

Implementation checkpoint (2026-07-26):

- Phase 1A is implemented by the incarnation-safe registry/control core.
- Phase 1B is implemented by the single-owner `SubagentRunHandle`.
- Phase 1C's Product-neutral substrate is implemented: deterministic
  watermark history planning, approval provenance bubbling, the
  `HostInputQueue` user-input facade, the Agent system mailbox, the
  `HostRuntime` round adapter, session-owned tree operations, queue-only
  completion notices, recursive release, and the lifecycle hook composer.
- Phase 2A Product integration is implemented: normal Coding CLI root sessions
  explicitly install a non-persistent Coding child-session factory and a
  bounded type catalog. `explorer`, `reviewer`, `synthesizer`, `proposer`,
  `critic`, and `judge` inherit the root workspace without dedicated `write`
  or `edit` tools; `explorer` additionally receives Coding's existing `bash`
  definition, including its configured policy and approval chain, for Git
  inspection, local search, Python analysis, and permitted network retrieval.
  `implementation_worker` and `test_runner` receive system-allocated isolated
  Git worktrees. `shared_implementation_worker` is the explicit shared-worktree
  option for bounded tasks that must see and directly preserve the parent
  session's uncommitted state: multiple workers may reuse the exact resolved
  Coding `cwd`, worktree, and branch only when the parent assigns disjoint file
  or responsibility ownership. Workers preserve and adapt to peer changes
  rather than reverting them; overlapping or tightly coupled writes remain
  serial or use isolated worktrees. Commit/merge/publish remain parent-owned. The
  latter four read-only roles are the built-in recipe roles. The factory maps the
  first round to the existing `prompt()` path, later rounds to the existing
  queue / `continue_run()` path, and interruption/disposal to the existing
  Coding session runtime. It follows the root session's current model and
  provider stream while copying only the role-admitted definitions from
  Coding's Product tool registry into each child. Every child resolver is
  bound to its incarnation before entering the common authorization Gateway.
  Root approval presentation and `/permissions` retain that actor provenance;
  closing a child cancels only its pending requests and ending it revokes only
  its session grants, without changing Root or sibling approval state.
- The Harness-owned live `MultiAgentToolPack` is implemented with
  `spawn_agent`, `send_message`, `wait_agent`, `list_agents`,
  `interrupt_agent`, and `close_agent`. Unrestricted Coding CLI sessions bind
  the pack to their current session runtime and receive a Product-specific
  prompt fragment describing the admitted roles. Explicitly restricted and
  no-tools sessions still install the control runtime but do not receive the
  collaboration tools. Each root session gets a cloned registry so a `/new`
  replacement cannot retain stale live-runtime closures.
- Harness deliberately has no default child factory. A Product that does not
  install a concrete factory cannot spawn a child; this prevents Harness from
  guessing Product transcript, model, tool, approval, or workspace semantics.
- The real immediate recipe runner is implemented by the Product-neutral
  `CollaborationRecipeCatalog` / `ImmediateRecipeExecutor` and Coding's
  non-persistent CLI adapter. It uses Host-only completion payloads for fan-in,
  never wakes a root model to duplicate synthesis, and recursively closes
  every child on success, failure, timeout, or cancellation.
- The Product-neutral `WorkspaceLeasePort` and Coding
  `CodingGitWorktreeLeasePort` are implemented. The current target path uses a
  managed detached worktree at immutable `base_oid`: clean worktrees are
  removed, changed worktrees are retained, and `workspace_ref` plus immutable
  `artifact_refs` flow through facts and completion notices. The transitional
  `change_set_ref` remains nullable but Coding leaves it empty.
- `/agents` is the Product-neutral command and full-screen, read-only Agent
  Tree owned by `loushang.harnesstui.multiagent`. It initializes from
  authoritative live records, subscribes to ordered `AgentFact` updates, and
  displays status, activity, usage, summaries, and workspace/artifact
  references. Coding is its first Product adapter: it supplies the current
  session runtime, while other Products reuse the command and surface with
  their own runtime bindings. The surface unsubscribes when closed.

### Phase 1A — Pure Control Core

### New Modules

```text
src/loushang/harness/multiagent/
  __init__.py
  types.py
  registry.py
  control.py
```

### Scope

- Implement `AgentPath`, incarnation-safe references, registry
  reservation/commit/rollback, open/closed state, authority checks, limits,
  progress/usage accounting, and immutable fact/notice shapes.
- Implement the lifecycle transitions as a pure synchronous control plane:
  spawn, begin round, progress, terminal, interrupt fact, message routing, and
  close.
- Key terminal idempotency by `(agent incarnation, run round)`, not only by
  path.  A stale callback is ignored and cannot mutate a closed or replacement
  agent.
- Keep `AgentFact`, `AgentInputMessage`, and `AgentCompletionNotice` as
  distinct contracts.  The core may publish a notice but does not enqueue it
  as a normal message or wake a parent runtime.
- Count only open agents for capacity and per-type child limits; close releases
  both capacity and the child name.

### Phase 1A Exit Criteria

- Reservation rollback, path reuse, authority, limit release, multi-round
  terminal notification, and stale-callback scenarios have focused tests.
- The package imports no session, Product, Work, Method, Channel, tool, or TUI
  package.

### Phase 1B — Run Ownership

```text
src/loushang/harness/multiagent/run_handle.py
```

- Add one `SubagentRunHandle` that owns the live task, abort signal, round
  number, and terminal observer.
- `interrupt()` aborts and awaits the current round while keeping the
  incarnation open; `close()` aborts, awaits, disposes, and only then commits
  the closed control state.
- Every first and follow-up round uses the same observation path.  No wake path
  may start an untracked task.

### Phase 1B Exit Criteria

- Fake-driver tests cover interrupt, close-vs-complete races, follow-up after a
  completed round, and exactly-once notice delivery.
- There are no fire-and-forget tasks without a handle owner.

### Phase 1C — Context And Session Adapter

```text
src/loushang/harness/multiagent/context.py
src/loushang/harness/session/multiagent.py
```

- Implement fresh/fork context construction with transcript watermark and
  deterministic history filtering.
- Directly compose existing `HostRuntime`, `HostInputQueue`, Agent mailbox,
  transcript access, approval handling, and the control fact stream. A Product factory
  adapts its already-prepared session/`run_agent()` round through the narrow
  `SubagentRoundDriver`; do not introduce a phase-one attachable
  `AgentExecutionPort` abstraction.
- Return the driver, optional input-activity capability, and initial workspace
  reference through an explicit `SessionSubagentBinding`; return workspace
  release and cleanup errors through `SubagentDisposeResult`, without probing
  implementation attributes.
- Implement session-owned spawn, send, wait, list, interrupt, and close.
- Translate completion notices through `AgentInputFacade` into the hidden
  system mailbox; its policy decides whether an idle parent is awakened.
  Recipe executors may await terminal facts directly and must not also
  synthesize a parent turn.
- Provide a `before_release` hook composer that closes session-owned children
  before the existing Product release hook. Product composition installs this
  when it supplies its concrete child factory; the generic lifecycle
  coordinator remains unchanged.

### Explicitly Deferred

- LRU residency and transparent reload.
- Durable execution and cross-process recovery.
- Work scheduler dependencies, retry, and acceptance.
- Method plans.

### Phase 1C Exit Criteria

- Focused unit/scenario coverage for all Phase 0 behaviours.
- A child can run in background, communicate with its parent, notify exactly
  once on terminal state, and be explicitly interrupted/closed.
- No new dependency from `harness.multiagent` to Product, Work, Method,
  Channel, or TUI packages.

## Phase 2 — Coding, Workspace, And TUI

### Product Integration

```text
src/loushang/coding/multiagent.py
src/loushang/coding/worktree.py
src/loushang/harnesstui/multiagent/
  __init__.py
  projection.py
  surface.py
```

- Add the Harness-owned collaboration tool surface (schema, authority and
  control calls), then register its admitted subset through Coding's existing
  live tool registry, closing over the active control instance:

  ```text
  spawn_agent
  send_message
  wait_agent
  list_agents
  interrupt_agent
  close_agent
  ```

- Add initial Coding types: `explorer`, `reviewer`,
  `implementation_worker`, and `test_runner`.
- Implement a Coding Git-worktree lease. A policy-checked explicit `cwd`
  attachment remains a separate future Product option; it is not accepted by
  the model-callable phase-two spawn schema.
- Project `AgentFact` into the shared `harnesstui.multiagent` agent tree by
  reusing existing screen surfaces, status line, Markdown rendering,
  scrolling, and approval UI. Product adapters only bind their current live
  runtime; they do not own or reimplement `/agents`.

The first Product slice installs non-writing `explorer`, `reviewer`,
`synthesizer`, `proposer`, `critic`, and `judge` types. All receive `read`,
`grep`, `find`, and `ls`; `explorer` also receives Coding's existing `bash`
definition for investigative commands, Python analysis, and permitted
retrieval. It does not receive dedicated `write` or `edit` tools, and its role
prompt forbids using shell redirection or in-place editing to bypass that role
constraint. Bash still follows the Product's configured policy and approval
chain; the role prompt is not a filesystem sandbox. The Product also admits
`implementation_worker` with Coding's normal write tools and `test_runner`
with shell/read tools, but both are forced into system-managed isolated Git
worktrees by `AgentTypeSpec.workspace_mode`.
The model selects the admitted type, never the physical worktree path or
branch. The Product factory remains explicit; a generic Harness default
factory is not part of this phase.

### Phase 2A Manual Validation

```console
# Product-neutral facts, run ownership, workspace propagation, and TUI surface.
uv run pytest \
  tests/harness/multiagent \
  tests/harness/session/test_multiagent.py \
  tests/coding/test_multiagent.py \
  tests/coding/test_worktree.py \
  tests/harnesstui/multiagent -q

# Interactive smoke test through the first Product adapter (Coding).
uv run loushang
# Ask the root model to spawn an explorer/reviewer/implementation_worker,
# then enter:
/agents
```

The real-Git test creates an actual temporary repository and worktree, then
verifies clean release. Fake-backend tests deterministically cover changed
worktree retention and branch references. Applying or merging retained
changes is intentionally not a generic multi-agent action; Coding will expose
that later through Product-specific review and approval semantics.

### Exit Criteria

- Parallel exploration, independent review, and test execution work from a
  Coding session.
- A worker can receive a managed worktree; unchanged leases are released and
  changed leases are retained and reported to the parent.
- TUI shows tree state, progress/activity, usage, terminal summary, and
  workspace references.

## Phase 2B — Git Workspace Handoff

The detailed design is
[Workspace Collaboration And Git Handoff](workspace-collaboration-and-git-handoff.md).
This checkpoint completes only the two workspace profiles already needed by
Coding:

```text
parent + current   # shared_implementation_worker
agent + detached  # implementation_worker / isolated test execution
```

### Scope

Implementation checkpoint (2026-07-27):

- `GitWorkspaceManager` now owns durable allocating/active/capturing/retained/
  applying/applied/discarding records, detached acquire, restart reconciliation,
  immutable descriptor/patch/manifest publication, strict apply planning, and
  fail-closed discard.
- `CodingGitWorktreeLeasePort` is a thin adapter and uses an XDG state root
  outside project worktrees by default.
- `loushang workspace list|show|diff|apply|discard` provides the Product-owned
  review path; non-interactive apply/discard require `--yes`.
- The isolated-artifact playback covers child terminal references, diff,
  approved apply, and discard over a real temporary Git repository.
- Apply targets normalize to their repository root; plan fingerprints bind
  actual staged, unstaged, and untracked content rather than porcelain labels.
  Transient operations compensate cancellation through `needs_inspection`,
  cross-process lock waits are bounded and cancellation-safe, atomic record
  replacement has a Windows fallback, and Git path capture preserves POSIX
  non-UTF-8 filenames.

- Move reusable Git worktree, patch capture, catalog, preflight, apply, and
  cleanup mechanics into focused `loushang.harness.workspace` modules.
- Keep `CodingGitWorktreeLeasePort` as the adapter from Product-admitted
  `WorkspaceLeaseRequest` to Git requests that contain no `AgentRef`, agent
  type, approval, CLI, or TUI dependency.
- Replace temporary branch identity with a detached worktree at immutable
  `base_oid` and a content-addressed binary patch plus touched-path manifest.
- Move Coding's managed-root default out of the repository and every
  registered worktree; fail closed when configuration violates that boundary.
- Persist `allocating` before Git creation and move it to `active` by revision
  compare-and-set before returning a lease; add cross-process lock, idempotent
  operations, and restart reconciliation for incomplete allocations.
- Capture a bounded immutable artifact for each terminal round. Capture
  timeout or expected Git failure preserves the model result and worktree,
  records `needs_inspection`, and returns a snapshot with empty
  `artifact_refs` rather than failing the child round.
- Bind patch digest, manifest digest, `base_oid`, and repository identity in
  the immutable descriptor addressed by each `artifact_ref`.
- Add opaque `artifact_refs` to `WorkspaceLeaseSnapshot`; stop producing
  `git-branch:` as Coding's change identity.
- Expose Product-approved Coding CLI operations for list, show, diff, strict
  apply, and discard. Apply does not use `--index`, `--3way`, or `--reject`
  and does not commit, merge, push, publish, or automatically discard.
- Treat apply as final handoff after runtime ownership is released; an applied
  workspace cannot accept another child follow-up or capture round.
- Make discard remove the live managed worktree while retaining an immutable
  artifact and tombstone. Permanent artifact purge remains deferred.
- Keep `release` non-destructive for changed, retained, applied, or
  inspection-needed workspaces; only explicit confirmed discard removes their
  live worktrees.

### Explicit Deferrals

- branch-backed agent or group workspaces;
- `WorkspaceGroup`, membership, ref-counting, and group finalization;
- durable branch ownership, commit, push, PR, or automatic merge;
- a cross-Product retained-workspace catalog;
- model-callable apply/discard tools;
- a generic VCS plugin system.

### Exit Criteria

- Real Git tests cover complete artifact capture, strict non-overlap apply,
  tamper/stale-plan rejection, restart reconciliation, concurrent mutations,
  and fail-closed path cleanup.
- One playback covers isolated spawn, terminal artifact reference, diff,
  approved apply, and discard; concurrency and crash cases remain integration
  tests rather than TUI simulations.
- `harness.workspace` imports no Product, multi-agent, Work, Method, Channel,
  AI, or TUI package; Coding remains the policy and experience owner.

### Phase 2B Release Gate

The 2026-07-27 release gate passed against the integrated Harness lane.  Keep
the gate reproducible with these layers rather than treating a rendered
playback as proof of the Git handoff:

```console
# Control, run ownership, Product adapter, and Agent Tree projection.
uv run pytest \
  tests/harness/multiagent \
  tests/harness/session/test_multiagent.py \
  tests/coding/test_multiagent.py \
  tests/harnesstui/multiagent -q

# Git workspace mechanics and the Coding review/approval CLI.
uv run pytest \
  tests/harness/workspace \
  tests/coding/test_worktree.py \
  tests/coding/test_cli_workspace.py \
  tests/coding/test_workspace_operation_compatibility.py \
  tests/coding/test_workspace_path_mutation_compatibility.py \
  tests/coding/test_workspace_tool_pack_compatibility.py -q

# Durable Work regressions and the workspace dependency boundary.
uv run pytest tests/work -q
uv run pytest tests/architecture/test_import_boundaries.py -k workspace -q

# Product-composed terminal projection and real-Git handoff playback.
uv run python scripts/run_tui_playback.py \
  multiagent-tools multiagent-messaging multiagent-followup \
  multiagent-nested-tree multiagent-lifecycle multiagent-quota-recovery \
  multiagent-parallel-review multiagent-debate \
  multiagent-shared-workspace multiagent-isolated-artifact \
  multiagent-shared-parallel-writers multiagent-render \
  --artifacts /tmp/loushang-phase2b-playback \
  --include-frames
```

`multiagent-isolated-artifact` must execute against a real temporary Git
repository and prove, in order: detached child execution, immutable artifact
review, an explicit apply decision, target content materialization, explicit
discard of the live worktree, and continued artifact readability.  The
concurrency, cancellation, tamper, stale-plan, and restart cases remain
real-Git tests under `tests/harness/workspace`; they are not simulated as TUI
frames.

## Independent Gate — Remote Agent Capabilities

Remote Agent access is not coupled to the durable hosted-execution phase. Add
only the weakest interaction contract required by a concrete Product:

1. For an Agent that runs once and returns a result, register a normal admitted
   capability with `invoke(request) -> result`. It is not a multiagent child.
2. If execution must outlive one tool call but does not accept follow-up, add a
   job client with `submit / await_result / cancel` and a stable `RunRef`.
3. If the caller needs steering or follow-up, bind `MultiAgentToolPack` to one
   remote collaboration client for the Session / capability profile and retain
   the existing `spawn / send / wait / list / interrupt / close` semantics.

The tool handler owns bounded input/output projection and injects protocol,
identity, idempotency and authorization metadata; model-visible tool schemas
are not reused as wire schemas. A service may externalize job or actor state,
so asynchronous execution does not require a stateful server process.

Do not mix local/plugin/remote children transparently in one tree in this gate.
Do not introduce `AgentExecutionPort`, AppService, Channel, or Work merely to
support remote placement. See
[Remote Agent Capability Boundary](remote-agent-capability-boundary.md).

## Phase 3 — Durable Work Correlation And Hosted Execution

### Scope

Add durable Work correlation for agent-backed business operations together
with a Host-owned execution backend. Work owns the accepted business lifecycle,
terminal outcome, evidence, and replayable facts. Host infrastructure owns
physical placement, worker leases, process health, and execution attachment.
Neither side duplicates the other's authority. This phase is entered for
durability, attach/recovery, or transparent mixed-placement requirements, not
because an Agent capability happens to be remote.

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

- Implement Work correlation, accepted lifecycle, retry policy, and replay over
  `WorkRuntime` / `EventLogBackend`; map technical execution facts through the
  Product `WorkDomainExecutor` rather than teaching Work about agent workers.
- Add one real Host-owned plugin or remote-worker backend with the attach,
  cancel, checkpoint, fencing, orphan detection, and recovery semantics that
  the admitted durable operation actually requires.
- Extract an `AgentExecutionPort` only if the Host must preserve one logical
  control model while transparently mixing physical backends, and only from the
  proven common behavior of the existing in-process path and that second
  physical backend.
- Preserve workspace/artifact references across detach and re-attach.

### Exit Criteria

- A durable worker can survive session replacement while remaining explicitly
  correlated with, but not authoritative for, its Work operation.
- A later session can attach, inspect state, cancel, or resume according to
  Work policy.
- Process restart never silently loses the task: it recovers or is explicitly
  marked orphaned.

## Phase 4 — Method Orchestration

### Scope

Compile Method plans into durable Work schedules:

```text
agent type + dependency topology + workspace strategy
  + durability + retry + acceptance rule
  -> Work schedule
```

### Target Patterns

- fan-out / fan-in research and synthesis;
- serial Explore -> Implement -> Test -> Review pipelines;
- independent and adversarial review;
- specialist routing and hierarchical aggregation;
- product-specific acceptance and artifact publication.

### Exit Criteria

- Method can declare work-product-specific agent topology and acceptance
  without importing or reimplementing the technical multi-agent runtime.
