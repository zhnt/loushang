# Loushang Agent Runtime

`loushang.agent` 是一个有状态的 agent runtime，负责：

- 维护对话状态
- 驱动模型流式响应
- 执行工具调用
- 派发生命周期事件
- 支持 steering / follow-up 队列
- 支持代理流适配

## Quick Start

```python
from loushang.agent import Agent

agent = Agent()

def on_event(event, signal) -> None:
    if event["type"] == "message_update":
        delta = event["assistant_message_event"]
        if delta["type"] == "text_delta":
            print(delta["delta"], end="")

agent.subscribe(on_event)
await agent.prompt("Hello")
```

## Core Objects

- `Agent`: stateful runtime facade
- `AgentState`: mutable runtime state
- `AgentContext`: loop input snapshot
- `AgentLoopConfig`: loop execution config
- `AgentEvent`: lifecycle and tool execution events

## Harness Direction

`loushang.agent` remains the low-level runtime package for `Agent`, agent
primitives, and the agent loop.

`loushang.harness` owns the prepared-run contract shared by product adapters:
`AgentRunSpec`, `AgentRunResult`, and `run_agent()`. These are the single
prepared-run contract, not a second `HarnessRunSpec` layer.

The next-stage harness target is broader than the initial facade:
`loushang.harness` is the product-neutral substrate for host, adapter,
command/effect, lifecycle, and diagnostics contracts used by coding and future
product lines. It still must not own concrete product semantics, TUI state,
method planning, work projection, provider auth, or model default persistence.

`loushang.harness` depends on `loushang.agent`; `loushang.agent` must not
depend on `loushang.harness`.

The former `src/loushang/agent/harness` / `loushang.agent.harness`
compatibility path has been removed. Code should import from `loushang.harness`.

See [ARD-001: Agent Harness and Product Adapter Boundaries](ARD-001-agent-harness-and-product-adapters.md).
See also [ARD-002: Harness Product Adapter Substrate](ARD-002-harness-product-adapter-substrate.md).
See also [ARD-001: Agent Loop Ownership And Extension Shape](../decisions/ARD-001-agent-loop-ownership-and-extension-shape.md) — the agent loop stays in `loushang.agent`; its extension shape is fixed skeleton plus injected `AgentLoopConfig` ports, not a replaceable plugin.
Detailed harness refactoring rules now live in
[Loushang Harness Architecture](../harness/README.md).
The current module ownership inventory is
[Agent Harness Module Ownership Inventory](agent-harness-module-ownership-inventory.md).

## Event Flow

Calling `await agent.prompt(...)` emits events in this shape:

```text
agent_start
turn_start
message_start   (user)
message_end     (user)
message_start   (assistant)
message_update  (assistant deltas, zero or more)
message_end     (assistant)
tool_execution_start / update / end   (if tool calls exist)
turn_end
agent_end
```

When an assistant message contains tool calls, tool execution completes before the next assistant turn begins. `agent_end` is the final loop event for the run.

## Listener Contract

Register listeners with `agent.subscribe(listener)`.

- Listeners are invoked only during an active run.
- Each listener receives the active run's abort signal.
- Listeners are awaited in first-registration order.
- Re-subscribing the same listener does not create duplicate callbacks.
- `wait_for_idle()` resolves only after all awaited listeners have settled.

## AgentState Contract

`Agent.state` exposes the current mutable runtime state.

- `state.messages` and `state.tools` return live internal lists.
- Whole-list replacement must use `state.set_messages(...)` and `state.set_tools(...)`.
- `set_messages()` and `set_tools()` copy the top-level list.
- In-place mutations on the returned lists, such as `append()` and `clear()`, intentionally mutate the current agent state.

Relevant state fields:

- `system_prompt`
- `model`
- `thinking_level`
- `messages`
- `tools`
- `is_streaming`
- `streaming_message`
- `pending_tool_calls`
- `error_message`

## Lifecycle Methods

### `await agent.prompt(input, images=None)`

Starts a new run from:

- a string prompt
- a single `AgentMessage`
- a list of `AgentMessage`

Raises when another run is already active.

### `await agent.continue_run()`

Continues from the current transcript.

- If the last message is `user` or `toolResult`, the loop continues normally.
- If the last message is `assistant`, queued steering messages run first.
- If there is no queued steering, queued follow-up messages run next.
- If the last message is `assistant` and no queued messages exist, it raises.

### `agent.abort()`

Aborts the active run, if one exists.

### `await agent.wait_for_idle()`

Waits until:

- the active run finishes
- `agent_end` has been emitted
- all awaited listeners have settled

### `agent.reset()`

Clears transcript state, runtime flags, pending tool calls, error state, and queued steering/follow-up messages.

## Steering And Follow-up Queues

- `agent.steer(message)`: queues a message to run after the current assistant turn completes
- `agent.follow_up(message)`: queues a message to run when the agent would otherwise stop
- `steering_mode` / `follow_up_mode`: control whether queues drain `one-at-a-time` or `all`

When continuing from an assistant-ended transcript, steering messages are preferred over follow-up messages.

## Tool Execution

Tool execution is controlled by `tool_execution`:

- `parallel`: preflight tool calls sequentially, then execute runnable calls concurrently; final tool results are emitted in assistant source order
- `sequential`: execute tool calls one by one
- Per-tool `execution_mode="sequential"` overrides the batch to sequential even when global `tool_execution="parallel"`
- Runtime tools that omit `execution_mode` are normalized at the agent/registry boundary with default `parallel`

Hooks:

- `before_tool_call(context, signal)`: runs after validated argument parsing and can block execution
- `after_tool_call(context, signal)`: runs after execution and can override final result fields

Tool lifecycle events:

- `tool_execution_start`
- `tool_execution_update`
- `tool_execution_end`

## Error And Abort Semantics

- Run failures are surfaced as assistant failure messages.
- `state.error_message` is updated from assistant error messages.
- Aborted runs surface `stop_reason="aborted"`.
- Failed runs surface `stop_reason="error"`.

## Proxy Streaming

Use `stream_proxy()` when the model stream comes from a remote proxy instead of a direct provider connection.

`stream_proxy()`:

- reconstructs standard assistant message events from proxy events
- rebuilds partial assistant messages on the client side
- maps proxy errors and aborts into standard assistant error events
