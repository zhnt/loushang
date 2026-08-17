# Architecture Artifact Model

## Status

- Authority: normative — documentation classification
- Design status: accepted
- Implementation status: partial
- Owner: Architecture method maintainers

## Scope

This document defines the compact classification for architecture,
specification, plan, implementation, validation and history. The complete
workflow and recursive scope rules are defined by
[Architecture Design And Governance Method](README.md).

## Why This Exists

A governed system simultaneously maintains accepted targets, current implementation
facts, current ownership interpretations, exact behavioral specifications,
temporary delivery plans, and historical decisions. Without explicit
classification, a proposed class becomes a claimed API, a completed migration
plan becomes a current owner map, or an accepted target is mistaken for an
implemented feature.

## Truth Classification

Every architecture statement should be readable as one of:

| Classification | Meaning | Normal evidence |
| --- | --- | --- |
| Fact | objectively exists today | source, tests, generated report |
| Current | evidence-linked interpretation of current ownership or behavior | current owner map/current scope summary |
| Target | accepted normative design | AOD, requirements, specification, accepted component model/ARD |
| Delta | explicit Current-to-Target difference | gap ledger |
| History | superseded rationale or completed migration record | history, superseded ARD, ledger, report |

Do not mix Current and Target in one diagram or paragraph without labeling each
claim. Do not use History to resolve a current ownership question.

## Document Types

### Architecture

Architecture documents define system/scope placement, ownership, boundaries,
components, composition, interactions, dependency policy, and accepted
structural decisions.

They are normally normative Target documents. A file explicitly marked
`descriptive Current` may interpret implemented architecture when it links to
source, tests, or generated facts. Generated facts under `generated/` are
observed inputs, not normative design.

Architecture does not own a delivery checklist or silently claim
implementation completeness.

### Requirements

Requirements define outcomes, constraints, quality attributes, non-goals and
acceptance criteria. They do not prescribe the final module/class structure.

### Specification

Specifications define precise observable contracts: public APIs, protocols,
state transitions, serialization, failure/cancellation behavior and
compatibility. A specification is a long-lived normative design artifact, not
the same thing as an implementation plan.

### Component Interfaces And Key Designs

Component interfaces and key designs remain architecture material. They define
accepted boundaries and important internal contracts, whether or not every
target detail is implemented. Their implementation status must be declared
separately from their design status.

### Plan

A plan describes how one delivery slice will change files, migrate state, stage
compatibility and validate completion. It is temporary execution guidance and
does not replace architecture, requirements or specification.

Completed plans move out of the current reading path or become historical
delivery records.

### Code And Tests

Code and executable tests define what actually works. Architecture and contract
tests additionally enforce selected intended constraints. When prose conflicts
with executable behavior, the prose is stale or the implementation has an
explicit Delta; prose does not make the behavior true.

### Generated Facts

Generated facts describe repository state such as package/import graphs,
entrypoints, public exports or accepted budgets. They must declare their source,
must be reproducible, and must not be edited manually.

### Validation And Spikes

Raw feasibility evidence belongs with its spike or test artifacts. Architecture
validation records the conclusion that evidence supports, what can be accepted,
and what remains open.

### Decisions And History

An accepted ARD records why a consequential choice was made. It is not rewritten
to describe a later architecture. A later decision marks it `superseded` and
links to its replacement.

Historical terminology may remain in `history/`, `reference/`, reports and
superseded records, but those files remain outside the Current reading path.

## Status Axes

Design and implementation status are independent:

- design: `draft`, `proposed`, `accepted`, `superseded`, `rejected`;
- implementation: `not-started`, `partial`, `implemented`, `deviated`,
  `retired`, `not-applicable`;
- authority: `normative`, `descriptive`, `generated`, `historical`.

`Accepted + partial` is valid. `Implemented + superseded` is also valid while a
replacement migration is underway. One free-form status sentence should not
carry all three meanings.

## Reading Rules

For implementation questions, prefer:

1. source and executable tests;
2. generated Current facts;
3. current owner maps;
4. accepted boundary documents and ARDs;
5. proposals, plans, ledgers, reports and history.

For design questions, prefer:

1. strategy and requirements;
2. AOD and principles;
3. parent placement and scope boundary;
4. specification and accepted component model;
5. accepted key designs and ARDs;
6. proposals and validation.

## Difference Analysis

Use the shared design-implementation terms:

- `missing`: Target exists, Current does not;
- `deviated`: both exist but disagree;
- `partial`: only part of the accepted design exists;
- `unmodeled`: Current exists without accepted design;
- `stale-document`: a current/accepted document describes a retired fact;
- `drift`: differences accumulated without explicit review.

An adoption profile may provide localized labels or project-specific aliases,
but it must preserve these classifications and meanings.

## One-Line Rule

Target says what must be true; Facts say what is true; Current interprets Facts;
Delta connects Current to Target; Plans change implementation; History explains
how an earlier state came to exist.
