# ARD-001: Agent Loop Ownership And Extension Shape

## Status

- Authority: normative — cross-scope Agent/Harness ownership decision
- Design status: accepted
- Implementation status: implemented
- Owner: Loushang Agent and Harness architecture
- Date: 2026-08-26

## Context

A cross-harness architecture evaluation compared `loushang` against
`deepseek-harness` (dsh, a Cordis-based plugin harness where "everything is a
plugin") and `codex-rs/core` (OpenAI Codex's single-product Rust kernel).

In that comparison, `deepseek-harness` treats the agent loop itself as a
replaceable plugin. That observation led to a follow-up question: should
`loushang` also move the agent loop into `loushang.harness` and make the loop
itself replaceable?

The current code already gives a clear answer:

- The full turn/tool driver lives in `loushang.agent/agent_loop.py`
  (`agent_loop`, `agent_loop_continue`, `run_agent_loop`).
- The loop is configured through `AgentLoopConfig`, which exposes injected
  behavior ports: `transform_context`, `prepare_model_call`,
  `before_tool_call`, `after_tool_call`, `stream_fn`,
  `get_mailbox_messages`, `get_steering_messages`, `get_follow_up_messages`,
  and `tool_execution`.
- [ARD-001: Agent Harness and Product Adapter Boundaries](../agent/ARD-001-agent-harness-and-product-adapters.md) already fixed the
  dependency direction as `loushang.agent -> loushang.ai` and
  `loushang.harness -> loushang.agent`, with `agent` forbidden from depending
  on `harness`.

Without a recorded decision, a future architecture evaluation could misread the
ownership as a defect and propose moving the loop into harness or making it a
swappable plugin. This ARD prevents that recurring misjudgment.

## Decision

### 1. `loushang.agent` owns the agent loop; harness does not

The agent loop is an `agent`-layer capability, not a harness capability.
`loushang.harness` is the cross-product product-adapter substrate that prepares
and runs product work; it depends on `loushang.agent` by design. This layering
is intentional:

```text
product adapters
  -> loushang.harness
  -> loushang.agent
  -> loushang.ai

loushang.harness -> loushang.agent   # allowed, required
loushang.agent -> loushang.harness   # forbidden
```

Moving the loop into `loushang.harness` would invert this dependency and
reintroduce the coupling that ARD-001 and ARD-002 removed. The loop stays in
`loushang.agent`.

### 2. The extension shape is "fixed skeleton + injected ports"

The loop is a stable skeleton. Product- and harness-specific behavior is
supplied through the `AgentLoopConfig` injection ports, not by replacing the
loop. The accepted seams are:

- `transform_context` — reshape context before conversion to provider messages.
- `convert_to_llm` — map agent messages to provider message vocabulary.
- `prepare_model_call` — resolve per-call options and durable commit state.
- `stream_fn` — substitute the model stream (e.g. proxy streaming).
- `before_tool_call` / `after_tool_call` — intercept tool lifecycle.
- `get_mailbox_messages` / `get_steering_messages` / `get_follow_up_messages` —
  supply queued input at each sampling boundary.
- `tool_execution` — select parallel or sequential tool scheduling.

These ports are the plugin boundary. They keep the loop product-neutral while
product adapters own policy, payload semantics, and provider behavior.

### 3. The loop itself is not a replaceable plugin

Making the loop itself a swappable plugin (as `deepseek-harness` does for its
`agent-loop` service) is rejected for `loushang`:

- `loushang` is layered around a stable primitive loop, not around a
  "everything is a plugin" runtime.
- A replaceable loop would expand the extension surface without a demonstrated
  need: the current ports already cover model transport, context shaping,
  tool interception, input queues, and scheduling mode.
- Replacing the whole loop would also make the loop's abort, ordering, and
  tool-scheduling invariants someone else's responsibility, weakening the
  guarantees the fixed skeleton provides.

If a future requirement genuinely needs multi-consumer interception inside the
loop, the correct first step is to widen the existing ports or add a
composable event surface **inside `loushang.agent`**, not to relocate or swap
the loop.

## Consequences

### Positive

- The `agent -> harness -> product adapter` dependency direction from ARD-001
  and ARD-002 stays intact and is recorded as an explicit, load-bearing
  decision.
- Future architecture evaluations have a stable reference point and will not
  re-derive "loop ownership outside harness is a defect".
- The loop keeps ownership of its abort, ordering, and scheduling invariants.
- The extension surface stays small and testable.

### Negative

- Cross-harness comparisons may still score `loushang` lower on a
  "everything is a plugin" rubric. That difference is a deliberate design
  choice, not a gap: the two harnesses optimize for different goals.
- Product behavior that cannot be expressed through the existing ports requires
  an explicit `loushang.agent` change instead of a local plugin swap.

## References

- [ARD-001: Agent Harness and Product Adapter Boundaries](../agent/ARD-001-agent-harness-and-product-adapters.md)
- [ARD-002: Harness Product Adapter Substrate](../agent/ARD-002-harness-product-adapter-substrate.md)
- `src/loushang/agent/agent_loop.py` — loop implementation and injection ports
- `src/loushang/agent/types.py` — `AgentLoopConfig`, `AgentContext`, tool hook contexts
