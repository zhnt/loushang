# ARD-001: Agent Harness and Product Adapter Boundaries

## Status

Accepted

## Reading Note

This ARD records the initial agent/harness split and the thin prepared-run
facade. [ARD-002: Harness Product Adapter Substrate](ARD-002-harness-product-adapter-substrate.md)
extends the target scope of `loushang.harness` to product-neutral host,
adapter, command, lifecycle, and diagnostics contracts. ARD-001 remains
authoritative for the low-level `agent` boundary and for the rule that harness
must not depend on product packages.

[ARD-001: Agent Loop Ownership And Extension Shape](../decisions/ARD-001-agent-loop-ownership-and-extension-shape.md)
fixes the follow-on decision that the agent loop stays in `loushang.agent` with
an injected-port extension shape, rather than moving into harness or becoming a
replaceable plugin.

## Context

`loushang.agent` already provides the stable low-level agent runtime surface:

- `Agent`
- `agent_loop`
- agent messages
- agent tools
- agent events
- abort / cancellation primitives

`loushang.coding` currently contains the V1 product assembly around that runtime,
including sessions, prompts, coding tools, slash commands, extensions, package /
plugin integration, TUI adapters, work projection, and method integration.

Future product lines such as `research`, `ppt`, and `cowork` need the same
agent execution foundation without inheriting coding-specific semantics. The
shared layer must therefore be explicit before coding grows more product
behavior around the low-level loop.

## Decision

### 1. Preserve `loushang.agent` as the stable primitive layer

`loushang.agent` remains the low-level agent runtime package.

It owns:

- agent message, tool, event, and abort primitives
- the stateful `Agent` facade
- the low-level agent loop
- model streaming integration through `loushang.ai`

It must not own:

- coding tools or workspace semantics
- slash commands
- TUI state
- AGENTS.md or product prompt assembly
- package / plugin / extension product policy
- work or method domain projection
- research, ppt, or cowork product semantics

### 2. Use `loushang.harness` as the prepared-run contract

`harness` here means execution scaffolding / carrying structure, not a
test-only harness.

`loushang.harness` owns the prepared agent run contract shared by product
adapters. It depends on `loushang.agent`; `loushang.agent` must not depend on
`loushang.harness`.

The surface is intentionally thin:

```text
AgentRunSpec
AgentRunResult
run_agent(spec)
```

`AgentRunSpec`, `AgentRunResult`, and `run_agent()` are not duplicated as a
second `HarnessRunSpec` layer. They are the single prepared-run contract.

`run_agent()` must reuse the existing low-level loop instead of implementing a
second loop.

Removal note: the former `src/loushang/agent/harness` /
`loushang.agent.harness` compatibility path has been removed. Code should
import from `loushang.harness`.

### 3. Treat coding, research, ppt, and cowork as product adapters

The product line packages are peers:

```text
loushang.coding
loushang.research   # future
loushang.ppt        # future
loushang.cowork     # future
```

Each product adapter may provide its own:

- tools
- prompts
- commands or product controls
- session / artifact model
- UI and protocol surfaces
- extension policy
- projection back into product state

Product adapters may use `loushang.harness` directly for ordinary agent runs.

### 4. Keep `loushang.work` as the cross-product work abstraction

`loushang.work` models work execution facts and projections:

- `WorkOperation`
- `WorkRun`
- `WorkEvent`
- future `ArtifactRef`
- artifact references / work product projections
- work logs
- work projections

It is not a product package and must not depend on `coding`, `research`, `ppt`,
or `cowork`.

Product adapters may write to or project through `work` directly.

Artifact ownership is split across three layers:

```text
method
  defines expected artifacts

work
  records actual artifact references

coding / research / ppt / cowork
  define concrete artifact types and content
```

The first shared work artifact object should be an `ArtifactRef`, not an
abstract `Artifact` base class. Product-specific packages own loading,
rendering, validation, and materialization behavior. If a common behavior
contract becomes necessary later, add an artifact provider protocol instead of
moving product behavior into `work`.

### 5. Keep `loushang.method` optional and above `work`

`loushang.method` describes structured ways to organize work:

- method resources
- `MethodPlan`
- `MethodStep`
- method compile / projection
- method policy hints and gates

`method` is optional for product execution. A product adapter can bypass
`method` and call `loushang.harness` plus `work` directly for lightweight runs.

Use `method` for structured or guided work, such as planning, staged execution,
review gates, or method-specific acceptance criteria. Do not force every
ordinary product turn through `method`.

### 6. Define the dependency direction

Target dependency direction (`A -> B` means `A` may depend on `B`):

```text
loushang.agent.Agent
  -> loushang.agent.agent_loop
  -> loushang.ai

loushang.harness
  -> loushang.agent

product adapters
  -> loushang.harness

loushang.method
  -> loushang.work

product adapters
  -> loushang.method   # optional, only for structured work
  -> loushang.work
```

Expanded product view:

```text
coding / research / ppt / cowork
  -> loushang.harness
  -> loushang.work
  -> loushang.method   # optional, only for structured work
```

Forbidden directions:

```text
loushang.agent -> loushang.harness / loushang.coding / work / method / research / ppt / cowork
loushang.harness -> product packages
loushang.work -> product packages
loushang.work -> loushang.method
product package -> peer product package, unless through an explicit adapter/protocol
```

### 7. Keep `loushang.channel` as protocol and transport, not UI or product runtime

`loushang.channel` remains a target package for cross-client operation/event
delivery. It should support TUI, WebUI, AppUI, SDK, and RPC clients by carrying
work operations and work events across transports such as in-process calls,
stdio/JSONL, HTTP, or WebSocket.

`channel` must not own UI layout, product session internals, agent loop state, or
method planning. It should not directly import every product package. A host
assembly layer registers product adapters and exposes them through the channel
protocol.

Target shape:

```text
UI client / SDK / RPC client
  -> channel client
  -> channel server / host assembly
  -> WorkOperation / WorkEvent
  -> product adapter
  -> loushang.harness
```

## Consequences

### Positive

- Product lines can share agent execution without inheriting coding semantics.
- Coding can keep lightweight turns fast by using harness and work directly.
- Method remains a structured-work layer instead of becoming mandatory runtime
  plumbing.
- Work remains a stable cross-product event/projection layer.
- The first implementation can be incremental: add a thin harness facade and
  connect one narrow coding path later.

### Negative

- Product adapters must do their own domain projection from `AgentRunResult`.
- Some temporary duplication may remain in coding until the harness contract is
  proven.
- Naming can be misunderstood: `harness` must be documented as execution
  scaffolding, not testing-only infrastructure.

## Initial Implementation Scope

The implementation includes:

1. Boundary documentation and dependency direction.
2. A module ownership inventory for current `coding`, `agent`, `work`, and
   `method` code.
3. A thin `loushang.harness` facade with `AgentRunSpec`,
   `AgentRunResult`, and `run_agent()`.

It should not include:

- large file moves
- new product packages
- moving coding tools into agent
- moving slash commands into agent
- moving AGENTS.md prompt assembly into agent
- top-level extension marketplace or dependency isolation
- work/method projection inside `agent`

The ownership inventory is tracked in
[Agent Harness Module Ownership Inventory](agent-harness-module-ownership-inventory.md).
