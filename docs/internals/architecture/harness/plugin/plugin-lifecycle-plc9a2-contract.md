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
   immediately before every route.
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
Product lifecycle is active.

`SessionPackageController.execute_package_lifecycle` preserves the transport's
action, provenance, operation id, and scope and dispatches exactly once. The
public optional Session facade only forwards that typed call. CLI creates one
operation id per source; RPC deterministically binds a supplied command id and
otherwise creates one operation id. Both prefer the typed executor before any
legacy compatibility method. Startup uses a deterministic per-session/source
identity and routes missing Sources before synchronous materialization.

Legacy compatibility remains available only when no Product lifecycle was
configured or classification returned explicit `non_plugin`. Because an
activated Product Session exposes the typed executor, CLI/RPC dynamic
compatibility cannot bypass its classifier even if an older runtime method is
also present.

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
  tests together with the existing PLC9B acceptance suite.

The rollback switch is omission of the Product lifecycle binding. That keeps
non-Plugin Package behavior intact but disables Plugin artifact activation; it
does not restore a Plugin-bound peer publisher. Roll forward uses only durable
PLC9B, handoff, retention, and epoch evidence.
