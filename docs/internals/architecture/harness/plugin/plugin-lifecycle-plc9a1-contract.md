# Plugin Lifecycle PLC9A1 Management Application Contract

## Status

- Contract version: PLC9A1.
- Delivery status: implemented. A1-1, A1-2, and A1-3 are delivered as one
  reviewed management-projection slice.
- Scope: internal Harness management application ports, legacy enablement
  migration, and Coding CLI list/enable/disable adaptation.
- Public author SDK effect: none. The `loushang.plugin` namespace remains an
  inert authoring and validation surface.
- Out of scope: RPC/UI/management SDK transport bindings (PLC9A2), Plugin-bound
  Package acquisition (PLC9B), Worker/remote topologies, artifact GC, private
  data deletion, and removal of downgrade compatibility fields (PLC9E).

PLC9A1 applies the ownership decisions frozen by the PLC9.0 baseline. It does
not create a second desired-state writer or a persisted projection clock.

## First Principles

1. A command expresses intent; a projection reports observed owner facts.
2. Desired state, source availability, runtime convergence, cleanup, and backup
   retention are independent dimensions and remain independently revisioned.
3. A projection is a read-only join. It records every captured owner revision,
   reports unsupported or unknown dimensions, and may expose skew; it never
   writes a synthesized truth back to an owner.
4. Correlation identity belongs to the application request/result. Durable
   operation and idempotency identities continue to belong to the management
   command journal.
5. Legacy enablement is imported once. Any desired-state history, including an
   `absent` tombstone, is authoritative forever and must not be reseeded.
6. Source add/remove changes availability. Plugin install/enable/disable/remove
   changes desired state. Compatibility aliases never cross that boundary.

## A1-1: Transport-neutral application ports

`src/loushang/harness/plugin_management/application.py` owns the common
application boundary:

- `PluginManagementCommandPort` accepts a versioned correlated request and
  returns the durable operation record without interpreting transport state;
- `PluginManagementQueryPort` accepts a Product/scope query and returns a
  versioned correlated projection;
- `PluginManagementCommandApplication` is a narrow adapter over
  `PluginManagementService`, which remains the sole desired-state command
  authority; and
- `PluginManagementReadModelProjector` captures desired-state, operation,
  enablement-migration, Source, Instance, Package, and retirement snapshots and
  joins them without persisting a new clock.

The projection keeps command status separate from convergence. It reports the
selected immutable Package and Instance revisions, operation summaries,
Instance state, retirement/cleanup evidence, owner revisions, unsupported or
unknown dimensions, and explicit skew classifications. Missing optional owner
ports remain visible as unsupported; missing facts from a supported owner are
unknown or skew and are never invented.

The source projection is intentionally inert. `manifest_enabled_default` is
input to the one-time A1-2 migration only. `availability` reports Source
Authority reachability and cannot enable or disable an Installation.

## A1-2: One-way legacy enablement migration

A1-2 implements one durable Product/scope/Installation migration journal with the
ordered states:

```text
accepted -> desired_committed -> compatibility_window -> finalized
```

The receipt binds the migration schema/epoch, Installation key, exact Package
revision, legacy input fingerprint, prior desired-state inventory revision,
the committed transition or `already_authoritative` disposition, and journal
revision. Under one migration lock:

- a never-seen Installation may be seeded once from explicit legacy disabled
  state and otherwise from the manifest install default;
- any pre-existing desired history wins without mutation;
- a crash before `desired_committed` replays the same deterministic operation;
- a crash after it observes the exact committed transition and advances the
  receipt instead of issuing a new intent; and
- a runtime that does not support an observed newer migration epoch fails
  closed before selection or mutation.

During `compatibility_window`, legacy fields are a derived downgrade projection
of canonical desired state. Current writers reject independent legacy Plugin
enablement mutation once a receipt exists. Finalization requires recorded
minimum-runtime, backup/restore, and roll-forward evidence; deletion of legacy
fields and mutators remains a later PLC9E change.

The compatibility floor is the minimum fence-aware runtime, not every binary
that predates PLC9A1. Once a receipt exists, direct downgrade to a pre-fence
binary is unsupported because that binary can recreate peer state. Recovery
from such a downgrade requires an offline restore followed by roll-forward;
the recorded finalization evidence makes that operational boundary explicit.

The generic implementation lives in
`src/loushang/harness/plugin_management/enablement_migration.py`. Coding binds
it to `enablement-migration.jsonl` under the existing workspace-private Plugin
state root and checks the supported epoch before recovering a management
operation. No migration journal is stored under Package data or a Session log.

Coding base, Capability, and Continuity composition import their exact legacy
selection inputs before mounting. An already-seen desired history is receipted
as `already_authoritative` and is never re-enabled by a Product default. A
never-seen disabled Installation is published to an exact immutable revision,
seeded disabled, and left unmounted.

`src/loushang/coding/plugin_enablement_compatibility.py::CodingPluginEnablementCompatibilityWriter`
is the Product-owned compatibility publisher. On POSIX it pins the existing
private workspace root with a no-follow directory handle; on Windows it opens
the existing direct coordination lock through `CreateFileW` with
`FILE_FLAG_OPEN_REPARSE_POINT` and without delete sharing, so that child handle
pins the validated parent tree. Other platforms without either capability fail
closed before reading state. Under the pinned root the reader takes the common
coordination lock, migration transaction lock, desired-journal lock, and
migration-journal lock in that fixed order. It therefore cannot observe a
writer's partial append or combine desired state from one migration transaction
with a receipt from another. The raw projection is read-only: an incomplete
crash tail is not a committed record and is ignored until the canonical owner
repairs it, while a malformed complete record remains fatal. The writer then
releases every workspace lock before sending a typed projection to the settings
owner. Stale captures cannot replace a newer per-workspace projection.
`LayeredConfig.transaction`
keys process-reentrant and cross-process locks by every normalized path-backed
layer, takes them in stable order, and strictly reloads every participating
layer; construction and tolerant reload take the same read locks. An unbound
engine may be used directly, but `ScopedConfigRuntime` claims exclusive mutation
and projection ownership when bound. Authority is checked again in the final
engine-locked mutation/transaction critical section, and direct `publish()` is
also fenced, so a concurrent bind cannot leave an unprojected commit. Every
runtime mutation therefore follows the single `path -> engine -> runtime`
order. Engine commit snapshots are
captured and queued before unlock, while runtime transactions publish one final
`ConfigChange`; mutation calls inside an explicit transaction return its result
handle rather than a provisional receipt. Both listener families run only after
mutation locks are released. The
compatibility transaction preserves only unmigrated legacy ids, clears a stale
session legacy overlay, publishes the project downgrade view, and verifies the
effective migrated values. Its opaque object capability cannot be reclaimed by
repeating a caller-chosen string. A shared settings owner accepts exactly one
Coding Product registry authority. That registry retains one writer and latest
projection per workspace, serializes aggregate publications without holding its
lock across config I/O, unions disabled ids conservatively, and calls every
workspace guard before any peer mutation. Coding startup, every Continuity
startup path (including empty-source and idempotent early returns), and CLI
binding reconcile it; early reconciliation failures use the same stable
`CodingContinuityBootstrapError`, retryability, and failed-status projection as
the full bootstrap path. An existing receipt with a non-fence settings owner
fails closed. A crash or
write failure after a canonical commit is repaired from the durable receipt and
desired journal. The command still fails visibly with
`plugin_enablement_compatibility_publish_failed`; it never rolls canonical
state back or reports runtime convergence.

## A1-3: Coding CLI adapters

A1-3 routes `--list-plugins`, `--enable-plugin`, and `--disable-plugin` through
the common query/command ports. Formatting and exit-code mapping remain pure
CLI adapters. They cannot import or construct durable ledgers, infer success
from settings, or mutate source configuration.

`--add-plugin-source`/`--remove-plugin-source` and their existing
`--add-plugin`/`--remove-plugin` aliases retain Source add/remove semantics.
Skill settings and Package commands retain their existing owners. A CLI
desired-state command against an uninstalled or unmigrated Installation fails
with a stable, visible diagnostic code instead of materializing a Package or
mutating the legacy settings peer. A receipt in `accepted` or
`desired_committed` is reported as migration-in-progress and is not command
admission.

Coding's CLI Product binding resolves relative local Sources against the
workspace, not the launcher process directory. After a canonical enable/disable
command it publishes the compatibility-window `disabled_plugins` value as a
derived downgrade view while retaining legacy ids that have not yet received a
migration receipt. That write is never used to infer command success.
Source-only rows report unknown enablement rather than disabled. Listing also
exposes desired state, convergence, and migration phase; command output says
only that desired state committed and never claims runtime convergence.

## Failure And Replay Semantics

- Query capture is non-transactional across owners by design. Owner revisions
  and skew make the observation boundary explicit.
- Desired snapshot/history capture and each complete migration transaction are
  atomic within their respective owner locks. Concurrent replay therefore
  records one exact migration outcome.
- Command retry uses the caller's operation/idempotency identity; correlation
  identity may change when an operator resumes the same operation.
- A terminal command result does not assert runtime convergence.
- Without an Instance owner, runtime convergence is `unknown`; an empty
  supported Instance snapshot may establish an inactive observation.
- An `absent` tombstone remains authoritative on restart: a still-configured
  mutable Source is neither reinspected nor republished.
- Unsupported backup, private-data, or Worker dimensions remain named as such.
- Neither migration nor CLI handling may execute Plugin code, acquire a remote
  artifact, delete data, or weaken retirement/cleanup evidence.

## Evidence And Deletion Gates

Behavioral tests cover correlated idempotent command/resume, owner-revisioned
projection, Product/scope filtering, versioned operation shapes, orphan skew,
migration crash/replay/concurrency/downgrade behavior, compatibility repair and
mutation fencing, workspace/restart isolation, tombstone replay, and real CLI
alias separation.
Architecture tests keep management implementation out of `loushang.plugin`,
prevent transport imports and projection persistence in the common application
module, and prevent CLI desired-state paths from reconstructing a ledger or
calling Plugin settings mutators.

The legacy `disabled_plugins` field, `PluginManager`, manifest/source selection
vetoes, Package/Resource projection inputs, and compatibility aliases are not
deleted by PLC9A1. Each remains subject to the explicit PLC9 inventory gate.
