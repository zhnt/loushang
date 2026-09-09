# Architecture Change Tailoring

## Status

- Authority: normative — supporting method for proportional architecture work
- Design status: accepted
- Implementation status: not-applicable
- Owner: Loushang architecture method

Apply the [canonical method](README.md) in proportion to the change's effects
and uncertainty. This guide selects work; it does not assign project owners,
choose architecture, or establish local delivery gates.

## Select The Path

Identify the intended outcome, affected scope, existing accepted contracts,
reversibility and important uncertainty. Classify the effect, not the number of
files: a small serialization edit can change a durable boundary.

| Change path | Minimum architecture work | Review and evidence |
| --- | --- | --- |
| Internal implementation change preserving accepted contracts and responsibilities | Reference the governing contract; update Current evidence when facts change. | Check preservation of the relevant behavior and dependencies; no new ARD unless an accepted boundary or consequential structural choice changes. |
| Component responsibility or capability contract change | Update affected requirements, ownership, observable contract, interactions/dependencies and traceability; update the parent view when a child's public contract changes. Record consequential alternatives in an ARD. | Review the changed boundary and collaborators; use success/failure scenarios and contract evidence appropriate to its effects. |
| Cross-scope ownership, dependency, trust or durable compatibility change | Update directly affected scopes and their common parent, a decision record, dependency/compatibility rules and remaining deltas. | Include the responsible scope perspectives, critical failure/migration evidence and a synthesis check of the combined design. |

Use the strongest applicable path for affected concerns. An internal change
with concurrency, recovery or resource-lifetime risk still needs the relevant
failure evidence even when its public API is unchanged.

For a new scope, work through requirements, black-box framing, component
discovery and contracts. For an existing scope, reuse accepted material and
revisit only what the change challenges. If examination exposes a previously
unknown boundary change, revise the path and record the expanded impact.

## Select Artifacts And Stages

The end-to-end stages are a reasoning sequence, not a requirement to produce
one file or one approval ceremony per stage. A small capability can use sections
in one architecture document; a complex scope may use the full package.

- Reuse applicable requirements, vocabulary and principles by reference.
- Keep drivers and alternatives inside the ARD when a decision is needed.
- Use a [key design](key-designs.md) when an important or high-risk mechanism
  needs focused explanation; embed it in an existing document when sufficient.
- Write or update a specification when observable behavior needs precision;
  link it from the ARD instead of duplicating it.
- Review only relevant views, increasing depth for material uncertainty or
  hard-to-reverse effects. One person may cover several views.
- Use a narrow experiment when uncertainty prevents a sound choice; feed the
  conclusion back into requirements, options or contracts as needed.
- Keep implementation sequencing in the delivery plan and results in evidence.

Stages may iterate, combine or reuse prior work. Record the reason for omitting
a material concern; routine low-risk work does not need a separate tailoring
report or a checklist of every inapplicable artifact.

## Prioritize Quality Scenarios

For important quality scenarios, distinguish business importance (whose outcome
is affected and the cost of failure) from technical difficulty (how hard the
scenario is to satisfy, including unresolved assumptions and evidence gaps).
High/medium/low with a short rationale is sufficient; do not manufacture a
numeric total. Unknown difficulty needs investigation rather than a low rating.

Analyze important, difficult scenarios first, while still checking applicable
hard constraints. Relevant business or scope owners confirm priorities; AI may
propose them with rationale. Customer participation follows the adoption profile.
Retain the selected scenarios and reasons for material exclusions in the review
frame, reusing requirement references rather than copying their definitions.

For many scenarios, an optional utility tree groups quality goals, refined
concerns and referenced scenarios. A short list suffices for a small scope;
neither a separate file nor a voting ceremony is required. Revisit priorities
when new evidence or stakeholder concerns change the analysis needs. Apply the
[quality-attribute analysis](architecture-review.md#quality-attribute-analysis)
to the selected scenarios within the existing review process.

## Generic Examples

- Replacing a parser's internal lookup structure while preserving its accepted
  inputs/errors follows the internal path; contract checks establish behavior.
- Adding a cancellation contract to an operation revisits state, ownership,
  caller behavior and failure interactions, even if only a few files change.
- Moving persisted-state authority between scopes requires a common-parent
  decision, compatibility/migration evidence and explicit Current/Target deltas.

These illustrate classification, not mandatory implementation designs.

## Completion And Proportionality

The selected work is complete when the affected contract and ownership are
clear, required decisions are accepted, relevant evidence supports the claimed
scope, and remaining uncertainty/deltas are explicit. A design review may close
design findings while implementation evidence is still pending; do not combine
those completion claims.

Use the [review method](architecture-review.md) and the canonical Architecture
Definition of Done for applicable boundary changes. Local tooling, named
reviewers, customer participation and rollout commitments belong in the project
adoption profile. Tailoring does not waive inherited constraints or required
acceptance; it keeps the work proportional to them.
