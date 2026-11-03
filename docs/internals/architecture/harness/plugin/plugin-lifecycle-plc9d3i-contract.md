# PLC9D3i Fenced Product Root GC Composition

## Status

- Tracking: PLC9 `#509`. This is an explicit offline POSIX Product composition.
  D3j subsequently adds a declared offline CLI route; no default management,
  RPC, UI, SDK, or scheduled deletion route selects it.
- The Product owner supplies its already fenced B Store, desired-state and
  management owners, GC reservation gate, and exact handoff crosswalk. Opening
  the composition does not prepare GC or delete anything.

## Offline Boundary

`open_posix_local_wheel_product_root_gc` constructs the durable Instance,
Package, retirement, result, committed-set, and Store-settlement owners from
the same private B Product state root. It refuses a changed workspace, Product
state root, epoch, or fenced Store identity. `prepare()` explicitly completes
the normal Product transaction/handoff recovery, refuses any still-acquired
Package transaction pin, completes the Package recovery barrier, and seals the
desired, Instance, and Package GC writer epochs. Candidate reads, preparation,
status reads, and deletion hold
the epoch registry's exclusive runtime-quiescence scope and refuse any active
Session lease. They then hold the Product reference gate through the operation.

A native Coding Product test starts after an actual offline cutover and three
real Product installs, removes one Installation through the Product management
owner, and obtains its exact GC candidate. An active Session lease refuses the
command before reservation or deletion. With the lease released, the command
records `deletion_started`, deletes only its exact rooted Store settlement,
and persists a result backed by both tombstones. Reopening the Product owners
returns the same attempt and successful status. A separate private-data marker
survives; root GC makes no backup or private-data claim.
An injected acquired transaction pin refuses candidate selection even though
the Plugin reference graph is sealed.

## Remaining Closure

Only the later D3j offline CLI selects this composition. Existing pre-B Coding
state still requires explicit adoption or migration before Product cutover; this
composition only addresses B-owned revisions with a complete handoff
crosswalk. Windows Product composition, terminal GC debt repair, private-data
deletion confirmation, and correlated backup status remain separate work.
