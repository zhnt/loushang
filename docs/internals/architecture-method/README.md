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

## Method Boundary And Reading Routes

Keep reusable method rules separate from their adoption and architecture content:

| Location | Owns | Examples |
| --- | --- | --- |
| Architecture method | how to design, express, review and govern architecture | change tailoring, review criteria, principle/term formats, decision lifecycle and evidence rules |
| Project adoption profile | how a project applies the method | responsible roles, customer participation, local paths, checks and adoption sequencing |
| Project architecture and vocabulary | the actual accepted design and its evidence | selected principles, term definitions, scope ownership, decisions, Current and deltas |

A method change does not select a project's principles, redefine its domain
terms, accept a product boundary or migrate its records. Project examples in
method documents illustrate application; their canonical scope documents own
the actual architecture.

Start with the relevant route:

- [Design Guidance](design-guidance.md): combine design directions, apply
  cohesion/coupling/granularity judgment and learn from references;
- [Change Tailoring](change-tailoring.md): select the necessary work for this change;
- [Requirement artifacts](#85-requirement-artifacts-and-change-management): manage
  scope requirements, stable identities, acceptance and verification;
- [Architecture Decisions](architecture-decisions.md): record background,
  options, rationale and acceptance in one ARD;
- [Key Designs](key-designs.md): select significant concerns and explain their
  mechanisms, constraints and verification;
- [Domain And Data Modeling](domain-data-modeling.md): establish meaning,
  information lifecycles, logical/physical representations and data ownership;
- [Deployment Views](deployment-views.md): map components and units to carriers,
  locations/zones and physical-context connections, then review scenario paths;
- [Architecture Review](architecture-review.md): choose review views, record
  findings and reconcile the result;
- [Verification And Validation](verification-and-validation.md): establish early,
  independent evaluation, regression coverage and meaningful baselines;
- [Glossary and principles](#64-glossary-versus-architecture-principles): govern
  definitions and design judgment, using the [glossary template](templates/glossary.md)
  and [principle template](templates/architecture-principle.md).

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

#### Target acceptance

Unqualified `Target` means accepted design. A `draft` or `proposed` design is a
candidate direction until the governing scope owner accepts the specific
contract through an authoritative decision or canonical scope document.
Candidates are design inputs, not another truth plane or an implementation
obligation. Label them explicitly and keep them outside accepted Target
summaries and diagrams.

Acceptance applies to the cited contract, not every future possibility
mentioned in its document. An accepted placement, optional extension point, or
prerequisite does not accept all later extensions or their activation. Likewise,
`Authority: normative` describes a document's intended role; a `draft` or
`proposed` design status still means it is not authoritative.

Gap ledgers must distinguish accepted Target deltas from candidate directions:

- each Target-based delta identifies its acceptance evidence and owning scope;
- use separate labeled sections or an explicit acceptance column; a ledger's
  own `accepted` status does not accept its rows;
- only compare Current with an accepted contract when assigning `missing`,
  `partial`, or `deviated`; an unaccepted extension is not implementation debt;
- split a mixed row into its accepted contract and its candidate extension;
- record Current without an accepted design as `unmodeled` where appropriate;
  that design-coverage gap does not endorse a particular candidate solution.

After acceptance, compare the accepted contract with Current evidence and
derive the actual delta. Rejecting or deferring a candidate does not close an
implementation gap. Design acceptance alone establishes neither implementation
completeness nor a delivery date or activation commitment.

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
5. candidate designs (`draft` or `proposed`);
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

Decision records use the same states. Review completion is recorded separately;
`reviewed` and `decided` are not additional design states. See
[Architecture Decisions](#11-architecture-decisions) for state directories,
transition requirements and acceptance records.

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
| Domain/data model | What do concepts and data mean, how do they change, and who owns their facts and representations? | class or database inventory presented as accepted semantics |
| Deployment view | Where and under which constraints do units/instances realize logical responsibilities? | physical-context duplication or a topology without contracts and evidence |
| Key design | How is one structurally important or high-risk concern constrained? | miscellaneous notes |
| ARD | Why was one consequential choice accepted over alternatives? | mutable current-status page |
| Plan | How will one delivery slice be implemented? | permanent architecture truth |
| Validation | What experiment or evidence supports a design conclusion? | raw spike log |
| Review | Does the specified revision satisfy the reviewed criteria, and what findings remain? | acceptance by implication or a generic checklist without evidence |
| Traceability | Where is each important requirement designed and verified? | duplicate specification |
| Gap ledger | How does Current differ from Target? | roadmap without evidence |

### 6.1 Requirements versus specifications

A requirement states an outcome, constraint, non-goal, and acceptance
condition. It should not prematurely choose the owner or class structure.

A specification freezes observable behavior: public APIs, protocols, state
transitions, error and cancellation behavior, serialization, interaction
contracts, and compatibility rules. Architecture assigns responsibility;
specification makes a selected boundary precise.

This distinction applies at every scope, not only across an external/internal
divide. An external API can have a specification; an internal component can
have allocated requirements. The requirement states the needed result or
constraint, while the specification defines the precise contract used to meet
it. Link derived component requirements to their source and keep consumer/provider
contracts authoritative in one place; avoid parallel copies of the same rule.

### 6.2 Logical versus physical system context

State the governed scope and treat it as a black box; neighboring scopes may
be external collaborators even within the same project. Create logical context
before physical context, iterating when physical constraints affect the design.

Logical context identifies:

- external actor roles, including people, agents and external systems;
- adjacent scopes and external systems;
- application protocol families;
- authority, information, and trust flows;
- sources of variation.

Physical context identifies:

- processes, packages, executables and deployment carriers;
- SDK/CLI/RPC/stdio/network connections;
- provider actor kinds and authentication material;
- host/runtime and packaging constraints.

Map logical actor roles to their actual clients, agent runtimes, external
services and communication paths where known. An agent's initiating or
delegated authority must be explicit; sharing a transport does not make human
and agent roles equivalent. Refine both views with the
[requirements and use cases](#stage-1-requirements), preserving the scope as a
black box rather than expanding its internal components into the context graph.

An external actor or transport is a source of variation, not automatically a
component. Promote a boundary component only when it absorbs stable variation.

Complete the context with these checks, using short notes or a relationship
table in the existing scope document when sufficient:

- **Logical-to-physical mapping:** identify which carriers realize important
  logical roles and connections; do not assume a one-to-one mapping. Distinguish
  access form, communication mechanism and transport where relevant.
- **Boundary relationships:** for each important connection, state its purpose,
  initiator and exchanged information, responsibility/authority, required or
  optional dependency, failure impact and trust conditions. Link the canonical
  contract and its owner rather than copying protocol details into the diagram.
- **Environment assumptions:** distinguish evidenced facts/constraints,
  commitments from external owners, unverified assumptions and this scope's
  design choices. For material assumptions, identify evidence or validation,
  a resolution owner and the consequence or reconsideration trigger if false.
- **Completion:** use representative success and risk-relevant failure scenarios
  to check that collaborators, responsibilities and constraints are covered.
  Readers should understand which external changes require architecture review.
  Route resulting constraints to requirements/contracts and consequential
  choices or uncertain mechanisms to ARDs, key designs or validation.

The [deployment view](deployment-views.md) expands internal carriers and unit
placement while reusing physical-context actors, ports and connection references.
Map significant boundary paths into deployment and scenario walkthroughs; keep
the context graph itself a black-box view.

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
- its kind: invariant, design preference, or heuristic;
- the scope in which it applies;
- the design preference or invariant;
- its rationale and important consequences;
- how reviewers or executable gates can verify it;
- the exception path when the principle cannot be followed.

Principles are not substitutes for requirements or ARDs. A principle guides a
class of decisions; a requirement states an outcome; an ARD records one
consequential choice. A mechanically enforceable principle should be backed by
an architecture test, schema check, generated fact, or review checklist.

Distinguish the kinds when applying a principle:

| Kind | How to apply it |
| --- | --- |
| Invariant | State a condition that must hold in the governed scope, its authority and the evidence that checks it. A local review cannot silently waive it. |
| Design preference | Compare the benefits and costs under the decision's actual drivers. Record consequential departures and their rationale. |
| Heuristic | Use it to prompt investigation; crossing a suggested range is not by itself an architecture defect. |

First-principles reasoning separates goals, constraints, facts and assumptions
before selecting a structure; record that reasoning in the ARD. High cohesion,
low coupling and interface stability can guide comparison, but must be made
observable for the decision: which responsibilities change together, which
boundaries a change crosses, and which contract an implementation replacement
must preserve. The method does not select concrete principles for a project.

Use [Design Guidance](design-guidance.md#common-design-judgment) for common
judgment questions, including appropriate granularity. Scope principles govern
adopted rules; the guidance supports reasoning across decisions.

For a principle conflict, identify the governing scope, distinguish constraints
from preferences, and record the trade-off in the relevant ARD. An exception
identifies the affected principle, scope, rationale, responsible owner,
compensating evidence and expiry or reconsideration trigger. Only the authority
owning the constraint may revise or permit an exception to it; a non-waivable
constraint excludes options that violate it. Use the
[principle template](templates/architecture-principle.md) for reusable entries.

A glossary entry identifies the canonical term, owning scope, concise meaning,
aliases/translations, deprecated names and the canonical contract or related
definitions. A shared index routes to those entries instead of copying them.
Definitions explain meaning; requirements, boundary rules and implementation
status belong in their respective artifacts and are linked from the definition.
Use the [glossary template](templates/glossary.md), retaining only relevant fields.

When a term's meaning changes, inspect the authoritative definition, consuming
specifications/decisions, aliases and translations together. Use a qualified term
for a genuinely different local meaning. A spelling-only correction need not
reopen architecture decisions; a semantic change follows the normal boundary
and acceptance rules. The project's actual terms and index remain adoption work.

### 6.5 Key designs versus decisions and specifications

A key design explains how one structurally important or high-risk mechanism
works across responsibilities, state, interactions and constraints. Select
concerns by impact, failure cost, reversibility, critical quality goals or
material uncertainty, rather than code size or technical novelty.

The ARD owns the choice and rationale; the key design explains the mechanism;
the specification owns its precise observable contracts. Small concerns may
combine these as sections, with one canonical definition for each contract.
Use a separate key design when sustained explanation, review or reuse warrants
it, following the [Key Design Method](key-designs.md) and
[template](templates/key-design.md).

Implementation readiness requires explicit consequential semantics and concrete
verification criteria. Design acceptance identifies the specific revision and
scope; a linked accepted ARD does not automatically accept every design detail.
Maintain effective mechanism descriptions while preserving historical decisions
and keeping proposed contract changes distinct from accepted Target.

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

### 7.1 Focused AOD views

Keep one AOD entrypoint and split focused views into `AOD-<viewpoint>.md` when
their audience or concerns warrant it. For example, `AOD-ard.md` provides a
decision overview. The main AOD links these views without repeating their
contents; existing canonical entrypoint filenames need not change. Use the
[AOD view template](templates/AOD-viewpoint.md) when helpful.

Each view identifies its audience/question, scope, owner, authority and source
documents. An AOD filename does not grant design acceptance or make a summary
authoritative over its sources. Apply the existing Current/Target/History rules.

`AOD-ard.md` explains the few decisions that shape the overall architecture,
their relationships and implications for important goals. Link the effective
ARDs and scope decision indexes for detailed status, acceptance and history.
Keep candidate questions visibly separate. Avoid another manually maintained
full decision register; an exhaustive listing should be generated from canonical
records/indexes when needed, with source revision and coverage stated.

Splitting files alone does not prevent staleness. A change that affects a view's
claims must update it or remove the obsolete claim in the same change. Prefer
links over copied status fields and acceptance records. Automation remains
project adoption work; this method does not imply a generator already exists.

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
3. Current and accepted Target summary, with candidate directions labeled
   separately when needed;
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

### 8.5 Requirement artifacts and change management

Each scope has one canonical requirements entrypoint: normally `requirements.md`,
or a section in its scope document when small. It owns goals/sources, lightweight
use cases, functional requirements, runtime/non-runtime quality criteria,
non-goals and unresolved questions. Use the
[requirements template](templates/requirements.md), combining or omitting unused
sections. Reference existing authoritative product requirements; record only
necessary derived requirements locally, with their source and rationale.

Keep system context in its canonical view and implementation evidence in
traceability/Current/Delta. A small document may combine these sections without
mixing their authority. Interviews, discussions and AI-generated suggestions
are source material, not accepted requirements by themselves.

#### Identity and file naming

Give important use cases, functional and non-functional requirements stable
scope-qualified IDs, such as `<scope>-UC-001`, `<scope>-FR-001` and
`<scope>-NFR-001`. Small entries remain rows or sections. Split substantial or
independently reviewed requirements into `requirements/` only when useful;
the entrypoint then indexes their IDs, titles, status and canonical links.

For a standalone entry, prefer `NFR-001-<req-name>.md` over `NFR-001.md`, for
example `NFR-001-recovery-time.md`; use a short descriptive kebab-case suffix.
The owning directory supplies local scope, while the document declares its
full qualified ID. The ID is the durable identity; the suffix aids browsing.
Preserve IDs across moves and editorial renames, update references when paths
change, and never reuse an ID for a different requirement. Runtime/non-runtime
is a concern label and need not create separate numbering schemes.

#### Acceptance and maintenance

Each important requirement identifies its statement/scope, source and related
use cases, acceptance conditions, accountable owner and acceptance evidence.
Shared fields may be declared once for a uniformly governed collection. Follow
`draft -> proposed -> accepted`, allowing the existing combined review/acceptance
path for small changes. Record the accepting owner, date, exact revision and
accepted entries or scope; required customer confirmation follows adoption policy.

Maintain the effective baseline separately from candidate changes, using a
linked proposal or explicitly labeled sections/entry states. A collection's
accepted status covers only the recorded revision and entries; it never accepts
later additions by implication. Stable paths with Git revision history suffice;
requirements do not need the ARD state-directory layout.

Before accepting a material change, assess affected use cases, quality criteria,
contracts, designs and verification. Then update the effective baseline and
references together, preserving prior acceptance records. Record changed clauses
or replacement/withdrawal relationships, owner and rationale; preserve the IDs
and historical evidence. Use an ARD for consequential architectural choices,
not for every requirement clarification or product prioritization decision.

Requirement acceptance and implementation verification are separate claims.
Trace important requirement IDs to design/contracts, verification methods and
results, and remaining deltas; keep one evidence record and link it from the
requirements entrypoint. Any document-level implementation summary must agree
with that evidence. Missing evidence is an open verification question, not proof
of satisfaction or automatically proof of a missing implementation.

## 9. End-To-End Design Method

Use the following sequence for a new system, subsystem, or bounded capability.
Apply [Design Guidance](design-guidance.md) throughout: combine top-down and
bottom-up reasoning, outside-in and inside-out views, and reference experience
with first principles. Revisit earlier stages when evidence changes assumptions;
the sequence does not require completing every design before validation begins.

### Stage 0: Frame the change

- apply [Change Tailoring](change-tailoring.md) to select the necessary stages,
  artifacts, review depth and evidence for this change;
- identify the strategy, user outcome, trigger, and affected scope;
- determine whether the change is local, component-level, boundary-level, or
  cross-system;
- identify existing authoritative documents and decisions.
- identify inherited terminology and principles, and flag terms or exceptions
  that the design may introduce.

### Stage 1: Requirements

- define functional requirements and non-functional quality requirements
  covering runtime and non-runtime concerns, constraints, non-goals and
  acceptance criteria;
- give stable IDs only to requirements worth tracing;
- do not encode the presumed module structure as a requirement.

Plan [verification and validation](verification-and-validation.md) alongside
requirements and scenarios. Establish independent acceptance criteria and an
executable evaluation path before substantial implementation; extend coverage
in proportion to risk.

#### Derive requirements from system context

Start from the existing logical and physical system context and the intended
outcome. If no context exists, sketch the scope and known external actors first.
Iterate this stage with black-box framing: new tasks may reveal missing actors
or relationships, while physical constraints may expose additional requirements.

| Context input | Refine into requirements |
| --- | --- |
| Logical roles and relationships: people, agents, external systems | Identify each role's goals, triggers, information exchanges, authority and expected outcomes; derive functional use cases and relevant quality expectations. |
| Physical realizations: clients/processes, connections, host/runtime and deployment conditions | Map them to logical roles/use cases; identify significant access variants, failure conditions, resource limits, platform, packaging and compatibility constraints. |

Record unknown physical conditions as questions or assumptions rather than
selecting technology prematurely. Collect actual tasks and constraints from
affected participants; AI suggestions are candidate inputs, not confirmation.
Also consider maintenance, testing and delivery concerns whose stakeholders may
not appear as runtime actors. The context graph is an input to discovery, not
proof that every requirement has been found.

#### Keep use cases and quality criteria lightweight

A use case describes an actor goal and an observable result; scenarios are its
important concrete paths or conditions. Prefer a short use-case table:

| Actor / context relationship | Goal and trigger | Expected result / acceptance | Material alternative or failure | Requirement links |
| --- | --- | --- | --- | --- |
| ... | ... | ... | ... | ... |

Keep only the main outcome and branches that change requirements or architecture.
Describe a short sequence when necessary; do not require a full prose document,
every UI step or every input combination for each use case. Several actors or
physical access paths may share one use case; record a variant only when its
contract or quality criteria differ. Use cases and requirements may map
many-to-many, and a cross-cutting quality requirement may apply to a whole scope.

| Requirement concern | Capture | Illustrative acceptance dimensions |
| --- | --- | --- |
| Functional | What behavior, business rule or result must be provided? | Accepted/rejected inputs, observable outcomes, permitted actions and state changes |
| Non-functional: runtime | How well must the system behave under stated operating conditions? | Latency/throughput under a workload, resource bounds, recovery time/data loss, isolation and access-control guarantees |
| Non-functional: non-runtime | How well must the system support development, change, testing and delivery? | Effort/scope of a change, supported-platform checks, compatibility criteria, build/test duration and installation or upgrade constraints |

These are review perspectives, not disjoint quality categories: a concern such
as security may have both runtime and non-runtime criteria. Link each important
criterion to its use case or scope, relevant logical/physical conditions,
observable measure, required threshold or pass/fail rule, and verification
approach. Separate required constraints from candidate solutions; the examples
above prescribe no project metric or implementation mechanism.

Consolidate duplicate requirements, resolve conflicts with the accountable
owners, and mark scope exclusions and unresolved inputs. Check both directions:
important actor tasks and environmental constraints have requirement coverage,
and important requirements have a source and acceptance basis. Refine only
material gaps before proceeding; do not require exhaustive use-case completion.

#### Express important quality scenarios

Express architecturally significant quality requirements as concrete scenarios:
**stimulus source -> stimulus -> environment -> affected scope/artifact ->
response -> response measure**. A sentence may cover all six elements; the
measure states an observable satisfaction criterion, including a metric and
threshold where appropriate. Scenarios may concern runtime behavior or changes
such as adding an integration or replacing a platform.

For example, introducing a new external protocol may require an adapter while
preserving existing consumer contracts and passing their compatibility checks.
This illustrates scenario form, not a project requirement or selected design.
Requirements own the canonical scenarios and their stable IDs when worth
tracing; ARDs, key designs and reviews reference them. Human and AI authors must
not invent thresholds to fill a template. Missing criteria remain explicit
questions with an owner; proposed criteria follow normal acceptance rules.

Use [scenario prioritization](change-tailoring.md#prioritize-quality-scenarios)
to select analysis depth and [quality-attribute analysis](architecture-review.md#quality-attribute-analysis)
to examine the mechanisms supporting important scenarios. The scenario format
draws on [SEI quality attribute scenarios](https://sei.cmu.edu/documents/704/2003_005_001_14213.pdf).

### Stage 2: Black-box framing

- refine logical and physical system context together with the use cases,
  runtime/non-runtime quality criteria and constraints from Stage 1;
- define the scope boundary, authority, trust boundaries, provided ports, and
  required ports;
- update the parent placement when the scope is nested;
- identify sources of variation that boundary components may need to absorb.

Develop the [domain and data model](domain-data-modeling.md) with requirements
and component discovery when meaning, state or data responsibility is material.
Refine logical/physical representations and optional component CRUD mappings
as constraints become clear; do not require a complete model before continuing.

### Stage 3: Candidate discovery

Create candidate function and component inventories from:

- requirements and scenarios;
- reference systems, used as evidence rather than templates;
- actors, protocols, transports, auth and host constraints from system context;
- extension points and non-functional concerns;
- cross-cutting cancellation, error, validation, safety and observability needs.

Function is not component. Actor, protocol, class, module, and transport are not
automatically components.

Use important quality scenarios during discovery and refinement. For each
consequential candidate mechanism, explain which quality it improves, how it
works, and the responsibilities and costs it introduces. Failure isolation may
affect resource boundaries; modifiability may suggest adapter responsibilities.
These are design options, not mandatory components. This applies
[SEI Attribute-Driven Design](https://www.sei.cmu.edu/documents/775/2006_005_001_14795.pdf)
reasoning alongside functional mapping rather than postponing quality analysis
until decomposition is complete.

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

- [high cohesion, low coupling and appropriate granularity](design-guidance.md#common-design-judgment);
- `split / merge / keep`;
- consistent decomposition view;
- restrained `layer` terminology;
- peer-object complexity as a review signal, without a required object count;
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

Develop [key designs](key-designs.md) for significant mechanisms as needed.
They may start during framing or discovery and iterate with the component model;
this stage is not a prerequisite for investigating a high-risk concern.

Use the [deployment method](deployment-views.md) when placement, distribution or
isolation matters. Relate unit/node/zone mappings to physical system context,
data responsibilities and deployment-aware walkthroughs before claiming that
the design supports its runtime and quality contracts.

### Stage 7: Decide and validate

- develop consequential decisions in an ARD: background and architectural
  drivers, options and comparison, decision and rationale, consequences,
  validation and reconsideration conditions;
- review the proposed revision and record acceptance by the governing owner
  before treating its selected contract as Target;
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

Routine refactoring, implementation notes and current status do not require an
ARD unless they change an accepted boundary.

Architectural drivers belong in the ARD's background; alternative designs and
their comparison belong in its options; the selected trade-off belongs in its
decision and rationale. Reference existing requirements and validation evidence
rather than creating a parallel driver or comparison document suite.

Use the [Architecture Decision Method](architecture-decisions.md) and
[ARD template](templates/architecture-decision.md). The normal lifecycle is
`draft -> proposed -> accepted`; an accepted decision becomes `superseded` only
when a replacement is accepted. One ARD records one decision question and its
options: unselected options remain in its comparison, not in separate rejected
records. Selecting Current or deciding against a new mechanism is also an
accepted decision when the owner accepts that conclusion.

Review records identify findings and disposition separately from design status.
A small personal-project decision may combine drafting, review and acceptance,
but must still record the explicit accepted outcome and its owner.

Each owning scope organizes its decision records under `decisions/draft/`,
`proposed/`, `accepted/` and `superseded/`, creating directories only when
needed. A `rejected` whole-record disposition is retained only when needed for
explicit rejection or legacy traceability; `rejected/` is not a required
directory and never holds individual unselected options. Cross-scope decisions
belong at the nearest common parent. The directory, document status and scope
decision index must agree. Preserve the
decision ID and filename during a status change; use `git mv` and update status,
acceptance/rejection/replacement records, index entries, incoming references and
relative links inside the moved record in the same change.

An accepted ARD remains normative for its selected contract while preserving
the original rationale. Reconsideration creates a new draft/proposal; the old
decision remains effective until a replacement is accepted. Then move the old
record to `superseded/` and link both records. Implementation progress alone
does not supersede a decision or make it rejected.

The adoption profile declares decision ownership, any customer participation
required for the affected contracts, and incremental migration of existing
records. A directory move or completed review alone never grants acceptance.

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

- `missing`: an accepted Target contract exists, Current does not;
- `deviated`: Current and the accepted Target disagree structurally or behaviorally;
- `partial`: only part of the accepted boundary exists;
- `unmodeled`: Current exists without accepted design;
- `stale-document`: accepted/current documentation describes a retired fact;
- `drift`: differences have accumulated without explicit review.

Apply the [Target acceptance rule](#target-acceptance) before classifying a
Target-based delta. Candidate directions carry no implementation-gap
classification until their relevant contract is accepted.

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
3. Current and Target are not mixed, and candidates are not counted as accepted
   Target deltas;
4. ownership and non-ownership are explicit;
5. required/allowed/forbidden dependencies have gates;
6. key requirements trace to tests;
7. generated facts are current;
8. old decisions/documents are superseded rather than silently contradicted;
9. vocabulary and inherited-principle impacts are resolved;
10. the remaining gap is explicit.

## 14. Practical Review Questions

Use the [Architecture Review Method](architecture-review.md) to select relevant
views and evidence, record findings, and check the combined design after related
decisions change. The [review template](templates/architecture-review.md) may be
embedded in an ARD for a small review. Review results are descriptive evidence;
design acceptance remains governed by the decision lifecycle.

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

## 15. Guidance Pending Refinement

The topics below need dedicated method guidance in a later change. This is a
method worklist, not a list of accepted project designs or implementation gaps.
Existing context, contract and review rules continue to apply. Until detailed
guidance is available, human and AI designers should consider the short prompts
when relevant and record consequential unknowns for review.

| Topic | Guidance status / intended follow-up | Interim questions |
| --- | --- | --- |
| Physical system context | Pending: dedicated explanation of physical actors, carriers, connections and environmental constraints | How do people, agents and external systems map to actual clients, runtimes and connections? Which assumptions, trust boundaries and environmental differences affect contracts or quality criteria? Keep the governed system a black box. |

Domain/data modeling and component deployment now use their dedicated
[modeling method](domain-data-modeling.md) and [deployment method](deployment-views.md).
Physical-context-to-deployment mapping is covered by the latter; the full
physical system context guidance remains pending.

Keep provisional notes in the affected scope's existing design/review material.
Identify assumptions and candidates explicitly; these prompts do not require
new project documents or establish a complete modeling/deployment method. Add
links here when the dedicated guidance is written and reviewed; do not create
empty placeholder documents to make the worklist appear complete.
