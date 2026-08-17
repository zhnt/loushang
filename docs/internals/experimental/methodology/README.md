# Experimental Methodology Notes

## Status

Experimental.

These documents explore method ontology, roles, phases, conductor behavior, and
multi-agent methodology concepts. They are design inputs for `loushang.method`
and future orchestration work, not current runtime contracts.

The terminology is informed by SPEM 2.0, but these notes neither reproduce the
complete SPEM metamodel nor establish a conformance claim.

## Notes

- [Decision-Oriented Review Requirements](./decision-oriented-review-requirements.md)
  captures requirements for reviewing long specs through decision indexes,
  review ledgers, grouped human review, side-conversation recovery, and
  role-based agent review.

## Reading Rule

- Preserve `methods/**` examples as experimental methodology layout examples.
- Do not infer that current CLI/TUI/RPC surfaces implement the full ontology.
- Do not treat phase/activity/task/role/guidance/workproduct terms as required
  runtime schema unless a live `loushang.method` spec or ARD says so.
- Current method resources and projection ownership live in `loushang.method`;
  coding only owns the `domain` bridge.
- Runtime enactment belongs to `loushang.work`. Do not interpret SPEM
  `WorkDefinition`, a transient agent checklist, or a conversation turn as a
  `WorkRun`.
- When a concept conflicts with live boundaries, prefer the canonical Method and
  Work architecture notes, then code and tests.

Current live references:

- [Loushang Method Architecture](../../architecture/method/README.md)
- [Loushang Work Architecture](../../architecture/work/README.md)
- [Coding Domain Component](../../architecture/coding/component-interfaces/domain.md)
- [Domain And Work Projection Objects](../../architecture/coding/core-data-objects/domain-work.md)
- [TUI Method Integration Constraints](../../architecture/coding/ARD-006-tui-method-integration-constraints.md)
