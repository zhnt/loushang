# <Scope> Requirements

> Template: keep small collections as sections of the scope document. Use this
> file as an index when substantial entries warrant `requirements/` files named
> `FR-001-<req-name>.md` or `NFR-001-<req-name>.md`. Remove unused sections and
> instructions. Rows and short statements normally suffice.

## Status And Ownership

- Scope: `<owning architecture scope>`
- Authority: normative
- Design status: draft
- Implementation status: not-started
- Owner: `<accountable requirements owner>`
- Source / inherited requirements: `<canonical references>`
- System context: `<logical and physical context reference>`
- Verification / Current / Delta: `<canonical evidence reference>`

Choose implementation status from evidence independently of acceptance status.
Shared owner/status applies only to the stated collection; identify entry-level
differences explicitly and keep candidates separate from the effective baseline.

## Goals, Scope And Sources

State whose problem is addressed, intended outcomes and exclusions. Identify
source participants or records and distinguish confirmed needs, assumptions and
AI suggestions. Reference authoritative product/parent requirements rather than
copying them; explain necessary derived requirements and their rationale.

## Lightweight Use Cases

| ID / actor and context relationship | Goal / trigger | Expected result | Material alternative or failure | Requirement IDs |
| --- | --- | --- | --- | --- |
| `<scope>-UC-001` / ... | ... | ... | ... | ... |

Include only paths that clarify requirements or affect architecture. Share use
cases across actors/access paths when contracts agree; describe differences
without duplicating complete use-case specifications.

## Functional Requirements

| ID / title | Required behavior or rule | Source / use cases | Acceptance conditions |
| --- | --- | --- | --- |
| `<scope>-FR-001` / ... | ... | ... | ... |

## Non-Functional Requirements

| ID / title | Runtime / non-runtime concern and applicable scope/use cases | Source | Conditions and measurable criterion | Verification approach |
| --- | --- | --- | --- | --- |
| `<scope>-NFR-001` / ... | ... | ... | ... | ... |

State relevant workload, platform or change conditions and the threshold or
pass/fail rule. A criterion may apply to several use cases or a whole scope.
Do not invent metrics or targets; record missing criteria below with an owner.
For important quality scenarios, use the
[scenario format](../README.md#express-important-quality-scenarios) within the
entry when needed, without duplicating its authoritative definition.

## Candidates And Open Questions

Identify candidate additions/changes with their actual draft/proposed state,
source, owner and next clarification or decision. Link a separate proposal when
needed. Listing an item here does not accept it or create implementation debt.

## Acceptance And Change Record

Record the accepting owner, date, unambiguous reviewed revision, exact accepted
entries/scope and relevant review/confirmation evidence. Document actual
entry-level exceptions; do not infer acceptance from this template or its status.
For changes, identify affected use cases, contracts/designs and verification;
record replaced or withdrawn clauses/IDs and preserve prior acceptance references.
Keep the effective baseline readable until candidate changes are accepted.

## Verification And Traceability

Link the canonical requirement-to-design-to-verification record. For a small
scope, keep it here with columns for requirement ID, design/contract, verification
method/result/evidence and remaining delta. Planned checks are not passed checks;
requirement acceptance does not establish implementation completion. Reuse this
record in summaries rather than maintaining independent progress tables.
