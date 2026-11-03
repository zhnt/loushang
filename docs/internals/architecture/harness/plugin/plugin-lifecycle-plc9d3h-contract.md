# PLC9D3h Root GC Result Projection

## Status

- Tracking: PLC9 `#509`. This is an internal, read-only Product projection.
  It grants no deletion, cancellation, repair, private-data, or backup power.
- POSIX native execution supplies the current evidence. Windows Product
  execution and default management/transport composition remain open.

## Exact Evidence Join

`PackageProductRootGcReadModel` holds the Product reservation gate while it
reads active reservations, deletion starts, the exact PLC9B handoff/Store
crosswalk, GC result attempts, and committed-set plus Store tombstones. Its
versioned rows expose only candidate and result identities, state, and a stable
reason code. No physical path or private data appears in the projection.

The states are `reserved`, `deletion_started`, `retryable_failure`,
`terminal_failure`, `succeeded`, and `evidence_conflict`. Success requires an
exact Store result for the resolved settlement and both durable root fences.
Missing, aliased, mismatched, or altered evidence becomes `evidence_conflict`;
it cannot be reported as success by replaying a result record alone. A corrupt
result journal fails the read rather than inventing a status.

Native Product cases prove reserved and irreversible-start states, success
after deletion or crash recovery, terminal Store collision debt, a foreign
result conflict, and downgrade to evidence conflict after tombstone removal.
These statuses do not imply private-data deletion or backup expiry.

The D1 all-revision retention view and this active-reservation view remain
separate. Operator repair for terminal debt, historical cancelled reservations,
default Product/transport wiring, and Windows native evidence remain open.
