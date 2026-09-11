# <Architecture Scope Name>

> Template: copy the relevant sections and remove instructions that do not
> apply. Small scopes should combine documents rather than create empty files.

## Status

- Scope: `<owner-qualified-id>`
- Parent: `<parent-scope>`
- Authority: `<normative | descriptive | generated | historical>`
- Design status: `<draft | proposed | accepted | superseded | rejected | not-applicable>`
- Implementation status: `<not-started | partial | implemented | deviated | retired | not-applicable>`
- Owner: `<owner>`

## Scope

State the scope's central purpose and why it is a subsystem, Product, bounded
capability, component group, or component. Link to the parent placement.

## Current

Summarize implemented ownership and link to source, tests, generated facts, or
a Current owner map. Do not copy a complete generated dependency table.

## Accepted Target

Summarize only accepted contracts and link their acceptance evidence. State
explicitly when no Target has been accepted. Do not claim Target objects exist
in Current or infer acceptance of an extension from an accepted prerequisite.

## Candidate Directions

Optional: list draft/proposed designs or questions awaiting a scope-owner
decision. Link the proposal when it exists and identify the decision owner.
These candidates have no implementation-gap classification; listing them does
not accept them or commit to delivery. Remove this section when unused.

## Owns

- ...

## Does Not Own

- ...

## Direct Actors And Neighboring Scopes

List only objects that cross this black-box boundary. Represent other scopes as
black boxes and link to them.

## Direct Child Scopes Or Components

| Child | Owns | Status | Canonical document |
| --- | --- | --- | --- |
| ... | ... | ... | ... |

## Core Invariants

1. ...

## Vocabulary And Inherited Principles

- Global glossary/index: ...
- Parent and cross-system principles: ...
- Local terms or stricter principles: ...

Link to inherited definitions and principles instead of copying them. Keep a
few local additions here; create `glossary.md` or `principles.md` only when the
scope has a substantial, stable body of its own language or design rules.

Local principles identify their kind (invariant, preference or heuristic),
verification and exception authority. Local terms identify their canonical
meaning, aliases and owning scope; link requirements and behavior to their
canonical contracts rather than embedding them in definitions.

## Composition, Interaction And Dependency

Use separate labeled views. Do not use one unlabeled arrow for construction,
runtime calls and static imports.

## Architecture Documents

Give the authoritative reading order: requirements, placement/boundary, system
context, inherited/local vocabulary and principles, specification, final
component model, key designs/ARDs, traceability, facts and history.

Link this scope's decision index, which groups ARDs under `draft/`, `proposed/`,
`accepted/` and `superseded/` as needed. Link cross-scope decisions at the nearest
common parent. Unselected options stay inside their ARD; review and acceptance
evidence remain distinct. Declare any legacy decision paths awaiting migration.

## Current-To-Target Gaps

- `<missing | partial | deviated>`: accepted contract and acceptance evidence;
  Current evidence; owning scope; remaining difference.
- `<unmodeled | stale-document | drift>`: Current/design evidence; owning scope;
  the design-coverage or documentation issue requiring review.

Keep unaccepted extensions in Candidate Directions even when a prerequisite is
already implemented. After acceptance, derive their delta from Current facts.

## Change Triggers And Evidence

- Source paths: ...
- Tests/gates: ...
- Parent/sibling documents updated with this boundary: ...
