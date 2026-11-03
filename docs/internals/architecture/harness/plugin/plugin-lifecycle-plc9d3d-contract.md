# PLC9D3d Committed-Set Root Ref Fence

## Status

- Tracking: PLC9 `#509`. This is a dark Package-owner prerequisite, not
  executable Product GC or PLC9D completion.
- No Product command, Store deletion caller, or private-data/backup effect.

## Concurrent Publication Counterexample

An exact root target resolved from current committed sets is not sufficient:
another Package transaction can publish a committed set carrying the same
physical root ref before GC deletes it. A Store tombstone alone blocks
re-staging, but it does not stop an already staged ref from entering a new
committed set.

The committed-set journal now accepts one versioned tombstone for an exact
prior set/root ref. It rejects the tombstone if the ref already appears in
multiple committed sets. After it is written, `publish()` refuses even an
otherwise exact replay of that ref; unrelated roots remain eligible. Current
replay validates the marker's exact predecessor and refuses a later set for
the retired ref. Previous committed-set codecs reject the incompatible marker
and therefore cannot append across the cutover. Business set revisions stay
contiguous when tombstone records intervene.

The future executor must first persist an irreversible Product GC start under
the reference gate, then append this committed-set fence, then the Store
tombstone, then perform rooted deletion. A crash at either fence is recoverable
by replaying the same exact target. This slice does not implement that
coordinator or a durable success/failure debt receipt.
