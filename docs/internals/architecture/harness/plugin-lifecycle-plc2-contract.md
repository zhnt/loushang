# Plugin Lifecycle PLC2 Contract

Status: PLC2-1 implementation contract. This document narrows the PLC2 section
of the [Unified Plugin Lifecycle And Coding Pluginization Delivery Plan](plugin-lifecycle-coding-pluginization-plan.md).
It does not make the Plugin authoring SDK public and does not authorize live
owner binding.

## Purpose And Slice Boundary

PLC2 closes management-state authority before `coding.base` becomes a
production Plugin. It is delivered in four independently rollback-safe slices:

1. **PLC2-1 desired-state ledger** freezes Package Revision, Installation,
   desired selection and transition records; provides durable replay,
   idempotency and inventory-revision compare-and-swap; and durably issues the
   existing PLC1B `PluginInstanceRevisionRef` identity.
2. **PLC2-2 management command core** places install, enable, disable and
   remove behind one internal typed `PluginManagementService` and journals
   operation progress/results.
3. **PLC2-3 staged update** adds package staging, migration fences, atomic
   desired-selection cutover and exact `restart_required` outcomes.
4. **PLC2-4 retirement and cleanup handoff** adds Instance execution-state,
   owner-retirement aggregation, journal-owned package-lease handoff, recovery
   and repair.

PLC2-1 is deliberately inert. Committing a desired selection must not run
preflight, evaluate a Definition, import Plugin code, construct a Capability
Graph, register a Tool or Command, publish a Resource, mutate a Runtime Profile,
or retire/delete owner state. `installed_enabled` means desired selection only;
it never means effective runtime state.

## Independent Identities

PLC2-1 preserves four identities:

| Identity | Durable key | Meaning |
| --- | --- | --- |
| Package Revision | Plugin ID, optional Plugin version, package content digest, dependency-lock digest, source identity | Immutable verified package evidence; not an Instance or cache state |
| Installation | Product ID, installation scope, scope ID, Plugin ID | Desired management placement; not a runtime owner scope or composition membership |
| Plugin Instance Revision | exact PLC1B `{instanceId, pluginId, revision}` | Management-issued provenance for one selected Plugin descriptor/configuration revision |
| Inventory Revision | one positive integer per committed transition | Global desired-state ledger CAS clock; not an owner generation |

The installation scopes accepted by PLC2-1 are `process`, `tenant`, and
`workspace`. Runtime scopes remain the existing `process`, `tenant`,
`workspace`, `session`, `turn`, and `channel` vocabulary and are not collapsed
into installation scope.

`instanceId` is opaque. Consumers must not parse a Plugin type, Product,
installation scope, or authority from it. The ledger issues a new opaque ID at
the first enable of an installation epoch and revision `1`; disable followed by
re-enable retains the ID and increments the revision; remove followed by a new
install starts a new installation epoch and therefore a new ID at revision
`1`. No caller may supply the committed Instance identity.

## Versioned Value Records

Every record is strict JSON: exact keys, native JSON integers only, non-empty
UTF-8 strings, and lowercase 64-character SHA-256 values. Unknown versions and
unknown fields fail closed.

### `PluginPackageRevisionRefV1`

```json
{
  "dependencyLockDigest": "<sha256>",
  "packageContentDigest": "<sha256>",
  "packageSourceIdentity": "embedded:coding.base",
  "pluginId": "coding.base",
  "pluginVersion": "1.0.0",
  "schemaVersion": 1
}
```

`pluginVersion` may be `null` because the existing verified package manifest
allows an absent version. Paths and mutable source objects are forbidden.

### `PluginInstallationKeyV1`

```json
{
  "installationScope": "workspace",
  "pluginId": "coding.base",
  "productId": "coding",
  "schemaVersion": 1,
  "scopeId": "workspace-1"
}
```

### `PluginDesiredSelectionV1`

The desired states are exactly `absent`, `installed_disabled`, and
`installed_enabled`.

```json
{
  "desiredState": "installed_enabled",
  "instanceRevisionRef": {
    "instanceId": "<opaque>",
    "pluginId": "coding.base",
    "revision": 1
  },
  "packageRevision": { "...": "PluginPackageRevisionRefV1" },
  "schemaVersion": 1
}
```

`absent` requires both references to be `null`.
`installed_disabled` requires a Package Revision and a null Instance Revision.
`installed_enabled` requires both references. All nested Plugin IDs must match
the Installation key.

### `PluginInstallationStateV1`

```json
{
  "installationKey": { "...": "PluginInstallationKeyV1" },
  "latestInstanceRevisionRef": {
    "instanceId": "<opaque>",
    "pluginId": "coding.base",
    "revision": 1
  },
  "schemaVersion": 1,
  "selection": { "...": "PluginDesiredSelectionV1" }
}
```

The latest issued reference is retained across disable and an `absent`
tombstone so retirement and audit work can identify the predecessor. A new
install from `absent` resets that lineage before any later enable. The
append-only transition history retains the old Package Revision; this record
does not authorize package deletion.

### `PluginDesiredStateMutationV1`

```json
{
  "actorId": "operator-1",
  "approvalReference": null,
  "desiredState": "installed_enabled",
  "expectedInventoryRevision": 3,
  "idempotencyKey": "request-4",
  "installationKey": { "...": "PluginInstallationKeyV1" },
  "operationId": "operation-4",
  "packageRevision": null,
  "policyRevision": "policy-7",
  "schemaVersion": 1
}
```

The request may omit `packageRevision` when retaining the currently installed
revision. Install from `absent` requires it. A different package while already
installed is rejected in PLC2-1 and enters only through PLC2-3 staged update.
The mutation never contains an Instance Revision reference.

### `PluginDesiredStateTransitionV1`

Each journal line contains exact `recordVersion`, assigned
`inventoryRevision`, `transitionKind`, the complete mutation, and complete
`previousState`/`committedState`. The allowed kinds are `install`, `enable`,
`disable`, `remove`, and `unchanged`. Replay recomputes the transition and
rejects a line whose kind or committed state cannot result from its previous
state and mutation.

An unseen Installation has the canonical initial state `absent` with no latest
Instance reference. An `unchanged` request is still journaled and advances the
inventory revision, so its operation/idempotency result remains durable.

## Linearization, Idempotency, And Recovery

The desired-state ledger is the only PLC2-1 writer. Under one exclusive journal
lock it:

1. repairs only an incomplete final JSONL tail left by an interrupted append;
2. strictly decodes and replays every complete record;
3. returns the prior transition for an exact retry of an operation or
   idempotency key;
4. rejects reuse of either key with a different mutation;
5. compares `expectedInventoryRevision` with the replayed head before issuing
   an identity or changing state;
6. computes the next state and any ledger-owned Instance identity; and
7. appends, flushes, and fsyncs the complete transition before returning it.

A failed append commits nothing. A malformed complete record, non-contiguous
revision, mismatched predecessor, illegal transition, duplicate identity, or
unverifiable issued revision fails closed. Startup does not skip such evidence.
The snapshot is derived only by replay and is sorted by Installation key.

## PLC2-1 Exact Error Codes

| Condition | Code |
| --- | --- |
| unsupported record/value version | `unsupported_plugin_lifecycle_record_version` |
| wrong/unknown field or invalid value | `invalid_plugin_lifecycle_record` |
| expected inventory revision differs from head | `plugin_inventory_revision_conflict` |
| idempotency key reused for another mutation | `plugin_management_idempotency_conflict` |
| operation ID reused for another mutation | `plugin_management_operation_conflict` |
| Package Revision Plugin ID differs from Installation | `plugin_package_revision_mismatch` |
| update attempted without the PLC2-3 staged path | `plugin_update_requires_staging` |
| illegal desired-state transition | `invalid_plugin_lifecycle_transition` |
| Instance identity issuer returns an invalid/already-issued ID | `plugin_instance_identity_conflict` |
| corrupt replay chain or issued identity | `plugin_lifecycle_journal_corrupt` |

Errors contain no package bytes, private Plugin data, approval secret, or
source credentials.

## PLC2-1 Regression Gate

PLC2-1 is complete only when tests prove:

- strict round-trip and unknown-version/field rejection for every value record;
- install/enable/disable/re-enable/remove/reinstall identity semantics;
- exact retry without a second append and conflicting operation/idempotency
  reuse rejection;
- stale CAS rejection before identity issue or append;
- deterministic restart replay, incomplete-tail recovery and fail-closed
  complete-record corruption;
- package change rejection outside staged update;
- remove creates only an inert desired-state tombstone and preserves predecessor
  evidence; and
- the new package has no imports or call sites for Coding, Session, Graph
  binding, runtime registration, owner publication, execution, private-data
  deletion, or package GC.
