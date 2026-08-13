# ARD-003: Declared State Authority And Multi-Source Materialization

Status: Accepted, 2026-08-09.

Tracking: [#439](https://github.com/zhnt/loushang/issues/439).

This decision partially supersedes ARD-001 and narrowly amends the
materialization and freshness parts of ARD-002. Its implemented foundation
slices originally kept the Phase 2 SQLite v2 table layout. Stable semantic IDs
and StateAuthority declarations were introduced in schema v3 and are retained
by the current schema v4 contract. Concrete source bindings, full mapped object/property/
link snapshots, multi-input cuts, operational origins, authority failure
contracts, and source-head freshness are implemented for the Memory-only
slices. [ARD-005](ARD-005-source-aware-sqlite-v3.md) later implements durable
SQLite source cuts and origins. Change sets, logic bindings, and transient
derivation remain unimplemented.

[ARD-004](ARD-004-schema-identity-semantic-references-and-source-input-cuts.md)
later refines this decision's identity and reproducibility coordinates: Facts
and source bindings target one complete schema identity, Fact predicates use
stable semantic IDs, and installed source cuts add coverage plus an exact
mapped-payload digest while freshness retains cheap revision-head comparison.

## Context

[ARD-001](ARD-001-factstore-semantic-authority.md) removed a dangerous split
inside Ontology: callers could no longer choose between mutable object writes
and Fact commits. That decision correctly made the append-only FactStore the
only accepted semantic write authority in the current runtime and made object,
property, link, index, and cache state disposable projections.

That boundary was decided before source adapters, application-version
mappings, Actions, or multi-source objects existed. Applying it literally to
ERP, HR, CRM, OA, and other enterprise systems would require every mapped
source property to become an individual Fact before materialization. It would
also conflate two different meanings of authority:

- which system owns a piece of business state and accepts changes to it;
- which Ontology store owns an accepted semantic record.

The distinction matters. An ERP can remain the system of record for a project
budget while Ontology retains a selected regulatory Claim about that budget.
Conversely, a source-backed property need not receive a full Fact envelope when
an immutable, versioned mapped source input can reproduce it with sufficient
lineage.

The Fact-only implementation reviewed before acceptance exposed three
correctness gaps that the first implementation slice resolves:

1. materialization selects `facts_as_of(...)` and reads the Fact watermark
   separately, so a concurrent commit can make an older selection claim a
   newer watermark;
2. immutable projection build coordinates and live freshness are represented
   by one `ProjectionState`; SQLite updates its source watermark after a Fact
   commit while Memory does not, producing different adapter semantics;
3. SQLite reconstructs a projection using several reads without one explicit
   read transaction, so a concurrent replacement can expose mixed versions.

Palantir's public documentation supports objects backed by input datasources,
user edits stored separately from those datasources, materialization of their
combined current state, and explicit conflict strategies. It does not establish
that every source-backed Action must write through to the external system or
that every source property is stored as a per-property Fact. Loushang must
declare its own authority and write-back contracts rather than present an
inference about Palantir internals as fact.

## Decision

### 1. Separate three orthogonal dimensions

The architecture uses separate names for state ownership, assertion production,
and value lineage.

```text
StateAuthority
  source-backed | ontology-owned | derived

AssertionKind
  asserted | derived | inferred

ValueOrigin
  source | fact | schema-default
```

`StateAuthority` answers who owns a business state and which write contract may
change it. For `derived`, the owner is the published computation contract rather
than a writable storage system. `AssertionKind` answers how a semantic assertion
was produced.
`ValueOrigin` answers which immutable input produced a projected value.

The shared word `derived` does not collapse the first two dimensions. A
transient value with `derived` StateAuthority has no `AssertionKind`, because it
is not a Fact. If that value is published as a Fact, the Fact must use
`AssertionKind.DERIVED`. Conversely, a derived Fact does not declare the
`StateAuthority` of the state it describes; the schema declaration still does
that independently.

FactStore remains the semantic record authority for the records inside its
declared scope. It is not renamed to, or confused with, `StateAuthority`.

### 2. Declare authority at operational granularity

Authority can be declared for:

- object existence;
- an object property;
- a link instance family.

The initial implementation permits one primary authority for each writable
state. If multiple sources supply the same state and no resolution policy is
published, materialization reports a conflict rather than choosing by adapter
order, ingestion time, or incidental storage order.

The three authority classes have these minimum meanings:

- `source-backed`: an external system owns the state. Source refresh can replace
  the mapped base value. A future Action cannot commit a local value as if the
  source had confirmed it; it requires a separately declared source-write or
  managed-edit strategy.
- `ontology-owned`: no external source owns the state. Accepted changes are
  committed through Ontology's semantic write contract and survive source
  refresh.
- `derived`: published logic computes the state. It cannot be directly edited;
  callers change its inputs or publish a new logic version.

The ordering, acknowledgement, overlay, and reconciliation semantics for
source-backed Actions are deferred to a later Action write-back ARD. This
decision does not require every source-backed edit to call an external system,
nor does it introduce a managed edit store.

### 3. Give semantic definitions stable identity

Source bindings and generated APIs must not depend on a renameable display or
API name. Published object types, properties, and link types therefore require
an explicit package-local stable ID. A globally resolvable identity consists of
the package namespace plus that stable ID.

Names, labels, aliases, and generated API names remain versioned metadata.
Mappings, authority declarations, and lineage refer to stable IDs. A rename can
then be distinguished from removal followed by addition.

### 4. Treat mapped source input as a first-class materialization input

Ontology owns the pure contracts for a mapped source input. Concrete database,
API, CDC, file, and SaaS adapters belong to a Product or deployment integration
layer.

The minimum source input identity is:

```text
MappedSourceInput
  binding_id
  mapping_version
  source_revision
  payload:
    immutable mapped snapshot
    | immutable mapped change set + base_revision
```

The contract does not require raw source data to be copied into Ontology. It
does require an immutable or content-addressed input that can reproduce the
selected object, property, and link values. A change set is reproducible only
when its base revision and the required immutable chain are available. A
connector that exposes neither a stable revision nor a reproducible snapshot or
change chain reports unknown coverage rather than claiming current data.

The Product or deployment integration is responsible for retaining or
reacquiring the mapped inputs named by an installed cut for as long as it
promises rebuildability. Ontology owns the input identity and validation
contract, not the raw-source retention system. If a required input can no longer
be obtained, diagnostics report rebuildability as unknown or degraded rather
than silently weakening the rebuild guarantee.

Application-version mappings resolve source record identities to canonical
object IDs and preserve alternate keys. Uncertain identities remain separate
until an explicit identity-resolution decision is made; display names are not
merge keys.

### 5. Narrow, but preserve, FactStore

FactStore remains appropriate for:

- ontology-owned state;
- important human-, Agent-, or rule-published semantic Claims;
- records requiring independent bitemporal validity, evidence, correction, or
  regulatory lineage;
- published derived or inferred Claims that have an independent semantic
  lifecycle;
- later Decision and Outcome semantic records where their own ARDs select this
  persistence model.

FactStore is not required for:

- unmapped raw source records;
- mechanical per-field copies of complete source tables;
- logs, clickstreams, high-frequency telemetry, or document bodies;
- ordinary source-backed values reproducible from a versioned mapped input;
- transient derived values that are cheap and deterministic to recompute;
- projections, indexes, and caches.

Source-backed Facts are not prohibited as a future modeling choice. A binding
may eventually select a source value for factization when its independent
bitemporal or audit lifecycle justifies the cost. The current materializer does
not accept such Facts as source-backed operational state; that contract remains
deferred and must be explicit rather than becoming a universal ingestion rule.

### 6. Capture immutable selections and cuts

Fact materialization first obtains one atomic selection:

```text
FactSelection
  facts
  fact_watermark
  valid_at
  recorded_at
```

Memory captures it under one lock. SQLite captures it under one read
transaction. A materializer consumes the immutable selection and does not read
an active FactStore again.

Multi-input materialization records the exact input combination:

```text
MaterializationCut
  schema_identity
  source_inputs[(binding_id, mapping_version, source_revision)]
  fact_watermark
  valid_at
  recorded_at
```

This is a revision vector, not a claim that unrelated source systems share one
global transaction. The first implementation needs only enough structure to
reproduce and compare cuts; it does not require a distributed synchronization
platform.

### 7. Separate projection identity from observed freshness

An immutable `ProjectionState` describes what was built:

```text
ProjectionState
  schema_identity
  projection_version
  materialization_cut
  built_at
```

A separate runtime value describes what is currently observed:

```text
ProjectionFreshness
  status: current | stale | unknown | degraded
  observed_source_heads
  observed_fact_watermark
  observed_at
  diagnostics
```

Committing a Fact or observing a new source revision does not mutate an
installed snapshot's build coordinates. A query or coordinator compares the
snapshot cut with observed heads. Per-query dependency-aware freshness can be
added later; the initial contract may report projection-wide status.

The initial freshness evaluator is pure: its inputs are the immutable snapshot
cut, the current Fact watermark, and source-head observations supplied by the
Product or deployment integration. A missing source-head observation yields
`unknown`; Ontology does not infer `current` from the absence of evidence.

ProjectionStore installation validates snapshot structure and monotonic
projection version, not freshness through adapter-local knowledge. A caller may
require a current cut before installation, but it does so through the same
explicit comparison contract for Memory and SQLite. SQLite co-location with a
FactStore must not create a hidden coverage check that the Memory adapter cannot
implement.

SQLite projection reconstruction must run within one read transaction, and
Memory and SQLite must pass the same freshness conformance suite.

### 8. Generalize projected value lineage minimally

The initial `ValueOrigin` union contains only:

```text
FactOrigin(fact_id)
SourceOrigin(binding_id, mapping_version, source_revision,
             source_record_ref, field_ref)
SchemaDefaultOrigin(schema_identity)
```

Object existence and links use the operational subset `FactOrigin |
SourceOrigin`; only ontology-owned properties may materialize
`SchemaDefaultOrigin`. A missing source-backed property remains unknown even if
its schema definition carries a default. A mapped object therefore carries the
source field used to establish its canonical identity, and a mapped link carries
the source field or record that established the relationship.

Ontology-owned edits and published derived Claims can initially use
`FactOrigin`. Recursive computation lineage, Action edit origins, and policy
origins are deferred until a demonstrated contract requires them. Transient
derived values are also deferred from the first materialization slice: they
must not be mislabeled as `FactOrigin`. Before such values enter a projection,
a later decision must add a computation origin that identifies the published
logic version and its selected inputs.

### 9. Preserve subsystem dependency direction

`loushang.ontology` owns schema, authority, source-input, fact, materialization,
projection, query, and future planning contracts. It does not own concrete
enterprise connectors or external capability execution.

```text
Product source adapter        ---> Ontology source contracts
Product ontology adapter      ---> Ontology + Harness + optional HarnessWork
Product method binding        ---> Method + Ontology

Ontology -X-> Harness / HarnessWork / Method / Product implementation
```

Source synchronization does not have to pass through Harness. Product
composition may use HarnessWork when durable scheduling, recovery, or execution
evidence is required. Harness and HarnessWork do not gain Ontology types in
their public protocols.

## Relationship To Earlier Decisions

This ARD partially supersedes ARD-001 as follows:

- rule 1 is narrowed: Ontology-owned state and published semantic Claims enter
  FactStore; versioned mapped source input may materialize without per-property
  Facts;
- rule 2 changes its rebuild inputs from schema + FactStore to schema + mapped
  source inputs + FactSelection;
- rule 5 changes: ontology-owned commands compile to FactBatch, while a
  source-backed command produces the source-write contract selected by the
  later Action ARD;
- rule 6 separates immutable projection build coordinates from live freshness.

The following ARD-001 decisions remain:

- no mutable ObjectStore or generic object mutation authority;
- projection, index, cache, and search state are disposable;
- failed projection installation cannot discard accepted semantic records;
- raw, unmapped external records are not Ontology Facts.

ARD-002 remains authoritative for port separation, adapter independence, and
immutable whole-snapshot replacement. Its then-current SQLite v2 layout was
later replaced by ARD-005; no compatibility reader or migration is implied.

This ARD also supersedes the target identity rule in
[Schema Evolution](schema-evolution.md): object-type, property, and link-type
names stop being stable identity keys and become versioned metadata; explicit
stable semantic IDs drive comparison and rename recognition. The remaining
offline comparison, impact classification, determinism, and non-goal rules stay
in force. Schema and schema-diff v3 introduced this identity rule for object
types, object properties, and link types; schema v4 retains it while adding
Action identity. Interface identity remains name-keyed.

## Consequences

Benefits:

- enterprise systems remain authoritative for the state they actually own;
- ordinary source data does not require an unbounded per-property Fact copy;
- ontology-owned and published semantic Claims retain strong provenance and
  bitemporal correction semantics;
- projections can expose exact multi-input build coordinates without pretending
  there is a global source transaction;
- Source Adapter, Action, and generated API work gain one explicit authority
  model instead of inventing write ownership independently.

Costs:

- schema needs explicit stable IDs and authority declarations;
- materialization and projected lineage become unions rather than Fact-only
  values;
- freshness needs a runtime comparison contract;
- the current SQLite layout cannot represent the target model unchanged;
- Action write-back and managed-edit behavior remain intentionally unresolved.

## Non-Goals

This decision does not add:

- ERP, HR, CRM, OA, CDC, streaming, or file connectors;
- a SourceSync service, scheduler, retry engine, or data lake;
- automatic entity resolution or multi-source merge policies;
- an Action planner, write-back executor, overlay, saga, or compensation engine;
- Decision, Scenario, Outcome, Agent, or HarnessWork integration;
- SQL pushdown, incremental materialization, distributed serving, or a new
  SQLite format;
- RDF, OWL, JSON-LD, SHACL, or an environmental/domain package.

## Implementation Status

Completed in the first correctness slice:

- Fact selection and watermark are captured atomically in Memory and SQLite;
- SQLite projection reconstruction uses one read transaction;
- Memory and SQLite expose identical snapshot and freshness semantics;
- ProjectionStore installation has no SQLite-only hidden freshness or coverage
  check;

Completed in the stable semantic ID slice:

- object types, object properties, and link types require an explicit
  package-local `semantic_id`;
- compiled schema v3 introduced package-wide uniqueness and round-tripped those
  IDs; schema v4 retains that contract;
- schema-diff v3 introduced matching by ID, explicit breaking rename
  when only the name changes, and treats an ID change as removal plus addition;
- current runtime lookups by API name remain available.

Completed in the declared StateAuthority slice:

- object existence, object properties, and link families require exactly one
  `source-backed`, `ontology-owned`, or `derived` declaration;
- authority declarations round-trip in compiled schema v4 and authority changes
  are breaking in schema-diff v4;
- interface contracts remain structural and do not accept operational
  authority;
- declarations alone do not select a concrete source/logic binding or route
  writes.

Completed in the Memory-only mapped-source and origin-contract slices:

- one Memory-only slice combines one source-backed value, one ontology-owned
  Fact, and one schema default into a deterministic projection;
- every projected object existence and link exposes `FactOrigin` or
  `SourceOrigin`; every projected property additionally permits
  `SchemaDefaultOrigin`;
- the initial slice contains no transient derived value until a computation
  origin is defined;
- an ambiguous multi-source value fails visibly rather than choosing silently;
- in the one-source slice, a supplied newer source revision makes an older cut
  stale without mutating that cut, while a missing source-head observation
  produces `unknown`;
- source bindings refer to object-existence, property, and link-family authority
  declarations through stable semantic IDs rather than API names;
- object existence and properties can be supplied by different bindings without
  depending on input order, and source values later than the selected valid time
  fail materialization;
- source-backed property absence remains unknown rather than being replaced by
  an ontology schema default;
- missing inputs, mapping-version mismatches, unknown stable IDs, inherited
  property IDs, cross-authority impersonation, ambiguous objects/links, mapped
  link endpoints, and multi-source freshness are explicit regression contracts;
- `ProjectionState` now owns a `MaterializationCut` with exact schema, source,
  Fact, validity, and recording coordinates;
- at this decision's first slice, SQLite v2 explicitly rejected source cuts and
  `SourceOrigin` values rather than silently discarding lineage; ARD-005 later
  supplied their durable representation;
- Ontology gains no import dependency on Harness, HarnessWork, Method, Product,
  or a concrete source adapter.

Remaining gates after this slice:

- reproducible change-set payloads with retained base-revision chains;
- concrete versioned logic bindings and a computation origin before transient
  derived values enter a projection;
- ARD-012 now decides the first source-backed write routing, acknowledgement,
  and reconciliation boundary. Its ontology-owned Action path is implemented;
  source-backed planning and execution remain outstanding.

## Deferred Decisions

- broader source-backed Action write-back beyond ARD-012's first external
  `SetProperty` slice, including any managed edit overlay;
- external multi-effect ordering and general reconciliation scheduling beyond
  ARD-012's request and receipt contract;
- cross-authority Action behavior beyond ARD-012's explicit rejection;
- delta versus full-snapshot source persistence;
- source-specific freshness and query dependency aggregation;
- multi-source precedence, merge, and identity-resolution policies;
- selective factization of source-backed operational state;
- incremental physical persistence beyond ARD-005's whole-snapshot SQLite v3
  layout.

## Evidence Reviewed

Reviewed 2026-08-09:

- [Palantir Data Connection](https://www.palantir.com/docs/foundry/data-connection/overview)
- [Palantir multi-datasource object types](https://www.palantir.com/docs/foundry/object-permissioning/multi-datasource-objects)
- [Palantir: How user edits are applied](https://www.palantir.com/docs/foundry/object-edits/how-edits-applied)
- [Palantir materializations](https://www.palantir.com/docs/foundry/object-edits/materializations)
- local read-only `gura105/operational-ontology` at commit
  `c79aa88c1f5d4fe2ac2b126a5852f1ba434aaa57`.

The local reference implements source-backed versus ontology-owned authority,
an ontology-owned overlay, re-index preservation, write-back-first execution,
and audit behavior. Its README discusses derived state conceptually; its core
runtime does not implement a `derived` StateAuthority declaration, source
revision vector, identity-resolution contract, or source coverage model. Those
parts of this decision are Loushang design inferences, not adopted reference
behavior.
