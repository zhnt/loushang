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

`Target` means accepted design. Drafts and proposals are candidate directions,
kept separately from accepted Target summaries and implementation deltas. They
are design inputs, not an additional truth plane. Apply the canonical
[Target acceptance rule](README.md#target-acceptance): cite acceptance of the
specific contract, and do not infer acceptance of an extension from its
prerequisites or its enclosing document's status.

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

The AOD may route to focused `AOD-<viewpoint>.md` views under the
[AOD view rules](README.md#71-focused-aod-views). A decision overview interprets
and links canonical ARDs/indexes; it does not create another acceptance record.

### Requirements

Requirements define outcomes, constraints, quality attributes, non-goals and
acceptance criteria. They do not prescribe the final module/class structure.

Derive functional use cases and runtime/non-runtime quality criteria together
with logical and physical system context. Use short tables and material scenario
branches, linking cross-cutting requirements to their applicable scopes rather
than duplicating them for every actor. The canonical
[requirements stage](README.md#stage-1-requirements) defines discovery, coverage
and lightweight expression.

The [requirement artifact rules](README.md#85-requirement-artifacts-and-change-management)
govern stable IDs, optional named files, acceptance baselines and change impact.
Requirement acceptance is separate from evidence that implementation satisfies it.

### Specification

Specifications define precise observable contracts: public APIs, protocols,
state transitions, serialization, failure/cancellation behavior and
compatibility. A specification is a long-lived normative design artifact, not
the same thing as an implementation plan.

Requirements and specifications can both exist at external boundaries and
within internal scopes. Distinguish needed outcomes from precise contracts,
linking component-level obligations to their source requirements.

### Domain And Data Models

Domain models express concepts, identity, behavior, relationships and invariants.
Data models cover information from creation and change through derivation,
storage, maintenance, use and deletion, with logical and physical views. The
[modeling method](domain-data-modeling.md) defines authority, consistency,
scale and optional component CRUD mapping. Keep canonical rules linked to
requirements and contracts; generated schemas are implementation facts, not
automatic acceptance of their domain semantics.

### Component Interfaces And Key Designs

Component interfaces and key designs remain architecture material. They define
accepted boundaries and important internal contracts, whether or not every
target detail is implemented. Their implementation status must be declared
separately from their design status.

The [Key Design Method](key-designs.md) defines selection, depth and maintenance.
An ARD records why an option was chosen; a key design explains its mechanism;
a specification owns the precise observable contract. Combine sections for a
small concern and use canonical links when separating documents. Key designs
maintain effective mechanisms while accepted ARDs retain historical rationale;
important contract changes require explicit decisions and acceptance.

### Deployment Views

The [deployment method](deployment-views.md) maps components through optional
units/instances to typed carriers, locations and zones. Reuse physical-context
actor/port/connection references and link them to scenario walkthroughs. Declare
accepted placement separately from candidate topologies and observed Current
instances; diagrams alone do not establish isolation or runtime behavior.

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

### Review

A review is descriptive evidence about a specified revision, question and set
of criteria. It records findings, their evidence/disposition and remaining
uncertainty. Use the [review method](architecture-review.md) to distinguish
individual decision checks from synthesis of their combined design.

Review completion does not accept a Target or establish untested implementation
behavior. Semantic revisions recheck affected evidence and dependent decisions;
acceptance remains recorded by the governing owner in the decision lifecycle.

### Decisions And History

An accepted ARD records why a consequential choice was made. It is not rewritten
to describe a later architecture. A later decision marks it `superseded` and
links to its replacement.

The ARD's background contains architectural drivers, its options contain the
comparison, and its decision contains the rationale. One decision question
owns its alternatives; unselected options remain inside the record. Selecting
Current or deciding not to introduce a mechanism is still an accepted outcome.
Use the [Architecture Decision Method](architecture-decisions.md) and
[ARD template](templates/architecture-decision.md) rather than creating
separate driver/comparison artifacts by default.

Decision directories express `draft`, `proposed`, `accepted` and `superseded`
status, while the record and index declare the same state. Review completion
is separate from acceptance. `rejected` is optional for explicit whole-record
rejection or legacy traceability; it does not classify losing options. A status
move preserves the ID and filename and repairs incoming and outgoing references
in the same change. Accepted decisions stay effective during reconsideration;
supersession occurs only when a replacement is accepted.

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

A normative document with `draft` or `proposed` design status expresses an
intended contract without making it authoritative. A descriptive ledger's own
design status does not confer acceptance on the designs it references.

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

- `missing`: an accepted Target contract exists, Current does not;
- `deviated`: Current and the accepted Target disagree;
- `partial`: only part of the accepted design exists;
- `unmodeled`: Current exists without accepted design;
- `stale-document`: a current/accepted document describes a retired fact;
- `drift`: differences accumulated without explicit review.

Candidate directions have no implementation-gap classification. A ledger may
retain them in a separately labeled section or distinguish them with an
explicit acceptance column. Split accepted and candidate claims rather than
assigning one `partial` status to both. An `unmodeled` Current fact identifies
missing accepted design coverage, not acceptance of a proposed replacement.

An adoption profile may provide localized labels or project-specific aliases,
but it must preserve these classifications and meanings.

## One-Line Rule

Target says what must be true; Facts say what is true; Current interprets Facts;
Delta connects Current to Target; Plans change implementation; History explains
how an earlier state came to exist.
