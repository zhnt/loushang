# Harness Host Runtime Boundary

## Status

Status: implementation complete for integration into `lane/harness`.

This document defines the product-neutral host lifecycle and input-queue ledger
owned by `loushang.harness.runtime`, composed with event facts and ordered
dispatch from `loushang.harness.events`. `loushang.harness.host` is the outer
RPC/channel/mode adapter and does not own the reusable execution mechanism.
Coding remains responsible for Product input semantics, session persistence,
controller policy and adapters, commands, resource activation, extension
policy, and presentation. Reusable controller state machines are defined by
the Host Turn And Session Orchestration Core boundary.

## Control Boundary

The runtime control stack is:

```text
product adapter
  -> loushang.harness.host       # RPC/channel/mode adapter
  -> loushang.harness.runtime    # host state and scheduling mechanism
  -> loushang.harness.run_agent  # prepared run facade
  -> loushang.agent              # agent task, cancellation, LLM/tool loop
```

`loushang.agent` continues to own the active agent task, cancellation signal,
message state, steering/follow-up delivery, and the LLM/tool feedback loop.
Harness must not implement a second agent loop or require Agent to import
Harness.

The Host Runtime coordinates an injected driver. It observes and controls the
driver through callbacks for running an operation, aborting, waiting for idle,
and optional disposal. A product adapter may use the stateful `Agent` facade or
the prepared-run facade behind those callbacks.

## Harness-Owned Types

The records are split by meaning:

- `loushang.harness.events.host` owns `HostStatus` and
  `HostLifecycleEvent`;
- `loushang.harness.events.session` owns `QueueKind`,
  `QueuedMessageSnapshot`, `QueueSnapshot`, `RetryAttempt`, and
  `RetryOutcome`;
- `loushang.harness.runtime.types` owns `HostSnapshot`, `RunState`, and
  `QueueMode`;
- `loushang.harness.host.types` owns only `HostActionResult`, an adapter
  result.

The broader Host status is not projected directly into Coding UI state.
Coding maps running, aborting, and disposing to its accepted running view when
needed.

## Host Runtime

`loushang.harness.runtime.execution.HostRuntime` owns:

- legal host state transitions;
- one-active-run enforcement;
- run identity tracking;
- state-based idle notification that does not couple deferred callers to the
  result or cancellation of the preceding run;
- delegation to an injected async operation;
- abort requests and wait-for-idle coordination;
- host-owned deferred-task settlement during disposal;
- idempotent disposal;
- ordered lifecycle event publication;
- rejection of new work after disposal.

`defer_run_handle()` returns a `HostTaskHandle` for one deferred run. The
handle exposes its reserved `run_id`, observational `wait()` semantics, and
runtime-routed cancellation without exposing the underlying task. Its
`wait()` shields the hosted operation from cancellation of a waiter.
`defer_run()` continues to return the underlying `asyncio.Task` for accepted
compatibility callers.

The injected driver still owns the actual task and cancellation mechanics.
Host Runtime does not inspect prompts, messages, models, tools, diagnostics,
work plans, artifacts, or session storage.

Operation exceptions continue to propagate to the product caller after Host
Runtime records a neutral failure event and returns to idle. An abort request
does not invent a new error contract: it delegates cancellation to the driver
and records the run as aborted when the delegated operation completes.

## Input Queue Ledger

`loushang.harness.runtime.input_queue.HostInputQueue` owns:

- stable queue ids;
- steering and follow-up ordering;
- queue snapshots;
- one-at-a-time and all-at-once ledger consumption;
- identity-first consumption with an optional visible-text fallback;
- next-turn payload buffering.

The queue is generic over its payload. It does not construct AI messages,
parse commands, run preflight policy, select visible text, or deliver messages
to Agent. Coding's queue controller remains the adapter that performs those
actions and mirrors Agent delivery in the Harness ledger.

`loushang.harness.runtime.turn.TurnInputQueue` composes that ledger with injected
delivery, notification, and continue-turn callbacks. `TurnOrchestrator` owns
the neutral interception, preflight, active-run queue, before-run, start-hook,
and delegated execution order. Coding still supplies every message and policy
callback.

## Ordered Events

`loushang.harness.events.OrderedEventBus` owns:

- subscription and unsubscription;
- sync or async listeners;
- serialized scheduled dispatch;
- direct dispatch and drain behavior;
- synchronous dispatch when no event loop is available.

The bus is generic over its event payload. `RuntimeEventPublisher` owns one
stream's event id, timestamp, and monotonic sequence. Harness owns common
Session runtime payloads. `harness.session.event_types` owns
`AgentSessionEvent` as the standard Agent-session projection contract; Product
UI interpretation and extension event mapping remain outside `events`. Common
observers subscribe to `RuntimeEvent`.
Transcript commit observations are scheduled from exact Store receipts after
durable success, so Product projection failure cannot roll back or repeat the
append.

## Coding Adapter

Coding adopts the Host Runtime core as follows:

- `coding.session.types.RunState` re-exports the Harness-owned record;
- `harness.session.QueueController` owns visible queue coordination over
  `HostInputQueue`; Coding injects preflight, extension-command rejection,
  queue-update projection, and its concrete Agent delivery;
- `harness.session.SessionRuntime` owns one scoped Runtime publisher, ordered
  bus, Agent subscription, transcript-commit observation, and the composition
  of HostRuntime, queue, prompt, Agent-event, and application-input controls;
- `AgentSession` delegates prompt/continue lifecycle, abort, idle waiting,
  disposal, and runtime-event subscription to that one Harness component;
- Coding supplies SessionRuntime's Product callbacks for prompt content,
  extensions, retry, compaction, diagnostics, and transcript access;
- resource and extension controllers supply Product discovery, event,
  diagnostic, and binding callbacks to Harness lifecycle coordinators.

Accepted Coding facade behavior remains available. Harness-owned records keep
their Harness `__module__`; a compatibility path is retained only where a
Product-facing import remains part of the accepted API.

## Product-Owned Behavior

This migration does not move or redesign:

- input text/image conversion, preflight, slash parsing, or command handlers;
- Product event dictionaries, wire fields, or presentation projection;
- prompts, skills, tools, active-tool policy, or product defaults;
- retry classification/defaults, compaction trigger policy, summarization
  prompts/model calls, or context salience; Harness owns only the injected
  retry and compaction lifecycle state machines;
- session JSONL, message entries, and concrete tree/fork/clone/resume/import/export
  decisions; generic current-session transition mechanics are defined by the
  [Product Runtime Core Boundary](product-runtime-core-boundary.md);
- resource content/activation and extension decisions, events, bindings, or
  permissions; Harness owns watch/refresh and bind/refresh/invalidate ordering;
- UI state, status text, diagnostics presentation, or artifact semantics;
- work, method, channel, model, provider, or auth behavior.

## Neutrality Evidence

The implementation must satisfy the
[Neutrality Evidence Gate](refactoring-principles.md#neutrality-evidence-gate)
without waiting for another production product:

- Coding exercises the compatibility adapter end to end;
- a product-neutral reference driver exercises Host Runtime without importing
  Coding runtime objects or vocabulary;
- generic queue payload tests use non-Coding objects;
- generic event tests use neutral event records;
- architecture tests forbid product imports from `loushang.harness.host` and
  reject strongly connected components between Harness subpackages;
- no host symbols are added to top-level `loushang.harness.__all__`.

## Validation

The migration must prove:

- legal transitions, concurrent-run rejection, abort, wait, failure recovery,
  idempotent disposal, and post-disposal rejection;
- queue ordering, ids, modes, duplicate identity, visible-text fallback,
  snapshots, clear, and next-turn buffering;
- ordered sync/async event delivery and no-loop behavior;
- Coding class identity and accepted queue/session behavior;
- AgentSession prompt, extension message, retry, abort, idle, and disposal
  behavior remains intact;
- Harness dependency direction and documentation guards pass.
