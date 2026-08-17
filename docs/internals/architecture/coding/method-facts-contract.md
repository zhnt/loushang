# Method Facts Contract

## Scope

Method facts are structured metadata emitted by `MethodProjector` so a prepared
coding turn and its work log can preserve method, plan, and step identity without
re-parsing method assets.

The facts flow is:

```text
MethodProjector
  -> CodingDomainPreparedTurn.metadata
  -> prompt/print/mode runner parameters
  -> CodingWorkShell operation and lifecycle payloads
  -> work-log JSONL
  -> project_work_plan_runs / plans-json inspect output
```

`loushang.method` owns the meaning and shape of these facts. `loushang.coding`
and `loushang.work` treat them as opaque mappings to persist and replay.

## Stable Public Fields

`plan_facts` has these stable fields:

- `plan_id`
- `method_id`
- `mode`
- `phase`
- `activity`
- `task`
- `metadata`
- `applicability`

`step_facts` has these stable fields:

- `step_id`
- `title`
- `executor`
- `role_variant`
- `step_index`
- `step_count`
- `applicability`

Downstream code may depend on these field names. Adding a new top-level fact is
allowed when it is documented here and covered by projector tests. Removing or
renaming a stable field is a compatibility change.

## Plan Metadata

`plan_facts["metadata"]` is a stable whitelist, not a dump of
`MethodPlan.metadata`.

Currently exposed keys:

- `method_kind`
- `element_type`
- `plan_mode`
- `step_count`

These keys are always present in `plan_facts["metadata"]`. A missing or
unsupported source value is projected as null.

Raw frontmatter, loader-local metadata, internal objects, and experimental
metadata do not belong in `plan_facts`. If a downstream consumer needs a new
metadata value, promote it to this whitelist with a projector test and update
this document.

## JSON Safety

Facts must be JSON-safe before they leave `MethodProjector`.

Allowed values are:

- strings
- numbers
- booleans
- null
- dictionaries with string keys
- lists containing allowed values

Tuple-like method data is projected as JSON arrays. Unsupported internal objects
are not exposed through stable facts. This keeps JSONL work logs and plans-json
inspect output serializable without downstream cleanup.

## Applicability

`applicability` is projected as a JSON-safe mapping with these keys:

- `domains`
- `task_types`
- `contexts`
- `artifact_types`
- `modalities`
- `toolchains`
- `lifecycle`
- `capabilities`
- `complexity`
- `risk`
- `tags`

Sequence fields are lists. `tags` maps string keys to lists of strings.

## Downstream Responsibilities

`CodingDomainApp.prepare_turns()` copies facts from `MethodProjection.metadata`
into `CodingDomainPreparedTurn.metadata`.

The prompt/print CLI paths convert those mappings to `SubmitCodingTurn` values.
Fixed plans use `CodingWorkShell.submit_coding_plan()` so `WorkRuntime` executes
their steps sequentially under one Work run; the single-turn compatibility path
continues to use `submit_coding_turn()`.

`CodingWorkShell` persists facts in:

- `SubmitCodingTurn`
- `WorkPlanStarted`
- `WorkStepStarted`
- `WorkStepCompleted`
- `WorkPlanCompleted`
- `WorkStepFailed`
- `WorkPlanFailed`

`project_work_plan_runs()` replays `plan_facts` into `WorkPlanRun.metadata` and
`step_facts` into `WorkStepRun.metadata`.

Downstream layers should not infer new semantics from the internal structure of
method assets. They should only persist, replay, and inspect the stable facts.

## Non-Goals

This contract is not TUI or RPC method integration.

It does not:

- enable `--method` in screen TUI
- enable `--method` in RPC mode
- add TUI method pickers or step status rendering
- change agent-loop or multi-agent scheduling semantics
- rewrite method asset formats

TUI and RPC method integration remain governed by
[ARD-006: TUI Method Integration Constraints](ARD-006-tui-method-integration-constraints.md).
