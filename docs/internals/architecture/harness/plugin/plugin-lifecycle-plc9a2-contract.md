# Plugin Lifecycle PLC9A2 Product Routing Contract

## Status

- Contract version: PLC9A2.
- Delivery status: implemented as PLC9A2.0, PLC9A2.1, and PLC9A2.2; the
  unified PLC9A2 gate is executable.
- Scope: internal Product composition, recovery/epoch activation, and the
  existing operations, Session, CLI, RPC, and startup Package entrypoints.
- Public author SDK effect: none. UI and a management SDK remain unimplemented.
- Deletion effect: none. PLC9D remains the only future authority for physical
  artifact GC and Plugin-private data deletion.

PLC9A2 activates the PLC9B route only when a Product explicitly injects one
activated composition. It does not make the composition a Harness singleton
and does not give a transport a Package owner, ledger, Store, path, or live
handle.

## First Principles

1. Product policy chooses and activates capabilities; Harness supplies
   capability-poor mechanisms and typed seams.
2. Classification precedes every legacy side effect. Only an independently
   evidenced `non_plugin` result may reach the legacy Package implementation.
3. `plugin_bound` and `indeterminate` never fall through. A refused Plugin
   operation is a handled, pathless result.
4. Recovery precedes exposure, and exact epoch admission is checked again
   immediately before every route. The admitted request identity is stored in
   the V2 lifecycle request's independent `runtimeAdmissionRequestId` field and
   therefore enters the same atomic accept/request fingerprint without
   changing the real resolution-environment fingerprint. An active operation
   cannot be resumed under a successor epoch and no second writer is required.
   The original V1 request type, wire shape, fingerprint, and journal decoder
   remain intact; the Product router requires V2 and rejects any mismatch
   between its ingress binding and admission receipt.
5. All transports carry the same versioned intent. Their only differences are
   provenance (`operations`, `session`, `cli`, `rpc`, or `startup`) and
   correlation identity.
6. A desired-state commit is made through `PluginManagementService`'s narrow
   command port. Retention settlement and transaction-pin release remain a
   separate durable owner.
7. `remove` and `uninstall` may express lifecycle intent, but PLC9A2 grants no
   filesystem deletion capability. Desired absence is not physical deletion.

## PLC9A2.0: Contract, Inventory, And Guards

`src/loushang/harness/resources/packages/product_contract.py` owns
`PackageProductLifecycleIntentV1`, `PackageProductLifecycleOutcomeV1`, and
`PackageProductLifecycleRecordV1` as the transport-neutral boundary. The
record exposes only canonical Source identity and durable lifecycle evidence;
its compatibility `path` is always empty. Raw locators, credentials, native
paths, Store objects, and live handles are not projected.

`PackageProductLifecycleMode` freezes the rollout states (`legacy`, `dark`,
`enforced`). `PackageProductLifecycleInventoryPort` owns update target and
check projections. Every target ref is the SHA-256 identity of its raw Source;
`PackageProductUpdateCheckRequestV1` preserves operation correlation,
entrypoint provenance, and canonical scope through the real inventory call.
Check names are derived from that ref and failure details collapse to one
stable generic code. `PackageProductLifecycleExecutionBinding` binds the
lifecycle owner and transaction owner at composition and each call.

Transport and Session layers import only that contract. The Product activation
module may depend on the accepted PLC9B router and
epoch admission owner. It may not import the legacy materializer, settings,
config, CLI/RPC transport, or concrete filesystem/process owners. The public
`loushang.plugin` author namespace does not export A2 application or owner
types.

The exact migrated call graph is:

```text
operations ─┐
Session ────┤
CLI ────────┼─> execute_package_lifecycle
RPC ────────┤      -> PackageOperationsRuntime
startup ────┘      -> PackageProductLifecycleActivation
                           -> PLC9B router -> injected transaction
```

No new UI or management-SDK protocol is inferred. A later transport must bind
the existing A1 command/query ports for management operations and this A2
Package intent port for artifact operations, then pass the same conformance
fixture before it is enabled.

## PLC9A2.1: Dark Product Composition And Recovery

`compose_package_product_lifecycle` is the sole composition helper. It binds
one `PackageLifecycleOwner`, one injected PLC9B transaction port, one
Product-owned ingress factory, one epoch admission owner/request, and an
ordered tuple of recovery ports. Construction is inert. `activate()` runs all
recoveries and admits the exact runtime epoch before publishing the internal
active receipt; a failed or stale recovery leaves the route unavailable.

`PluginManagementPackageDesiredStateAdapter` translates the post-publication
PLC9B desired handoff into the sole management command owner. V1 covers the
accepted install handoff and installs the exact admitted revision disabled; it
does not reinterpret source availability or implement remove/GC. The adapter
requires an exact owner-revision projection and reports a CAS conflict with the
observed revision instead of guessing it.

`PackageProductRetentionSettlementOwner` durably owns dependency-pin
acquisition/abort/settlement. On settlement it first transitions the exact
transaction pin to `released`, then records the dependency pin as `settled`.
Replay repairs the crash window between those two appends without creating a
second physical pin or releasing an unrelated pin. Corrupt, foreign, or stale
chains fail closed. `PackageRetentionHandoffRecovery` resumes every
nonterminal handoff before activation; retryable and stale outcomes prevent
activation.

These owners remain dark until a Product creates all policy-specific inputs
and injects the same activated lifecycle into bootstrap and Session
construction. Harness does not invent Source credentials, Product policy,
scope, Store roots, or epoch leases.

## PLC9A2.2: Layered Activation

`PackageOperationsRuntime` is the one side-effect choke point. For each source
operation it submits the typed Product intent before resolving a local path,
calling the legacy materializer, changing Package Source settings, or invoking
mutable remove/forget behavior. Bulk update becomes per-record routing while a
Product lifecycle is active. Its Product-owned inventory supplies opaque,
scope-bound targets; stable child operation IDs allow a restart to skip
committed children and resume only the interrupted child. Update availability
checks use a separate pathless Product inventory projection and cannot call the
legacy materializer while Product routing is active.

`PackageProductUpdateManifestJournal` durably freezes each lifecycle owner
binding, batch operation id, canonical scope, and ordered target-ref set before
its first child runs. It returns a typed, pathless
`PackageProductUpdateManifestReceiptV1`; the operation owner recomputes and
exactly compares that receipt before routing children. It persists no locator
or credential. Restart may resume only the exact owner-bound manifest; an
owner change or an added, removed, aliased, or reordered target fails closed.
Existing permissive, linked, foreign-owned, or non-regular storage is rejected.
The manifest uses the common directory-synced, locked,
partial-tail-repairing JSONL contract inside a private owner directory.

`SessionPackageController.execute_package_lifecycle` preserves the transport's
action, provenance, operation id, and scope and dispatches exactly once. The
public optional Session facade only forwards that typed call. CLI creates one
operation id per source; RPC deterministically binds a supplied command id and
otherwise creates one operation id. Both prefer the typed executor before any
legacy compatibility method. Startup uses a deterministic per-session/source
identity and routes missing Sources before synchronous materialization.

RPC runtime Product executors are usable only when the current Session attests
the same binding. Product collection exceptions collapse to stable error
codes; single and bulk Plugin lifecycle rows are reconstructed as exact
`PackageProductLifecycleRecordV1` projections with derived names, opaque
sources, empty paths, expected action/correlation, and bounded stable failure
codes. Names are recomputed from opaque source identities, failure codes come
from an explicit Product-owned allowlist, and Product failure details never
cross RPC. Explicit non-Plugin fallback rows are reduced to a separate opaque,
pathless compatibility projection. Update-check rows are likewise rebuilt
against their exact schema, and any failed bulk child makes the RPC collection
fail without returning partial records.

Rollout mode is explicit: `legacy` rejects Product bindings, `dark` permits a
missing binding but uses it whenever activated, and `enforced` requires an
activated lifecycle. A Product inventory must carry the exact lifecycle
`binding_id`. Legacy compatibility remains available only in legacy/dark
fallback or when classification returned explicit `non_plugin`. Because an
activated Product Session exposes the typed single-source and collection
executors, CLI/RPC dynamic compatibility cannot bypass its classifier even if
an older runtime method is also present. RPC accepts a runtime-side typed
executor only when the current Session attests the same owner binding; owner
mismatch and hidden typed helpers fail closed.

Transports validate but preserve compatibility `global` until any explicit
`non_plugin` fallback completes. Product intents canonicalize it to `user`;
the sole legacy settings bridge maps `user` back to `global` and rejects every
unknown scope instead of silently writing Session state. Product inventory
reads run only through `execute_guarded_query`, which holds the same epoch
guard as a mutation route and deactivates on admission, query, or owner-binding
failure.

## Unified Acceptance Gate

The PLC9A2 gate combines:

- architecture tests for import direction, author-SDK exclusion, inventory,
  typed entrypoint provenance, and absence of concrete materializer/settings
  authority in Product activation;
- route conformance for all five entrypoints with one durable operation;
- negative tests proving activation-before-route, indeterminate fail-closed,
  explicit-non-Plugin-only fallback, no path/secret projection, and no legacy
  materializer/settings/delete effect for handled Plugin input;
- CLI and RPC correlation/provenance tests; and
- recovery, replay, desired-CAS, retention settlement, and epoch-admission
  tests together with the existing PLC9B acceptance suite;
- cross-epoch active-operation replay refusal and mutable transaction-owner
  refusal; and
- partial bulk crash/restart, owner-bound manifest receipts, unsafe-storage
  refusal, and Product-owned update-check tests that prove correlation reaches
  the real inventory while legacy materializer paths stay untouched.

The rollback switch is omission of the Product lifecycle binding. That keeps
non-Plugin Package behavior intact but disables Plugin artifact activation; it
does not restore a Plugin-bound peer publisher. Roll forward uses only durable
PLC9B, handoff, retention, and epoch evidence.
