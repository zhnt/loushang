# Verification And Validation Method

## Status

- Authority: normative — supporting method for verification and validation
- Design status: accepted
- Implementation status: not-applicable
- Owner: Loushang architecture method

Verification checks conformance to specified contracts; validation checks whether
the system serves intended actor goals in its operating context. Establish an
evaluation framework early, with criteria and evidence review independent of
implementation choices. Red/green tests provide development feedback within
this framework; passing assertions alone does not establish requirement coverage.

## Plan Early, Scale With Risk

During requirements and scenario discovery, identify critical success/failure
paths, acceptance criteria, verification methods, environments and accountable
owners. Before substantial implementation, make a minimal evaluation path
executable, including how results are judged and retained. New systems start
with a critical scenario; existing systems first capture relevant behavior,
performance and known failures. Extend coverage with risk and implementation.

| Method | Purpose |
| --- | --- |
| [Architecture review](architecture-review.md), walkthrough and focused experiments | Assess design choices, interactions, assumptions, feasibility and evidence sufficiency. |
| Code review, static analysis and architecture checks | Check implementation quality, dependency rules and boundary constraints. |
| Unit, contract and integration tests | Check local behavior and collaboration against specifications. |
| End-to-end validation | Exercise critical actor goals through relevant logical and physical environment paths. |
| Performance and resource evaluation | Measure latency, throughput and resource use under stated workloads and environments. |

Regression checks span these methods to detect loss of accepted behavior,
compatibility or quality. Distinguish measured baselines from required thresholds;
record workload, environment, measurement procedure and acceptable variation for
meaningful comparisons. A known failure remains a gap, not an accepted outcome.

## Keep Evaluation Independent

- Derive expected outcomes from requirements, scenarios and contracts. Avoid
  merely reproducing implementation logic in test assertions.
- For critical acceptance, prefer an independent evaluator agent or reviewer
  that can inspect requirements, evaluation coverage and raw results. Separate
  agent identity alone does not establish independent judgment.
- Version acceptance criteria, evaluation assets and baselines. Implementers may
  propose corrections, but must not weaken criteria or reset baselines merely to
  obtain a pass; material changes need rationale and accountable owner review.

## Evidence And Closure

Link important requirement IDs to checks and results, identifying the evaluated
revision, environment, limitations and unresolved gaps. Preserve reproducible
commands and relevant raw evidence. Recheck affected behavior after changes and
reuse unaffected evidence; a review, mock or local test supports only its covered
claims and cannot stand in for unexecuted system validation.

Keep a concise evaluation plan and evidence links in the existing scope's
requirements or validation records. Project adoption owns concrete commands, CI
gates, datasets, thresholds and storage locations. Apply
[change tailoring](change-tailoring.md): no separate platform or exhaustive suite
is required for every scope. Acceptance remains with the governing owner.
