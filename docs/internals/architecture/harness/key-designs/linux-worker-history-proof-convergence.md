# Linux Worker History Proof Convergence

- Authority: bounded implementation under COD-RESP-GOAL-002.
- Design status: accepted for reversible implementation on 2026-11-09.
- Implementation status: implemented; bounded technical acceptance on 2026-11-09.
- Owner: existing Package Product for the complete Product proof programs;
  Worker.history for pure reference joins and Review projections.
- Baseline: `f2c7a6fe79ae246aa13f128a2d423a5c740e1134`.
- Method: clean local archmethod master
  `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`; no upstream revision claim.

## Complete Responsibility And Reuse

A77 closes the complete Linux retention review, gated offline read, committed-V2
proof and strict GC history revalidation. Package Product owns their Product,
epoch, GC, root, native and cross-history coordination. Worker.history owns the
pure receipt/gate/activation/no-effect/repair joins, GC revision references and
Review derived proofs. The old Code operation bodies exit together.

Existing StartGateHistory, RootedSupervisorJournal, ReceiptHistory, OptInJournal,
SegmentedActivationJournal, SnapshotHistory, CheckpointCommands,
RetainedHistoryReader, PreparationHistory, PayloadStorage/RepairJournal and
is_no_effect_closure remain the sole storage, replay and primitive proof owners.
A70 native custody and A76 topology custody are directly reused. They are not
rewritten or counted as new deduplication.

The frozen HistoryProofBindings carries26 actual-owner construction/getter and
Product-value bindings. It has no descriptors, Tasks, ledgers, phase dispatcher
or persistent state. Core invokes the actual read/capture/status/verify methods;
Code does not supply complete history-review, scan, committed-proof or GC
callbacks. Getters remain lazy to preserve construction/error timing and the
checkpoint/read-V2/retention import cycle. The Supervisor factory keeps its
original currentness check, and the one-method CurrentOptIn port retains the
original admitted Owner.current rather than borrowing its private journal.

The backup-attestation binding is the retained narrow Product policy entry:
closed kinds, exact Code DTO and admission stay Code, while A76 already owns the
entire physical topology program. This is distinct from returning a thick Code
history or storage program. Receipt public reads keep their original admission
and construct the same existing history owner through a small new Code factory.

Code retains actual public DTOs, Product/type/attempt admission, the original
public quiescence/GC scopes, history filename policy and thin compatibility
entries. AttemptReference has8 own fields, Review41 and GatedReview5. Review's
three original getter signatures, annotations, FQN and docstrings remain as thin
explicit-super wrappers; their algorithms are solely Core methods with empty
slots. GC Authority preserves constructor admission, its single Product identity
and product_owner property. No public entry or persisted schema is renamed.

## Distinct Contracts Kept Intact

- Public retention retains runtime quiescence with read_only=True, then GC
  read_snapshot_guard. Its under-guard entry does not reacquire those locks.
  Strict GC borrows its caller's admission; it does not call public retention.
- Retention first reads the committed archive, then gate/Supervisor/native
  closure/group, then receipts, current opt-in, projection, C5, all gates and
  Supervisor records. Inventory, five-stream capture and V2 total revisions are
  later independent reads. Backup attestation remains last. No cached aggregate
  snapshot replaces these scopes or fresh observations.
- Gated read retains both native closure reads: open_reader verifies one, then
  its caller reads again. Only the original NativeReleaseError is swallowed;
  other exceptions and synchronous interruptions retain their original escape.
  The unused native_closure_current result is not a reason to remove that IO.
- Current opt-in still uses its nested gc.guard(). Replacing it with
  current_read_only would reject the original read-snapshot nesting.
- Retention groups decisions by digest and requires exactly one historical
  allow. Strict GC keeps the original last-value dictionary projection. Selected
  receipt lookup keeps its first match, while global maps retain their last.
- Retention returns missing proofs in the original order. Strict GC performs its
  separate ordered rejection program; it does not read backup topology, current
  opt-in or native release. A recognized payload name alone is not rejected by
  this history authority: the Root GC payload-debt admission is a separate owner.
- Strict GC compares inventory sets at both ends of the same pinned-root scope,
  while preserving observed tuple order and duplicates for subsequent traversal.
  It verifies five V2 streams before preparation. Retention initially reads only
  the committed archive and verifies streams later.
- Retention reports ordinary repair references conservatively; strict GC reads
  and verifies empty/unmarked/complete/registered references independently.
  Registered no-effect proof permits an intent gate with no Supervisor. Its
  archive repair digest includes LF; complete Supervisor digest has no LF.
- V1 receipt revision remains retained-record count; gate/Supervisor use max
  revision. V2 must reopen readers for total last_revision, including retired
  records. Currentness, root pins, cleanup and exception replacement keep their
  original ordering, with no extra final checks added to failed paths.

## Immutable Source And Fixed Observations

Original source, full before/after production frames, external builder and
rejected/intermediate prototypes, raw observations and execution logs are retained
outside Product in workspace runtime
`coding-convergence-continue/a77-linux-history-proof`.

Two prototype blockers were found before Product installation: removal of the
dynamic NativeError alias would replace an original exception with ImportError;
zero-argument super in a slots dataclass would fail after dataclass class
replacement. The actual source preserves the alias explicitly and uses
super(CodingWorkerHistoryRetentionReviewV1, self). Both earlier variants remain
as evidence; mypy alone did not prove the slots behavior.

The observation harness also had genuine setup failures: nonempty data passed
to an empty-head initializer, missing C5 initial state, invalid first opt-in
generation and missing fixture imports. Its initial96 selection had90 failures
and6 passes. These failures and later corrections are retained as harness
failures, not Product regressions. A ten-scene successful-setup check then passed.
Empty-scope and ineffective fault labels were corrected; GC closure fault labels
were removed because strict GC intentionally does not read that closure.

Fixed expectations come only from byte-guarded original production:112 raw
observations plus reflection from capture4, and8 real archive observations from
capture5. Archive setup uses actual checkpoint publication, preflight, stage and
V2 owner commit. Only a valid leaseId change in a registered intent invalidates
its retained archive digest: retention reports missing proof, GC rejects. All
four repair types, global unrelated references, actual snapshot file drift and
native first/second-read failures are observed. DTO pickle identity/equality and
own fields/annotations/signatures are included.

The explicit121-node immutable comparison passed on original production
**121 tests (18.00s)**. A full external source copy then passed **122 tests
(33.12s)**, including an eight-source origin/byte guard; pytest pythonpath was
explicitly overridden, so the original checkout could not accidentally pass as
the candidate. No expected values are captured from the migrated implementation.
Only24-hex Rooted temporary nonces are normalized by complete-name ordinal;
distinct temporary identities stay distinct, and original raw names are retained.

## Actual Integration And Limits

The first installed probe had missing json/Path imports and stopped at collection;
its failure is retained. The next real-worktree selection was **147 passed,
1 failed** because an original root-swap hook still targeted Code's removed os
alias. The single hook now targets actual Package Product os. Inverse removal of
one added import and that one name change leaves the whole original test program
and import facts identical, preserving1171 original assert/raises predicates.

Actual ordinary-src execution, with no overlay, then passed **148 tests
(39.27s)**: fixed121 plus original27 consumers. Existing private review and
committed-V2 thin entries remain for checkpoint/preflight and actual old callers.
Project-context isort only reorders/merges imports; all eight program ASTs and
flattened import facts match the reviewed prototype. The external lint context
did not enforce those project import groups; that correction is recorded.

The additional original preflight/commit/three V2 routes, checkpoint/receipt
compatibility probes and architecture owner/import selection passed **203 tests
(114.62s)**. Actual eight-source mypy, ten-source Ruff and nine-source format
checks passed. The three independent responsibility/reuse, runtime/failure and
data/compatibility reviews accepted direction, corrected prototype and actual
integration within these finite boundaries. The implementation owner accepts
this bounded slice; no whole-Goal or native-platform acceptance is implied.

Native closure/group, Product current/pin/epoch/quiescence and some projection/
GC-pin inputs are controlled. GC-pin values are not persisted reservations.
Rooted IO, journals, checkpoint/preflight/V2 commit and archive reads are real;
retirement fixtures use actual unlink plus ledger, not the full retirement
transaction. Synchronous CancelledError/KeyboardInterrupt is not Task.cancel.
Cleanup/pin-exit failures occur after real cleanup/close, not before close.
This is not native crash, ACL, cross-process contention or registered-driver
acceptance. Original host-runtime exclusions remain unchanged.

## Complete Cost And Remaining Scope

| Production scope | Before | After | Change |
| --- | ---: | ---: | ---: |
| Code retention | 839 | 398 | -441 |
| Code strict GC | 340 | 60 | -280 |
| Code gated recovery module | 382 | 350 | -32 |
| Code receipt | 885 | 890 | +5 |
| Code registered repair | 422 | 412 | -10 |
| Code GC references | 55 | 45 | -10 |
| Package Product receiver | 0 | 838 | +838 |
| Worker.history pure receiver | 0 | 394 | +394 |
| Entire Coding /430 files | 116741 | 115973 | -768 |
| Entire system | 645685 /1960 files | 646149 /1962 files | +464 /+2 |

All other1954 original production sources are byte-identical. All constructors,
Protocols, generic annotations, compatibility wrappers, imports and formatting
are counted. The necessary net increase separates complete Product coordination
and pure Worker proof mechanics from actual Code DTOs and Product admission;
there is no new execution engine. This is responsibility migration, not net
deduplication. Code's remaining398-line module is not an irreducible floor.

Registered recovery now has directly reusable Core proof and strict-revalidation
programs behind the existing thin entries. Its recovery driver, cleanup authority
and remaining P1–P4 responsibilities are still unfinished. Coding remains100973
lines above15K; no claim of impossibility or full achievement follows from this
batch. KD003 is unimplemented; KD011/A33 remain user-pending and unadopted.
Rollback restores the complete eight-source slice together; no data migration is
needed because byte formats, paths and identity/recovery contracts are unchanged.
