# Context Compaction Binding

## Status

Implemented by the `harness/context-compaction-binding` wave. Harness owns the
selected, transcript-aware capability. Harness supplies the standard Agent
transcript summary executor; Coding supplies its prompt/profile binding,
file-operation decoration, and extension translation. The wave does not move
Coding prompt content or model/credential policy into Harness.

## Purpose And Requirements

`context.compaction` lets a Product select bounded-context behavior without
copying transcript planning, lifecycle, checkpoint, or diagnostic mechanics.
This component satisfies PDRI-001 through PDRI-012, with particular emphasis
on durable fact protection (PDRI-006), resume snapshots (PDRI-008), and
controlled contribution admission (PDRI-009).

The durable Agent transcript remains the source of truth. A compaction writes
a checkpoint that changes the context projection; it never deletes transcript
records. Memory retrieval and compaction are separate capabilities.

## Slot And Capability Shape

The existing `context.compaction` slot is a session-scoped, single selection
with a `turn` refresh boundary. A selection identifies one mechanism and a
strict JSON configuration:

```json
{
  "implementation": "agent_transcript.turn_aware_summary",
  "implementationVersion": 1,
  "config": {
    "enabled": true,
    "compactPercent": 80,
    "reserveTokens": 8192,
    "keepRecentTokens": 32768
  }
}
```

`agent_transcript.turn_aware_summary/v1` is the standard Harness mechanism.
It computes threshold and overflow decisions, preserves user-turn and tool
result boundaries, prepares a summary input, and commits an Agent transcript
compaction checkpoint exactly once after successful execution.

The initial schema deliberately contains only the four values that control
the established runtime semantics:

| Field | Meaning |
| --- | --- |
| `enabled` | Enables automatic threshold compaction. Manual compaction remains available. |
| `compactPercent` | Percent-of-context threshold. |
| `reserveTokens` | Reserve-based threshold. The lower threshold wins. |
| `keepRecentTokens` | Token budget retained from the newest transcript history. |

Unknown fields, non-integral token values, invalid percentages, and unsupported
mechanism versions fail profile binding. There is no implicit fallback to a
different mechanism.

## Ownership And Ports

Harness owns the mechanism and all product-neutral behavior:

- budget normalization and automatic threshold / one-shot overflow decisions;
- transcript cut-point planning, including previous checkpoints, complete turns,
  tool result non-cut boundaries, and split-turn preparation;
- cancellation, single-flight lifecycle, checkpoint commit ordering, retry
  continuation decisions, common runtime events, and diagnostics;
- mechanism identifier, version, configuration validation, snapshot semantics,
  and binding lifecycle.

The Product supplies three bounded bindings:

1. a summary profile, selected model/completion policy, and optional JSON-safe
   summary decoration for the Harness executor;
2. an optional pre-compaction adapter, such as a Product extension hook;
3. an optional post-commit projection adapter.

The executor callable is the public
`loushang.harness.session.ProductCompactionExecutor` contract. Product adapters
depend on that narrow callable shape; the internal positional executor used by
the transcript mechanism remains an implementation detail of composition.

The Harness executor may call the stable AI completion surface, but it cannot
choose a different cut point or append a transcript record. Only Harness
commits the checkpoint. Coding therefore retains its code-change/file-operation
summary format, prompts, model/auth policy, extension event translation,
commands, settings defaults, and UI/RPC projections.

Branch summarization is not context compaction: it cannot produce a compaction
checkpoint. It is nevertheless a standard Agent transcript operation owned by
the same Harness summary runtime; a Product selects its prompt/profile and
domain detail decoration.

## Binding, Refresh, And Resume

The selected mechanism ID and version are session-stable in the current Coding
binding because a resumed transcript must retain the same checkpoint semantics.
The slot declares a `turn` refresh boundary, but this first adoption binds the
mechanism for the session lifetime. A future Product refresh may apply only at
an idle turn boundary and must retain implementation/version compatibility with
existing checkpoints; it must fail rather than cancelling or replacing an
active compaction.

The selected JSON configuration supplies the mechanism policy. Coding's
`CompactionSettings` are higher-priority, field-level Product overrides:
`None` inherits the selected capability value, while a concrete value overrides
that field. Changing enablement therefore does not freeze unrelated capability
thresholds into Product settings.

The resolved runtime profile is persisted as session metadata. It records only
the mechanism ID, version, and JSON configuration; it never serializes prompt
text, credentials, model objects, executors, or extension instances.

## OEM And Extension Admission

The first implementation admits Product and trusted OEM selection of registered
Harness mechanisms. OEM configuration must pass the selected mechanism's
schema. Extensions may contribute ordinary Product hook instructions through
the Product adapter, but they may not register arbitrary Python planners,
executors, or transcript writers.

A later trusted-provider contract may admit an additional mechanism only after
it declares a versioned schema, lifecycle behavior, permission grant, and
contract suite. This restriction prevents `context.compaction` from becoming a
generic code-execution injection point.

## Failure And Transaction Rules

- Cancellation, executor failure, invalid preparation, and hook cancellation
  leave the transcript and current context projection unchanged.
- A successful executor result is appended once as a checkpoint and the context
  projection is refreshed before post-commit adapters run.
- A failed post-commit adapter is reported as a Product diagnostic and must not
  retry the append.
- Overflow recovery performs at most one compact-and-retry attempt per run.
- A branch-context summary is visible context but never a compaction boundary.

## Required Contract Tests

- configuration validation and JSON snapshot round-trip;
- default threshold parity with Coding's current settings;
- complete tool turn preservation, split-turn preparation, and previous-summary
  continuation;
- cancellation/failure leaves no checkpoint; successful execution appends one;
- overflow recovery and retry do not append duplicate summaries;
- an independent neutral executor can bind the standard mechanism;
- Coding retains its prompt/model executor but contains no private planner or
  `CodingCompactionRuntime` facade after cutover.
