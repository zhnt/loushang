# Host Turn And Session Orchestration Core Boundary

## Status

Status: implementation complete for integration into `lane/harness`.

This boundary completes the product-neutral control mechanics around one host
turn and one active Product session. It extends the Host Runtime and Product
Runtime cores without moving the Agent loop, Product transcript schema, model
policy, prompts, commands, or UI into Harness.

The governing split is:

> Product retains controller policy, Product semantics, and adapters; reusable
> control state machines, lifecycle ordering, cancellation, and coordination
> belong to Harness.

## Harness Ownership

`loushang.harness.runtime` owns:

- `TurnOrchestrator`, which orders interception, preflight, active-run queueing,
  before-run preparation, message construction, pending-input drain, start
  hooks, acceptance reporting, and delegated execution;
- `TurnInputQueue`, which combines the neutral input ledger with an injected
  delivery queue while preserving snapshots, notification, consumption, clear,
  and continue-turn ordering;
- `RetryCoordinator`, which owns attempt state, exponential backoff,
  single-flight delay, cancellation handles, waiter completion, exhaustion,
  and delegated continuation;

`loushang.harness.host.routing.PayloadEventRouter` remains an outer
payload-neutral adapter utility; it is not part of the execution/queue/retry
state-machine core.

The existing `loushang.harness.context.CompactionCoordinator` remains the only
generic compaction single-flight lifecycle. Product compaction adapters reuse
it rather than introducing a parallel Host compaction state machine.

`loushang.harness.resources` owns filesystem snapshot polling and the ordered
`prepare -> load -> discover -> commit` refresh pipeline. Sync entry points
reject async drivers instead of leaking un-awaited operations. Async entry
points support both current and legacy runtime discovery signatures.

`loushang.harness.extensions.ExtensionRuntimeCoordinator` owns:

```text
reload request
  -> invalidate captured contexts
  -> refresh resources
  -> build and bind runtime capabilities
  -> emit Product-supplied session start event
  -> synchronize diagnostics
```

It also owns refresh guards, failure containment, binding refresh order, and
context invalidation delegation. Product adapters supply event values,
diagnostic records, and binding contents.

`loushang.harness.runtime` owns:

- `SessionOperationCoordinator`, which serializes prepare, cancellation,
  replacement, activation, after-commit callbacks, phase-aware failure
  reporting, and rollback of an uncommitted candidate;
- exclusive file-import staging and cleanup without Product transcript
  interpretation;
- async replacement callback validation and callback ordering;
- `NavigationTransactionCoordinator`, which owns one active abort scope and
  deterministic before, commit, success, failure, and final cleanup ordering.

`SessionOperationCoordinator` composes the existing `SessionTransitionHost`.
Cancellation during candidate preparation or replacement cleans up an
uncommitted candidate and staged file without misclassifying cancellation as a
Product runtime failure. Activation and after-commit failures still propagate
after the new candidate becomes current, matching the accepted session
transition contract.

`SessionTransitionHost` also exposes post-release invalidation notifications.
They run after the previous session is disposed and the current slot is cleared,
but before candidate activation. Unlike the existing primary and subscribed
before-invalidate callbacks, these notifications are non-veto observers:
ordinary observer failures are isolated so cleanup projections cannot roll a
transition back after the old runtime has already been released. Cancellation
still propagates. An observer may schedule a later transition, but direct
same-task replacement or disposal re-entry is rejected because the outer
candidate has not yet reached activation.

The release boundary is split around its irreversible step. Product
before-release callbacks and primary/before-invalidate callbacks run while the
old session is still current and may veto the transition. After they succeed,
the host clears the current slot before calling the session disposer. A disposer
failure or cancellation therefore propagates without republishing an object
that may already be partly or fully finalized; an uncommitted candidate is
still rolled back by `SessionOperationCoordinator`.

`loushang.harness.session.SessionLifecycleRuntime` is the higher-level active
session profile over those two primitives. It supplies the common
new/restore/fork/import/dispose transaction and accepts Product store/hooks.
Its default `ForkProfile` supports only `at`; a Product can inject extra fork
positions and a resolver without putting Product transcript semantics into
Harness. See [Session Lifecycle Runtime Boundary](session-lifecycle-runtime-boundary.md).

## Product Ownership

Coding and future Product adapters retain:

- concrete message construction, input transformation, Product preflight
  decisions, prompts, skills, and before-start hook payloads; neutral slash
  parsing now lives in `loushang.harness.commands`;
- retry error classification, retry defaults, Product events, and user-facing
  failure wording;
- compaction thresholds, exact summary prompts, model calls, transcript
  mutation, artifacts, and continuation policy;
- extension event and decision schemas, binding contents, activation and
  permission policy, diagnostic codes, and remediation;
- session header and entry codecs, JSONL compatibility, storage roots, cwd
  recovery, import acceptance policy, summary/index fields, and retention;
- concrete fork/tree targets, branch-summary generation and artifacts,
  commands, control/model/auth, channels, and UI.

`AgentSession` remains the Coding composition root and public Product facade.
`AgentSessionRuntime` remains the Product adapter for concrete fork payload
interpretation, extension events, diagnostics, roots, and presentation. The
reusable active-session transaction and lifecycle state now live in
`harness.session.SessionLifecycleRuntime`.

## Non-Goals

Harness does not:

- implement or import the Agent loop or AI message/model types;
- parse Product commands or choose retryable errors;
- define Product compaction, summary, artifact, or transcript semantics;
- choose resource activation, extension permissions, or Product diagnostics;
- choose session paths, cwd fallback, retention, or index projections;
- expose these symbols from top-level `loushang.harness.__all__`.

## Neutrality And Validation

Harness tests use opaque strings, records, and callbacks rather than Coding or
Agent values. Coding characterization tests verify prompt queueing, retry and
compaction events, resource refresh, extension lifecycle, session replacement,
fork/restore/import, branch-summary navigation, callback order, diagnostics,
and cancellation cleanup.

The migration is complete only while:

- Harness imports no AI, Agent implementation, Coding, Product, Method, Work,
  channel, or TUI implementation;
- Product adapters do not retain a second implementation of the transferred
  state machines;
- focused Harness and Coding tests, architecture boundaries, and the full
  non-live repository suite pass.
