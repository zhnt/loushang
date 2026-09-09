# Key Design Method

## Status

- Authority: normative — supporting method for key designs
- Design status: accepted
- Implementation status: not-applicable
- Owner: Loushang architecture method

A key design explains the mechanism, responsibilities and constraints of one
structurally important or high-risk concern. Apply the [canonical method](README.md)
and [change tailoring](change-tailoring.md); use the
[key design template](templates/key-design.md) when a separate document helps.
The examples here illustrate the method and do not select a project's design.

## Select The Concern

Judge architectural significance by effects, not code size or technical novelty:

| Signal | Reason for focused design |
| --- | --- |
| Broad impact | Several components must agree on collaboration, state or resource ownership. |
| High failure cost | Incorrect behavior threatens consistency, authority, recovery or data preservation. |
| Costly change | A public protocol, persistent format or structural commitment is difficult to reverse. |
| Critical quality outcome | A performance, capacity or reliability goal depends on an explicit mechanism and its operating limits. |
| Material uncertainty | An unverified assumption could change the architecture or invalidate a selected option. |

These signals call for deeper design, not automatically another file. Use an
existing scope document or ARD section when it can explain the concern clearly.
Create a separate key design when the mechanism needs sustained explanation,
independent review or reuse by several contracts. Group tightly related aspects
of one mechanism; do not turn every interface or implementation helper into a
key design.

Start when the concern becomes apparent, including during boundary framing or
component discovery. Refine it as ownership and interactions become clear; it
need not wait for the component model to be final.

## Distinguish Artifacts

| Artifact | Owns |
| --- | --- |
| ARD | The decision question, drivers, compared options, selected trade-off and historical rationale |
| Key design | How the selected or explicitly proposed mechanism works across responsibilities, state, interactions and constraints |
| Specification | The precise observable contract that callers or collaborators can rely on |
| Component model | The scope's stable responsibility units and their structural relationships |
| Delivery plan | Implementation sequence, tasks and rollout steps for a delivery slice |

For a generic cancellation concern, an ARD may explain the choice of cooperative
cancellation; the key design explains propagation, completion races and cleanup
ownership; the specification defines the caller's observable result. These may
be sections in one document. Separate them only when their size or maintenance
needs justify it, retaining one canonical definition for each contract.

Reference existing drivers, alternatives, component responsibilities and exact
contracts. Explain how they compose without copying their normative definitions.
When a combined document records an ARD, preserve the accepted decision and its
rationale under the [decision method](architecture-decisions.md), even if the
mechanism later needs a new revision or separate maintained document.

## Minimum Content And Depth

Cover these questions with detail proportional to the concern:

1. **Problem and scope:** What outcome and constraints govern the design? What
   is excluded, and which scopes and contracts are affected?
2. **Mechanism and responsibility:** What makes the design work? Who owns state,
   may change it, initiates work, and terminates work or releases resources?
3. **Critical interactions:** How does the main scenario run? Where relevant,
   define concurrency, failure, cancellation, retry, exhaustion and recovery.
   Specify ordering and race outcomes when correctness depends on them.
4. **Invariants and boundaries:** What must remain true, what dependencies are
   allowed or forbidden, and what operating or resource limits apply?
5. **Trade-offs and evolution:** Which ARDs govern the mechanism? What limits
   its applicability, and what compatibility or migration rules must hold?
6. **Verification and open questions:** Which analysis, scenarios or checks
   establish each important claim? What remains assumed, who resolves it, and
   what new evidence would trigger reconsideration?

Select diagrams by the question: state transitions for lifecycle rules,
sequences for ordering and collaboration, structure for responsibility and
dependency relationships. A document need not contain every kind of diagram.
Avoid code inventories and function-by-function implementation instructions.

For data-intensive mechanisms, reference the [domain/data model](domain-data-modeling.md)
for identities, lifecycle, fact ownership and consistency rules. Explain how the
mechanism realizes those contracts without duplicating the model.

An uncertain runtime property may need a narrow experiment before acceptance.
Do not require a spike for every design; conceptual ownership and protocol
questions can first be resolved through explicit contracts and reasoning.
Separate executed validation from planned checks and state the evidence's limits.

## Readiness And Review

A design is ready for implementation when an implementer can proceed without
inventing consequential architectural semantics, and a reviewer can identify
how to verify the claims and under what conditions the mechanism fails.
Check that:

- ownership, invariants, critical outcomes and relevant operating limits are
  explicit and consistent with the governing contracts;
- related mechanisms compose without contradictory ownership, ordering or
  assumptions;
- required choices and the relevant design revision are accepted, with blocking
  findings and architecture-changing uncertainties resolved;
- validation criteria are concrete, and remaining non-blocking uncertainty or
  implementation work has an owner and a closure or reconsideration trigger.

Local data structures and private function organization may remain implementation
choices when they preserve these constraints. Apply the
[review method](architecture-review.md), including synthesis after related
decisions change. Design readiness does not claim implementation completeness.

## Ownership, Acceptance And Maintenance

Place a separate document under its owning scope's `key-designs/` and link it
from the scope overview. A concern crossing sibling scopes is coordinated by
their nearest common parent; participating scopes retain their own canonical
contracts. Use a stable owner-qualified ID for traceability.

For a cross-cutting mechanism, keep one canonical key design under its governing
scope. State the participating components, shared contract, each participant's
obligations and permitted variations or explicit exceptions. Component specs
link the shared design and describe their local obligations; they do not copy
the common rules. A shared mechanism does not by itself require a shared runtime
component. Principles guide the choice; the ARD preserves its rationale.

Declare design and implementation status separately under the canonical method.
A `draft` or `proposed` key design is a candidate, not accepted Target. Acceptance
through an ARD or canonical scope document identifies the accepting owner,
date, exact revision and accepted clauses or scope. Accepting an option does
not silently accept every detail or future extension in a linked key design.
Record review and acceptance evidence separately. The ARD status-directory
workflow does not require an equivalent directory tree for key designs.

Maintain the effective mechanism description while preserving accepted ARD
rationale and references to reviewed revisions. Propose changes to important
accepted contracts through the normal decision and acceptance rules; until
accepted, keep the effective contract and candidate changes clearly separate.
Editorial clarification needs no new decision. When retiring or replacing a
whole design, identify its successor or retirement authority and preserve the
historical reference rather than leaving competing canonical designs.

Update affected contracts, component views, traceability and Current/Target
deltas together. Actual project topics, chosen mechanisms, named owners and
adoption sequencing belong in project architecture and its adoption profile.
