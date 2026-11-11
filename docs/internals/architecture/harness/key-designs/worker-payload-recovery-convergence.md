# Worker Payload Recovery Coordination Convergence

- Authority: bounded implementation under COD-RESP-GOAL-002.
- Design status: accepted for reversible implementation on 2026-11-09.
- Implementation status: implemented; bounded technical acceptance on 2026-11-09.
- Owner: existing Harness Worker payload recovery, PayloadStorage, RepairJournal
  and RootedSupervisorJournal; Product retains offline admission.
- Baseline: `039d787ed425c949bca2336aad95fe33e7ed923c`.
- Method: clean local archmethod master
  `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`; no upstream synchronization claim.

## Complete Responsibility And Existing Reuse

A74 completes three retained Linux payload-debt recovery programs: complete,
empty and unmarked stage review/preview, complete inventory, repair publication,
physical cleanup, read/reopen and retry. Thirteen public Coding entry signatures
and all actual DTOs remain; their operation bodies and two private helpers exit
Coding. Registered-before-effect repair has a different evidence contract and
remains a separate outstanding responsibility, not covered by this acceptance.

All scanning, no-follow verification, physical deletion and codecs were already
in PayloadStorage; named repair publication/read/settle was already RepairJournal;
Supervisor status/history was already the original RootedSupervisorJournal.
Those mechanisms are directly reused without a second journal, state machine,
registry, manager or transaction authority. Existing primitives do not express
the complete cross-owner ordering of Supervisor revalidation, prior intent and
partial deletion, which is the real gap closed by the private payload._recovery
programs. No existing mechanism earns duplicate implementation credit.

Alternatives were checked before prototyping: directly combining the existing
low-level calls still left the full programs in Coding; adding Supervisor policy
to PayloadStorage mixed history/settlement with physical storage; adding debt to
_selected_payload mixed retained recovery with current receipt/launch selection.
The selected private module groups the complete fixed recovery programs within
the existing Worker payload component, without new state or general controller.

Coding retains original isinstance admission, Product _offline policy and
PayloadStorage.open_root borrowing scopes. Core receives the actual Storage,
borrowed root FD and the original Supervisor owner factory. That factory is
explicitly effectful: the original Code open function performs type/currentness
admission and constructs the original history owner at every original status
point. It is not cached, replaced by Code status(), or described as a pure getter.
No Coding scan/verify/intent/write/delete callback is supplied to Core.

Core owns each stage FD it opens and closes it in the original finally. It never
closes the borrowed root FD. Code still constructs the actual RecoveryReview DTO
inside the original Product/root scopes after the second verification. The two
root-path reads remain inside the original open_root entry, after offline entry.

## Exact Recovery, Failure And Data Contract

- Complete review is verify -> status -> verify -> fact DTO, accepting absent or
  unsettled status as review facts. Preview/inventory do not query Supervisor.
- Complete repair first compares any prior plan, verifies fresh debt when no
  intent exists, and requires a process-settled Supervisor record. The fingerprint
  covers the complete canonical record.to_dict(), not just phase or an id.
  It preserves prior fingerprint comparison, absent-stage settle, first remainder
  verification, publication, fresh Supervisor fingerprint, second remainder
  verification, then fresh full deletion or prior partial deletion respectively.
- Unmarked repair compares prior review before claim admission, requires unclaimed
  status even on absent-stage settle, scans fresh debt only without prior intent,
  verifies remainder with allow_partial exactly when prior exists, publishes, then
  rechecks unclaimed before removing with allow_partial=True.
- Empty repair preserves prior/absent settle and otherwise re-verifies current,
  checks unclaimed, opens stage, verifies visibility/identity/emptiness, publishes,
  rechecks visibility and removes. There is deliberately no second Supervisor
  query after publication. A newly injected claim can therefore coexist with
  successful original cleanup, while subsequent reopen/retry rejects that claim.
  This original asymmetry is preserved rather than silently strengthened.
- Complete/unmarked repair return the caller's expected object. Empty normal
  deletion returns the newly verified current object; only prior/absent settle
  returns expected. Values equal does not erase this identity difference.
- Read-intent and reopen preserve their distinct absent/present-stage short
  circuits and conditional Supervisor checks. Partial deletion and stage-already-
  absent retries retain original intent settlement and error precedence.
- Inventory sorts all names and rejects any malformed prefix name or invalid
  stage as a whole; only the original listdir OSError is wrapped. No partial list
  is returned and unreadable debt does not become absent proof.

All persisted filenames, versions, limits, bytes, record classes and codecs remain
unchanged in their original owners; no migration is needed. All Code classes,
DTO fields/annotations/validation/fingerprints, _offline and non-target functions
are AST-identical. Error types remain the actual original class through Storage;
arbitrary runtime replacement of Code module globals is not an added contract.
Normal-exit final currentness, exception exit skipping that check, root/stage
close priority, exception cause/context and cleanup debt remain as before.

## Immutable Evidence, Failures And Limits

Before edits all1958 production source hashes and six complete original sources
were frozen outside Product under a74-worker-payload-recovery. Original capture
guards check actual bytes, and durable fixture source/observer hashes plus113
canonical raw observation hashes all match the immutable originals. Expected
observations are not generated by the replacement, and the explicit probe has
no recapture mode or default discovery route.

The probe uses actual PayloadStorage, RepairJournal, validated original DTOs and
RootedSupervisorJournal status/history IO over real files and FDs. Product and
RootedAccess quiescence, GC and currentness ports are controlled; this is not
proof of actual Product contention. Physical device/inode numbers are normalized
by identity while retaining distinct relationships. The fixture keeps complete
outcome/error/metadata and hashes/counts of every normalized byte template and
ordered trace; raw observations remain outside Product. These are template byte
hashes, not unnormalized physical-file hashes. Trace omits variable IO byte counts;
final byte templates and existing low-level repair tests cover the content.

Cases cover prior mismatch, missing/changed stage, real0600/0500 members, damaged
intent, zero/short write, short read, post-link/fsync/settle faults, partial/after
removal, authority changes, read/reopen/retry and entry/exit failure priority.
KeyboardInterrupt and CancelledError are separately injected synchronously, not
Task.cancel. close-error performs real close before raising: it proves exception
priority and root/stage custody order, not failure-before-close descriptor leaks.
Complete late-status change returns an altered actual record revision as a
controlled authority fault; empty/unmarked late claim writes the real journal.

The first exploratory119 capture plus original guard passed120. It was refined
to remove duplicate inputs, distinguish normal0600 from0500, inject root-close
at the borrowed root specifically and write the empty late claim at publication;
the113 final capture plus guard passed114. All preliminary observations remain.
The first durable rerun produced111 passes/two trace failures: during late claim,
the original atomic head publication used a random24hex temporary name. Separate
old-source recapture showed all other trace entries, outcomes and files identical.
Per-original-name TMP mapping now preserves different temporary identities; only
those two trace hashes were recalculated from the original raw observations.
Neither raw observation nor Product code was changed to make comparison pass.

Terminal evidence uses the managed wrapper, mandated private disk runtime,
worktree src PYTHONPATH, outside-sandbox execution and original non-live/host
selectors:

1. Original three-debt consumers and original four-profile repair probe:51 passed
   in62.78s. This is the pre-migration baseline, not additional unique coverage.
2. Stable durable113 on unchanged old production:113 passed in7.19s.
3. Replacement same113 plus the same original51:164 passed in107.02s.
4. Additional GC/history/repair SDK/Linux Product boundaries:16 passed and one
   source-dependency fact failed in60.59s. The existing exact import set had not
   listed the new receiving module. Its single fact now names payload._recovery
   precisely; Code imports that module directly. All49 original C54 assertions,
   nodes and selectors stay unchanged. Focused terminal verification is recorded
   below, without rerunning the already passing16.
5. Final unchanged113 fixed observations plus the original corrected dependency
   assertion:114 passed in28.39s. This is a focused closure, not a claim that the
   previous17-node boundary selection was rerun as one green suite.

Three original interruption hooks now target the actual PayloadStorage class
methods and accept self; all1171 original assert/raises ASTs and20 test functions,
parameters/decorators/selectors remain. The large consumer file was not generally
reformatted. The existing publication/repair probe is unchanged.

Prototype shadow/overlay type checks could not resolve the absent/new submodule;
initial incremental actual checks also reported that attribute. The complete
fresh actual two-source mypy run passed, with no ignore or API weakening. The new
Core import block needed three Ruff whitespace lines; they are included in cost.
The final two-source mypy check also passed after the direct module import.
Three-source Ruff/format, dependency freshness, nine documentation invariants,
existing change-plan generation and diff checks pass. No CI catalog/route/workflow,
platform matrix or merge-blocking coverage is added.

## Whole Cost And Remaining Goal

| Production owner | Before | After | Delta |
| --- | ---: | ---: | ---: |
| Coding payload | 1011 | 882 | −129 |
| Existing Worker payload, new private recovery module | 0 | 351 | +351 |
| Whole system | 645338 | 645560 | +222 |

Coding430 files/116879 physical lines, system1959 sources/645560 lines; all1957
other old source hashes are unchanged. Cost includes every cast, thin public
entry, supervisor binding, retained scope, annotations, docstrings and formatting.
This is responsibility migration with necessary bounded interface cost permitted
by the user's Nov9 revision; it is not system net deduplication or directory moving.
The shared fixed programs contain no Coding domain algorithm or hidden Product
engine; original persisted legacy diagnostic names are compatibility vocabulary.

Validation artifacts are measured separately from the unchanged production-source
frame: the new explicit probe has669 lines and its structured JSON fixture21923
lines; existing consumer hooks add6 net lines and the C54 fact adds1. These test
and evidence costs are not claimed as production reduction or excluded Coding
implementation. Full raw evidence remains outside the Product repository.

Three independent direction/prototype and actual-code views found no bounded
responsibility, runtime or compatibility blocker. The focused terminal boundary result and static closure complete this bounded
acceptance; stated execution limits remain. This
only closes the three-debt recovery coordination candidate. Full P1–P4 and <=15K
remain active with101879 lines above the limit. Registered recovery, prepared-task
lifetime and other inventory obligations remain. KD003 is still unimplemented;
KD011/A33 retain their original user-pending/unadopted boundaries.
