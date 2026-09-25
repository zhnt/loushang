# PLC9D3f Internal Root GC Execution

## Status

- Tracking: PLC9 `#509`. This is an internal, manually composed root-GC
  executor. No CLI, RPC, UI, SDK, scheduled job, or default Product deletion
  command selects it. PLC9D is not complete.
- Native evidence currently covers POSIX only. The Store Port is platform
  neutral, but Windows execution and failure evidence remain required.

## Exact Root Sequence

`PackageProductRootGcExecutor` holds the Product reservation/reference gate
from active-reservation lookup through result append. It requires the desired,
Instance, and Package writer epoch seals, then reads the confirmed Product
handoff claim/binding, committed set, and Store settlement under that gate.
The exact-target resolver rejects missing or aliased roots. The executor then:

1. durably records `deletion_started` for that one settlement;
2. tombstones the committed-set root ref, excluding a later committed alias;
3. calls the Store owner's exact `delete_settlement` primitive, which tombstones
   the Store ref before unlinking and verifies rooted physical identity; and
4. appends the typed Store result or a terminal Store identity failure to the
   GC result journal before releasing the reference gate.

The start identity is stable for a reservation. Reusing an attempt identity
returns its prior result; a new attempt can recover an interrupted deletion as
`already_absent`. A recorded success is returned only while both committed-set
and Store tombstones remain durable. Generic unexpected exceptions leave the
irreversible start unsettled for a later exact retry rather than inventing a
success receipt. Malformed attempt identities are refused before the
irreversible start or any Store effect. The result journal also preflights
settlement ownership and attempt identities before either root fence or the
physical Store effect, so a prior result conflict cannot strand a deleted root.

## Evidence And Remaining Gates

The POSIX integration fixture starts from a real Product transaction and
management desired handoff, retires the revision, reserves a real lifecycle GC
candidate, and proves `deletion_started → exact root deletion → durable result`.
It covers root-only and shared-dependency Wheels; dependency trees remain
untouched. Injecting a crash after physical deletion but before result append
proves replay through a reopened Store and result journal settles
`already_absent`. Removing the Store tombstone after success makes replay refuse
the claim. Replacing a recorded file with a symlink to an outside file leaves
that outside file untouched and records terminal Store identity debt.
Seeding a conflicting result for the same settlement proves that preflight
refuses deletion while leaving both root fences open.

Product-wide GC ingress and operator recovery/repair are still absent. Older
legacy Package revisions without an exact PLC9B crosswalk remain blocked.
Shared dependency GC needs separate reference accounting. Generic Plugin
private-data deletion requires its own explicit confirmation and domain-owned
receipt; backup retention must project real owner evidence or report unknown.
