# Plugin Lifecycle PLC2 Contract

Status: PLC2-1, PLC2-2, PLC2-3, PLC2-4A, PLC2-4B and PLC2-4C implemented;
PLC2-4D not started. This document
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

## PLC2-3 Staged Update Contract

PLC2-3 adds one update transaction to the same internal management authority.
It remains inert: staging does not materialize/import package code, inspect a
live Session, migrate private data, publish an owner generation, or claim that
an effective runtime has restarted. A Package Revision reference is immutable
verified-package evidence supplied to this layer, not permission to execute it.

### Version And Command Boundary

The frozen PLC2-2 `PluginManagementCommandV1` remains exact and never learns an
extra action. Update uses `PluginManagementUpdateCommandV2`; both versions are
accepted by the one `PluginManagementService` and share one operation journal,
operation-ID namespace, idempotency-key namespace and same-Installation busy
gate. The v2 command carries exactly:

- operation ID, idempotency key and expected inventory revision;
- Installation key and the exact expected current Package Revision;
- one different immutable staged Package Revision;
- actor, policy and optional approval provenance; and
- the fixed action `update` and `commandVersion=2` discriminators.

The command does not choose an Instance Revision, current desired state,
migration outcome, restart outcome or transition kind. The service derives
those facts from the CAS-protected current state. Update of `absent`, Package
Plugin-ID mismatch, an equal target revision, or a current Package Revision
different from the staged command's expected predecessor fails closed.

### Durable Update Sequence And Migration Fence

The v2 operation has this exact append-only sequence:

```text
accepted(command_accepted, operationRevision=1)
  -> running(update_staged, operationRevision=2)
  -> running(migration_fence_satisfied, operationRevision=3)
  -> running(desired_state_committing, operationRevision=4)
  -> terminal(desired_state_committed | update_restart_required |
              desired_state_failed, operationRevision=5)
```

`update_staged` persists the complete target while leaving desired selection
unchanged. PLC2 has no bound `PluginDataFacet` or private-data generation, so
the only legal `PluginMigrationFenceV1` disposition is
`not_applicable_unbound`. It states only that this inert management slice has
no data pointer or writer lease to migrate. It must never be translated into
schema compatibility or completed-migration evidence. Adding a bound data
owner requires a new fence version and the Product/data-owner gate frozen by
UPA; it cannot broaden this disposition in place.

After the fence, the service constructs a ledger-only
`PluginDesiredStateUpdateMutationV1`. The desired-state journal stores update
cutover as record version 2 and transition kind `update`; record version 1 is
not widened. The new record embeds the exact command-derived mutation, fence,
previous state and committed state.

Under the operation-journal lock followed by the desired-state-ledger lock,
cutover compares both the global inventory revision and exact expected current
Package Revision. One append atomically replaces the Package Revision in the
desired selection. Disabled selection stays disabled and retains its latest
Instance lineage. Enabled selection stays enabled and advances the same opaque
Instance ID by one revision. A failed precondition or append leaves the old
selection unchanged.

There is no cross-file atomicity claim. Recovery resumes from the last exact
operation revision. Retrying record revision 4 reuses the same update mutation;
the desired ledger returns the already committed transition when a crash
occurred after cutover but before the terminal operation event.

### Exact Restart Outcome

The update terminal dispositions are `succeeded`, `restart_required`, and
`failed`. `restart_required` is a successful desired-selection cutover with a
runtime boundary still owed; it is not a failure and not evidence that a host
or Session restarted.

PLC2-3 has no declaration/owner admission evidence with which to prove a safe
live declarative, isolated-service or single-owner refresh exception. It
therefore applies one conservative, deterministic rule:

- updating `installed_disabled` returns `succeeded` with no restart record;
- updating `installed_enabled` returns `restart_required` with reason code
  `enabled_package_revision_changed` and a non-empty, canonical list of the
  exact Package Revision fields that changed.

The changed-field vocabulary is `pluginVersion`, `packageContentDigest`,
`dependencyLockDigest`, and `packageSourceIdentity`, in that order. A future
owner-bound protocol may narrow this conservative result only from durable
admission/import-realm evidence; an adapter or caller assertion cannot do so.
Until then no live owner may consume the new enabled revision without honoring
the returned restart boundary.

### PLC2-3 Exact Error Codes

| Condition | Code |
| --- | --- |
| update targets an absent Installation | `plugin_update_not_installed` |
| current Package Revision differs from the staged predecessor | `plugin_update_expected_package_mismatch` |
| command target equals its expected predecessor | `plugin_update_target_not_new` |
| unsupported v2 command/event/result/fence/update record version | existing unsupported management/lifecycle record code |
| invalid v2 shape, sequence or cross-journal evidence | existing invalid/corrupt management/lifecycle code |

Inventory CAS, Package Plugin-ID, operation/idempotency conflict and Instance
identity errors retain the PLC2-1/PLC2-2 codes.

### PLC2-3 Regression Gate

PLC2-3 is complete only when tests prove:

- strict round trips and unknown-version/field rejection for every v2 record;
- v1 journals remain replayable and mixed v1/v2 operation and desired-state
  journals preserve one contiguous revision sequence;
- staging and the migration-fence event leave the old selection unchanged;
- disabled and enabled cutovers preserve desired state, replace only the exact
  staged Package Revision, and apply the specified Instance lineage rules;
- enabled updates return the exact canonical changed-field restart evidence;
- stale inventory, absent Installation and expected-package mismatch leave the
  old selection byte-for-byte unchanged;
- exact retry appends nothing, conflicting keys fail closed, and an incomplete
  update blocks every other command for the same Installation;
- crash after desired-state cutover recovers to one matching terminal result;
- terminal success/restart evidence cannot survive without its exact durable
  update transition, and terminal failure cannot contradict one; and
- architecture gates retain one management authority and introduce no Product,
  Session, Graph, registration, execution, private-data or GC dependency.

## PLC2-4 Retirement And Cleanup Handoff

PLC2-4 is divided into four rollback-safe increments because retirement
coordination, Instance execution state, exact-owner results and package cleanup
belong to different authorities:

1. **PLC2-4A retirement intent handoff** durably identifies the exact replaced
   enabled Instance Revision and Package Revision after a desired-state cutover.
2. **PLC2-4B owner-retirement aggregation** records opaque owner/generation
   handles and redacted owner-issued outcomes without invoking a disposer.
3. **PLC2-4C Instance lease/state gate** implements `ACTIVE`, `DRAINING`,
   `REVOKING` and `RETIRED` under the Product Plugin Host's acquisition and
   membership authority.
4. **PLC2-4D cleanup lease handoff** implements the package lifecycle owner's
   write-ahead cleanup journal, startup recovery barrier, retry/repair evidence
   and journal-owned Package Revision lease.

This order does not imply that management desired state owns effective state.
In particular, an `installed_enabled` selection and a retirement intent do not
prove that an Instance was ever `ACTIVE`, that it entered `DRAINING`, that an
owner generation stopped, or that package bytes are GC-eligible.

## PLC2-4A Durable Retirement Intent

PLC2-4A extends the one management transaction with a durable coordination
handoff. It introduces no owner callback, disposer, registration handle,
runtime lease, Session lookup, security-revoke action, package-cache mutation,
private-data action or cleanup execution.

### Exact Retirement Subject

`PluginRetirementIntentV1` embeds the complete source desired-state transition
and redundantly records only facts derived from it:

- one service-derived opaque `retirementId`;
- trigger `disable`, `remove`, or `update`;
- mode `graceful` only;
- the previous selection's exact `PluginInstanceRevisionRef`; and
- the previous selection's exact `PluginPackageRevisionRefV1`.

An intent exists only when the source transition replaced an
`installed_enabled` selection:

| Source transition | PLC2-4A result |
| --- | --- |
| enabled -> disabled | graceful intent, trigger `disable` |
| enabled -> absent | graceful intent, trigger `remove` |
| enabled revision N -> enabled revision N+1 | graceful intent for revision N, trigger `update` |
| install, enable, unchanged, disabled update/remove, absent remove | no intent |

The retirement ID is the lowercase SHA-256 of a domain separator plus the
canonical source-transition bytes. No adapter or caller supplies it. The
intent validator recomputes every redundant field and rejects a record that
changes the trigger, mode, Instance, Package Revision or ID.

`PluginRetirementIntentRecordV1` adds one contiguous positive retirement-
journal revision. The ledger rejects two source operations for one retirement
ID, two graceful intents for one Instance Revision, or the same source
operation with different evidence. Strict decoding, partial-tail repair and
complete-record fail-closed behavior match the earlier PLC2 journals.

### Three-Journal Ordering And Recovery

The service lock order is:

```text
management operation journal
  -> desired-state journal
  -> retirement-intent journal
```

After a successful desired cutover and before the terminal operation event,
the service derives and durably appends the exact retirement intent when one is
required. There is no cross-file atomicity claim:

- a crash before desired cutover leaves neither transition nor intent;
- a crash after desired cutover recovers the same idempotent transition, then
  writes the missing intent;
- a crash after intent append recovers the same intent without a second append,
  then writes the terminal operation event; and
- a terminal committed operation is corrupt unless its exact required intent
  exists; every intent is corrupt unless its embedded source transition exists
  exactly in desired state.

An intent-journal infrastructure or corruption failure leaves the management
operation non-terminal. It is not converted to a successful disable/remove/
update and does not synthesize a retryable cleanup result. Owner retirement and
cleanup have not begun in PLC2-4A.

### PLC2-4A Exact Error Codes

| Condition | Code |
| --- | --- |
| unsupported intent/record version | `unsupported_plugin_retirement_record_version` |
| wrong/unknown intent/record field or invalid derived evidence | `invalid_plugin_retirement_record` |
| retirement/source-operation/Instance identity reused with different evidence | `plugin_retirement_intent_conflict` |
| intent journal cannot be replayed or contradicts desired/operation evidence | `plugin_retirement_journal_corrupt` |

These are infrastructure/recovery errors, not normal terminal management
failure codes. They contain no owner result text, package bytes, private data,
secret or source credential.

### PLC2-4A Regression Gate

PLC2-4A is complete only when tests prove:

- strict intent/record round trips and version/field rejection;
- the exact transition matrix above, including old Instance/Package identity;
- exact retry and restart replay without duplicate intent;
- crash after desired cutover and crash after intent append both recover to one
  desired transition, one intent and one terminal operation result;
- terminal operation/desired transition/intent cross-log contradictions fail
  closed, while a valid non-terminal recovery window remains accepted;
- two service instances serialize the same handoff and an incomplete operation
  continues to block a conflicting command for the same Installation; and
- architecture gates find one production intent append call site inside
  `PluginManagementService` and no owner, disposer, Session, registration,
  execution, private-data, package-cache or GC dependency.

## PLC2-4B Exact-Owner Retirement Aggregation

PLC2-4B adds a durable `PluginRetirementSet` projection for each PLC2-4A
intent. The set coordinates immutable owner references and owner-issued
outcomes only. It cannot look up a live registry, call or retain a callable,
deactivate a lease, invoke a disposer, stop an external service, mutate an
owner generation, change Instance execution state, release package bytes, or
claim cleanup success.

### Open Set And Complete Owner Plan

The management handoff opens exactly one `collecting` set after it durably
creates an intent and before it writes the terminal management event. Opening a
set stores the complete exact intent; it does not infer that the Instance was
active or that any owner target exists.

A future Product Plugin Host may commit one complete
`PluginOwnerRetirementPlanV1` after exact owner binding exists. PLC2-4B defines
the port and durable validation but has no production caller that fabricates
such a plan. The plan contains:

- the exact `retirementId` and one opaque `ownerClosureReference` issued by the
  Product Plugin Host;
- a contract-derived plan ID over canonical plan bytes; and
- zero or more canonical `PluginOwnerRetirementTargetV1` values.

Each target contains only an opaque owner reference, owner-generation
reference, owner-issued retirement handle and a non-empty sorted unique tuple
of contribution IDs. A target ID is derived from those exact canonical fields.
Targets are strictly sorted by target ID; owner-generation pairs, retirement
handles, target IDs and contribution IDs are unique within a plan.
There is no top-level Plugin type code and no callback or authority object.

An empty sealed plan is legal only as the Product Plugin Host's explicit
statement that the exact Instance has no foreign owner generations. It makes
owner-retirement aggregation complete but does not prove the Instance was
inactive, release a direct-host or membership lease, or make the Package
Revision reclaimable.

### Owner-Issued Outcomes And Aggregate State

`PluginOwnerRetirementOutcomeV1` references one exact target and carries:

- owner-issued operation ID and idempotency key;
- a positive attempt number;
- disposition `succeeded`, `retryable_failure`, or `terminal_failure`;
- one bounded structural `resultCode`; and
- one opaque owner outcome reference.

There is no free-form result text. Result codes use only lowercase ASCII
letters, digits, `.`, `_`, `-`, and `:` and are at most 128 characters. They
must not contain package bytes, private data, secrets, credentials or exception
text.

The first outcome for a target is attempt 1. Only `retryable_failure` permits
the next contiguous attempt. `succeeded` and `terminal_failure` are terminal
for that target. Operation IDs and idempotency keys are scoped by the exact
retirement ID plus target ID, so independent owners need no shared naming
registry. Exact retry in that scope returns the current aggregate without
appending another event; reuse with different evidence fails closed.

The set state is derived, never caller-supplied:

| Evidence | Aggregate state |
| --- | --- |
| no sealed plan | `collecting` |
| sealed plan with pending targets | `retiring` |
| every target succeeded, including an empty plan | `succeeded` |
| no terminal failure and at least one latest retryable failure | `retryable_failure` |
| any target has terminal failure | `terminal_failure` |

Succeeded targets remain visible when another target is pending or failed.
The aggregate contains the latest outcome per target and all append-only
attempt evidence. `succeeded` means only that the sealed foreign-owner plan
completed; PLC2-4C must still prove zero Instance leases before `RETIRED`, and
PLC2-4D must separately own cleanup/package-lease release.

### Four-Journal Ordering And Recovery

The management handoff lock order becomes:

```text
management operation journal
  -> desired-state journal
  -> retirement-intent journal
  -> retirement-set journal
```

The service uses one `_handoff_retirement()` path for normal and update
operations. That path creates the exact intent and opens its collecting set.
A crash after either append leaves the operation non-terminal; retry reuses the
same desired transition, intent and set. A terminal management success or
`restart_required` is corrupt when a required intent or its exact open set is
missing. A set is corrupt when its embedded intent is absent/different in the
intent journal.

Owner plan/outcome writes occur later through the retirement-set ledger's typed
port and its own exclusive journal lock; they never hold the management lock or
call back into management. Startup replay recomputes every target ID, plan ID,
attempt transition and aggregate state. Incomplete tails repair; complete or
cross-journal contradictions fail closed.

### PLC2-4B Exact Error Codes

| Condition | Code |
| --- | --- |
| unsupported set/target/plan/outcome/event version | `unsupported_plugin_retirement_set_record_version` |
| wrong/unknown field or invalid canonical/derived value | `invalid_plugin_retirement_set_record` |
| plan, target, operation or idempotency identity reused with different evidence | `plugin_retirement_set_conflict` |
| plan/outcome violates set or attempt state | `invalid_plugin_retirement_set_transition` |
| set journal/replay/cross-journal evidence is corrupt | `plugin_retirement_set_journal_corrupt` |

These remain infrastructure/owner-coordination errors, not management terminal
failure codes.

### PLC2-4B Regression Gate

PLC2-4B is complete only when tests prove:

- strict round trips and field/version rejection for target, plan, outcome and
  event records;
- target/plan IDs and sorted uniqueness are derived and fail closed;
- opening is exact/idempotent and management crashes before/after open recover
  without duplicate desired, intent, set or terminal records;
- empty, pending, all-success, retryable and terminal-failure aggregate states;
- exact outcome retry, conflict rejection, contiguous retry attempts and no
  retry after a terminal target result;
- journal tail repair, complete corruption rejection and cross-intent checks;
- one service handoff path opens sets for disable/remove/enabled-update only;
  and
- architecture gates find no callable, owner lookup/disposal, Instance-state,
  package-cache, private-data, cleanup, GC, Session, Graph or registration
  dependency.

## PLC2-4C Instance Lease And State Gate

PLC2-4C adds the internal Product Plugin Host primitive that owns effective
Plugin Instance Revision state and reference counts. It does not make desired
selection effective, bind a Capability, discover an owner, invoke a disposer,
release package bytes, run cleanup, or publish a public Plugin SDK.

### Independent State And Activation Evidence

The only Instance execution states are:

```text
ACTIVE --graceful--> DRAINING --> RETIRED
ACTIVE --security--> REVOKING --> RETIRED
DRAINING --security--> REVOKING
```

There is no `INSTALLED`, `ENABLED`, `STARTING`, `FAILED`, `REMOVED`, cleanup or
package-cache state in this machine. Desired `installed_enabled`, an activation
operation, an open retirement set and owner aggregate `succeeded` remain
independent facts.

Only a Product Plugin Host may append one `PluginInstanceActivationV1`. The
activation names the exact Installation, Instance Revision, Package Revision,
desired inventory revision, host-issued operation/idempotency keys and opaque
direct-host reference. The runtime gate checks, under the management operation
lock, that the exact revision is the current enabled desired selection. One
activation event atomically creates `ACTIVE` state and its one-member
`direct_host` lease family. An intent or desired selection can never synthesize
activation evidence.

Replay validates the activation against desired state as it existed at the
recorded global inventory revision, not merely against the current selection.
This permits an old activated revision to remain reconstructible while it
drains after a later desired cutover.

### Durable Lease Families

Every Instance reference owned by this primitive belongs to one immutable
`PluginInstanceLeaseFamilyV1`. A family carries a derived family ID,
host-issued operation/idempotency keys, an opaque holder reference, its kind,
an optional parent family and a sorted exact member tuple. Each member contains
the Installation, Instance Revision and Package Revision and has a derived
lease ID.

The kinds are:

| Kind | Acquisition rule |
| --- | --- |
| `direct_host` | one member, created only with activation |
| `independent` | one current `ACTIVE` Instance |
| `owner_generation` | one current `ACTIVE` Instance |
| `session_membership` | one or more current `ACTIVE` Instances in one atomic family |
| `agent_membership` | derived atomically from one open Session/Agent family |

Root acquisition resolves every requested Installation from one desired-state
snapshot while holding the management operation lock, then commits the whole
family in one runtime-journal event. A failed member check appends nothing.
This is the PLC2 Product-host primitive for multi-revision Session acquisition;
no Session implementation calls it before the later production cutover.

`DRAINING` rejects every new root acquisition, but an open Session/Agent parent
may derive an `agent_membership` family over the same pinned members.
`REVOKING` and `RETIRED` reject root and derived acquisition. A parent cannot
release while an open child family exists. Family release is an explicit
durable event with its own operation/idempotency identity and opaque release
reference; exact retry appends nothing. No process restart implicitly releases
an open family. Startup therefore reconstructs uncertain references as pinned
until their Product owner reconciles them.

The management operation journal lock is also the PLC2-4C cross-journal
linearization gate. Management already holds it across desired cutover and
retirement handoff. Activation, root/derived acquisition, release, drain,
revoke and retirement completion acquire the same lock before their source
reads and runtime append. The nested order is:

```text
management operation/coordination lock
  -> desired-state or retirement source journals
  -> instance-runtime journal
```

This prevents a root acquisition from racing through a disable, remove or
update cutover without introducing another selection authority.

### Graceful Drain, Security Revoke And Retirement

`begin_drain()` accepts only the exact PLC2-4A intent for an `ACTIVE` Instance
and requires its exact PLC2-4B open set. It records `DRAINING`; it does not call
owners or release any family. Missing activation is an invalid transition, not
evidence for manufacturing a runtime state.

`PluginInstanceRevocationV1` contains exact Instance identity, host-issued
operation/idempotency keys, an opaque authority reference and one bounded
structural reason code. It can move `ACTIVE` or `DRAINING` to `REVOKING`.
PLC2-4C defines the Product-host port but has no management, trust or adapter
caller that fabricates security authority.

Retirement is a separate confirmed append:

- `DRAINING -> RETIRED` requires the same retirement set to be `succeeded` and
  every direct-host, independent, owner-generation, Session and Agent family
  member for that Instance to be released;
- `REVOKING -> RETIRED` requires the exact revocation evidence and the same
  zero-open-family invariant; and
- `ACTIVE -> RETIRED` is never legal.

The completion stores only host-issued operation/idempotency keys and an opaque
completion reference. `RETIRED` proves the Instance runtime has no lease owned
by this gate. It does not make its Package Revision `gc_eligible`; PLC2-4D must
still reconstruct package/cleanup leases and decide cleanup disposition.

### PLC2-4C Exact Error Codes

| Condition | Code |
| --- | --- |
| unsupported activation/family/member/release/revocation/completion/event version | `unsupported_plugin_instance_runtime_record_version` |
| wrong/unknown field or invalid canonical/derived value | `invalid_plugin_instance_runtime_record` |
| operation, idempotency, activation, family or security identity reused with different evidence | `plugin_instance_runtime_conflict` |
| illegal state, family, parent, release or retirement transition | `invalid_plugin_instance_runtime_transition` |
| current selection/state cannot serve an acquisition | `plugin_instance_acquisition_unavailable` |
| runtime journal/replay/source evidence is corrupt | `plugin_instance_runtime_journal_corrupt` |

These codes never contain holder data, exception text, package bytes, private
data, credentials or cleanup output.

### PLC2-4C Regression Gate

PLC2-4C is complete only when tests prove:

- strict record round trips, version/field rejection, canonical sorting and
  derived family/member identities;
- activation requires the exact current enabled desired revision and creates
  one direct-host family atomically;
- root multi-Instance acquisition is all-or-nothing and serializes with
  management cutover through the one operation lock;
- `DRAINING` rejects roots but permits exact open-parent Agent derivation,
  while `REVOKING` rejects both;
- parent-before-child release is rejected and every exact release/retry remains
  reconstructible after restart;
- graceful drain requires exact intent/set evidence, owner aggregate success
  alone cannot retire an Instance, and every open family blocks retirement;
- security revoke is exact, dominates graceful drain and retires only at zero
  open families;
- incomplete tails repair and complete, sequence or cross-journal corruption
  fails closed; and
- architecture gates find no Product/Session/Graph/registration/disposer,
  package-cache, cleanup, GC, private-data or MCP dependency and no production
  caller that fabricates activation, membership or revocation evidence.
