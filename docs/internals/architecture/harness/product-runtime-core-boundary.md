# Harness Product Runtime Core Boundary

## Status

Status: implementation complete for integration into `lane/harness`.

This boundary completes the product-neutral runtime mechanisms needed by a
small product adapter without turning Harness into an Agent loop, an AI SDK, a
session store, or a product framework.

## Ownership Stack

The runtime dependency direction is:

```text
Product adapter
  -> loushang.harness.host          # optional RPC/channel/mode adapter
  -> loushang.harness.session       # Agent-session composition
  -> loushang.harness.runtime       # lifecycle, queue, retry, transitions
  -> loushang.harness.events        # immutable facts and ordered delivery

loushang.harness.session -> loushang.agent -> loushang.ai
```

Related data contracts live with their actual lower-layer owner rather than in
Harness:

- `loushang.foundation.json` owns the strict cross-layer JSON value algebra;
- `loushang.ai.json_codec` owns AI message, content-part, usage, and assistant
  event JSON codecs;
- `loushang.ai.model.ModelSelection` owns stable model references;
- `loushang.ai.auth` owns request-ready credential types and credential-to-header
  resolution;
- `loushang.agent.json_codec.AgentMessageJsonCodec` composes AI messages with
  product-registered custom message codecs;
- `loushang.agent.tool_output.ToolOutputProjector` owns raw tool-result
  projection into transcript, event, hook, and diagnostic-preview views.

AI does not import Agent, Harness, or Product. Agent does not import Harness or
Product. Harness does not import AI or Product.

## Harness Runtime Ownership

`loushang.harness.runtime` owns:

- `ProductRuntimeBindings`, the product-neutral capability record used by
  extension and host-facing runtime surfaces;
- `RuntimeBindingState` and generation-scoped `RuntimeBindingLease` objects;
- `BoundProductRuntimeContext` and `UnboundProductRuntimeContext`, including
  snake-case/Pi-style aliases, conservative unavailable behavior, opaque UI
  delegation, tool/source propagation, and optional callback handling;
- `SessionTransitionHost`, which owns the current opaque session slot,
  reentrant transition serialization, invalidation/disposal ordering, activation,
  rebinding, and idempotent current-session disposal;
- `CoalescingScheduler`, which owns delayed scheduling, pending-request merge,
  cancellation, synchronous fallback, and deterministic drain behavior.

Bindings refresh live within one generation. A captured context sees replacement
binding values until its state is explicitly invalidated. Invalidation makes
old contexts fail with the product-supplied stale diagnostic while newly
captured contexts remain usable.

Session replacement preserves this order:

```text
prepare candidate
  -> emit product before-release/shutdown callback for previous session
  -> invalidate captured runtime contexts
  -> dispose previous session
  -> publish candidate as current
  -> activate candidate runtime
  -> rebind product/channel surfaces
```

Candidate preparation failure leaves the previous session current. Activation
or rebind failure propagates after the candidate becomes current, matching the
accepted Coding contract. Concurrent replacement operations are serialized;
callbacks may safely re-enter the same transition scope.

## Product Ownership

Coding and future Product adapters retain:

- product goals, domain language, completion criteria, prompt and skill content;
- domain-specific tools and activation of shared tool packs;
- model choice, provider registration, auth error presentation,
  risk/approval defaults, and configuration fields/defaults;
- context salience, exact compaction/summary prompts, and artifact semantics;
- transcript header/custom record schemas and codecs, session paths, naming,
  retention, import/clone decisions, and Product query/summary fields; generic
  repository, tree/fork, replay, catalog, and query mechanics live in Harness;
- concrete extension events/decisions, diagnostics classification/remediation,
  commands, controller policy/adapters, UI contexts, and presentation. Shared
  controller state machines and lifecycle order live in Harness.

Coding's `ExtensionRuntimeBindings` is now only a typed specialization of
`ProductRuntimeBindings`. Its extension context classes are zero-logic naming
adapters over Harness contexts. `AgentSessionRuntime` supplies product callbacks
to `SessionTransitionHost` and navigation transactions while keeping every
Coding-specific session decision and projection. `AgentTranscriptDirectoryRuntime`
owns the reusable catalog queries, index refresh, and coalesced refresh
scheduling that it consumes.

## Explicit Non-Goals

Harness runtime does not:

- implement a second Agent loop or model/provider registry;
- read credentials, choose a model, or produce missing-auth guidance;
- serialize Product transcript records, choose Product storage roots, or select
  a storage backend;
- define product prompts, skills, tool defaults, artifacts, commands, or UI;
- interpret Coding session shutdown/start events, cwd recovery, fork/import
  options, diagnostics codes, or index contents. Harness may stage an opaque
  import file, but Product chooses whether and how it becomes a session.

Artifact lifecycle remains a Work concern when generalized. Product artifact
semantics remain in each Product.

## Neutrality Evidence

The independent Research-shaped fixture in
`tests/harness/runtime/test_context.py` constructs bindings, selects tools and a
model, compacts context, refreshes live state, and invalidates a session without
importing Coding objects or vocabulary. Additional Harness tests exercise
concurrent and reentrant transition ordering plus coalesced async/sync scheduling.

Coding compatibility tests cover message JSON round trips, exact type hints,
extension handler contexts, stale contexts, session replacement, shutdown/start
ordering, fork/import/restore, bootstrap, RPC mode, and index-flush diagnostics.

## Validation

This migration is complete only while all of these remain true:

- Harness runtime has no imports from AI, Coding, Design, Research, PPT,
  Cowork, Method, Work, TUI, or channel implementations;
- AI, Agent, and Coding compatibility paths resolve to their designated owners;
- no Product Runtime Core symbol is exported from top-level
  `loushang.harness.__all__`;
- focused Harness, AI, Agent, Coding, and architecture tests pass;
- the full non-live repository test suite passes.
