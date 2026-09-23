# PLC9D1 Package GC Operator Projection Contract

## Status And Scope

- Tracking: PLC9 issue `#509`; this is a narrow implementation candidate, not
  PLC9D or PLC9 completion evidence.
- Owner: `PluginPackageLifecycleLedger` remains the sole retention-evidence
  owner. `PluginPackageGcReadModel` is a read-only internal projection.
- Effect: no artifact deletion, GC lease/reservation, Store mutation, private
  data deletion, backup-expiry claim, or new management command.

PLC9D1 makes existing durable retention and cleanup evidence inspectable for
**every known Package revision**, including a revision present only in history.
The existing management Installation view is keyed by current Installations;
it cannot by itself list an orphaned revision that might be GC eligible.

## Operator Query

`PluginPackageGcReadModel.snapshot()` captures one
`PluginPackageLifecycleSnapshotV1` and returns a versioned projection sorted by
exact Package revision. Each row carries the exact revision, zero or more
blocker codes, an optional GC candidate, and that revision's cleanup task
states. Cleanup summaries expose attempt count, last result code, retry time,
last repair action, and whether the lease is still open; they do not invent an
operator repair decision.

The blocker codes are `startup_recovery`, `desired_installation`,
`nonretired_instance`, `runtime_family`, `retention_pin`, `cleanup_lease`, and
`terminal_cleanup_failure`. The candidate is present exactly when the existing
retention owner reports no blocker. Its identity binds the desired, Instance,
Package journal, and recovery-barrier revisions. It proves retention eligibility,
not that a published Store tree currently exists. A terminal cleanup failure
retains a lease and stays blocked until the existing durable repair/attempt
sequence reaches success or an explicit `safe_abandon` decision.

The operator projection grants no deletion authority. A later executable GC
slice must first add a durable exclusive reservation that prevents new
references during deletion, bind the exact published Store tree and native
identity, recheck the candidate under the appropriate Product/owner fence,
perform rooted deletion through the Store owner, and durably settle success or
retryable debt. Calling `recheck_gc_candidate()` alone cannot close the race
between a read and physical deletion.

## Caller Inventory And Verification

| Seam | Before | PLC9D1 |
| --- | --- | --- |
| Package lifecycle ledger | retention snapshots, candidate generation/recheck, cleanup attempts and repair evidence | unchanged authority and journal format |
| Internal GC operator | no all-revision projection | `plugin_management.package_gc.PluginPackageGcReadModel` consumes only `snapshot()`; no command or Store dependency |
| Coding/CLI/RPC/UI | no artifact GC route | unchanged; no new Product or transport caller |

The focused durable-ledger regression covers recovery gating, an exact
candidate, stale candidate rejection after a new pin, visible terminal cleanup
debt, and explicit safe abandonment. Static checks keep the read model free of
deletion or Store imports. No physical deletion or crash-restart GC claim is
made by this slice.
