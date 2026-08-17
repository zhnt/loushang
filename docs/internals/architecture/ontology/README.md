# Loushang Ontology Architecture

## Current State

The ontology subsystem has completed the schema kernel, the Wave 2A
Fact/Provenance spine, the single-authority reset in
[ARD-001](ARD-001-factstore-semantic-authority.md), and the Phase 2 port,
projection, and adapter split in
[ARD-002](ARD-002-ports-immutable-projection-and-sqlite-v2.md). The
materialization-correctness, stable semantic identity, and declared
StateAuthority slices of
[ARD-003](ARD-003-declared-state-authority-and-multi-source-materialization.md)
are implemented. Its Memory-only mapped-source materialization and complete
operational-origin slices are also implemented. The identity and
reproducibility closure in
[ARD-004](ARD-004-schema-identity-semantic-references-and-source-input-cuts.md)
is implemented. [ARD-005](ARD-005-source-aware-sqlite-v3.md),
[ARD-006](ARD-006-product-hosted-source-adapter-contract.md), and
[ARD-007](ARD-007-fact-schema-revalidation-receipts.md) now close durable
source-aware projection, the Product-hosted adapter boundary, and exact
Fact-selection reuse across schema versions. [ARD-008](ARD-008-immutable-deployment-profile-and-artifact-locks.md)
adds the first immutable deployment selection without adding an executable
deployment runtime. [ARD-009](ARD-009-explicit-identity-crosswalk-snapshots.md)
adds a Product-injected, immutable explicit identity crosswalk without adding
an identity matcher or registry. [ARD-010](ARD-010-deployment-bound-source-instances-and-identity-lock.md)
replaces Profile v1 with source-instance-aware v2 and locks the selected
Crosswalk. [ARD-011](ARD-011-deterministic-ontology-package-artifacts.md)
adds deterministic single-Schema package artifacts and exact dependency-closure
validation without adding a registry or multi-package runtime.
[ARD-012](ARD-012-authority-aware-action-planning-and-product-hosted-write-back.md)
now implements the ontology-owned half of the first authority-aware Action
boundary; Product-hosted source write-back remains unimplemented.

It currently provides:

- versioned Schema v4 drafts, compilation, immutable snapshots, diagnostics,
  and schema diff, with package-local stable semantic IDs for object types,
  object properties, link types, and narrow `SetProperty` Action definitions,
  plus an explicit StateAuthority for each operational state definition;
- an append-only bitemporal FactStore with provenance and lineage, where Fact
  v2 records bind a complete `SchemaIdentity` and durable assertions use stable
  semantic IDs rather than renameable API names;
- pure, deterministic Fact commit planning and atomic bitemporal
  `FactSelection`;
- an explicit guarded Fact commit that performs idempotent replay/content
  conflict checks before atomically comparing the expected watermark in both
  Memory and SQLite;
- immutable, schema-bound source bindings and mapped source snapshots for
  source-backed object existence, properties, and links, with explicit
  complete/partial/unknown coverage;
- deterministic source-adapter manifests that distinguish vendor application
  schema versions from target Ontology schema identity, plus detached output
  conformance checks;
- deployment-scoped, content-addressed identity crosswalk snapshots with
  explicit confirmed, unresolved, and conflict states, plus a read-only
  resolver that never selects an ambiguous candidate;
- two Product-side SQLite ERP and maintenance fixtures under
  `tests/integration/ontology/` proving that different source keys can resolve
  to one canonical object, contribute non-overlapping authority, remain input
  order independent, survive restart, and reject ambiguous identity without
  adding production connectors or an identity provider;
- deterministic source-plus-Fact object/property/link materialization, including
  property bindings independent from object-existence bindings: object existence
  and links expose `FactOrigin` or `SourceOrigin`, while ontology-owned
  properties may additionally expose `SchemaDefaultOrigin`;
- explicit rejection of mapped properties or links whose `valid_from` is later
  than the selected materialization `valid_at`;
- immutable `MaterializationCut` build coordinates containing deterministic
  mapped-payload digests plus explicit, pure Fact and source-head
  `ProjectionFreshness` evaluation;
- a narrow ProjectionReadStore and atomic whole-snapshot ProjectionStore,
  including synchronized replacement in the Memory reference adapter;
- backend-neutral typed queries over projection reads, guarded by complete
  `SchemaIdentity` rather than a version string alone;
- independent Memory and SQLite FactStore/ProjectionStore adapters;
- SQLite v3 source-aware cut/origin persistence, corruption checks, schema
  identity, restart, and backup;
- content-addressed Fact schema-revalidation receipts that authorize an exact
  old-schema Fact selection for one target schema without rewriting Facts;
- strict Deployment Profile v2 values that independently lock compiled Schema,
  Adapter manifests, concrete source-instance/binding selections, an optional
  immutable Identity Crosswalk, and opaque Fact/Projection store references;
- deterministic Ontology package artifacts that bundle one compiled Schema,
  exact direct dependency locks, and closed-set diagnostics for missing,
  changed, duplicated, namespace-conflicting, or cyclic package artifacts;
- strict `ActionRequest`, `ProjectionGuard`, and `ActionPlan` values plus a pure
  planner that consumes one exact Projection and detached Fact selection,
  deterministically emits an ontology-owned Fact batch, rejects derived writes,
  and reports source-backed Actions as not implemented.

The materialization path accepts both a detached `FactSelection` and
immutable mapped source snapshots. Ordinary source-backed values therefore do
not require per-property Facts, while FactStore remains authoritative for
records inside its declared scope. Memory and SQLite now preserve the same
source cuts and origin kinds. Source adapter implementations remain hosted and
executed by Product; Ontology serializes manifests and validates detached
outputs but contains no connector runtime. Product also owns identity matching,
review, and mutable identity state; Ontology accepts only an explicit immutable
resolver result at the Product Adapter boundary.
Projection replacement installs disposable infrastructure state; it is not
object CRUD. There is no dynamic `Ontology` facade, mutable ObjectStore,
callable RuleEngine, direct DataFusion, or Ontology/HarnessWork Action bridge.

This is infrastructure, not a domain ontology and not a Palantir product
clone. Runtime coordination, concrete vendor adapters, source-backed Action
execution, Decisions, generated SDKs, standards bridges, SQL pushdown, and
environmental packages remain later work.

## Accepted Direction And Implementation Boundary

[ARD-003](ARD-003-declared-state-authority-and-multi-source-materialization.md)
defines how application-version source mappings and multiple systems of record
will enter materialization. It separates business-state ownership
(`StateAuthority`) from FactStore's semantic-record authority, adding immutable
mapped source inputs, and separating a projection's build cut from observed
freshness. It is tracked in
[#439](https://github.com/zhnt/loushang/issues/439).

The implemented ARD-003 foundation includes materialization correctness
(atomic Fact selection, immutable build coordinates, explicit Fact freshness,
and snapshot-consistent SQLite reads), stable semantic identity, and declared
state ownership (now carried forward by schema v4 and schema-diff v4), plus
the Memory-only source composition and origin-contract slices. They add
concrete source bindings, full mapped object/property/link snapshots,
`MaterializationCut`, complete operational origins, explicit authority failure
contracts, and source-head freshness.

[ARD-004](ARD-004-schema-identity-semantic-references-and-source-input-cuts.md)
closes the first runtime identity boundary: schema owns the single-package
`SchemaIdentity`; Facts and source bindings target it explicitly; Fact
assertions use stable semantic IDs; and a selected source cut includes coverage
and the exact mapped-payload digest while freshness continues to compare cheap
observable heads. Whole-snapshot materialization accepts only complete source
coverage.

ARD-005 replaces the undeployed SQLite v2 physical layout with one v3 format
that round-trips exact source cuts, `FactOrigin`, `SourceOrigin`, and
`SchemaDefaultOrigin`. ARD-006 defines a serializable adapter manifest,
structural Product-hosted protocol, and public output conformance boundary;
Ontology still does not run vendor code. ARD-007 permits an exact old-schema
Fact selection to be validated for a target schema through a content-addressed
receipt recorded in the materialization cut. Change sets, logic bindings,
derived computation origins, source write routing, multi-package dependency
profiles, full Fact journal migration, and deployment switching remain deferred.

ARD-008 records the historical Profile v1 rationale. Its v1 shape is superseded
by ARD-010 and has no compatibility reader.

ARD-009 defines the first executable identity boundary. A source record is
scoped by source instance, binding, record type, and source key; only an
explicitly confirmed resolution may become a canonical UUID.

ARD-010 defines the current Profile v2 contract. Source instances select
bindings through locked Adapters, and an optional Crosswalk lock validates
deployment, namespace, revision, content, and selected source scope. It still
does not load endpoints, credentials, stores, or Adapter implementations.

ARD-011 defines a pure package artifact and exact dependency-closure check. It
does not merge Schemas, resolve versions, publish artifacts, or alter the
single-Schema runtime and Deployment Profile.

ARD-012's ontology-owned Phase 2 slice is implemented. Published
`ActionDefinition` values belong to compiled Schema v4 and package content; a
pure planner validates one exact Profile, Projection guard, and detached Fact
selection before emitting a deterministic guarded Fact batch. Derived state is
not writable and source-backed Actions fail explicitly until the locked write
capability and Product-hosted adapter slice exists. Authorization remains
outside Ontology. External acknowledgement, cross-authority Actions, overlays,
sagas, and generic effect DSLs remain deferred.

## Proposed Target Designs

[Domain Ontology Ecosystem And Multi-Application Deployment](key-designs/domain-ontology-ecosystem-and-deployment.md)
proposes how the domain-neutral Ontology substrate can support independently
delivered domain packages, mature-ontology alignments, standards knowledge,
vendor adapters, warehouses, and one bureau deployment serving several
applications. Environmental information systems are its first validation
scenario; the design explicitly forbids an environmental package or vendor
adapter dependency in `loushang.ontology`.

This proposal is not Current implementation truth and is not part of the
accepted ARD reading order until reviewed and accepted.

## Runtime Shape

```text
OntologyPackageArtifact --> compiled Schema ---------------------+
DeploymentProfile v2 --> validated Schema + source instances ---+
locked CrosswalkSnapshot --> Product-hosted adapter -------------+
Source system -------------> Product-hosted adapter              |
Product-hosted adapter ----> Manifest + MappedInput -------------+
                                                               |
Fact Producer -------------> FactStore --> FactSelection -------+
                                                               |
CompiledOntologySchema -----------------------------------------+
                                                               v
                                                    +-------------------+
                                                    | Pure Materializer |
                                                    +-------------------+
                                                               |
                                                               v
                                       ProjectionSnapshot + MaterializationCut
                                                               |
                                                atomic replace | read
                                                               v
                                                     ProjectionStore
                                                               |
                                                               v
                                                    QueryRequest/Result
```

A failed materialization or projection replacement cannot undo an accepted
Fact batch. A later Fact commit or source revision never mutates the installed
snapshot's build coordinates. Callers compare its cut with explicitly observed
Fact and source heads through `evaluate_projection_freshness(...)`.

The implemented ontology-owned Action path is separate from materialization:

```text
ActionRequest + DeploymentProfile v2
ProjectionSnapshot + exact FactSelection
                |
                v
        +---------------------+
        | Pure Action Planner |
        +---------------------+
                |
                v
 OntologyFactEffect(FactBatch + expected watermark)
                |
       guarded commit
                v
            FactStore
                |
       later materialization
                v
        refreshed Projection
```

## Dependency Direction

```text
schema.identity ----------------------> Foundation JSON
schema compiler/diff -----------------> schema.identity + Foundation JSON
facts.model --------------------------> schema.identity + Foundation JSON
facts.ports --------------------------> facts.model
facts.commit -------------------------> facts.model + facts.ports
source.model -------------------------> schema.identity + Foundation JSON
source.adapter -----------------------> source.model + schema.identity
identity -----------------------------> Foundation JSON
package ------------------------------> schema + Foundation JSON
deployment.model ---------------------> schema.identity + Foundation JSON
deployment.validation ----------------> deployment.model + schema + source
                                       + identity
projection.model ---------------------> schema + Foundation JSON
projection.ports ---------------------> projection.model
projection.materializer -------------> facts.ports + source
                                       + projection.model + schema
projection.revalidation -------------> facts + schema + materializer
action ------------------------------> deployment + facts + projection
                                       + schema + source
query --------------------------------> projection ports/models
storage.memory -----------------------> facts + projection ports/models
storage.sqlite -----------------------> facts + projection ports/models + schema

domain packages -X-> storage
query           -X-> storage
memory adapter  -X-> SQLite adapter
SQLite adapter  -X-> memory adapter
ontology        -X-> Harness / HarnessWork / Method / Product
schema / source / facts / projection / query / storage -X-> identity
facts / source / identity / projection / query / storage / deployment
                -X-> package
schema / source / facts / projection / query / storage / deployment
                -X-> action
```

Product or domain adapters may depend on public Ontology contracts when they
need semantic typing. Ontology does not depend back on an execution runtime or
product subsystem.

## Source Ownership

- `schema/`: drafts, stable semantic identity, StateAuthority declarations,
  compiler, immutable schemas, diagnostics, and diff;
- `facts/model.py`: immutable Fact envelope, typed assertions, provenance, and
  FactBatch;
- `facts/ports.py`: Fact read/write ports, stable commit values, and atomic
  `FactSelection`, including explicit guarded Action commit;
- `facts/commit.py`: pure commit planning, journal validation, lineage, and
  bitemporal selection;
- `source/`: immutable schema-bound source authority bindings, mapped
  object/property/link snapshots, exact content-digested cuts, declared
  coverage, observable source revision coordinates, adapter manifests, and
  detached conformance checks; no concrete connector;
- `identity/`: immutable deployment-scoped explicit crosswalk snapshots,
  source-record identity, resolution states, and a read-only resolver port; no
  matching, review, mutable registry, or persistence service;
- `package/`: one compiled Schema, exact package dependency locks, canonical
  artifact digests, and pure closed-set validation; no registry, version solver,
  multi-Schema composition, Alignment payload, or Standards payload;
- `deployment/`: immutable Schema/Adapter/Crosswalk artifact locks,
  source-instance/binding selection, opaque store references, and pure
  compatibility validation; no runtime loader or deployment service;
- `action/`: strict request/guard/plan contracts and pure ontology-owned
  `SetProperty` planning; no Store access, authorization, source write, Product,
  Harness, or HarnessWork execution;
- `projection/model.py`: immutable object, property, link, build state,
  value origins, materialization cut, freshness observation, and snapshot;
- `projection/ports.py`: projection reads and atomic replacement;
- `projection/materializer.py`: schema validation and deterministic snapshot
  construction;
- `projection/revalidation*.py`: immutable schema-revalidation receipts and
  pure validation of an exact Fact selection against a target schema;
- `query/`: immutable requests/results, fluent builder, and reference evaluator;
- `storage/memory.py`: independent reference Fact and Projection adapters;
- `storage/sqlite.py`: direct SQLite Fact and Projection adapters plus physical
  compatibility failures.

The complete package deliberately has no `ontology/core/` directory.

## SQLite v3

The only supported physical identity is `loushang.ontology.sqlite`, version 3,
with `storage_layout=source-aware-projection`. Any other storage version or
layout is rejected; there is no v2 compatibility reader or migration path for
development stores.

```text
ontology_metadata       ontology_schema
semantic_facts          fact_batches
projection_metadata     projection_source_inputs
projection_objects
projection_properties   projection_links
```

`authority_objects`, `mutation_journal`, and `projection_unique_values` are
not part of the current layout. Every projected object, property, and link
stores a constrained origin kind plus strict kind-specific JSON. Startup
reconstructs the public snapshot and rejects missing cuts, malformed origins,
or origin/cut mismatches.

## Removed Greenfield Surface

These paths and symbols intentionally do not exist:

- `ontology.core` and `ontology.core.ontology.Ontology`;
- `ontology.rules`;
- `ontology.fusion`;
- `ontology.integrations.harnesswork`;
- top-level `ObjectStore` and mutable object-store ports;
- public `SQLiteObjectStore`;
- `FactProjection` wrappers and runtime-sealed mutable views.

They must not return as compatibility aliases. Future broader CRUD, derivation,
Agent, source-backed Action, and Decision surfaces use their declared
authority. Implemented ontology-owned Actions are Fact-backed; ARD-012 controls
the source-backed command boundary, which remains unimplemented.

## Normative Reading Order

1. [ARD-001: FactStore Is The Sole Semantic Authority](ARD-001-factstore-semantic-authority.md)
2. [ARD-002: Ports, Immutable Projections, And The Phase 2 SQLite v2 Layout](ARD-002-ports-immutable-projection-and-sqlite-v2.md)
3. [ARD-003: Declared State Authority And Multi-Source Materialization](ARD-003-declared-state-authority-and-multi-source-materialization.md)
4. [ARD-004: Schema Identity, Semantic References, And Source Input Cuts](ARD-004-schema-identity-semantic-references-and-source-input-cuts.md)
5. [ARD-005: Source-Aware SQLite v3](ARD-005-source-aware-sqlite-v3.md)
6. [ARD-006: Product-Hosted Source Adapter Contract](ARD-006-product-hosted-source-adapter-contract.md)
7. [ARD-007: Fact Schema Revalidation Receipts](ARD-007-fact-schema-revalidation-receipts.md)
8. [ARD-008: Immutable Deployment Profile And Artifact Locks](ARD-008-immutable-deployment-profile-and-artifact-locks.md)
9. [ARD-009: Explicit Identity Crosswalk Snapshots](ARD-009-explicit-identity-crosswalk-snapshots.md)
10. [ARD-010: Deployment-Bound Source Instances And Identity Lock](ARD-010-deployment-bound-source-instances-and-identity-lock.md)
11. [ARD-011: Deterministic Ontology Package Artifacts](ARD-011-deterministic-ontology-package-artifacts.md)
12. [ARD-012: Authority-Aware Action Planning And Product-Hosted Write-Back](ARD-012-authority-aware-action-planning-and-product-hosted-write-back.md)
13. [Wave 2A Facts And Provenance](wave2a-facts-provenance.md)
14. [Schema Evolution](schema-evolution.md)

The larger design and reference analysis remains in
[`drafts/loushang-ontology-operational-infrastructure.md`](drafts/loushang-ontology-operational-infrastructure.md).
It is directional material, not current implementation truth.
