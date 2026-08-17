# ARD-002: Harness Product Adapter Substrate

## Status

Accepted

## Context

[ARD-001](ARD-001-agent-harness-and-product-adapters.md) established
`loushang.harness` as the thin prepared-run contract between product adapters
and the low-level `loushang.agent` loop:

```text
AgentRunSpec
AgentRunResult
run_agent(spec)
```

That boundary is still useful, but it is too narrow for the next product
direction. `loushang.coding` now contains reusable host mechanics that future
product lines such as `design`, `research`, `ppt`, and `cowork` will also need:

- product adapter preparation and result handoff
- command and command-effect descriptions
- run/session lifecycle coordination
- abort, idle, queue, and steering contracts
- generic diagnostics and status reporting
- product-neutral hooks for model/run options

Keeping those mechanics in `loushang.coding` would make later product lines
depend on coding semantics. Retaining `loushang.runtime` or creating a new
`loushang.product` package would add another abstraction layer before the
existing `harness` boundary is fully used.

The architecture should therefore extend `loushang.harness` instead of
introducing a parallel top-level runtime or product substrate.

## Decision

### 1. Extend `loushang.harness` beyond the thin run facade

`loushang.harness` is the cross-product product-adapter substrate.

The existing prepared-run API remains valid and should stay small. Future
modules inside `loushang.harness` may add product-neutral contracts around that
run API, such as:

```text
loushang.harness.run          # AgentRunSpec, AgentRunResult, run_agent
loushang.harness.adapter      # ProductAdapter / PreparedTurn / AdapterResult protocols
loushang.harness.host         # host/session/run coordination protocols
loushang.harness.commands     # CommandDef / CommandEffect primitives
loushang.harness.lifecycle    # abort, idle, dispose, queue/steer contracts
loushang.harness.diagnostics  # generic diagnostic/status records
```

These names are target ownership markers, not a requirement to create every
module at once.

The landed `loushang.harness.commands` module is intentionally only a command
vocabulary module. It owns product-neutral value types such as `CommandDef`,
`CommandEffect`, `CommandKind`, and `CommandEffectKind`; it does not own a
command registry, command catalog, command handler, slash parser, or command
execution policy.

Detailed refactoring criteria and shared capability boundaries are maintained
under [Loushang Harness Architecture](../harness/README.md). This ARD defines
the accepted subsystem direction; the harness architecture docs record the
working migration rules and inventories.

### 2. Do not retain top-level `runtime` or introduce top-level `product`

No new `loushang.product` package should be created for this substrate.

The existing `loushang.runtime.commands` path is an obsolete temporary location,
not a compatibility surface to preserve. When implementation work begins, its
product-neutral command/effect types should move under `loushang.harness`, and
the `loushang.runtime` package should be deleted rather than kept as a re-export
shim.

### 3. Keep harness product-neutral

`loushang.harness` may define protocols, value objects, and coordination
contracts that product adapters implement or consume.

It must not own concrete product behavior:

- coding tools
- coding command catalog, registry, parser, or execution policy
- slash commands and command handlers
- product prompt assembly or product-specific instruction projection; Harness
  may own reusable `AGENTS.md` discovery and standard resource conventions
- coding session JSONL schema
- extension, package, or plugin policy
- product UI adapters
- TUI layout, render loop, input handling, or screen state
- method planning
- work projection or work event persistence
- AI provider registry, auth, endpoint availability, or default-model storage
- concrete artifacts for coding, design, research, ppt, cowork, or other products

The TUI package remains a pure terminal UI library. Product-specific TUI wiring
belongs in the product adapter, not in `loushang.tui` or `loushang.harness`.

### 4. Preserve the low-level agent boundary

`loushang.agent` remains the owner of low-level agent primitives, the stateful
`Agent` facade, and the agent loop.

`loushang.harness` may use stable agent primitives and the existing loop. It
should not re-export the stateful `Agent` facade as a product host and should
not implement a second agent loop.

### 5. Keep work and method separate from harness

`loushang.work` and `loushang.method` remain separate cross-product layers.

Product adapters may compose:

```text
product adapter -> loushang.harness
product adapter -> loushang.work
product adapter -> loushang.method   # optional, for structured work
```

`loushang.harness` should not import `loushang.work` or `loushang.method` just
to expose product host contracts. If a harness protocol needs to carry a work
run id, method id, or artifact id, it should use opaque identifiers or
protocol-shaped metadata instead of depending on those packages.

### 6. Define migration pressure by neutrality evidence, not consumer count

Code may move from `loushang.coding` into `loushang.harness` before another
production product exists when it is product-neutral and satisfies the
[Neutrality Evidence Gate](../harness/refactoring-principles.md#neutrality-evidence-gate).
A second production consumer is strong validation, not a prerequisite.

Good candidates:

- command/effect value types
- product adapter protocol shapes
- run host lifecycle contracts
- generic abort/idle/dispose state contracts
- generic diagnostic records

Poor candidates:

- concrete coding tools
- coding command catalog and handlers
- coding prompt/resource loading policy
- coding settings and model persistence behavior
- coding transcript and session persistence
- coding TUI controller state

The product goals, prompt and skill content, domain tools, context and risk
policy, artifact semantics, commands, defaults, presentation projections, and
resource conventions that remain product-owned are defined under
[Product Kernel Ownership](../harness/shared-capability-boundaries.md#product-kernel-ownership).

## Dependency Rules

Target dependency direction:

```text
loushang.agent
  -> loushang.ai

loushang.harness
  -> loushang.agent

product adapters
  -> loushang.harness
  -> loushang.work
  -> loushang.method   # optional
  -> loushang.ai       # only for product-level helper calls

product TUI adapters
  -> loushang.tui
```

Forbidden directions:

```text
loushang.agent -> loushang.harness
loushang.harness -> loushang.ai
loushang.harness -> product packages, such as loushang.coding / loushang.design / loushang.research / loushang.ppt / loushang.cowork
loushang.harness -> loushang.tui
loushang.harness -> loushang.work / loushang.method
product adapter -> peer product adapter, unless through an explicit protocol
```

Architecture import-boundary tests should continue to enforce the product-free
harness boundary while allowing `loushang.harness` to grow internally.

## Current Decisions

- `loushang.harness` is the place for cross-product host and adapter contracts.
- `loushang.runtime` should be removed as part of the command/effect migration.
- No `loushang.product` package is introduced.
- `loushang.tui` remains a pure terminal UI library.
- Coding remains the first product adapter and the main migration source, but
  coding-specific behavior stays in `loushang.coding`.
- Model defaults, auth behavior, provider/model registry resolution, and
  endpoint availability stay outside harness. Harness can carry selected model
  options as run inputs, but it does not decide or persist them.

## Phased Direction

### Phase 0: Document and inventory

Record the target boundary in this ARD and update subsystem documentation so
new work does not treat `loushang.runtime` or a future `loushang.product` as a
valid target.

### Phase 1: Command/effect substrate

Move product-neutral `CommandDef`, `CommandEffect`, and related enums from the
obsolete `loushang.runtime.commands` path into `loushang.harness.commands`.
Update internal imports to the new path and delete
`src/loushang/runtime/__init__.py` plus `src/loushang/runtime/commands.py`.
Do not keep `loushang.runtime` as a compatibility shim.

The command substrate now includes value types, descriptors, parsing,
completion, dispatch, and immutable local/session catalog composition under
`loushang.harness.commands`. HarnessTUI binds that substrate to conversation
routes through `ConversationCommandCatalog`. Products retain command selection,
session operation bindings, local action handlers, and final wording; Coding
does not retain a parallel catalog.

### Phase 2: Host and adapter contracts

Introduce minimal product-neutral protocols only when implementation work needs
them. These protocols should describe handoff points, not concrete product
state:

- preparing a turn
- running a prepared turn
- emitting adapter results
- aborting or waiting for idle
- disposing a host
- reporting generic diagnostics

### Phase 3: Coding migration slices

Move only the shared substrate out of coding. Each slice should have focused
tests that prove coding behavior is unchanged and import-boundary tests that
prove harness remains product-free.

The current migration inventory is
[Coding To Harness Migration Inventory](../harness/coding-to-harness-migration-inventory.md).

### Phase 4: Independent neutrality validation

Do not block product-neutral extraction on a second production consumer.
Validate each proposed Harness contract through the current Coding adapter and
an independent contract probe that does not use Coding runtime objects or
vocabulary. The probe may be a minimal `design`, `research`, `ppt`, or `cowork`
reference adapter, a product spike, or a product-neutral test fixture.

When a real additional product begins implementation, validate and refine the
contract again. If the contract requires Coding policy or only serves Coding,
split it or keep it Coding-local.

## Consequences

### Positive

- Future product lines can share host mechanics without importing coding.
- The existing `harness` boundary becomes more useful instead of creating a new
  top-level abstraction layer.
- `agent`, `work`, `method`, `tui`, and product packages keep clear ownership.
- The migration can proceed in small slices with import-boundary tests.

### Negative

- `harness` is no longer only a thin run facade, so documentation and module
  names must make the internal split clear.
- Removing `loushang.runtime` is a breaking cleanup for any stale importers.
- Independent contract probes add work before a real additional product exists,
  and some contracts may still need refinement when one arrives.

## Relationship To ARD-001

ARD-001 remains authoritative for the original agent/harness split:

- `loushang.agent` owns the low-level agent runtime.
- `loushang.harness` depends on `loushang.agent`, never the reverse.
- product packages depend on harness, not the reverse.
- harness does not own product semantics.

This ARD extends ARD-001 by defining the next-stage scope of
`loushang.harness` as a product-adapter substrate, not only the initial
`AgentRunSpec` / `AgentRunResult` / `run_agent()` facade.
