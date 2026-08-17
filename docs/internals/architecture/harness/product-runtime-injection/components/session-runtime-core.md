# Session Runtime Core

## Purpose

`loushang.harness.session` supplies the coordination mechanics that turn a
prepared input into an Agent turn and turn Agent observations into durable and
observable Session facts. It is an optional Agent/AI profile, not part of the
neutral conversation, storage, or event cores.

The component has four composable mechanisms:

- `SessionRuntime` is the one owner for an Agent subscription, Host lifecycle,
  ordered RuntimeEvent stream, transcript-commit observation, and the standard
  session controller composition below.

- `QueueController` maintains visible steering, follow-up, and next-turn input
  queues while delegating delivery to an Agent.
- `PromptController` orders interceptors, preflight, busy-turn queueing,
  pre-run compaction, and Agent start hooks.
- `AgentEventRouter` orders transcript commit, runtime publication, extension
  observation, retry, and post-turn compaction checks.
- `ApplicationInputRuntime` routes standard application input through direct,
  trigger-turn, next-turn, steering, and follow-up delivery while one injected
  committer owns durable application-message records.

## Product Binding Contract

Products construct one `SessionRuntime` per Session and inject its transcript,
turn-policy, and after-turn-policy ports. `SessionRuntime` composes the
controllers once; Products do not construct parallel queue, prompt, event, or
event-publisher state. Product callbacks decide extension command syntax, input
preflight, resource-derived system-prompt options, diagnostics, retry rules,
compaction rules, transcript provider, and runtime-event projection.

Harness owns only the ordering contract:

```text
input interception -> preflight -> queue or pre-run -> agent start
agent message end -> transcript append -> runtime observation -> product observers
agent end -> diagnostics -> retry decision -> compaction check
direct application input -> commit -> context refresh -> Product projection
```

An append failure stops later observation. A repeat after an observer failure
may reuse the committed message identity and must not append it again. This is
not a crash-safe ApplicationInput exactly-once protocol; that remains a later,
separate transcript-commit capability.

## Dependency And Lifecycle Rules

- This profile may import public `loushang.agent` and `loushang.ai.types`
  message values, plus Harness host, transcript, and observability primitives.
- It must not import Coding, provider APIs, model registries, authentication,
  concrete stores, shell execution, TUI, Work, or Method.
- The Agent binding is structural (`SessionAgentPort`), not a dependency on a
  concrete Agent-loop implementation. It, the queue delivery callbacks,
  transcript append callback, event publisher, and policy ports are sealed for
  one Session lifetime; they are not refreshable bindings.
- Product/OEM extension behavior is represented only by injected callbacks or
  structurally typed runners. It cannot replace the Session's durable store or
  runtime event publisher after construction.

## Verification

- Harness unit tests exercise SessionRuntime's turn, direct application input,
  transcript-commit publication, and teardown ownership with neutral fakes.
- Coding's `AgentSession` remains a compatibility consumer and provides the
  concrete Coding policy ports.
- Import-boundary tests permit only this narrow Agent/AI dependency allowance
  for `harness.session`.

## Non-goals

This component does not define Product prompt content, extension APIs,
retry/compaction policy, command execution, store selection, persistent events,
or presentation projections. Its ApplicationMessage contract is deliberately
limited to in-process commit and direct-projection idempotence; it does not
claim queue or cross-process exactly-once delivery.
