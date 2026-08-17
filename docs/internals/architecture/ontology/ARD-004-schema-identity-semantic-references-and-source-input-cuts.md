# ARD-004: Schema Identity, Semantic References, And Source Input Cuts

Status: Accepted, 2026-08-10.

[ARD-005](ARD-005-source-aware-sqlite-v3.md) later persists these exact cuts in
SQLite v3. [ARD-006](ARD-006-product-hosted-source-adapter-contract.md) places
schema-bound bindings in a versioned vendor manifest, and
[ARD-007](ARD-007-fact-schema-revalidation-receipts.md) defines explicit reuse
of old-schema Fact selections without weakening the identity check.

## Context

ARD-003 established package-local stable semantic IDs, declared state
authority, mapped source inputs, and immutable materialization cuts. The first
implementation still leaves three identity gaps:

1. `SchemaIdentity` is owned by the projection package even though schema,
   Facts, source bindings, queries, and storage all need it.
2. Fact assertions identify object types, properties, and link types by
   renameable API names. A Fact batch and source binding can therefore be
   presented to a same-version but different package unless the caller catches
   the mistake.
3. A source cut records `binding_id + mapping_version + source_revision`, but
   not the exact mapped payload or its coverage. Reusing those coordinates with
   different content would produce cuts that look equal while representing
   different inputs.

The future domain-package ecosystem will require a deployment profile and a
multi-package lock. Those artifacts do not exist yet. Introducing a registry,
dependency solver, or synthetic installed-profile type now would create a name
without an executable contract.

## Decision

### 1. Schema owns `SchemaIdentity`

`SchemaIdentity(package_id, namespace, version)` moves to
`loushang.ontology.schema`. It is the exact identity of one compiled schema and
is reused by Facts, source bindings, projection state, queries, and storage.

The current runtime remains single-package. `SchemaIdentity` is not renamed to
deployment or profile identity and does not claim to identify a future
multi-package installation.

### 2. Fact assertions use stable semantic IDs

The Fact contract becomes schema v2:

```text
FactRecord
  schema_identity
  subject_id
  ObjectAssertion(object_type_id)
  | PropertyAssertion(property_id, value)
  | LinkAssertion(link_type_id, target_id, properties)
  provenance and bitemporal coordinates
```

API names remain serving and generated-API metadata. They are not durable Fact
predicates. Materialization resolves semantic IDs through the selected compiled
schema and emits the current API names into the projection.

Every Fact in one `FactBatch` must carry the same complete `SchemaIdentity`.
Fact stores reject a journal or commit that mixes identities. SQLite additionally
requires the batch identity to equal its bound schema. Materialization rejects a
Fact selection whose identity differs from the selected schema.

This slice does not define online schema migration. A later migration decision
may describe how Facts accepted under an older version are revalidated against
stable IDs in a newer installed schema.

### 3. Source bindings are schema-bound

Each `SourceBinding` carries the complete target `SchemaIdentity`. The
materializer rejects a binding for another package, namespace, or version before
resolving any authority target.

`MappedSourceInput` remains linked to a binding by `binding_id` and
`mapping_version`; it does not repeat the target identity. The validated binding
is the authority and schema anchor.

### 4. Separate observable heads from exact input cuts

An observed source head remains:

```text
SourceInputRevision(binding_id, mapping_version, source_revision)
```

It answers whether a source has advanced and can be obtained without reading the
full payload.

An installed materialization cut instead records:

```text
SourceInputCut
  binding_id
  mapping_version
  source_revision
  payload_digest
  coverage
```

`payload_digest` is SHA-256 over a deterministic strict-JSON projection of the
complete mapped snapshot. It covers canonical object IDs, semantic IDs, source
record and field references, values, validity coordinates, links, and link
properties. It does not digest credentials, endpoints, transport envelopes, or
raw source records.

Freshness compares the revision coordinates of selected cuts with observed
heads. Payload digests are reproducibility coordinates, not a requirement for a
cheap head observation.

### 5. Coverage is explicit and initially narrow

Mapped source coverage is one of:

- `complete`: the payload is a complete snapshot for the binding's declared
  source view at that revision;
- `partial`: the payload intentionally covers only part of that view;
- `unknown`: the adapter cannot establish coverage.

The current whole-snapshot materializer accepts only `complete`. `partial` and
`unknown` fail explicitly because omission cannot yet be distinguished from
deletion. This records the contract without adding merge state, CDC, or a
partial-update engine.

## Dependency Direction

```text
schema.identity <--- facts.model
        ^        <--- source.model
        |        <--- projection.model
        +--------<--- query contracts

projection.materializer ---> schema + facts + source
storage adapters ----------> schema + facts + projection
```

Schema identity imports neither Facts, Source, Projection, Query, nor Storage.

## Consequences

Benefits:

- durable Facts survive API-name renames at the assertion boundary;
- wrong-package and same-version schema collisions fail explicitly;
- a source cut identifies the exact mapped payload, not only a claimed source
  revision;
- freshness remains observable without downloading or hashing the payload;
- incomplete snapshots cannot silently erase omitted source state.

Costs:

- Fact and FactBatch JSON formats advance to v2;
- all Fact producers and source bindings must provide schema identity;
- SQLite v2 development stores containing Fact v1 payloads are recreated rather
  than migrated;
- partial source snapshots remain unsupported.

## Acceptance Gates

- `SchemaIdentity` has one definition under `ontology.schema`;
- Fact v2 JSON round-trips complete schema identity and stable semantic IDs;
- a Fact batch with mixed identities fails before commit;
- Memory and SQLite reject cross-schema Fact commits consistently;
- materialization resolves renamed API metadata by semantic ID and rejects a
  wrong schema identity;
- `SourceBinding` rejects cross-schema use;
- two mapped payloads with the same source revision but different content
  produce different `SourceInputCut` values;
- freshness compares selected cut revisions with observed source heads;
- partial and unknown coverage fail explicitly;
- Ontology and architecture tests remain green without a new Product,
  connector, registry, or execution dependency.

## Deferred Decisions

- multi-package `DeploymentProfile` and installed-profile identity;
- package dependency locks, artifact registries, signing, and distribution;
- online Fact/schema migration and cross-version journal policy;
- concrete adapter packaging, registry, and deployment composition beyond the
  ARD-006 manifest and conformance boundary;
- partial snapshot merge state, change sets, CDC, and scheduling;
- source-backed write routing and Action reconciliation;
- incremental projection persistence beyond ARD-005's whole-snapshot SQLite v3
  layout.
