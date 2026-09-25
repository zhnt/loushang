# PLC9D3j Offline Root GC Command

## Status

- Tracking: PLC9 `#509`. `loushang-package-gc` is a declared POSIX offline
  operator route for an already fenced Coding B workspace. It is not a
  Session, RPC, UI, SDK, or scheduled deletion route.
- It deletes only exact B-owned immutable Plugin roots with a complete Product
  handoff crosswalk. It has no private-data or backup-retention authority.

## Command Sequence

`prepare` invokes normal Product transaction/handoff recovery, refuses active
runtime leases or acquired transaction pins, completes the Package recovery
barrier, and durably seals the three GC reference writers. `list` returns
pathless candidate IDs, Plugin IDs, and exact durable statuses. `delete`
requires one listed candidate ID and an operator attempt key; it reserves and
starts only that candidate through the D3i Product owner. The reservation
operation identity is deterministic for the Store and candidate. Repeating
the same candidate and attempt key returns the same settled result.

`retry` requires the durable reservation ID returned by `delete` or `list`
and a new attempt key. It refuses a reservation without `deletion_started`.
After an interrupted deletion it uses the recorded settlement rather than
recomputing a potentially stale candidate. The Product Store still verifies
its exact rooted physical identity and both durable tombstones before success
is projected. An attempt key is hashed before it enters the journal; operators
must retain it for exact replay.

The persistent-workspace subprocess test proves preparation, candidate
selection, unknown-candidate refusal without deletion, exact root removal,
unrelated-root survival, idempotent replay, reservation retry, and success
projection across separate CLI processes. A second native case interrupts
after exact physical deletion but before result append: the status remains
`deletion_started`, and a new CLI process retries that reservation to persist
`already_absent` Store success without recapturing a candidate.

## Remaining Closure

Existing pre-B state adoption, Windows Product execution, default management
and RPC selection, terminal debt repair, explicit private-data confirmation,
and correlated backup-status projection remain separate acceptance work.
