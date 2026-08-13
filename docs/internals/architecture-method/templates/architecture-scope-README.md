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

## Target

Summarize accepted/proposed design and label its maturity. Do not claim Target
objects exist in Current.

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

## Composition, Interaction And Dependency

Use separate labeled views. Do not use one unlabeled arrow for construction,
runtime calls and static imports.

## Architecture Documents

Give the authoritative reading order: requirements, placement/boundary, system
context, inherited/local vocabulary and principles, specification, final
component model, key designs/ARDs, traceability, facts and history.

## Current-To-Target Gaps

- `<missing | partial | deviated | unmodeled | stale-document | drift>`: ...

## Change Triggers And Evidence

- Source paths: ...
- Tests/gates: ...
- Parent/sibling documents updated with this boundary: ...
