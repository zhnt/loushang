# Linux Worker Registered And Crash Recovery Convergence

- Authority: bounded implementation under COD-RESP-GOAL-002.
- Design status: accepted for reversible implementation on 2026-11-09.
- Implementation status: implemented; bounded technical acceptance on 2026-11-09.
- Owner: existing Package Product for Product recovery and cleanup evidence;
  existing Worker coordinator, history, payload and Registry retain their state.
- Baseline: `9756a965df7cbd4c25b0c8ff783ecc6b34b76502` (A77).
- Method: clean local archmethod master
  `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`; no upstream revision claim.

## Complete Responsibility And Existing Owners

A78 replaces registered orphan review/lease repair, payload repair, registered C5
settlement and settled reopening, the sequential recovery entry, ordinary crash
C5 settlement, cleanup evidence, and POSIX C5 Store GC/epoch custody together.
The complete operations execute in Package Product's internal
`_linux_worker_recovery`; public history locking joins the existing A77 proof
module. No second C5 engine, recovery manager, phase dispatcher, durable state
or permission identity is introduced.

The original Registry still owns lease review and repair. PayloadStorage and the
actual RepairJournal own payload verification, publication, deletion and retry.
StartGateHistory, RootedSupervisorJournal, ReceiptHistory and
SegmentedActivationJournal remain the history owners. The original
ProductWorkerActivationCoordinator alone owns transitions and CAS semantics.
A77 history proof/strict GC, native custody and backup topology are directly
reused, not counted again as deduplication.

RecoveryBindings contains13 actual DTO/error/owner construction bindings and
Product values, including one existing HistoryProofBindings. There are no Code
review/verify/delete/settle callbacks. Core calls the actual owners at each
original read and mutation point. Code retains actual public classes,14-field
RegisteredReview and8-field repair intent, Product identities/admission values,
wire/codec policy, exact public signatures and thin compatible entries.
The POSIX Store constructor retains candidate policy admission; Windows Store
implementation is unchanged. Its path/load/CAS observations remain compatible.

Public Evidence and Store remain real Code classes with normal methods. The
under-guard evidence adapters inherit the shared implementation and the original
Code authority class; explicit base initialization avoids a second admission or
an incompatible constructor in the multiple-inheritance chain. C5 still binds
class-level static authority strings and plain methods with getattr_static.
Ordinary Evidence remains closed to registered recovery. The specialized owner
carries the exact original registered review; it is not a selectable broad mode.

## Ordering, Failure And Retry Contracts

- Registered review calls review_orphans before the GC guard, joins gate,
  Supervisor, C5, receipt and payload under GC/root custody, then queries repaired
  orphan evidence after the guard. These are independent reads, not one snapshot.
- The sequential entry repairs the lease, obtains a new review, repairs payload
  if eligible, then settles C5. Each owner remains independently retryable;
  there is no enclosing all-or-nothing transaction or automatic restart.
- Payload repair builds expected intent first, checks quiescence/owner revision,
  then enters the GC write guard. It reopens the same evidence before and after
  durable intent publication and verifies the remainder twice before deletion.
  Fresh and partial deletion use the original distinct Storage methods. The
  stage descriptor closes in finally. A prior intent with an absent stage settles
  its journal staging and returns early, preserving the skipped final currentness
  check. Failures retain their original durable intent, partial stage or C5 debt.
- Registered settlement requires the exact transient unbound-gate witness, not
  generic missing_proofs. It reopens raw C5 authority fields, invokes the original
  coordinator and durably rereads no-effect settlement. A settled retry instead
  checks repaired owner revision, intent/no-effect binding, strict GC and retained
  C5 again; it does not replay the transient witness predicate.
- Ordinary crash settlement checks settled Supervisor/native/gate/receipt,
  complete repair intent and retained/raw C5 before transitions. Retire, protocol
  terminal, optional prior-boot debt and settlement remain separate CAS steps.
  A committed intermediate step survives a later failure. The original settled
  fast return still validates intent and raw C5, without another fresh witness.
- Public history uses read-only quiescence then GC read_snapshot_guard. Under-
  guard evidence borrows its caller's locks and directly calls A77 under-guard
  proof. Strict GC remains a separate program; no nested public review is added.
- Ordinary verifier identity/fresh reads are inside its original catch; registered
  verifier's initial identity getters remain outside. Catch types, final equality
  checks and complete-repair catch scope are unchanged. Same-boot ordinary proof
  does not acquire the additional prior-boot historical/revision requirements.
- POSIX Store load/CAS retain write guard, currentness, actual journal operation
  and currentness in that order. The journal and coordinator sources themselves
  remain byte-identical. No new state or mirrored revision is kept.

The generic Evidence/Bindings retain the actual Code History DTO type. The
private registered verifier has a broad keyword forwarding facade solely to
match its original base's typing contract; the original exact parameter binding
and complete predicate execute in its typed helper. It adds no conversion,
filter, catch or result interpretation. Private helper FQNs/TypeError wording are
not promised; all public identities/signatures/errors are preserved.
Intent owner generation0, permissive from_dict version equality (True/1.0),
and the stricter canonical JSON+LF durable codec keep their original differences.
RegisteredReview still adds no constructor validation.

## Source And Independent Evidence

Full original1962-source and installed frames, original source copies, complete
external prototypes, manifests, raw observations, immutable expectations, failure
history and three independent reviews are retained outside Product in workspace
runtime `coding-convergence-continue/a78-registered-recovery`.

The initial generated prototype had static name-rewrite errors and a cold import
cycle, fixed before installation. Scoped type checking then found27 concrete
factory/generic/override errors; actual DTO generics and precise constructor
bindings resolve them without Any or ignores. The first broad-import invocation
also reported unrelated imported-module diagnostics; it is not a clean baseline.
A tree-external AST helper accidentally appended while iterating and was stopped;
only the helper was corrected. None of these failures changed Product behavior.

Runtime setup initially failed because its trace called a nonexistent native
identity to_dict and its original Supervisor helper stopped at stopped rather
than process_settled. Corrected setup11 passed before capture. All failed setup
outputs are retained. Fixed expectations come only from SHA-guarded original
production:85 IO observations plus reflection and57 separate API/codec cases.
There is no recapture path in the explicit Product probes.

The85 observations retain results, exception chains, final physical bytes/tree,
ordered IO/lock/currentness trace, descriptor tracking and same-disk retry. They
include real deletion and CAS before/after failures, registered verifier escape
versus catch windows, ordinary complete-read failure, and V2 settlement reopening.
Original physical stage device/inode fields and complete-name24-hex temporary
nonces are normalized; raw identities remain available outside Product.

The four V2 scenes use actual checkpoint/seal/preflight/stage/commit and readers.
One retirement fixture uses real unlink plus deletion ledger. Actual intent
payload-digest drift and C5 active-head corruption are rejected. Their initial
already-deleted registered intent uses a fixed historical stage identity; it does
not prove deletion of that historical inode. Actual deletion is covered by the
other original scenes. These scenes prove settled V2 reopening, not first-time
active-V2 C5 CAS or a native process crash.

Original fixed86 passed (36.73s), and the complete external candidate passed the
same86 (37.42s), with all9 source origins/bytes checked. Separate original57 API
observations plus a9-source origin guard passed58 (2.60s). Existing A77 fixed121
also passed against the candidate (17.27s). Original affected Worker/C5 consumers
passed128 (279.24s), with15 existing live/host exclusions.

Actual ordinary-src execution passed392 (502.63s):143 fixed A78 cases,
121 original A77 fixed cases and128 original consumers, with15 original selector
exclusions. Additional original owner/import/V2/Windows consumers passed200
(355.40s), with1 original exclusion. Nine-source mypy,15-target Ruff and11-source
format passed; documentation9/link checks, dependency freshness, scoped plan and
diff checks passed. All three independent reviewers accepted the actual bounded
slice; the implementation owner records technical acceptance on this evidence.
The complete Goal remains active, and these results are not whole-platform or
native-crash acceptance.

Three original architecture tests failed before installation (24 passed), because
accepted Session/Worker/native/history owner enumerations were stale. Only their
expected owner sets/mapping were reconciled. The existing scanners,27 nodes and
208 assertions are unchanged; inverse fact normalization leaves all other AST
identical. No gate, required condition, route or platform is added. One original
host-runtime fault hook now targets the actual frozen Storage class using a
staticmethod descriptor; the same four-argument fault function is unchanged.
Inverse hook/import changes restore the entire original test AST, including1171
assert/raises predicates and all selectors. The host-runtime case remains excluded.

A later portability review found that the controlled native identity used the
execution user's UID. This value also entered gate bytes/digests and trace.
Only that synthetic input is now fixed1000, matching A77; real Rooted/Storage
owner checks still use the actual UID. An independent original-runtime copy
matches every file and the complete1962-source before-frame set. Its guarded
old-source capture passed86 (22.03s), fixed old comparison86 (39.17s) and guarded
candidate86 (39.61s). Forty bound-native observations changed (26 crash/14 cleanup),
while45 and reflection stayed identical; all prior raw/expected files remain.
The new expected values were never captured from the candidate.

Final actual fixed-input probes passed144 (20.65s):the same143 fixed cases plus
one real leaf-deletion/intent/retry hook check. The same fault function also passed
on original source using its original cached module alias (1 test,3.04s).
An earlier class-only hook experiment on old source did not intercept that cached
alias and failed its harness assertion; that failure and the corrected adapter
are retained. These repeated fixed-input checks are not additional independent
consumer coverage, and no native process was launched. Full traceability is in
[the execution record](../coding-responsibility-convergence-progress.md).
Product current/pin/epoch/Registry and native/identity observations are controlled;
Registry mutations are in-memory, not real cross-process lease repair. IO,
Storage, Journal and C5 coordinator effects are real. Interrupts are synchronous
KeyboardInterrupt/CancelledError, not Task.cancel. Cleanup and pin-exit failures
occur after real closure. Original host-runtime exclusions remain unchanged.

## Full Cost And Remaining Scope

| Production scope | Before | After | Change |
| --- | ---: | ---: | ---: |
| Code registered review/driver | 297 | 199 | -98 |
| Code registered repair | 412 | 291 | -121 |
| Code registered C5 | 368 | 102 | -266 |
| Code ordinary crash C5 | 327 | 102 | -225 |
| Code cleanup evidence | 252 | 153 | -99 |
| Code activation state | 114 | 113 | -1 |
| Code history retention | 398 | 379 | -19 |
| Existing Package Product history | 838 | 873 | +35 |
| Package Product recovery | 0 | 1402 | +1402 |
| Entire Coding /430 files | 115973 | 115144 | -829 |
| Entire system | 646149 /1962 sources | 646757 /1963 sources | +608 /+1 |

All other1954 original production sources are byte-identical. This counts every
Protocol field, generic, constructor, compatibility wrapper, import and format
change. The net increase separates complete recovery/evidence custody from real
Code API/value/wire policy, with explicit typed boundaries and no duplicate
engine. This is responsibility migration, not net source deduplication. The
small receipt first-match/validation helper still parallels its public Code thin
entry; neither those lines nor the already-shared receipt engine are credited
as deduplication or final receipt-surface convergence.

P1 ordinary Worker startup/stop/reopen and remaining P2/P3/P4 obligations still
need their complete final disposition. Coding remains100144 lines above15K;
this batch does not prove a necessary lower bound or impossibility. KD003 remains
unimplemented; KD011/A33 remain user-pending and unadopted. Rollback restores all
nine production sources together; no persisted data migration is needed.
