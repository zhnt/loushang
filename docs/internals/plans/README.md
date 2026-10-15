# Internal Plans

[Internals](../) | [Public docs](../../)

This directory contains implementation plans for documentation and development work.

- Current internal plans live directly in this directory.
- Historical plans moved from the former `docs/superpowers/plans/` live in [archive](./archive/).

## Current Plans

- [Loushang `/goal` Command Plan](./2026-10-15-goal-command-plan.md) proposes durable Session goals, safe continuation, lifecycle controls, budgets and evidence-based completion. [Three independent design reviews](./2026-10-15-goal-command-reviews.md) track findings and revision closure; implementation remains future work.
- [Third-party Worker Admission Delivery](./2026-10-13-third-party-worker-admission-goal2.md)
  tracks Goal 2's explicit native author/operator flow, real Session lifecycle
  evidence and remaining delivery gates.
- [Resume Compatibility And Background Activation Design](./2026-10-12-resume-compatibility-and-activation-design.md)
  proposes ordinary resume under the current environment, background pure
  planning, reuse of existing prepare owners, and shared Embedded/LMUX
  continuation semantics. Independent GPT-6 Astra review evidence is recorded
  in [Resume Compatibility And Activation Review](./2026-10-12-resume-compatibility-and-activation-review.md).
- [Model Input Persistence And Capacity Recovery Tracking Draft](./2026-08-15-model-input-persistence-capacity-recovery.md)
  is the local umbrella-issue draft for the PR #451 persistence, failure,
  selection, and bounded-recovery follow-up.
- [Loushang AI Quality Hardening Charter](./2026-06-20-loushang-ai-quality-hardening-charter.md) is the accepted branch entrypoint.
- [Loushang AI Quality Hardening Execution Plan](./2026-06-20-loushang-ai-quality-hardening-execution-plan.md) is the detailed Plan-ID sequence and gate checklist governed by the charter.
- [Loushang AI Core Freeze Goal](./2026-06-24-loushang-ai-core-freeze-goal.md) is the accepted execution document for the `ai/core-freeze-v1` branch.
