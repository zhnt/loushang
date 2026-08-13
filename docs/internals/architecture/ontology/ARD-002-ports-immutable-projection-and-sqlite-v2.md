# ARD-002: Ports, Immutable Projections, And The Phase 2 SQLite v2 Layout

Status: Accepted, 2026-08-09.

Tracking: [#438](https://github.com/zhnt/loushang/issues/438).

The materialization and freshness portions are partially superseded by
[ARD-003](ARD-003-declared-state-authority-and-multi-source-materialization.md).
The port separation, adapter independence, and immutable replacement remain
accepted. [ARD-005](ARD-005-source-aware-sqlite-v3.md) supersedes the Phase 2
SQLite v2 physical table set with the source-aware v3 layout.

## Context

[ARD-001](ARD-001-factstore-semantic-authority.md) made the append-only
FactStore the sole semantic authority, but Phase 1 deliberately retained two
implementation artifacts:

- `ontology.core.ObjectStore`, a mutable object graph used to build and then
  seal a Fact projection;
- a combined SQLite backend that inherited the object store and delegated Fact
  behavior to `MemoryFactStore` before persisting both models.

Those artifacts obscured the authority decision. They also made it possible
for SQLite correctness to depend on an in-memory adapter and made a projection
look like a disabled mutable store rather than an immutable value.

There is still no deployed Ontology database or compatibility commitment. The
pre-Phase-2 SQLite v2 layout may therefore be rejected and recreated rather
than migrated.

## Decision

Ontology is split into domain contracts, pure domain services, and adapters.

```text
schema ───────────────────────────────────────────────> Foundation JSON

facts.model ──> Foundation JSON
facts.ports ──> facts.model
facts.commit ─> facts.model + facts.ports

projection.model ───────> schema + Foundation JSON
projection.ports ───────> projection.model
projection.materializer -> facts.ports + projection.model + schema

query ──────────────────> projection.ports + projection.model

storage.memory ─────────> facts + projection ports/models
storage.sqlite ─────────> facts + projection ports/models + schema
```

The dependency rules are normative:

1. Domain packages do not import storage adapters.
2. Query does not import a concrete adapter.
3. Memory and SQLite adapters do not import or delegate to each other.
4. Ontology does not import Harness, HarnessWork, Method, Product, or a
   domain package.
5. `ontology.core` does not exist. It is not a compatibility namespace.

## Fact Commit Boundary

`facts.ports` owns `FactReadStore`, `FactStore`, `StoredFact`, `FactCommit`,
atomic `FactSelection`, and the stable conflict error. `facts.commit` owns pure
commit planning, journal validation, lineage validation, and bitemporal
selection.

`prepare_fact_commit(...)` receives an explicit fact-journal snapshot and
committed-batch identities. It returns `PreparedFactCommit` without changing
state. Each adapter applies that plan atomically using its own storage
mechanism:

- `MemoryFactStore` updates only its own collections;
- `SQLiteFactStore` plans and writes inside one `BEGIN IMMEDIATE` transaction.

SQLite does not mirror a `MemoryFactStore`, subclass an object store, or call a
private method on another adapter.

## Projection Boundary

Materialization returns a `ProjectionSnapshot`, not a sealed mutation object.
The snapshot contains only frozen values:

- `ProjectedObject`;
- `ProjectedProperty`, which stores a canonical JSON value and returns detached
  JSON trees;
- `ProjectedLink`, which stores detached link properties;
- `ProjectionState`, including schema version, projection version, the captured
  Fact watermark, valid time, recorded time, and build time.

`materialize_projection(...)` consumes a detached atomic `FactSelection` and
does not read a live FactStore.
It validates object type, inherited property declaration, value type, required
and unique properties, link endpoint types, link cardinality, required links,
and cross-source conflicts. It cannot write Facts or projection storage.

`ProjectionReadStore` is the query port. `read_snapshot()` captures one
immutable graph so a multi-step query cannot mix two concurrent replacements.
`ProjectionStore` adds exactly one write operation: `replace(snapshot)`.
Replacement is infrastructure state installation, not business CRUD. It
atomically replaces the complete serving graph; there are no public create,
set-property, link, unlink, or delete commands.

Bitemporal coordinates are chosen when the snapshot is materialized. Query no
longer has an `AsOf` step that could imply a sealed snapshot contains other
valid-time views. A different valid or recorded time requires another
snapshot.

## Failure And Freshness Contract

- A successful Fact commit is never rolled back because later materialization
  or projection replacement fails.
- Rejected Fact batches leave the fact journal, batch identities, and watermark
  unchanged.
- Rejected projection replacement leaves the previously installed graph and
  projection version unchanged.
- A later Fact commit does not mutate an installed snapshot's build
  coordinates. `evaluate_projection_freshness(...)` compares its captured Fact
  watermark with an explicit runtime observation.
- Memory and SQLite apply the same replacement contract: structural validity
  and the next monotonic projection version. Installation freshness policy
  belongs to the caller, not an adapter-local hidden check.
- SQLite reconstructs one projection under one read transaction.
- Projection rows are disposable. Rebuilding from schema, Facts, and explicit
  time coordinates is the recovery operation.

## SQLite v2 Physical Layout

The physical identity is `loushang.ontology.sqlite`, version `2`, with the
required layout marker `storage_layout=phase2`. A file without that marker, or
with the removed authority/journal tables, is rejected with an instruction to
recreate the development store. There is no reader, migration, alias, or
silent repair for obsolete development layouts.

The complete Phase 2 table set is:

```text
ontology_metadata
ontology_schema
semantic_facts
fact_batches
projection_metadata
projection_objects
projection_properties
projection_links
```

The following tables no longer exist:

```text
authority_objects
mutation_journal
projection_unique_values
```

`projection_metadata` retains the Phase 2 physical columns
`source_fact_watermark` and `projected_fact_watermark`. The adapter requires
them to be equal and writes the immutable `ProjectionState.fact_watermark` to
both; Fact commits never update them. A later multi-source layout may replace
these historical column names. The table also records `schema_version`,
`valid_at`, `recorded_at`, `projection_version`, `built_at`, and the selected
Fact identities.

## Public Package Shape

```text
ontology/
  schema/
    definitions.py
    compiler.py
    diagnostics.py
    evolution.py
  facts/
    model.py
    ports.py
    commit.py
  projection/
    model.py
    ports.py
    materializer.py
  query/
    contracts.py
    builder.py
    engine.py
  storage/
    memory.py
    sqlite.py
```

The top-level package re-exports stable domain values, ports, query values,
and memory reference adapters. Durable adapters remain under
`loushang.ontology.storage`.

## Consequences

Benefits:

- the source tree now makes the sole Fact authority visible;
- projections are immutable by construction rather than by a runtime seal;
- storage conformance can compare independent adapters;
- Fact durability and projection refresh have separate failure domains;
- ontology-owned command compilers have one target: deterministic FactBatch
  commit; source-backed commands follow the later authority-specific contract.

Costs:

- old development SQLite v2 files must be recreated;
- projection replacement currently rewrites the complete SQLite serving graph;
- the reference query engine reads the projection port in memory and does not
  push predicates into SQL;
- there is not yet a coordinator that schedules materialization or increments
  projection versions for callers.

## Phase 2 Non-Goals

This decision does not add:

- CRUD or Action command compilation;
- source discovery, staging, mapping, or write-back;
- rule, derivation, Decision, or Agent execution;
- HarnessWork integration;
- OWL, SHACL, RDF, or JSON-LD exporters;
- domain ontology packages;
- SQL query pushdown, incremental materialization, or distributed serving.

Those capabilities must preserve FactStore authority and treat
`ProjectionStore.replace` as infrastructure installation, never a second
semantic mutation path.
