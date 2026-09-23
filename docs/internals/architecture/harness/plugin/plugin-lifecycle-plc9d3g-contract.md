# PLC9D3g Explicit Product Root GC Command

## Status

- Tracking: PLC9 `#509`. This is an explicitly composed internal Product
  command, not a default management, CLI, RPC, UI, SDK, or scheduled GC route.
- POSIX native execution is tested. Windows native Product composition and
  failure evidence remain open. PLC9D is not complete.

## Command Boundary

`PackageProductRootGcCommandV1` names the exact retention candidate and
separate reservation and deletion-attempt identities. It is distinct from
Plugin removal and carries no private-data or backup action.
`PackageProductRootGcApplication` requires the same Product reservation gate
and Package lifecycle owner as its root executor. Under that gate, it refuses
an unsealed writer epoch, rechecks and durably reserves the exact candidate,
then delegates to the D3f executor. The root Store adapter exposes only its
existing exact-settlement deletion primitive to this internal composition;
the Store still verifies its own root and physical identity.

The POSIX real-Store/Product fixture proves a command can take a candidate
from the retired Package lifecycle through reservation, `deletion_started`,
root deletion, and a durable result. Repeating the same command returns the
same result. A stale candidate and an unsealed writer epoch are refused before
reservation or any root fence, and a shared dependency tree remains intact.

Default Product composition and transport selection of this command, operator
result/debt projection and repair, Windows native execution, and legacy
revision crosswalk are still absent. Shared dependency GC needs separate
reference accounting. Private-data deletion and backup retention remain
separate domain-owned operations.
