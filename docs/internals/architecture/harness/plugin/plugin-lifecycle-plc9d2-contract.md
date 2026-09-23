# PLC9D2 Dark Package GC Reservation Contract

## Status And Boundary

- Tracking: PLC9 `#509`. This is a local implementation candidate, not an
  accepted executable-GC or PLC9D completion claim.
- Owner: `PluginPackageGcReservationJournal` durably owns only reservation and
  cancellation evidence. The Package lifecycle ledger still owns retention
  candidates; Desired State and Instance Runtime still own their references.
- Activation: dark. No Coding/Product, CLI, RPC, UI, author SDK, Store, or
  physical deletion route is added.

An executable GC owner cannot rely on a read-time candidate recheck: another
writer could select or pin the same revision before deletion. D2 introduces a
shared, explicitly injected guard over the three reference-writing ledgers.
It is a prerequisite for deletion, not deletion authorization.

## Reservation Protocol

An opt-in owner graph binds **one journal object** to the desired-state,
Instance-runtime, and Package-lifecycle ledgers. `reserve()` refuses an
unbound graph, rechecks the exact D1 candidate while holding the journal's
exclusive cross-process lock, then appends a versioned reservation. Repeating
the same operation rechecks the candidate and converges. Changed operation or
idempotency identities and another active reservation for the same revision
fail closed. A cancellation
requires the exact reservation ID, a new operation identity, and a reason; D2
permits cancellation because it never starts physical deletion.

Bound reference writers acquire the reservation guard **before** their owner
locks. The management service also takes it before its operation journal lock,
so its nested desired-state commit and recovery follow the same order. A
reentrant in-process guard avoids reacquiring the file lock in that nested
path. A reserved revision cannot be newly selected by desired-state commit or
update, activated or leased by the Instance runtime, or pinned by Package
retention. Unrelated revisions and reference release remain available.

The journal replays active reservations after restart, repairs only an
incomplete tail, and rejects a complete corrupt record. Bound writers fail
closed when the reservation journal cannot be reconstructed. The operator can
inspect active reservations separately from the D1 retention projection; an
ordinary D1 candidate remains a retention candidate, not a deletion receipt.

## Explicit Limits And Next Gate

An older or separately constructed writer that omits the injected guard can
still write the same desired-state journal. The regression freezes this
counterexample and proves that a bound Instance runtime refuses activation of
its newly selected revision. Consequently **D2 does not authorize deletion**.
Before D3, one Product composition must bind every supported writer and prove
a minimum-version/downgrade fence excludes legacy writers; D3 must recheck
desired, Instance, Package, and reservation evidence under that authority.

D3 must also bind the exact published Store tree/native identity, execute
rooted deletion through the Store owner, and persist a result or retryable
debt. Neither reservation cancellation nor Plugin remove may invoke private
data deletion or assert backup expiry.

| Seam | Old caller | D2 caller and authority |
| --- | --- | --- |
| Desired selection | management service or direct desired ledger | optional gate before operation/desired locks; same desired owner |
| Instance activation/family | runtime ledger | optional gate before operation/runtime locks; same Instance owner |
| Package pin | lifecycle ledger | optional gate before Package lock; same retention owner |
| Reservation | absent | internal `package_gc_reservation.py` journal only; no Product or Store caller |

Focused durable-ledger tests cover exact replay, cancellation, stale candidate,
new pin/selection refusal, management lock order, restart and partial-tail
repair, corrupt-log fail-closed behavior, unbound-graph refusal, and the legacy
writer counterexample. No native deletion or end-to-end GC test is claimed.
