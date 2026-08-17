# Architecture Design And Governance Method

## Status

- Authority: normative — architecture method
- Design status: accepted
- Implementation status: partial
- Owner: Loushang architecture method

This document is the canonical method for designing, recording, reviewing, and
governing architecture. It combines the existing black-box and
component-design method with a recursive Architecture Scope model, explicit
Current/Target/History separation, executable current facts, and change
governance.

Loushang applies this reusable method through its project-specific
[Architecture Governance Profile](../architecture/governance-profile.md).

The focused
[Component Design Method](component-design.md) and
[Component Identification Method](component-identification.md)
remain supporting references. When their process or terminology conflicts with
this document, this document is authoritative.

## 1. Goals

The method exists so that an engineer entering any architecture scope can
answer, without reconciling several contradictory diagrams:

1. What does this scope own, and what must it not own?
2. What does the implementation objectively contain today?
3. What architecture has been accepted as the target?
4. What remains between Current and Target?
5. Which requirement, decision, component, interface, code, and test establish
   each important contract?
6. Which vocabulary and architecture principles govern the words and design
   choices used by this scope?

The method must scale from a whole governed system to a Product Capability
such as `coding.lsp`, without turning every source directory into a subsystem or
requiring a full document suite for every helper.

## 2. Core Model

Architecture is governed through four truth planes, one delta plane,
and a recursive scope tree.

### 2.1 Truth planes

| Plane | Question | Canonical evidence | Authority |
| --- | --- | --- | --- |
| Facts | What objectively exists and executes now? | source, tests, generated inventories and graphs | observed |
| Current | How are those facts interpreted as ownership, boundaries, and runtime shape? | current owner maps and current architecture projections linked to evidence | descriptive |
| Target | What design has the governed system accepted? | AOD, principles, requirements, specifications, accepted ARDs and component designs | normative |
| History | Why did an earlier design exist and how did migration happen? | superseded ARDs, ledgers, reports, old designs and handoffs | historical |
| Delta | How does Current differ from Target? | design-implementation gap ledger | derived |

Rules:

- Target cannot override Facts by claiming that an unimplemented capability
  already exists.
- Facts do not automatically define the desired design; they may reveal drift
  or an unmodeled implementation.
- Current must link to executable or generated evidence.
- History is retained for traceability but is never a current ownership source.
- Delta is the only normal place to combine Current and Target assertions.
- Do not maintain complete parallel Current and Target copies of every
  architecture document. Keep one normative design, generated facts, a concise
  current projection, and an explicit delta.

### 2.2 Architecture Scope tree

Architecture is recursive, but the architectural names are not interchangeable:

```text
L0  System
    governed system

L1  Top-Level Subsystem Or Product
    harness, ai, agent, coding, tui, method, ontology

L2  Bounded Capability / Nested Architecture Scope
    coding.lsp, coding.arch, harness.multiagent

L3  Component / Component Group
    LSP Supervisor, Client, Documents, Diagnostics

L4  Implementation Module
    supervisor.py, client.py, documents.py
```

`Architecture Scope` is the generic governance term. A top-level subsystem and
a nested Product Capability are both scopes, but they have different placement
and reuse promises.

### 2.3 One-level expansion rule

Every architecture scope expands only its direct children:

- the system AOD expands top-level subsystems and Products;
- Coding architecture expands Coding-owned components and bounded
  capabilities such as LSP and Arch;
- LSP architecture expands its internal components;
- a component design mentions implementation modules only when their
  separation is architecturally important.

Do not draw LSP Client internals in the system AOD or copy the entire Harness
component graph into Coding. Cross-scope diagrams represent the other scope as
a black box and link to its canonical document.

## 3. Scope Promotion And Demotion

A responsibility cluster should become a nested Architecture Scope only when
most of the following are true:

- it has a stable, owner-qualified identity;
- it has a black-box contract or an external actor/system boundary;
- it owns lifecycle, state, configuration, trust, security, or failure
  semantics;
- it contains several stable components or component groups;
- it can be tested, delivered, or evolved independently;
- it has one accountable owner;
- its provided and required ports can be stated independently of its modules;
- hiding it inside one parent component would cause its contract to scatter.

Keep an object as a component or responsibility cluster when it lacks an
independent boundary, lifecycle, or evolution path. Keep local helpers and
utilities below the architecture model unless changing them changes a stable
contract.

A nested scope becomes top-level only through an accepted cross-system
placement decision. A source package, a Capability ID, and a top-level
subsystem are not equivalent merely because they have names.

## 4. Authority And Reading Order

Use the following authority order for implementation questions:

1. source and executable contract/architecture tests;
2. generated Current facts;
3. the scope's current owner map or current architecture projection;
4. accepted ARDs and normative scope documents;
5. proposed Target designs;
6. implementation plans, migration ledgers, reports, references, and history.

Use the following order for design questions:

1. strategy and accepted system requirements;
2. the global glossary, AOD, and cross-system principles;
3. parent scope placement and boundary;
4. inherited and local vocabulary/principles, then the scope's accepted
   requirements, boundary, and specification;
5. accepted component model, key designs, and ARDs;
6. proposed designs and validation material.

When a current fact and an accepted target differ, record a Delta. Do not
silently rewrite one as the other.

## 5. Status Model

Design maturity and implementation maturity are orthogonal. Every canonical
architecture document should declare both when they are relevant.

### 5.1 Design status

- `draft`: exploratory and incomplete;
- `proposed`: ready for review but not yet authoritative;
- `accepted`: normative target or decision;
- `superseded`: replaced by a named accepted document;
- `rejected`: considered but not adopted.
- `not-applicable`: generated or historical material with no design maturity.

### 5.2 Implementation status

- `not-started`;
- `partial`;
- `implemented`;
- `deviated`;
- `retired`;
- `not-applicable`.

### 5.3 Authority kind

- `normative`: states what must be true;
- `descriptive`: interprets current facts;
- `generated`: produced from objective repository facts;
- `historical`: preserved only for rationale and traceability.

Canonical documents should use a short status block or front matter containing:

```yaml
id: COD-LSP-ARCH
kind: scope-overview
scope: coding.lsp
parent: coding
authority: normative
design_status: accepted
implementation_status: partial
owner: coding
evidence:
  - tests/coding/lsp
supersedes: []
superseded_by: null
```

Dates and reviewed commits are useful audit metadata but do not create
authority. Evidence and change triggers are stronger than a manually refreshed
"last reviewed" date.

## 6. Architecture Artifacts And Their Questions

Each artifact must answer one primary question.

| Artifact | Primary question | Must not become |
| --- | --- | --- |
| Strategy | Why does the product/system exist? | component design |
| Requirement | What outcome or constraint must hold? | implementation solution |
| Glossary | What does one term mean in this scope, and where is that meaning authoritative? | requirements, design assertions, or a general dictionary |
| Architecture principle | Which durable design preference or invariant guides decisions in this scope? | feature wish list, implementation recipe, or unenforced slogan |
| AOD | What is the whole-system architecture and navigation model? | subsystem encyclopedia |
| System context | Who or what crosses this black-box boundary? | internal component graph |
| Scope boundary | What does this scope own, collaborate on, and exclude? | source inventory |
| Specification | What exact observable contract must hold? | implementation plan |
| Component model | Which stable internal responsibility units own the requirements? | class/module listing |
| Component composition | Who contains, creates, binds, or mounts whom? | runtime sequence |
| Component interaction | In what temporal order do calls, events, state and failures flow? | static import graph |
| Component dependency | Which static or contract dependencies are allowed, required, or forbidden? | unlabeled interaction diagram |
| Key design | How is one structurally important or high-risk concern constrained? | miscellaneous notes |
| ARD | Why was one consequential choice accepted over alternatives? | mutable current-status page |
| Plan | How will one delivery slice be implemented? | permanent architecture truth |
| Validation | What experiment or evidence supports a design conclusion? | raw spike log |
| Traceability | Where is each important requirement designed and verified? | duplicate specification |
| Gap ledger | How does Current differ from Target? | roadmap without evidence |

### 6.1 Requirements versus specifications

A requirement states an outcome, constraint, non-goal, and acceptance
condition. It should not prematurely choose the owner or class structure.

A specification freezes observable behavior: public APIs, protocols, state
transitions, error and cancellation behavior, serialization, interaction
contracts, and compatibility rules. Architecture assigns responsibility;
specification makes a selected boundary precise.

### 6.2 Logical versus physical system context

Create logical context before physical context.

Logical context identifies:

- users and logical actors;
- adjacent scopes and external systems;
- application protocol families;
- authority, information, and trust flows;
- sources of variation.

Physical context identifies:

- processes, packages, executables and deployment carriers;
- SDK/CLI/RPC/stdio/network connections;
- provider actor kinds and authentication material;
- host/runtime and packaging constraints.

An external actor or transport is a source of variation, not automatically a
component. Promote a boundary component only when it absorbs stable variation.

### 6.3 Composition, interaction, and dependency

These are separate views and must use labeled edges:

| View | Example edges |
| --- | --- |
| Composition | contains, constructs, binds, mounts |
| Interaction | calls, emits, approves, persists, projects |
| Dependency | imports, uses-contract, allowed, forbidden, optional |

For dependency views, distinguish:

- intended dependencies, expressed by normative design and architecture gates;
- observed dependencies, generated from source imports and exports;
- runtime interactions, expressed by scenarios and sequences.

An observed import edge is not proof that the dependency is desirable. An
accepted dependency is not proof that code already uses it.

### 6.4 Glossary versus architecture principles

A glossary controls architectural language. It defines a term, its scope,
canonical spelling, allowed aliases, deprecated names, and links to the
contract that gives the term operational meaning. It must not hide a
requirement, decision, ownership rule, or implementation status inside a
definition.

An architecture-principles document controls durable design judgment. Each
principle should state:

- a stable owner-qualified ID and title;
- the scope in which it applies;
- the design preference or invariant;
- its rationale and important consequences;
- how reviewers or executable gates can verify it;
- the exception path when the principle cannot be followed.

Principles are not substitutes for requirements or ARDs. A principle guides a
class of decisions; a requirement states an outcome; an ARD records one
consequential choice. A mechanically enforceable principle should be backed by
an architecture test, schema check, generated fact, or review checklist.

## 7. AOD And Top-Level Architecture

Each governed system maintains an Architecture Overview Document (AOD) whose
location is declared by its adoption profile. It is a concise constitution and
router, not the aggregate of all subsystem details.

The AOD owns:

1. system scope and architectural goals;
2. cross-system principles and invariants;
3. the top-level scope map and ownership summary;
4. a Current summary that links to generated facts;
5. an accepted Target summary;
6. the most important Current/Target deltas;
7. links to scope entrypoints, decision indexes, and terminology.

The AOD does not own component details, protocol fields, migration checklists,
provider-specific behavior, or unresolved speculative design.

Every top-level diagram must declare whether it is Current observed, Current
interpreted, or accepted Target. A diagram may not mix those states without
visually and textually identifying every target-only edge.

## 8. Scope Architecture Package

Every top-level scope has a `README.md` entrypoint. A sufficiently complex
nested scope has its own directory and README. The scalable full form is:

```text
<scope>/
  README.md
  glossary.md
  principles.md
  requirements.md
  placement-and-boundary.md
  system-context.md
  specification.md
  component-model.md
  component-interactions.md
  component-dependencies.md
  traceability.md
  interfaces/
  key-designs/
  decisions/
  generated/
  validation/
  reference/
  history/
```

Use proportional documentation:

- a small component remains a section in its parent component model;
- a medium capability may use one `architecture.md` with the standard
  sections;
- a complex bounded capability uses the full package.

Do not create empty placeholder files merely to match the full form.

### 8.1 Scope README contract

The README is a local architecture overview and router. It contains:

1. identity, parent, owner, and status;
2. scope and non-scope;
3. Current and Target summary;
4. core invariants;
5. direct external scopes and actors;
6. direct child component/capability summary;
7. authoritative reading order;
8. concise gap summary;
9. history/reference entrypoints.

It links rather than copies detailed component and protocol designs.

### 8.2 Parent-child contract

The parent scope owns:

- why the child exists and its placement;
- Product or subsystem policy for selection, mounting and composition;
- the parent's use of the child's provided contract;
- sibling relationships and cross-child dependency approval;
- constraints inherited by the child.

The child scope owns:

- its black-box boundary and provided/required ports;
- its requirements, specification and internal components;
- internal lifecycle, state, interactions and dependencies;
- its evidence and Current/Target delta.

The child's boundary document is canonical for the detailed child contract.
The parent represents the child as one box and links to that contract.

### 8.3 Sibling dependencies

A new dependency between sibling scopes must be approved at their nearest
common parent. It requires:

1. an entry in the parent dependency/capability graph;
2. a required port in the consumer scope;
3. a provided adapter or port in the provider scope;
4. an ARD when ownership, lifecycle, optionality, or authority changes;
5. an executable architecture gate.

Prefer consumer-owned narrow protocols over imports of provider internals.
Sibling scopes must not form an implicit cycle through convenience imports.

### 8.4 Vocabulary and principle inheritance

Glossaries and principles follow the same recursive scope tree as architecture:

- the global glossary owns cross-system vocabulary;
- cross-system principles apply to every top-level and nested scope;
- a scope inherits its ancestors' vocabulary and principles by reference;
- a local glossary defines only domain-specific terms or qualified meanings;
- local principles add stricter or domain-specific constraints rather than
  copying the global principles.

A child must not silently redefine a parent term or weaken a parent principle.
Resolve a collision by using a qualified local term, promoting one definition
to the nearest common parent, or accepting an ARD-owned exception at that
parent. The parent records the exception; the child links to it.

Split a glossary or principles file out of the scope README when the content is
stable and reused across several requirements, specifications, key designs, or
teams, or when inconsistent language/design judgment has already caused
ambiguity. Keep a short local section in the README when only a few terms or
rules exist. Do not create empty files for documentary symmetry.

When translations are useful, keep one normative language source and make
localized files mappings to that source. The native TUI's normative English
glossary plus Chinese terminology map is the reference pattern. A translation
must not independently introduce or change architectural meaning.

## 9. End-To-End Design Method

Use the following sequence for a new system, subsystem, or bounded capability.

### Stage 0: Frame the change

- identify the strategy, user outcome, trigger, and affected scope;
- determine whether the change is local, component-level, boundary-level, or
  cross-system;
- identify existing authoritative documents and decisions.
- identify inherited terminology and principles, and flag terms or exceptions
  that the design may introduce.

### Stage 1: Requirements

- define functional requirements, quality requirements, constraints,
  non-goals, and acceptance criteria;
- give stable IDs only to requirements worth tracing;
- do not encode the presumed module structure as a requirement.

### Stage 2: Black-box framing

- update logical and physical system context;
- define the scope boundary, authority, trust boundaries, provided ports, and
  required ports;
- update the parent placement when the scope is nested;
- identify sources of variation that boundary components may need to absorb.

### Stage 3: Candidate discovery

Create candidate function and component inventories from:

- requirements and scenarios;
- reference systems, used as evidence rather than templates;
- actors, protocols, transports, auth and host constraints from system context;
- extension points and non-functional concerns;
- cross-cutting cancellation, error, validation, safety and observability needs.

Function is not component. Actor, protocol, class, module, and transport are not
automatically components.

### Stage 4: Function-to-component mapping

Map every important function to:

- primary owner;
- collaborators;
- explicit non-owners;
- provided and required interfaces.

Allow one-to-one, one-to-many, many-to-one and many-to-many mappings. A
many-to-many cluster is a signal to inspect ownership, not an automatic reason
to create a generic manager.

### Stage 5: Refine components

Apply:

- high cohesion and low coupling;
- `split / merge / keep`;
- consistent decomposition view;
- restrained `layer` terminology;
- the `3-7` peer-object review heuristic;
- explicit owner/collaborator/non-owner answers;
- promotion or demotion between responsibility cluster, component and nested
  Architecture Scope.

Candidate inventories are working material. Once accepted, preserve them as
history or validation and publish one final component model.

### Stage 6: Structure, interfaces, interaction and dependency

- define final components and their responsibilities;
- define public and private interfaces;
- document construction, binding, mounting and lifecycle composition;
- document critical success, failure, cancellation, retry and recovery
  sequences;
- declare intended, optional and forbidden dependencies;
- define exact specifications for externally observable contracts.

### Stage 7: Decide and validate

- write an ARD for consequential alternatives and accepted trade-offs;
- use a narrow spike only for runtime feasibility or uncertain external
  behavior;
- keep raw spike evidence under `spikes/` and architecture conclusions under
  `validation/`;
- define contract and architecture tests before calling the design
  implementation-ready.

### Stage 8: Plan and implement

- write a delivery plan outside the permanent architecture truth;
- implement in dependency-safe vertical slices;
- update tests and generated facts in the same change;
- do not call an accepted target implemented until its acceptance evidence
  passes.

### Stage 9: Reconcile and close

- regenerate Current facts;
- classify every remaining design-implementation difference;
- update the scope's concise Current/Target summary and gap ledger;
- mark replaced decisions and documents `superseded`;
- move completed temporary plans and candidate material to history when they
  no longer guide implementation.

## 10. Traceability

The normal traceability chain is:

```text
Requirement
  -> canonical term / AOD principle / scope boundary
  -> Component
  -> Interface / Specification / Key Design
  -> ARD, when a decision was required
  -> Code
  -> Test
  -> Generated Fact
  -> Current/Target Delta
```

Not every helper needs an ID. Stable requirements, capabilities, components,
specifications, key designs and decisions should use owner-qualified IDs, for
example:

```text
COD-LSP-FR-001
COD-LSP-CMP-SUPERVISOR
COD-LSP-KD-003
COD-LSP-ARD-001
```

Durable principles should also use stable IDs such as `LS-PRIN-001` or
`TUI-PRIN-003` so that requirements, ARDs, reviews, and architecture tests can
refer to them without depending on heading numbers. Terms normally use their
canonical name rather than an artificial ID; the glossary index records their
authoritative owner.

Each scope rolls up only the status of its direct children. The AOD does not
repeat leaf requirement rows. A child README summarizes its gaps; the detailed
traceability matrix remains in the child scope.

## 11. Architecture Decisions

Use an ARD when a change affects one or more of:

- scope placement or ownership;
- public contracts or persisted authority;
- cross-scope dependency direction;
- security, approval, isolation or trust boundaries;
- lifecycle, recovery, cancellation or compatibility semantics;
- a costly or hard-to-reverse structural choice.

An accepted ARD is a historical decision record. Do not silently rewrite it to
describe a later world. Add a new ARD or accepted boundary decision, mark the
old record `superseded`, and link in both directions.

Routine refactoring, implementation notes and current status do not require an
ARD unless they change an accepted boundary.

## 12. Current Facts And Drift Control

Generate facts that can be derived safely, including:

- package and nested-scope inventory;
- observed top-level import dependencies;
- public export and entrypoint inventories where stable;
- architecture-test mappings;
- measured budgets when a budget is itself an accepted contract.

Generated documents must state their source and must not be edited manually.
Architecture tests continue to enforce allowed and forbidden direction; a
generated observed graph does not replace normative gates.

Current descriptive documents should reference generated facts and explain
ownership or meaningful exceptions. They should not copy long edge lists.

Classify deltas consistently:

- `missing`: Target exists, Current does not;
- `deviated`: both exist but disagree structurally or behaviorally;
- `partial`: only part of the accepted boundary exists;
- `unmodeled`: Current exists without accepted design;
- `stale-document`: accepted/current documentation describes a retired fact;
- `drift`: differences have accumulated without explicit review.

## 13. Change Governance

Changes update only the necessary scopes, then bubble upward when they cross a
boundary:

| Change | Required architecture updates |
| --- | --- |
| internal module refactor | tests and generated facts; component doc only if a stable responsibility moved |
| component responsibility change | component model, interaction/dependency views and traceability |
| child public contract change | child boundary/specification and parent component/capability model |
| sibling dependency change | both child scopes, common-parent dependency graph, gate and usually ARD |
| top-level ownership move | both top-level scopes, AOD, subsystem map, gates and ARD |
| new top-level Product/subsystem | AOD, packaging/entrypoints, system context and governance ownership |
| cross-scope term added or meaning changed | global glossary index, authoritative glossary, affected specifications, aliases/deprecations and migration notes |
| architecture principle added, weakened or excepted | owning principles document, affected scopes, verification gate and usually an ARD for exceptions |

Review ownership follows scope ownership. A change crossing two sibling scopes
requires review from both owners and their common parent architecture owner.

Architecture Definition of Done for a boundary-changing change:

1. requirements and acceptance criteria are identified;
2. affected context and boundary views are updated;
3. Current and Target are not mixed;
4. ownership and non-ownership are explicit;
5. required/allowed/forbidden dependencies have gates;
6. key requirements trace to tests;
7. generated facts are current;
8. old decisions/documents are superseded rather than silently contradicted;
9. vocabulary and inherited-principle impacts are resolved;
10. the remaining gap is explicit.

## 14. Practical Review Questions

For every architecture review, ask:

1. Which Architecture Scope owns this concern?
2. Is this statement Fact, Current interpretation, Target, Delta, or History?
3. Are logical context, physical context, composition, interaction and
   dependency being confused?
4. Does the proposed component own a stable responsibility, or is it a class,
   transport, actor or helper in disguise?
5. Who owns, collaborates, and must not own the capability?
6. Does a new child or sibling dependency require parent approval?
7. Which requirement and test establish the contract?
8. Which existing decision or document becomes superseded?
9. Can objective Current facts be generated rather than copied manually?
10. Is every important term owned once, inherited rather than copied, and used
    consistently?
11. Which inherited principle governs the choice, and is any exception explicit
    and approved?
12. What explicit gap remains after this delivery slice?
