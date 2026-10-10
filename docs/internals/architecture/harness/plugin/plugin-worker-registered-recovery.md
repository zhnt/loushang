# Registered Worker Recovery Contract

## Status

- Tracking: #509.
- Scope: the explicit Linux Coding Product Worker route.
- Status: the explicit Linux Product route has local cross-process coverage for
  recovery before or after a V2 cutover. The cutover-after-recovery branch now
  covers no-effect-only and mixed Worker histories, V1 segment retirement, and
  post-retirement proof tampering. Release still requires the remaining
  negative evidence cases, broad CI, and a physical reboot drill.

## Durable boundary

The Coding Worker creates a private payload stage and a start-gate `intent`
before C5 admission records `registered`. The C5 transition to
`effect_started` occurs before Supervisor launch. A crash in the registered
window can therefore leave a payload stage and gate intent even though no
Worker process was admitted. A C5 `registered` record alone is insufficient
to release either the runtime lease or the payload stage.

## Admission and repair sequence

The offline Product command must bind one exact attempt ID and reopen all
evidence under Product custody. It must refuse when any of these facts fail:

1. The original receipt, selected Package revision, Product scope, owner
   generation, host identity, and C5 attempt match. The C5 phase is exactly
   `registered`, and its original boot identity differs from the current
   machine boot identity.
2. The original runtime lease is orphaned and no Product runtime remains
   active. The lease belongs to the runtime named by the original receipt.
   A current or unrelated lease cannot be repaired through this command.
3. The start gate is exactly the unreleased `intent` for the same receipt and
   Worker identity. It has no native identity or `bound` record. The Supervisor
   journal contains no claim for the attempt. Any ambiguous or unrecognized
   Worker state fails closed.
4. The payload stage is either absent or an exact Product-owned stage whose
   contents are verified before removal. The command retains a durable repair
   intent so a crash during deletion can resume without treating a partial
   directory as an empty stage. The existing complete-stage repair requires a
   settled Supervisor fingerprint and cannot be reused for this case without
   a distinct registered-attempt proof.
5. The retained opt-in, receipt, gate, Supervisor, and C5 streams reopen with
   matching revisions and no competing reference. Existing V2 history and
   Package GC locks remain authoritative; a stream cutover cannot erase the
   proof needed for a later recovery or GC review.

The command repairs the orphan runtime lease and payload debt through their
respective owners, then reopens the full evidence under one runtime-quiescence
and GC write guard. Only then may it call
`ProductWorkerActivationCoordinator.recover_registered_no_effect` with a
Product witness freshly validated under that guard. A rejected witness leaves
C5 registered and retains cleanup debt. Repeating a committed operation is
idempotent and returns the exact settled attempt.

## Retention and tests

A settled registered attempt has an `intent` gate, no Supervisor claim, and a
C5 settlement. The Product history-retention review needs this as a distinct
no-effect closure shape. It must not require a bound gate or settled Supervisor
for this shape, and must prove the C5 transition never crossed `effect_started`,
including after V2 history cutover. The present GC check equates all gate IDs
with Supervisor IDs; it must instead account for this separately proved
`intent` gate while preserving exact equality for every bound gate. GC still
requires the exact receipt, opt-in, history, backup, payload, runtime, and
Package reference checks. Unknown native state remains a refusal.

Required regressions cover crash after C5 registration, lease and payload
repair across a new Product runtime, C5 settlement and reopen, replay after a
commit-before-return crash, V2 history retention and GC, plus refusal for a
same-boot lease, changed receipt or gate, Supervisor claim, bound native gate,
active runtime, changed payload bytes, and concurrent GC/cutover.

A separate real reboot drill must persist the workspace before host shutdown,
then verify a changed OS boot identity and reopen the same Product state after
restart. Changing a boot-ID function inside one process is simulation evidence,
not completion of that drill.

## V2 retirement boundary

The registered no-effect attempt has an `intent` gate and no Supervisor
record. A checkpoint may accept its retained registered repair reference only
when the Product reader verifies every such reference against the exact gate,
receipt, C5 settlement, absent Supervisor claim, and absent payload stage.
The V2 preparation reopens all five V1 sources under runtime quiescence and the
GC write gate. It archives the exact no-effect gate, receipt, C5 projection,
historical allow, and registered repair intent digest. Each archived record
must match its V1 source. The Product cutover index binds the archive digest;
the preparation intent binds its bytes before the owner index can commit.

Supervisor retirement IDs exclude only attempt IDs proved by this archive.
They still include every normally settled Supervisor attempt. A no-effect-only
history uses a typed zero-record Supervisor base and generation-zero manifest;
it does not synthesize a Supervisor claim. After V1 source deletion, retained
Product readers project the archived proof for GC and idempotent recovery.
Missing or changed archive bytes, repair intent bytes, or an unexpected
Supervisor record cause a refusal.

When V2 was committed before this attempt, the new attempt lives in active V2
generations and the Product can recover it. Retention must compare total gate
and Supervisor revisions from the verified V2 replay; taking the maximum
revision among only currently retained records loses retired history and
falsely rejects the recovery witness.

The remaining acceptance work covers competing Supervisor claims, a bound
native gate, active runtime and concurrent GC/cutover refusals, broad
cross-platform checks, and the real reboot drill.
