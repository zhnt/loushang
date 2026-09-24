# PLC9D3m Cutover Backup Status Projection

## Status

- Tracking: PLC9 `#509`. This is a POSIX read-only operator projection of the
  real PLC9B pre-B workspace snapshot owner. It is available through
  `loushang-package-cutover --backup-status` only after a completed B fence.
- It describes one workspace cutover backup. It is not per-Plugin backup
  retention, an expiry schedule, a restore command, or private-data deletion.

The query reopens the current exact Product fence, reads its snapshot receipt
ID, and asks `PackagePosixEpochSnapshotEvidenceStore` to verify the immutable
snapshot bundle. A retained result requires owner evidence matching the fence's
Store, legacy-root identity, and quiescence receipt. Output is pathless and
includes the snapshot receipt/evidence IDs and verified entry and byte counts.
Backup expiry is always `unknown` because this owner issues no expiry receipt.

A missing evidence file or snapshot authority yields `unknown`, never
`retained` or `expired`. Malformed or contradictory evidence is refused rather
than translated into a successful status. The command does not bootstrap
Plugins, mutate Product desired state, or run GC. A subprocess regression
checks verified retention, missing-evidence unknown, corrupted-evidence
refusal, and unchanged fence bytes.

The D3k management projection still reports per-Installation backup retention
as unsupported unless a separate owner with exact per-Installation records is
bound. The cutover snapshot cannot be projected as every Plugin's backup:
later Installations may not have existed when it was captured.
