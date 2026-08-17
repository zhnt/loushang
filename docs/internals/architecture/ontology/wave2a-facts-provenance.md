# Ontology Wave 2A Facts And Provenance

> The Fact envelope, lineage, and bitemporal authority in this document remain
> accepted. ARD-002 supersedes its projection API and original SQLite
> table-layout descriptions: current code uses `ProjectionSnapshot`,
> `materialize_projection`, and independent adapters.
> See [ARD-002](ARD-002-ports-immutable-projection-and-sqlite-v2.md).
> [ARD-003](ARD-003-declared-state-authority-and-multi-source-materialization.md)
> later replaced direct live-store materialization with atomic `FactSelection`
> and separated immutable projection state from runtime freshness.
> [ARD-004](ARD-004-schema-identity-semantic-references-and-source-input-cuts.md)
> advances Fact and FactBatch JSON to v2: every Fact targets one complete
> `SchemaIdentity`, and assertion predicates are stable semantic IDs rather
> than renameable API names. Those ARD-004 rules supersede the original payload
> names below.
> [ARD-005](ARD-005-source-aware-sqlite-v3.md) replaces the undeployed v2
> physical layout with the sole supported source-aware SQLite v3 format.
> [ARD-007](ARD-007-fact-schema-revalidation-receipts.md) permits an exact
> selection to be revalidated against a compatible newer schema through an
> immutable receipt; it does not change historical Fact identity or authority.

## Status

Accepted implementation boundary for Wave 2A. This wave introduces the
append-only semantic Fact/Provenance authority, deterministic bitemporal
selection, and Fact-to-Object/Property/Link projection. Its original SQLite
format decision is historical; ARD-005 now controls physical format v3.

SQLite persistence accepts only the current source-aware v3 layout. Incompatible
development stores are rejected and must be recreated; there is no legacy
reader or migration path.

[ARD-001](ARD-001-factstore-semantic-authority.md) later made this FactStore the
sole semantic authority and removed the earlier public object-mutation path.

## Runtime Spine

```text
Source / future Adapter
          |
          | immutable FactBatch
          v
   +-------------------+
   | Semantic FactStore|  append-only authority + provenance
   +-------------------+
          |
          | select(valid_at, recorded_at)
          v
   +-------------------+
   | Fact Projector    |  schema validation + strict conflict detection
   +-------------------+
          |
          v
 Object / Property / Link projection
          |
          v
 QueryRequest -> QueryResult
```

The original Wave 2A SQLite v2 layout contained an operational mutation journal.
ARD-002 removed that table when it reset the undeployed v2 layout to Phase 2;
the current adapter rejects `mutation_journal` as a legacy table. Applications
append `FactRecord` values; object mutation is not an alternative authority
path.

## Fact Envelope

Every immutable `FactRecord` contains:

- a stable `fact_id`, one complete `SchemaIdentity`, and one typed assertion
  payload using package-local stable semantic IDs;
- `assertion_kind`: `asserted`, `derived`, or `inferred`;
- non-empty `source_ref` and `source_record_ref`;
- optional ordered `evidence_refs`, `methodology_ref`, `author_ref`, and
  `agent_ref`;
- optional finite confidence in the closed interval `[0, 1]`;
- business validity `[valid_from, valid_to)`;
- immutable system `recorded_at`;
- at most one lineage edge: `supersedes` or `corrects`.

The three infrastructure assertion payloads are deliberately small:

| Assertion | Meaning |
| --- | --- |
| `ObjectAssertion(object_type_id)` | the subject exists as one stable schema object-type ID |
| `PropertyAssertion(property_id, value)` | one strict Foundation JSON value is asserted for a stable property ID |
| `LinkAssertion(link_type_id, target_id, properties)` | one stable link-family edge exists from subject to target |

Measurement and Claim are domain object types built with these facts, not new
hard-coded infrastructure enums. Property `null` is a real JSON value and is
not confused with an absent assertion payload.

Facts are immutable after commit. A correction or newer observation appends a
new fact; it never updates or deletes the earlier record.
Retraction uses the same append-only mechanism: a correcting successor repeats
the assertion with a closed `valid_to`; after that boundary neither the retired
predecessor nor the expired successor appears in the current valid-time view.

## Bitemporal And Lineage Semantics

Selection always names both axes:

- `valid_at` answers what was true in the business world at that time;
- `recorded_at` answers what the system knew by that time.

A fact is selectable when it was recorded no later than `recorded_at` and its
half-open valid interval contains `valid_at`. A visible successor linked by
`supersedes` or `corrects` retires its referenced fact from the selected view.
Historical reads before the successor's `recorded_at` still expose the older
fact.

Lineage edges must point to a previously committed fact or an earlier fact in
the same batch. The predecessor must have the same subject, assertion category,
assertion kind, predicate, source, and source-record identity. The successor
cannot have an
earlier `recorded_at`. These rules make lineage acyclic and prevent one source
from silently overwriting another source's assertion.

Facts from different sources may coexist. Wave 2A has no merge-policy or source
priority framework. When coexisting current facts imply different object
types or property values, projection fails with explicit diagnostics instead
of choosing a winner. Equivalent assertions are safely coalesced.

## Batch And Idempotency Contract

`FactBatch` is the atomic ingestion unit and has a stable non-empty `batch_id`.
All fact IDs within a batch are unique, and all Facts in the batch carry the
same complete `SchemaIdentity`. A Fact journal cannot mix schema identities.

- the first successful commit appends each fact with one contiguous fact
  sequence and advances the fact watermark;
- replaying the same batch ID with byte-equivalent canonical content returns
  the original commit range with `replayed=True` and appends nothing;
- reusing a batch ID with different content raises
  `FactBatchConflictError`;
- duplicate fact IDs, invalid lineage, invalid envelopes, or persistence
  failures append nothing and do not advance the watermark.

Batch idempotency is infrastructure replay protection. `source_record_ref`
remains the semantic source identity used by future adapters and fusion.

## Projection Contract

Projection consumes one compiled schema and a fact selection at explicit
`valid_at` and `recorded_at` values. It performs these deterministic steps:

1. resolve current facts through recorded-time lineage;
2. require exactly one compatible object type per subject;
3. coalesce equal property/link assertions and reject conflicting properties;
4. materialize objects with their complete current property sets;
5. materialize links after all endpoints exist;
6. run the normal schema, unique, type, cardinality, required-field, endpoint,
   and reference-integrity checks.

The result carries the selected fact IDs, source fact watermark, schema
version, and the two projection times. Repeating projection with the same
schema, fact sequence, and times produces an equivalent object/link graph.

Projection does not mutate the FactStore and does not append semantic or
operational records. It is safe to rebuild after restart or from an online
backup.

## SQLite Physical Format

The current physical identity is `loushang.ontology.sqlite`, version `3`, with
`storage_layout=source-aware-projection`. `SQLiteFactStore` writes
`semantic_facts` and `fact_batches` directly; it does not delegate to the
Memory adapter or expose object mutation. Fact commits and whole-projection
replacement remain distinct transactions. Projection replacement atomically
persists exact source-input cuts, all operational origins, immutable build
coordinates, and any Fact revalidation receipt digest. Reopen and online
backup restore the same Fact sequence, replay behavior, projection cut, and
origins.

The loader rejects other versions/layouts, incomplete tables, malformed facts,
and inconsistent watermarks. There is no silent DDL repair, implicit migration,
or compatibility facade.

## Public Surface

The Fact package publishes:

- `AssertionKind`, `ObjectAssertion`, `PropertyAssertion`, `LinkAssertion`;
- `FactRecord`, `FactBatch`, `StoredFact`, `FactCommit`;
- `FactReadStore`, `FactStore`, and pure commit-planning contracts;
- stable fact validation and batch-conflict failures.

Immutable projection models, ports, diagnostics, and
`materialize_projection` live in `loushang.ontology.projection`. Memory and
SQLite adapters live in `loushang.ontology.storage`; the top-level package
re-exports stable domain values and Memory reference adapters.

The SQLite implementation remains under `loushang.ontology.storage` because
backend selection is an application composition concern.

## Acceptance Gates

- one FactStore conformance suite passes for Memory and SQLite;
- asserted, derived, and inferred records remain distinguishable after commit,
  restart, and backup;
- duplicate batch replay is idempotent and conflicting replay is rejected;
- correction/supersession preserves historical recorded-time reads;
- valid-time boundaries use `[from, to)` consistently;
- invalid lineage and failed SQLite transactions leave facts and watermark
  unchanged;
- projection materialization is deterministic, schema-valid, and rebuildable for objects,
  properties, links, uniqueness, and cardinality;
- SQLite v3 rejects incompatible versions and layouts without altering them;
- Fact authority and ProjectionStore APIs remain visibly separate;
- Foundation-only and product-execution import boundaries remain intact.

## Non-Goals

- legacy migration, repair, or dual-format readers;
- source/API/database adapters, cursors, mappings, or entity resolution;
- JSON-LD, RDF, OWL, SHACL, or safe-expression standards work;
- source-priority and merge-policy resolution;
- Actions, Decisions, authorization, approval, or external write-back;
- SQL query pushdown, generated SDKs, domain packages, or distributed serving.
