# Plugin Lifecycle PLC2 Contract

Status: PLC2-1 and PLC2-2 implemented; PLC2-3/PLC2-4 not started. This document
narrows the PLC2 section of the
[Unified Plugin Lifecycle And Coding Pluginization Delivery Plan](plugin-lifecycle-coding-pluginization-plan.md).
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

## PLC2-2 Typed Management Command Core

PLC2-2 makes one internal `PluginManagementService` the only source-code caller
of `PluginDesiredStateLedger.commit()`. Product, CLI, RPC, UI, settings and
package adapters remain outside this slice and must not write either journal.
The service is an orchestration authority over desired state only; it does not
become the package, approval, admission, owner-publication, retirement, private-
data or package-GC authority.

### `PluginManagementCommandV1`

The command wraps the already frozen PLC2-1 mutation instead of repeating its
operation/idempotency, CAS, Product/scope, actor/policy, approval and Package
Revision fields:

```json
{
  "action": "install",
  "commandVersion": 1,
  "mutation": { "...": "PluginDesiredStateMutationV1" }
}
```

Actions are exactly `install`, `enable`, `disable`, and `remove`:

| Action | Required mutation shape |
| --- | --- |
| `install` | `desiredState=installed_disabled` and non-null Package Revision |
| `enable` | `desiredState=installed_enabled` and null Package Revision |
| `disable` | `desiredState=installed_disabled` and null Package Revision |
| `remove` | `desiredState=absent` and null Package Revision |

Install is intentionally disabled-by-default. Install-and-enable is two CAS-
ordered commands. Package replacement is never smuggled through `install`; an
already-installed different revision still requires PLC2-3 staged update.
An `install` against an already-enabled Installation terminates with
`plugin_installation_already_enabled`; it never silently becomes `disable`.

### Operation Events And Results

The operation journal is append-only and independent of the desired-state
ledger. Each strict `PluginManagementOperationEventV1` contains:

- global positive `journalRevision` and per-operation positive
  `operationRevision`;
- the complete exact command;
- status `accepted`, `running`, or `terminal`;
- progress code `command_accepted`, `desired_state_committing`,
  `desired_state_committed`, or `desired_state_failed`;
- compensation state, exactly `not_required` in PLC2-2; and
- a nullable terminal `PluginManagementOperationResultV1`.

The event sequence is exact:

```text
accepted(command_accepted, operationRevision=1)
  -> running(desired_state_committing, operationRevision=2)
  -> terminal(desired_state_committed|desired_state_failed,
              operationRevision=3)
```

A successful result embeds the exact committed
`PluginDesiredStateTransitionV1` and has no error code. A failed result has one
stable error code and no transition. It contains no arbitrary exception text,
package bytes, secrets or private Plugin data.

`pending_approval` and `cancelling` remain reserved UPA operation-family states,
not fake aliases for PLC2-2 behavior. They become issuable only when a real
management approval/cancellation owner and resume protocol are implemented.
PLC2-2 commands are already authorized inputs whose `approvalReference`, when
present, is provenance rather than authority minted by this service.

### Dual-Journal Linearization And Recovery

Under one exclusive operation-journal lock, the service:

1. strictly repairs/replays the operation journal;
2. returns the same terminal snapshot for an exact operation/idempotency retry;
3. rejects either key reused with another command;
4. rejects a different incomplete command for the same Installation;
5. appends and fsyncs `accepted`, then `running`;
6. submits the command's exact mutation to the PLC2-1 ledger; and
7. appends and fsyncs one `terminal` success or expected domain failure.

The operation lock is acquired before the desired-state ledger lock; no path
acquires them in reverse order. Holding the operation lock prevents two service
instances from writing duplicate progress events. The ledger remains the sole
desired-state CAS/Instance-identity linearization point.

There is deliberately no claim of atomic commit across the two JSONL files. A
crash before the ledger append leaves `accepted` or `running`; recovery retries
the exact idempotent mutation. A crash after the ledger append but before the
terminal event observes the same ledger transition and completes the operation.
An expected lifecycle-domain rejection becomes a durable terminal failure.
Journal corruption or an unexpected infrastructure/programming exception stays
non-terminal and fails closed for explicit recovery/repair; it is never
laundered into a successful or permanently failed command.

`recover()` processes accepted/running operations in original accepted order.
Until recovery completes, a conflicting command for the same Installation is
rejected; unrelated Installations may proceed. Query/list projects only the
latest strictly replayed event for each operation and never infers owner-runtime
effectiveness. Every replay also requires a terminal success to match the exact
desired-state transition with the same operation ID; a terminal failure cannot
contradict a committed transition. This cross-log fact check does not create a
new write authority or cross-file atomicity claim.

## PLC2-2 Exact Error Codes

| Condition | Code |
| --- | --- |
| unsupported command/event/result version | `unsupported_plugin_management_record_version` |
| wrong/unknown command/event/result field or value | `invalid_plugin_management_record` |
| command operation ID reused with another command | `plugin_management_operation_conflict` |
| command idempotency key reused with another command | `plugin_management_idempotency_conflict` |
| another non-terminal command owns the Installation | `plugin_management_installation_busy` |
| install would disable an already-enabled Installation | `plugin_installation_already_enabled` |
| operation journal cannot be decoded or replayed | `plugin_management_journal_corrupt` |

Expected ledger-domain failures retain their PLC2-1 code inside the terminal
operation result. Infrastructure exceptions are raised and do not synthesize a
terminal result.

## PLC2-2 Regression Gate

PLC2-2 is complete only when tests prove:

- strict command/event/result round trips and exact action-to-mutation shapes;
- install/enable/disable/remove all pass through one service call site and
  produce exact three-event terminal histories;
- exact retry performs no second operation or desired-state append, while
  conflicting operation/idempotency reuse fails closed;
- stale CAS and other expected ledger rejections become stable terminal failure
  results;
- crash after the desired-state append leaves `running`, and a fresh service
  instance recovers the same ledger transition to one terminal success;
- two service instances serialize operation progress and same-Installation
  incomplete work blocks conflicting commands;
- operation-journal incomplete tails repair, while complete semantic corruption
  fails closed; and
- terminal success cannot survive without its exact desired-state transition;
  cross-log contradictions fail closed; and
- architecture tests find exactly one production `PluginDesiredStateLedger`
  mutation call site, inside `PluginManagementService`, with no new live owner,
  Product, adapter, import/evaluation, registration or binding dependency.
