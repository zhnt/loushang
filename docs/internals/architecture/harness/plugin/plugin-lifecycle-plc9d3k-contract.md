# PLC9D3k Private-Data Confirmation And Backup Projection Seams

## Status

- Tracking: PLC9 `#509`. This slice adds inert Harness contracts and a
  conditional management read projection. It does not add a Product deletion
  command, a Coding private-data owner, a confirmation issuer, a backup owner,
  or a backup-expiry executor.
- Package remove and root GC retain no private-data or backup authority.

## Private Data

`PluginPrivateDataDeletionCoordinator` previews one data-domain-owned plan
identified by Installation, owner, and opaque target. Deletion requires a
separately supplied confirmation bound to the plan fingerprint, a successful
check by an injected Product/operator confirmation authority, and a fresh plan
from the same data owner. It delegates mutation to that owner and accepts only
an exact matching receipt. The coordinator never receives a filesystem path or
deletes data itself. The data owner must revalidate at mutation time and
durably settle and replay its receipt; the confirmation authority must issue
and verify operator intent independently. Neither production binding exists
yet, so the generic command is not enabled.

The isolated acceptance test uses a separate test data owner with a persistent
receipt. Wrong-plan confirmation, stale plan, unapproved confirmation, and a
foreign receipt cannot produce a successful coordinator result. A successful
test deletion removes only the owner's test marker; re-instantiating the owner
replays the same receipt. Earlier Product GC tests independently prove their
own marker survives Package removal and root GC.

## Backup Retention

`PluginManagementReadModelProjector` accepts an optional read-only backup-owner
snapshot. Without a bound owner it retains `backup_retention` as unsupported.
With an owner it reports the owner's revision and per-Installation record;
missing or explicitly unknown records remain unknown. An `expired` record
requires an owner-supplied expiry receipt ID. The projection never derives
backup state from desired absence, Package GC, or private-data deletion.

The current acceptance uses an injected test owner. Production backup-owner
composition and evidence authentication remain open before any live expiry
claim can be made.
