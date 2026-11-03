# PLC9D3a Writer Fence And Store Deletion Primitive

## Status

- Tracking: PLC9 `#509`. This is a dark prerequisite, not executable GC or PLC9D completion.
- Product composition binds the same durable reservation path to Coding desired,
  Instance, and Package ledgers. `prepare_gc_writer_epoch()` explicitly seals
  their journals after startup recovery; normal startup never invokes it.
- No CLI, RPC, UI, SDK, scheduled job, or Product deletion command is exposed.

## Writer Exclusion And Irreversible Start

The three owner journals accept one marker that records the exact owner and
reservation-journal path digests. It does not consume a business revision.
Current bound readers require the matching gate. Previous codecs and current
unbound readers reject a sealed journal, so they cannot append a new reference
after cutover. The Product seal is idempotent; a crash between three seals can
be retried. An executor must check all three seals before deletion.

The reservation journal can record `deletion_started` only for one active exact
reservation, a sealed writer graph, an unchanged retention candidate, and a
canonical set of settlement IDs. Once recorded, cancellation is refused and
the reservation remains active across restart. A later executor may retry the
same physical operation without rechecking a now stale candidate, but must
verify the recorded target set. The D2 reservation/cancellation reader rejects
the newer record version.

## Exact Physical Primitive

The POSIX and Windows Store owners have a private `delete_settlement` primitive.
It checks the Store role and identity, pinned root identities, exact settlement
membership, final-tree native identity, every remaining member identity and
content, and absence of unexpected members. It deletes through the pinned
Store root; a partially deleted recorded tree can be retried. The returned
typed result says `deleted` or `already_absent`. This result is not yet a
durable GC receipt. The primitive has no public Materialization Store port and
is not called by Product.

A durable crosswalk can record a successful PLC9B desired handoff's exact
committed-set root ref and management Package revision. The later precommit
claim refinement records that root before the desired command, so an
interrupted crosswalk append remains a conservative GC blocker. Missing
crosswalks are not reconstructed from path, plugin name, or digest similarity.

## Remaining Closure Gates

1. Product still publishes Coding Plugin revisions through the legacy
   `PluginRevisionStore`; the PLC9B desired handoff adapter has no Product
   caller. Historical revisions lack an exact PLC9B Store settlement. Migrating
   or conservatively excluding them needs a separate Product cutover proof.
2. A GC coordinator must resolve the crosswalk to one committed set and its
   exact Store settlements, exclude aliases and shared dependency refs, and
   hold the reference gate through deletion. PLC9D3b adds a durable Store
   tombstone for re-publication; the coordinator must still use it under the
   exact Product reference fence.
3. The coordinator must durably journal Store success or retryable debt and
   expose recovery/repair. Neither a `deletion_started` event nor the Store
   return value is a settled GC outcome.
4. Generic Plugin-private data deletion needs separate explicit confirmation
   and a domain-owned plan/receipt. Backup retention must project its actual
   owner or explicitly report unknown. Artifact GC cannot claim either effect.

The focused regressions cover writer downgrade refusal, durable reservation
start/cancellation exclusion, crosswalk replay, POSIX exact deletion and
partial retry, and a native Windows deletion test. Windows execution still
requires Windows CI evidence. These tests do not demonstrate end-to-end GC.
