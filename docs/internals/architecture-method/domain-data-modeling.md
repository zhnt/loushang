# Domain And Data Modeling Method

## Status

- Authority: normative — supporting method for domain and data modeling
- Design status: accepted
- Implementation status: not-applicable
- Owner: Loushang architecture method

Use this method with the [canonical architecture method](README.md) to clarify
domain meaning, the information lifecycle and implementation mappings. The
[model template](templates/domain-data-model.md) is optional; combine views in
one document or existing scope sections when small. Concrete project concepts,
schemas and technology choices remain scope architecture work.

## Modeling Views And Lifecycle

| View | Primary question |
| --- | --- |
| Domain | What concepts, identities, relationships, behaviors and invariants express the actual problem? |
| Logical data | What information structures, keys, relationships and integrity rules represent those meanings precisely and support expected changes? |
| Physical data | How are those structures represented, accessed and maintained in runtime memory, messages, files, databases or other concrete carriers? |

The data lifecycle spans all these views: creation/collection, modification,
derivation, transfer/synchronization, storage, maintenance, use and archival or
deletion. It may branch or repeat; not all data is persisted. Domain concepts,
runtime objects, messages, stored records and read projections need not map
one-to-one. State their mappings when the differences matter.

These views may evolve together. Start with meaning and known constraints,
then use implementation evidence to refine the model. Existing classes or
schemas establish Current facts, not automatically the desired domain model.

## Discover Domain Meaning From First Principles

Start with [requirements, use cases and system context](README.md#stage-1-requirements).
Ask whose outcome depends on each concept and what problem it solves. Separate
observed domain facts, accepted rules, assumptions and inherited implementation
choices. Ask which rules would remain if the current technology were replaced.

Follow actor tasks and meaningful actions to identify:

- **Identity:** what makes an object the same over time, across retries,
  copies or renames; distinguish identity from display name and version.
- **Relationships:** meaning, direction, cardinality and optionality; distinguish
  association, containment and responsibility for another object's lifetime.
- **Behavior and state:** permitted operations, state transitions, actor
  authority and important concurrent or failure outcomes.
- **Invariants:** conditions that must hold, the boundary within which they
  must hold together, and who enforces them.
- **Scope:** where each meaning applies and how another scope's concepts map
  to it; do not force different local meanings into a universal object model.

A noun alone does not justify an entity, component, class or table. Use concrete
scenarios and counterexamples to test candidate concepts. For a generic task
model, ask whether retries create distinct executions, which execution owns a
result, and how cancellation affects prior results. The answers come from
requirements and accountable participants, not from this example.

Human and AI designers must expose unsupported identities, cardinalities or
rules as questions. First-principles reasoning does not replace confirmation
of domain facts or authorize acceptance of a proposed rule.

## Describe Important Data Across Its Lifecycle

For each architecturally significant data object or fact, answer the relevant
questions below. Shared rules may be stated once and referenced.

| Concern | Required clarity |
| --- | --- |
| Authority and origin | Which record/source is authoritative for which fact or field? Who can create, interpret and modify it? How do multiple writers divide responsibility or resolve conflicts? |
| Creation and modification | How is information collected or created, validated and updated? Which operations and state rules constrain changes? |
| Derivation and propagation | Which sources produce derived data, copies or snapshots? What lineage, versions and time semantics are needed? How are updates, invalidation and rebuilding handled? |
| Scale and change | What are expected counts, object sizes, growth, read/write rates, hot spots, bursts and retention? State workload assumptions and unknowns explicitly. |
| Consistency | Which updates must hold together, within what boundary? What staleness or temporary disagreement is allowed, and how are ordering and conflicts handled? |
| Storage and maintenance | What persists and what can be reconstructed? Who handles integrity checks, repair, backup/recovery, retention, archival, deletion and migration? |
| Use and access | Which actors/components consume which representation, through which contract and access pattern? What permissions, freshness and observable results apply? |

Distinguish semantic ownership of a fact from the infrastructure that stores
its bytes. An external system may own the fact; a local component may own only
an imported copy or projection. Cached and derived values need explicit source,
freshness and reconstruction rules. Do not assume that deletion of a source
automatically removes replicas, derived values or retained historical records.

## Refine The Logical Model

Make the information model precise enough to implement while preserving useful
technology choices:

- use canonical names and qualified meanings; define identifiers, units, time
  meanings, versions and distinctions such as absent, unknown, empty and zero;
- state necessary structures/types, relationships, cardinalities, uniqueness,
  integrity and state rules, linking authoritative definitions;
- support evidenced or accepted variation with explicit extension and
  compatibility rules; speculative variation remains a candidate concern;
- map domain meaning to API/event, runtime and storage representations where
  different, including conversions, defaults or information loss;
- check that implementers can realize constraints and mappings without inventing
  consequential semantics. Do not bind to a database or language merely to fill
  in the model, or promise extensibility without identifying the expected change.

Naming consistency and data consistency are distinct checks. Document agreement
in meaning as well as integrity, update and synchronization behavior. Link
business requirements to their realization rather than rewriting them as new,
potentially conflicting rules.

## Design Physical Representations For Their Workload

Use the logical model, scale/change assumptions, access patterns and accepted
quality scenarios to justify physical choices. Relevant choices may include
layout and encoding, indexes, partitioning, buffering, caching, replicas and
denormalized projections. Describe the mechanism and evidence behind expected
latency, throughput and resource costs; invented sizes or benchmark claims are
not a design basis.

Preserve the logical contracts while assessing durability, recovery, security,
maintenance and migration costs. An optimization that introduces another copy
or derived representation must identify its synchronization, invalidation,
consistency and rebuild rules. Record consequential trade-offs in an ARD and
complex mechanisms in a key design. Generated schemas, migration files and
measured facts should be linked rather than manually reproduced in full.

Physical data modeling describes representations and their access. System
context and component deployment describe actors, execution locations and
infrastructure relationships. Use the [deployment method](deployment-views.md)
to map data-related units, carriers and physical connections into walkthroughs;
full physical system context guidance remains
[pending](README.md#15-guidance-pending-refinement).

## Map Component Responsibilities To Data

When several components participate in a data lifecycle, use a compact CRUD
matrix: rows are components, columns are important logical data objects, and
cells identify Create, Read, Update and Delete responsibilities. Declare the
authoritative fact owner separately for each object or relevant field. Make
delegated operations explicit; physical writes on another owner's behalf do
not establish semantic ownership.

Add a short relationship table for derivation, replication, synchronization,
archival or repair when CRUD cannot express the responsibility. State source,
target, owner, trigger and consistency/freshness expectations. Matrix entries
describe governed responsibilities, not unrestricted permission to mutate data.
Commands such as approve, cancel or settle retain their preconditions, authority,
state transitions and invariants in the relevant specification.

Review for data without a responsible owner, unexplained multiple writers,
cross-boundary access without a contract, and missing deletion or propagation
responsibility. Use meaningful objects, not every implementation field; skip
the matrix when a simple ownership statement already answers the questions.

## Review, Placement And Maintenance

Walk through representative creation, change, use and retirement scenarios,
selecting concurrency, failure, replay and schema evolution cases by risk.
Check concept identities, relationships, invariants, component responsibilities
and physical representations together. Use the
[quality-attribute analysis](architecture-review.md#quality-attribute-analysis)
for material scale, consistency and performance trade-offs. State evidence
limits; a schema check does not establish runtime consistency or performance.

Use a small concept graph and key-rule table first, adding state/flow views only
when useful. A substantial scope may maintain `domain-model.md` and `data-model.md`;
these names are optional, not a requirement for parallel document sets. Keep one
canonical owner for each model/rule and link glossary meanings, requirements,
component views, specifications, ARDs and validation. A shared model follows
the common-parent governance rules while local meanings remain qualified.

Declare authority and design/implementation status independently. Candidate
models are not accepted Target. Acceptance identifies the reviewed revision,
scope and contracts under the existing rules. Material changes to meaning,
identity, consistency or schema compatibility require impact review of related
requirements, consumers, derived data, migrations and checks. Update Current
and Delta from evidence, preserving prior decisions and acceptance references.
