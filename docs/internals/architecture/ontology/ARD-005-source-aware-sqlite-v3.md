# ARD-005: Source-Aware SQLite v3

Status: Accepted, 2026-08-10.

## Context

ARD-003 introduced mapped-source materialization and ARD-004 made each selected
source input content-addressed. The Memory projection adapter could preserve
those contracts, but the SQLite v2 layout stored only Fact-backed origins and
no source-input vector. It therefore rejected every source-aware snapshot.

That rejection prevented silent lineage loss, but it left the implemented
multi-source runtime without a durable restart and backup path.

## Decision

### 1. Replace v2 with one v3 format

The only supported SQLite physical format is now:

```text
storage_format         = loushang.ontology.sqlite
storage_format_version = 3
storage_layout         = source-aware-projection
```

There is no v2 reader, writer, migration command, or dual-format compatibility
path. These stores are not deployed legacy state; old development files are
recreated explicitly.

### 2. Persist exact materialization cuts

`projection_source_inputs` stores one row per selected binding:

```text
binding_id
mapping_version
source_revision
payload_digest
coverage
```

These rows reconstruct the exact `SourceInputCut` vector. Observable source
heads remain runtime freshness observations and are not persisted as projection
state.

### 3. Persist every origin without inference

Projection object, property, and link rows store:

```text
origin_kind = fact | source | schema_default
origin_json = strict kind-specific JSON
```

The JSON field is not a second generic provenance model. Its accepted fields
are fixed by `origin_kind` and decoded into exactly one of `FactOrigin`,
`SourceOrigin`, or `SchemaDefaultOrigin`. Extra, missing, malformed, or
kind-incompatible fields fail store validation.

`fact_id` remains a nullable projection convenience for Fact-backed properties
and links. It must agree with `FactOrigin`; source-backed values carry no
`fact_id`.

### 4. Preserve atomic snapshot semantics

Whole-snapshot replacement deletes and inserts source cuts, objects,
properties, links, and metadata in one `BEGIN IMMEDIATE` transaction. Snapshot
reconstruction reads all tables in one read transaction. A failed replacement
leaves the prior installed snapshot and Fact journal unchanged.

Startup validation rebuilds the public `ProjectionSnapshot`. Its existing
invariants then verify that:

- every `SourceOrigin` references a selected source cut;
- every `FactOrigin` references a selected Fact ID;
- every `SchemaDefaultOrigin` matches the installed schema identity;
- schema shape, endpoints, value types, and required constraints remain valid.

## Consequences

- Memory and SQLite now implement the same source-aware projection contract.
- Restart and SQLite backup preserve exact cuts and all origin kinds.
- v2 files are rejected without modification.
- The physical schema remains a disposable serving projection, not a business
  mutation authority or provenance event store.

## Acceptance Gates

- one source-plus-Fact-plus-default snapshot is equal before and after SQLite
  replacement, restart, and backup restore;
- Memory and SQLite pass the same source-aware projection assertion;
- missing source-cut rows, malformed digests, and malformed origin payloads are
  rejected as storage-format failures;
- Fact-only projection and FactStore conformance remain green;
- no adapter scheduler, CDC state, merge journal, or Action state is added.

## Deferred

- incremental projection persistence and SQL pushdown;
- partial snapshot merge state and deletion semantics;
- connector cursors, scheduling, retry, and CDC checkpoints;
- in-place migration of old development SQLite files;
- deployment-level atomic switching between schema versions.
