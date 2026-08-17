# ARD-007: Fact Schema Revalidation Receipts

Status: Accepted, 2026-08-10.

## Context

Fact v2 binds each immutable record to a complete `SchemaIdentity`. This prevents
accidental cross-schema use, but it also means an old Fact selection cannot be
silently presented to a newer schema even when stable semantic IDs would make
the selected data compatible.

Changing old Fact payloads in place would violate append-only authority.
Allowing the materializer to ignore schema versions would discard the identity
boundary established by ARD-004. Treating every schema-diff `breaking` label as
a data-migration failure is also too coarse: an API-name rename is breaking for
generated clients but safe for Facts that already use stable semantic IDs.

## Decision

### 1. Revalidate an exact detached Fact selection

`revalidate_fact_selection(selection, source_schema, target_schema)` is a pure
operation. It first proves that the selected Facts target the complete source
schema identity and that the source selection still materializes correctly.
It then creates only an in-memory identity-rebound view and validates that view
through the normal target materializer.

The original Fact records, FactStore, schema, and installed projection are never
modified.

Schema package lineage must match. A namespace change is blocked. Different
schema content under the same complete identity is invalid and must be released
under a new version.

### 2. Record a content-addressed receipt

The immutable `FactSchemaRevalidationReceipt` contains:

```text
source and target SchemaIdentity
source and target schema content digests
exact FactSelection digest and coordinates
ordered selected Fact IDs
schema-diff change codes
accepted | blocked status
deterministic diagnostics
```

The selection digest covers sequence numbers, canonical Fact v2 documents,
watermark, valid time, and recorded time. The receipt digest is SHA-256 over the
canonical receipt JSON.

An accepted receipt has no diagnostics. A blocked receipt has at least one
diagnostic and cannot authorize materialization.

### 3. Require the receipt at target materialization

Without a receipt, the existing exact-schema check remains unchanged. With an
accepted receipt, materialization verifies target identity and content,
selection identity, selection content, Fact IDs, watermark, and both temporal
coordinates before accepting source-schema Facts.

The installed `MaterializationCut` records `fact_revalidation_digest`; SQLite
v3 persists it. `FactOrigin` continues to reference the original immutable Fact
ID, not a synthetic rewritten record.

### 4. Use side-by-side upgrade, not in-place mutation

This contract supports the safe first workflow:

```text
old FactStore + old installed projection remain readable
                 |
                 +--> exact FactSelection
                         |
                    revalidation receipt
                         |
                    build target projection in a target store
                         |
                    Product/deployment verifies before switching
```

If revalidation or target projection fails, no old state has changed. The
deployment-level switch is outside Ontology and remains a later decision.

## Acceptance Gates

- stable-ID object/property API renames produce an accepted receipt and target
  projection while original Facts retain their source identity;
- new required data that is absent produces a blocked receipt;
- receipt JSON and digest are deterministic;
- changed selection coordinates or changed target schema content invalidate a
  previously accepted receipt;
- the receipt digest survives SQLite replacement and restart;
- no FactStore mixes schema identities and no Fact payload is rewritten.

## Deferred

- full historical Fact-journal migration and preservation of batch boundaries;
- in-place SQLite schema replacement;
- source-binding and mapped-input upgrade receipts;
- deployment switching, rollback coordination, and package locks;
- automated semantic transforms when stable IDs or value types truly change.
