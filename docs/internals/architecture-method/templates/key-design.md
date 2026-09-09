# <OWNER-KD-NNN>: <Design Concern>

> Template: use in the owning scope's `key-designs/` when a separate document
> helps. A small concern can be a section in an existing scope document or ARD.
> Combine sections, link canonical definitions and remove unused instructions.

## Status And Scope

- ID: `<stable owner-qualified ID>`
- Authority: normative
- Design status: draft
- Implementation status: not-started
- Owner / scope: `<accountable design owner and governed scope>`
- Governing decisions / contracts: `<canonical links>`

Choose implementation status independently of design status. Label a proposed
mechanism as a candidate until its specific contract is accepted.

## Problem And Significance

State the concern, intended outcome, constraints, affected scopes and exclusions.
Explain why its impact, failure cost, reversibility, quality goals or uncertainty
needs focused design. Reference the ARD's drivers and alternatives when present.

## Mechanism And Responsibilities

Explain how the mechanism works and why its parts establish the intended
behavior. Identify state and resource owners, permitted mutations, collaborators,
and initiation, termination and cleanup responsibilities as applicable. Link
canonical component responsibilities and specifications.

For a cross-cutting mechanism, list participants, shared obligations and allowed
variations/exceptions; link component specs to the common rules instead of
duplicating them in each component.

## Critical Scenarios And Boundaries

Describe the main path and relevant failure, concurrency, cancellation, retry
and recovery cases. Make ordering, race outcomes, invariants, dependency rules
and operating limits explicit where they matter. Choose diagrams that answer
these questions; do not add diagrams or runtime cases just to fill a checklist.

## Trade-Offs And Evolution

Link governing ARDs without duplicating their options and historical rationale.
Explain applicability limits and necessary compatibility or migration rules.
Keep delivery sequencing in a linked plan.

## Verification And Open Questions

Map important claims to analysis, scenarios or executable checks. Distinguish
observed results from planned validation and record their limits. Identify
unverified assumptions, resolution owners and closure/reconsideration triggers.
Resolve architecture-changing uncertainty before claiming implementation readiness.

## Review And Acceptance

Link review evidence for the specified revision, including the consistency of
related mechanisms. Record acceptance here or link the governing acceptance
record: owner, date, exact revision and accepted scope or clauses. Do not infer
blanket acceptance from an ARD's selected option or fabricate approval evidence.

Keep candidate changes distinct from the effective accepted contract. Changes
to important accepted contracts follow the decision and acceptance rules;
editorial clarification does not require a new ARD. Preserve revision references
and link successors when the design is replaced or retired.
