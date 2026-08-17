# Harness Context Budget And Accounting Boundary

## Status

Status: accepted for `lane/harness`.

This document defines deterministic context compaction-budget accounting and
the neutral result record for context usage estimation as
`loushang.harness.context` responsibilities. Coding keeps model adaptation,
message token estimation, compaction decisions, transcript policy, packing, and
summarization.

## Budget Decision

`loushang.harness.context.budget` owns:

- `CompactionBudget`;
- `calculate_compaction_budget`;
- normalization of context-window, percentage, and reserve inputs;
- selection of the more conservative percentage or reserve threshold.

The calculation is deterministic. It does not decide whether compaction is
enabled, when a product should invoke compaction, or how context is rebuilt.
The optional `settings` object remains a compatibility input whose
`compact_percent` and `reserve_tokens` attributes are read without importing or
interpreting a Coding settings class. Explicit keyword values continue to take
precedence over that object.

The existing `CompactionBudget` name is retained because the record describes
the threshold for a context compaction operation, not the total allocation or
contents of a general context bundle.

## Usage Estimate Decision

`loushang.harness.context.usage` owns `ContextUsageEstimate`, a frozen record
containing:

- total estimated context tokens;
- tokens taken from the latest observed usage;
- estimated trailing tokens;
- the index of the latest usage-bearing item, when known.

Harness owns only the record. Coding remains responsible for inspecting
`AgentMessage`, choosing the last trustworthy assistant usage, estimating
message content, and constructing the record. Harness therefore does not import
`loushang.agent` or `loushang.ai` for this migration.

## Coding Adapters

The former `loushang.coding.compaction.policy` and generic
`loushang.coding.compaction.types` facades are removed. Products import budget
and usage records from `loushang.harness.context` and transcript maintenance
records from `loushang.harness.transcript` directly.

Coding internal consumers import the focused Harness owners directly:

- compaction threshold checks call the Harness budget calculator;
- session context-usage assembly calls the Harness budget calculator;
- the Coding message estimator constructs the Harness usage-estimate record.

`loushang.coding.compaction` no longer re-exports Harness records. Products
import Harness-owned classes and functions from their canonical owners; Coding
keeps only its prompt/profile and output-quality policy.

## Coding-Owned Behavior

This migration does not move or redesign:

- `CompactionSettings`, defaults, configuration merge, or enablement policy;
- `calculate_context_tokens`, `estimate_context_tokens`, or message heuristics;
- `should_compact` and the decision to trigger compaction;
- model capability lookup or context-window adaptation;
- `ContextUsage`, `ContextUsageSnapshot`, or `CompactionDecision`;
- stale-after-compaction and branch-entry interpretation;
- `CompactionPlan`, message cut points, transcript rebuild, or retry behavior;
- summarization prompts, branch summaries, salience rules, or packing policy.

Context item references, bundles, diagnostics, and general packing contracts
remain deferred. This migration establishes budget and accounting ownership
only and does not complete the broader context boundary.

## Dependency Direction

The target direction is:

```text
coding compaction and session adapters -> loushang.harness.context.budget
coding message estimator              -> loushang.harness.context.usage
```

The two Harness modules are independent standard-library contracts. They must
not import coding, method, work, TUI, AI, agent runtime, provider, or product
packages. No context symbols are added to top-level
`loushang.harness.__all__`.

## Migration Result

The old Coding compatibility imports are intentionally removed. Product and
extension authors import from the canonical owners:

```python
from loushang.harness.context import CompactionBudget
from loushang.harness.context import ContextUsageEstimate
from loushang.harness.context import calculate_compaction_budget
```

The record fields, frozen-record behavior, threshold normalization,
explicit-value precedence, error behavior, and Coding estimator results remain
unchanged; only the ownership path changes.

## Validation

The migration must prove:

- percentage and reserve thresholds preserve their current calculation;
- invalid ranges preserve normalization behavior;
- explicit values still override an optional settings object;
- Product and Coding consumers import the canonical owners;
- Coding token estimation returns the Harness-owned result record;
- threshold decisions and context-usage snapshots remain unchanged;
- Coding internal consumers use the Harness owners directly;
- Harness import boundaries and top-level export discipline still pass.
