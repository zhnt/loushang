# PLC9D3b Store GC Re-publication Fence

## Status

- Tracking: PLC9 `#509`. This is a dark Store-owner hardening slice, not
  executable Product GC or PLC9D completion.
- The private `delete_settlement` route is still unbound from any Product
  command, scheduler, RPC, or UI.

## Counterexample And Rule

Before this slice, `delete_settlement` could remove one exact published tree,
then the same staging request could recreate the same final ref. A durable
deletion result would therefore be false as soon as that retry ran.

The Store settlement journal now records a versioned tombstone for one exact
settlement and stable ref before the first physical unlink. It requires the
settlement to exist and rejects ambiguous physical settlements for the same
ref. The Store's cross-process owner lock serializes this append with staging.
POSIX and Windows staging refuse a tombstoned ref before creating a staging
tree; settlement authorization and receipt reuse also refuse it. Other refs
remain publishable. A crash after the tombstone but before or during removal
leaves a blocked ref and a tree that the same private deletion primitive can
resume. Repeating the tombstone operation is idempotent.

The tombstone is an incompatible record in the existing Store settlement
journal. Previous settlement codecs reject it, excluding older Store writers
that replay the journal before publication. Current journal replay validates
its exact prior settlement and refuses any later publication of that ref.
Settlement business revisions remain contiguous across intervening tombstones.

## Still Required

This Store fence does not authorize deletion. PLC9D still needs a Product
cutover to the PLC9B Store handoff, exact crosswalk/committed-set/settlement
resolution, alias and shared-dependency protection, and a durable GC
result/debt coordinator. Generic private-data confirmation and backup
retention remain separate contracts. The POSIX replay and re-publication tests
pass locally; Windows execution requires Windows CI.
